"""Normalized SQLite storage for KOSIS metadata and verification caches."""

from __future__ import annotations

import csv
import json
import math
import sqlite3
import time
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 4
SCHEMA_NAME = "kosis_metadata"
DEFAULT_REQUEST_INTERVAL = 0.5
DEFAULT_RATE_LIMIT_COOLDOWN = 65.0
LONG_FORMAT_FIELDS = (
    "org_id", "tbl_id", "tbl_name", "category_path",
    "axis_id", "axis_name", "axis_order",
    "code_id", "code_name", "parent_code_id",
    "is_item", "unit_id", "unit_name", "unit_eng_name",
    "prd_se_list", "prd_ranges",
)

REQUIRED_COLUMNS = {
    "metadata_versions": {"schema_name", "schema_version", "updated_at"},
    "tables": {"org_id", "tbl_id", "tbl_name", "category_path", "updated_at"},
    "items": {
        "org_id", "tbl_id", "item_id", "item_name", "parent_item_id", "unit_id",
        "unit_name", "unit_eng_name",
    },
    "axes": {"org_id", "tbl_id", "axis_id", "axis_name", "axis_order"},
    "axis_values": {
        "org_id", "tbl_id", "axis_id", "value_id", "value_name", "parent_value_id",
    },
    "periodicities": {"org_id", "tbl_id", "prd_se", "range_text"},
    "metadata_fetch_state": {
        "org_id", "tbl_id", "status", "attempts", "row_count", "error", "fetched_at",
        "updated_at",
    },
    "mapping_cache": {
        "request_fingerprint", "response_json", "status", "created_at", "updated_at",
    },
    "api_response_cache": {
        "request_fingerprint", "response_json", "status", "created_at", "updated_at",
        "expires_at",
    },
    "verified_mapping_patterns": {
        "mapping_signature", "contract_version", "coordinate_json", "status",
        "source_measurement_id", "metadata_vintage", "verified_at", "evidence_count",
        "created_at", "updated_at",
    },
    "verified_stat_facts": {
        "stat_fact_fingerprint", "mapping_signature", "contract_version",
        "coordinate_json", "value_json", "status", "source_measurement_id",
        "metadata_vintage", "verified_at", "evidence_count", "created_at", "updated_at",
    },
    "verified_evidence": {
        "mapping_signature", "stat_fact_fingerprint", "source_measurement_id", "created_at",
    },
}

REQUIRED_INDEXES = {
    "idx_items_name": ("item_name",),
    "idx_axis_values_name": ("value_name",),
    "idx_fetch_status": ("status",),
    "idx_verified_patterns_contract": ("contract_version",),
    "idx_verified_facts_mapping": ("mapping_signature",),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc_datetime(value: Any) -> datetime | None:
    """Parse timestamps deterministically, treating legacy naive values as UTC."""
    text = _text(value)
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_expiry(value: Any) -> str | None:
    if value is None or not _text(value):
        return None
    parsed = _parse_utc_datetime(value)
    if parsed is None:
        raise ValueError(f"invalid expires_at timestamp: {value!r}")
    return parsed.isoformat(timespec="seconds")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return ""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _positive_integer(value: Any, *, field: str) -> int:
    """Accept CSV/pandas integer spellings without silently rounding values."""
    text = _text(value)
    try:
        number = float(text)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {field} {text!r}") from None
    if not math.isfinite(number) or not number.is_integer() or number <= 0:
        raise ValueError(f"invalid {field} {text!r}")
    return int(number)


def _is_item(row: Mapping[str, Any], axis_id: str) -> bool:
    marker = _first(row, "is_item", "IS_ITEM").upper()
    return axis_id.upper() == "ITEM" or marker in {"Y", "YES", "TRUE", "1"}


def _period_rows(prd_se_list: str, prd_ranges: str) -> list[tuple[str, str]]:
    ranges: dict[str, str] = {}
    for value in filter(None, (_text(part) for part in prd_ranges.split(";"))):
        code, separator, _ = value.partition(":")
        if separator and _text(code):
            ranges.setdefault(_text(code), value)
    codes = [_text(code) for code in prd_se_list.split("|") if _text(code)]
    for code in ranges:
        if code not in codes:
            codes.append(code)
    return [(code, ranges.get(code, "")) for code in codes]


class SQLiteKosisRequestLimiter:
    """Cross-process KOSIS request scheduler backed by SQLite epoch time."""

    def __init__(
        self,
        path: str | Path,
        *,
        interval: float = DEFAULT_REQUEST_INTERVAL,
        cooldown_seconds: float = DEFAULT_RATE_LIMIT_COOLDOWN,
        busy_timeout_ms: int = 30_000,
        clock=time.time,
        sleeper=time.sleep,
    ):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.interval = max(0.0, float(interval))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._clock = clock
        self._sleeper = sleeper
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path), timeout=self.busy_timeout_ms / 1000, isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS kosis_request_limit (
                       limiter_key TEXT PRIMARY KEY,
                       next_request_at REAL NOT NULL DEFAULT 0,
                       cooldown_until REAL NOT NULL DEFAULT 0,
                       updated_at REAL NOT NULL DEFAULT 0
                   )"""
            )
            connection.execute(
                """INSERT OR IGNORE INTO kosis_request_limit
                   (limiter_key,next_request_at,cooldown_until,updated_at)
                   VALUES ('global',0,0,0)"""
            )

    def acquire(self) -> None:
        """Wait until this process atomically owns the next global request slot."""
        while True:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT next_request_at,cooldown_until
                       FROM kosis_request_limit WHERE limiter_key='global'"""
                ).fetchone()
                now = float(self._clock())
                allowed_at = max(float(row[0]), float(row[1]))
                if now >= allowed_at:
                    connection.execute(
                        """UPDATE kosis_request_limit
                           SET next_request_at=?,updated_at=? WHERE limiter_key='global'""",
                        (now + self.interval, now),
                    )
                    connection.commit()
                    return
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            self._sleeper(max(0.0, allowed_at - now))

    def cooldown(self, seconds: float | None = None) -> None:
        """Extend a cooldown that every process observes before its next request."""
        duration = self.cooldown_seconds if seconds is None else max(0.0, float(seconds))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT cooldown_until FROM kosis_request_limit WHERE limiter_key='global'"
            ).fetchone()
            now = float(self._clock())
            cooldown_until = max(float(row[0]), now + duration)
            connection.execute(
                """UPDATE kosis_request_limit
                   SET cooldown_until=?,next_request_at=max(next_request_at,?),updated_at=?
                   WHERE limiter_key='global'""",
                (cooldown_until, cooldown_until, now),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def sleep(self, seconds: float) -> None:
        self._sleeper(max(0.0, float(seconds)))


class KosisMetadataStore:
    """SQLite-backed exact retrieval without materialized ITEM/OBJ products."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 30_000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), timeout=busy_timeout_ms / 1000)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def __enter__(self) -> "KosisMetadataStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError("nested transactions are not supported")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    @staticmethod
    def _statement_schema_version(statement: str) -> int:
        normalized = " ".join(statement.lower().split())
        if any(relation in normalized for relation in (
            "verified_mapping_patterns", "verified_stat_facts", "verified_evidence",
        )):
            return 3
        if "api_response_cache" in normalized:
            return 2
        return 1

    def _execute_script(self, script: str, *, schema_version: int) -> None:
        statement = ""
        for line in script.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                sql = statement.strip()
                if sql and self._statement_schema_version(sql) == schema_version:
                    self.connection.execute(sql)
                statement = ""
        if statement.strip():
            raise RuntimeError("incomplete schema SQL statement")

    def _schema_version(self) -> int:
        user_version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata_versions'"
        ).fetchone()
        metadata_version = 0
        if table_exists:
            row = self.connection.execute(
                "SELECT schema_version FROM metadata_versions WHERE schema_name=?",
                (SCHEMA_NAME,),
            ).fetchone()
            if row is not None:
                metadata_version = int(row[0])
        if user_version and metadata_version and user_version != metadata_version:
            raise RuntimeError(
                f"inconsistent schema versions: user_version={user_version}, "
                f"metadata_version={metadata_version}"
            )
        return metadata_version or user_version

    def _record_schema_version(self, version: int) -> None:
        self.connection.execute(
            """INSERT INTO metadata_versions(schema_name,schema_version,updated_at)
               VALUES (?,?,?) ON CONFLICT(schema_name) DO UPDATE SET
               schema_version=excluded.schema_version,updated_at=excluded.updated_at""",
            (SCHEMA_NAME, version, _now()),
        )
        self.connection.execute(f"PRAGMA user_version = {int(version)}")

    def _ensure_api_cache_expiry_column(self) -> None:
        columns = self._table_columns("api_response_cache")
        if "expires_at" not in columns:
            self.connection.execute("ALTER TABLE api_response_cache ADD COLUMN expires_at TEXT")

    def _migrate_v1_to_v2(self, schema_sql: str) -> None:
        self._execute_script(schema_sql, schema_version=2)
        self._ensure_api_cache_expiry_column()
        self._record_schema_version(2)

    def _migrate_v2_to_v3(self, schema_sql: str) -> None:
        self._ensure_api_cache_expiry_column()
        self._execute_script(schema_sql, schema_version=3)
        self._record_schema_version(3)

    def _migrate_v3_to_v4(self) -> None:
        """Allow alternative KOSIS axes to share one objL slot."""
        statements = (
            """CREATE TABLE axes_v4 (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                axis_id TEXT NOT NULL,
                axis_name TEXT NOT NULL DEFAULT '',
                axis_order INTEGER NOT NULL CHECK (axis_order > 0),
                PRIMARY KEY (org_id, tbl_id, axis_id),
                FOREIGN KEY (org_id, tbl_id)
                    REFERENCES tables(org_id, tbl_id) ON DELETE CASCADE
            )""",
            "INSERT INTO axes_v4 SELECT * FROM axes",
            """CREATE TABLE axis_values_v4 (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                axis_id TEXT NOT NULL,
                value_id TEXT NOT NULL,
                value_name TEXT NOT NULL DEFAULT '',
                parent_value_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (org_id, tbl_id, axis_id, value_id),
                FOREIGN KEY (org_id, tbl_id, axis_id)
                    REFERENCES axes_v4(org_id, tbl_id, axis_id) ON DELETE CASCADE
            )""",
            "INSERT INTO axis_values_v4 SELECT * FROM axis_values",
            "DROP TABLE axis_values",
            "DROP TABLE axes",
            "ALTER TABLE axes_v4 RENAME TO axes",
            "ALTER TABLE axis_values_v4 RENAME TO axis_values",
            "CREATE INDEX IF NOT EXISTS idx_axis_values_name ON axis_values(value_name)",
        )
        for statement in statements:
            self.connection.execute(statement)
        self._record_schema_version(4)

    def _table_columns(self, table: str) -> set[str]:
        return {str(row[1]) for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def _create_schema(self) -> None:
        version = self._schema_version()
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported schema version: {version} (latest supported: {SCHEMA_VERSION})"
            )
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            schema_sql = """
            CREATE TABLE IF NOT EXISTS metadata_versions (
                schema_name TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tables (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                tbl_name TEXT NOT NULL DEFAULT '',
                category_path TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (org_id, tbl_id)
            );
            CREATE TABLE IF NOT EXISTS items (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                item_name TEXT NOT NULL DEFAULT '',
                parent_item_id TEXT NOT NULL DEFAULT '',
                unit_id TEXT NOT NULL DEFAULT '',
                unit_name TEXT NOT NULL DEFAULT '',
                unit_eng_name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (org_id, tbl_id, item_id),
                FOREIGN KEY (org_id, tbl_id) REFERENCES tables(org_id, tbl_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS axes (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                axis_id TEXT NOT NULL,
                axis_name TEXT NOT NULL DEFAULT '',
                axis_order INTEGER NOT NULL CHECK (axis_order > 0),
                PRIMARY KEY (org_id, tbl_id, axis_id),
                FOREIGN KEY (org_id, tbl_id) REFERENCES tables(org_id, tbl_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS axis_values (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                axis_id TEXT NOT NULL,
                value_id TEXT NOT NULL,
                value_name TEXT NOT NULL DEFAULT '',
                parent_value_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (org_id, tbl_id, axis_id, value_id),
                FOREIGN KEY (org_id, tbl_id, axis_id)
                    REFERENCES axes(org_id, tbl_id, axis_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS periodicities (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                prd_se TEXT NOT NULL,
                range_text TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (org_id, tbl_id, prd_se),
                FOREIGN KEY (org_id, tbl_id) REFERENCES tables(org_id, tbl_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS metadata_fetch_state (
                org_id TEXT NOT NULL,
                tbl_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                row_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                fetched_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (org_id, tbl_id)
            );
            CREATE TABLE IF NOT EXISTS mapping_cache (
                request_fingerprint TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_response_cache (
                request_fingerprint TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS verified_mapping_patterns (
                mapping_signature TEXT PRIMARY KEY,
                contract_version TEXT NOT NULL,
                coordinate_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status = 'MATCH'),
                source_measurement_id TEXT NOT NULL,
                metadata_vintage TEXT NOT NULL DEFAULT '',
                verified_at TEXT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 1 CHECK (evidence_count > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verified_stat_facts (
                stat_fact_fingerprint TEXT PRIMARY KEY,
                mapping_signature TEXT NOT NULL,
                contract_version TEXT NOT NULL,
                coordinate_json TEXT NOT NULL,
                value_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status = 'MATCH'),
                source_measurement_id TEXT NOT NULL,
                metadata_vintage TEXT NOT NULL DEFAULT '',
                verified_at TEXT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 1 CHECK (evidence_count > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (mapping_signature)
                    REFERENCES verified_mapping_patterns(mapping_signature)
                    ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS verified_evidence (
                mapping_signature TEXT NOT NULL,
                stat_fact_fingerprint TEXT NOT NULL,
                source_measurement_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    mapping_signature, stat_fact_fingerprint, source_measurement_id
                ),
                FOREIGN KEY (mapping_signature)
                    REFERENCES verified_mapping_patterns(mapping_signature)
                    ON DELETE RESTRICT,
                FOREIGN KEY (stat_fact_fingerprint)
                    REFERENCES verified_stat_facts(stat_fact_fingerprint)
                    ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(item_name);
            CREATE INDEX IF NOT EXISTS idx_axis_values_name ON axis_values(value_name);
            CREATE INDEX IF NOT EXISTS idx_fetch_status ON metadata_fetch_state(status);
            CREATE INDEX IF NOT EXISTS idx_verified_patterns_contract
                ON verified_mapping_patterns(contract_version);
            CREATE INDEX IF NOT EXISTS idx_verified_facts_mapping
                ON verified_stat_facts(mapping_signature);
            """
            self._execute_script(schema_sql, schema_version=1)
            if version < 1:
                self._record_schema_version(1)
                version = 1
            if version < 2:
                self._migrate_v1_to_v2(schema_sql)
                version = 2
            else:
                self._execute_script(schema_sql, schema_version=2)
                self._ensure_api_cache_expiry_column()
            if version < 3:
                self._migrate_v2_to_v3(schema_sql)
                version = 3
            else:
                self._execute_script(schema_sql, schema_version=3)
            if version < 4:
                self._migrate_v3_to_v4()
            else:
                self._record_schema_version(SCHEMA_VERSION)
            check = self.integrity_check()
            if not check["ok"]:
                raise RuntimeError(f"invalid KOSIS metadata schema: {check['schema_errors']}")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def integrity_check(self) -> dict[str, Any]:
        quick = [row[0] for row in self.connection.execute("PRAGMA quick_check")]
        foreign_keys = [tuple(row) for row in self.connection.execute("PRAGMA foreign_key_check")]
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        schema_errors: list[str] = []
        for table, required in REQUIRED_COLUMNS.items():
            actual = self._table_columns(table)
            if not actual:
                schema_errors.append(f"missing table: {table}")
                continue
            missing = sorted(required - actual)
            if missing:
                schema_errors.append(f"{table} missing columns: {','.join(missing)}")
        for index, expected_columns in REQUIRED_INDEXES.items():
            exists = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (index,)
            ).fetchone()
            if exists is None:
                schema_errors.append(f"missing index: {index}")
                continue
            actual_columns = tuple(
                str(row[2]) for row in self.connection.execute(f"PRAGMA index_info({index})")
            )
            if actual_columns != expected_columns:
                schema_errors.append(
                    f"{index} columns {actual_columns!r} != {expected_columns!r}"
                )
        metadata = self.connection.execute(
            "SELECT schema_version FROM metadata_versions WHERE schema_name=?", (SCHEMA_NAME,)
        ).fetchone()
        metadata_version = int(metadata[0]) if metadata is not None else None
        if metadata_version != SCHEMA_VERSION:
            schema_errors.append(f"metadata schema version: {metadata_version!r}")
        return {
            "ok": (
                quick == ["ok"] and not foreign_keys and version == SCHEMA_VERSION
                and not schema_errors
            ),
            "quick_check": quick,
            "foreign_key_errors": foreign_keys,
            "schema_version": version,
            "schema_errors": schema_errors,
        }

    def ingest_table(self, rows: Iterable[Mapping[str, Any]]) -> tuple[str, str]:
        source = [dict(row) for row in rows]
        if not source:
            raise ValueError("table metadata rows must not be empty")

        normalized = []
        table_keys: set[tuple[str, str]] = set()
        table_names: set[str] = set()
        category_paths: set[str] = set()
        periods: set[tuple[str, str]] = set()
        axis_definitions: dict[str, tuple[str, int]] = {}
        item_definitions: dict[str, tuple[str, str, str, str, str]] = {}
        axis_value_definitions: dict[tuple[str, str], tuple[str, str]] = {}
        for index, row in enumerate(source):
            org_id = _first(row, "org_id", "ORG_ID", "OrgId")
            tbl_id = _first(row, "tbl_id", "TBL_ID", "TblId")
            code_id = _first(row, "code_id", "ITM_ID", "itm_id", "code")
            axis_id = _first(row, "axis_id", "OBJ_ID", "obj_id")
            if not org_id or not tbl_id or not code_id or not axis_id:
                raise ValueError(f"malformed metadata row {index}: missing table/component identifier")
            table_keys.add((org_id, tbl_id))
            table_names.add(_first(row, "tbl_name", "TBL_NM"))
            category_paths.add(_first(row, "category_path", "path"))
            item = _is_item(row, axis_id)
            axis_order: int | None = None
            if not item:
                raw_order = _first(row, "axis_order", "OBJ_ID_SN", "obj_id_sn", "obj_level")
                try:
                    axis_order = _positive_integer(raw_order, field="axis_order")
                except ValueError:
                    raise ValueError(f"malformed metadata row {index}: invalid axis_order {raw_order!r}")
                axis_name = _first(row, "axis_name", "OBJ_NM", "obj_nm")
                definition = (axis_name, axis_order)
                if axis_id in axis_definitions and axis_definitions[axis_id] != definition:
                    raise ValueError(f"conflicting definition for axis {axis_id!r}")
                axis_definitions[axis_id] = definition
                value_key = (axis_id, code_id)
                value_definition = (
                    _first(row, "code_name", "ITM_NM", "itm_nm", "name"),
                    _first(row, "parent_code_id", "UP_ITM_ID"),
                )
                if (
                    value_key in axis_value_definitions
                    and axis_value_definitions[value_key] != value_definition
                ):
                    raise ValueError(
                        f"conflicting definition for axis value {axis_id!r}/{code_id!r}"
                    )
                axis_value_definitions[value_key] = value_definition
            else:
                item_definition = (
                    _first(row, "code_name", "ITM_NM", "itm_nm", "name"),
                    _first(row, "parent_code_id", "UP_ITM_ID"),
                    _first(row, "unit_id", "UNIT_ID"),
                    _first(row, "unit_name", "UNIT_NM", "unit"),
                    _first(row, "unit_eng_name", "UNIT_ENG_NM"),
                )
                if code_id in item_definitions and item_definitions[code_id] != item_definition:
                    raise ValueError(f"conflicting definition for item {code_id!r}")
                item_definitions[code_id] = item_definition
            normalized.append((row, org_id, tbl_id, axis_id, code_id, item, axis_order))
            periods.update(_period_rows(
                _first(row, "prd_se_list", "PRD_SE_LIST", "prd_se", "PRD_SE"),
                _first(row, "prd_ranges", "PRD_RANGES"),
            ))

        if len(table_keys) != 1:
            raise ValueError("ingest_table accepts rows for exactly one table")
        if len(table_names) > 1 or len(category_paths) > 1:
            raise ValueError("conflicting table metadata in input rows")
        org_id, tbl_id = next(iter(table_keys))
        timestamp = _now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO tables(org_id,tbl_id,tbl_name,category_path,updated_at)
                   VALUES (?,?,?,?,?) ON CONFLICT(org_id,tbl_id) DO UPDATE SET
                   tbl_name=excluded.tbl_name, category_path=excluded.category_path,
                   updated_at=excluded.updated_at""",
                (org_id, tbl_id, next(iter(table_names)), next(iter(category_paths)), timestamp),
            )
            for relation in ("items", "axis_values", "axes", "periodicities"):
                connection.execute(
                    f"DELETE FROM {relation} WHERE org_id=? AND tbl_id=?", (org_id, tbl_id)
                )
            for axis_id, (axis_name, axis_order) in sorted(
                axis_definitions.items(), key=lambda item: (item[1][1], item[0])
            ):
                connection.execute(
                    "INSERT INTO axes VALUES (?,?,?,?,?)",
                    (org_id, tbl_id, axis_id, axis_name, axis_order),
                )
            for row, _, _, axis_id, code_id, item, _axis_order in normalized:
                if item:
                    connection.execute(
                        """INSERT INTO items VALUES (?,?,?,?,?,?,?,?)
                           ON CONFLICT(org_id,tbl_id,item_id) DO UPDATE SET
                           item_name=excluded.item_name,parent_item_id=excluded.parent_item_id,
                           unit_id=excluded.unit_id,unit_name=excluded.unit_name,
                           unit_eng_name=excluded.unit_eng_name""",
                        (org_id, tbl_id, code_id,
                         _first(row, "code_name", "ITM_NM", "itm_nm", "name"),
                         _first(row, "parent_code_id", "UP_ITM_ID"),
                         _first(row, "unit_id", "UNIT_ID"),
                         _first(row, "unit_name", "UNIT_NM", "unit"),
                         _first(row, "unit_eng_name", "UNIT_ENG_NM")),
                    )
                else:
                    connection.execute(
                        """INSERT INTO axis_values VALUES (?,?,?,?,?,?)
                           ON CONFLICT(org_id,tbl_id,axis_id,value_id) DO UPDATE SET
                           value_name=excluded.value_name,parent_value_id=excluded.parent_value_id""",
                        (org_id, tbl_id, axis_id, code_id,
                         _first(row, "code_name", "ITM_NM", "itm_nm", "name"),
                         _first(row, "parent_code_id", "UP_ITM_ID")),
                    )
            connection.executemany(
                "INSERT INTO periodicities VALUES (?,?,?,?)",
                [(org_id, tbl_id, code, range_text) for code, range_text in sorted(periods)],
            )
            connection.execute(
                """INSERT INTO metadata_fetch_state
                   (org_id,tbl_id,status,attempts,row_count,error,fetched_at,updated_at)
                   VALUES (?,?, 'complete', 1, ?, '', ?, ?)
                   ON CONFLICT(org_id,tbl_id) DO UPDATE SET status='complete',
                   attempts=metadata_fetch_state.attempts+1,row_count=excluded.row_count,
                   error='',fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                (org_id, tbl_id, len(source), timestamp, timestamp),
            )
        return org_id, tbl_id

    def table_exists(self, org_id: str, tbl_id: str) -> bool:
        return self._exists("tables", org_id, tbl_id)

    def record_fetch_failure(
        self, org_id: str, tbl_id: str, error: str, *, attempts: int = 1,
    ) -> None:
        timestamp = _now()
        with self.connection:
            self.connection.execute(
                """INSERT INTO metadata_fetch_state
                   (org_id,tbl_id,status,attempts,row_count,error,fetched_at,updated_at)
                   VALUES (?,?,'failed',?,0,?,NULL,?)
                   ON CONFLICT(org_id,tbl_id) DO UPDATE SET status='failed',
                   attempts=metadata_fetch_state.attempts+excluded.attempts,row_count=0,
                   error=excluded.error,updated_at=excluded.updated_at""",
                (_text(org_id), _text(tbl_id), max(1, int(attempts)), _text(error), timestamp),
            )

    def table_complete(
        self, org_id: str, tbl_id: str, *, max_age_days: int | None = None,
        require_periodicity: bool = True,
    ) -> bool:
        state = self.connection.execute(
            """SELECT status,row_count,fetched_at FROM metadata_fetch_state
               WHERE org_id=? AND tbl_id=?""",
            (_text(org_id), _text(tbl_id)),
        ).fetchone()
        if state is None or state["status"] != "complete" or int(state["row_count"]) <= 0:
            return False
        has_item = self.connection.execute(
            "SELECT 1 FROM items WHERE org_id=? AND tbl_id=? LIMIT 1",
            (_text(org_id), _text(tbl_id)),
        ).fetchone()
        if has_item is None:
            return False
        if require_periodicity and not self._exists("periodicities", org_id, tbl_id):
            return False
        if max_age_days is not None:
            fetched = _parse_utc_datetime(state["fetched_at"])
            if fetched is None:
                return False
            if fetched < datetime.now(timezone.utc) - timedelta(days=max_age_days):
                return False
        return True

    def item_exists(self, org_id: str, tbl_id: str, item_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM items WHERE org_id=? AND tbl_id=? AND item_id=?",
            (_text(org_id), _text(tbl_id), _text(item_id)),
        ).fetchone() is not None

    def axis_exists(self, org_id: str, tbl_id: str, axis_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM axes WHERE org_id=? AND tbl_id=? AND axis_id=?",
            (_text(org_id), _text(tbl_id), _text(axis_id)),
        ).fetchone() is not None

    def axis_value_exists(
        self, org_id: str, tbl_id: str, axis_id: str, value_id: str
    ) -> bool:
        return self.connection.execute(
            """SELECT 1 FROM axis_values
               WHERE org_id=? AND tbl_id=? AND axis_id=? AND value_id=?""",
            (_text(org_id), _text(tbl_id), _text(axis_id), _text(value_id)),
        ).fetchone() is not None

    def component_exists(
        self, org_id: str, tbl_id: str, code_id: str, *, axis_id: str = "ITEM"
    ) -> bool:
        if _text(axis_id).upper() == "ITEM":
            return self.item_exists(org_id, tbl_id, code_id)
        return self.axis_value_exists(org_id, tbl_id, axis_id, code_id)

    def _exists(self, relation: str, org_id: str, tbl_id: str) -> bool:
        return self.connection.execute(
            f"SELECT 1 FROM {relation} WHERE org_id=? AND tbl_id=?",
            (_text(org_id), _text(tbl_id)),
        ).fetchone() is not None

    def list_missing_table_keys(
        self, keys: Iterable[tuple[str, str]], *, max_age_days: int | None = None,
        require_periodicity: bool = True,
    ) -> list[tuple[str, str]]:
        unique = sorted({(_text(org), _text(table)) for org, table in keys})
        return [
            key for key in unique
            if not self.table_complete(
                *key, max_age_days=max_age_days, require_periodicity=require_periodicity,
            )
        ]

    def export_long_rows(
        self, table_keys: Iterable[tuple[str, str]]
    ) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        for org_id, tbl_id in sorted({(_text(a), _text(b)) for a, b in table_keys}):
            table = self.connection.execute(
                "SELECT * FROM tables WHERE org_id=? AND tbl_id=?", (org_id, tbl_id)
            ).fetchone()
            if table is None:
                continue
            periods = list(self.connection.execute(
                """SELECT prd_se,range_text FROM periodicities
                   WHERE org_id=? AND tbl_id=? ORDER BY prd_se""", (org_id, tbl_id)
            ))
            common = {
                "org_id": org_id, "tbl_id": tbl_id,
                "tbl_name": table["tbl_name"], "category_path": table["category_path"],
                "prd_se_list": "|".join(row["prd_se"] for row in periods),
                "prd_ranges": ";".join(row["range_text"] for row in periods if row["range_text"]),
            }
            for row in self.connection.execute(
                """SELECT * FROM items WHERE org_id=? AND tbl_id=? ORDER BY item_id""",
                (org_id, tbl_id),
            ):
                output.append({**common, "axis_id": "ITEM", "axis_name": "",
                    "axis_order": "", "code_id": row["item_id"],
                    "code_name": row["item_name"], "parent_code_id": row["parent_item_id"],
                    "is_item": "Y", "unit_id": row["unit_id"],
                    "unit_name": row["unit_name"], "unit_eng_name": row["unit_eng_name"]})
            for row in self.connection.execute(
                """SELECT a.axis_id,a.axis_name,a.axis_order,v.value_id,v.value_name,v.parent_value_id
                   FROM axes a JOIN axis_values v USING(org_id,tbl_id,axis_id)
                   WHERE a.org_id=? AND a.tbl_id=?
                   ORDER BY a.axis_order,a.axis_id,v.value_id""", (org_id, tbl_id)
            ):
                output.append({**common, "axis_id": row["axis_id"],
                    "axis_name": row["axis_name"], "axis_order": str(row["axis_order"]),
                    "code_id": row["value_id"], "code_name": row["value_name"],
                    "parent_code_id": row["parent_value_id"], "is_item": "N",
                    "unit_id": "", "unit_name": "", "unit_eng_name": ""})
        return [{field: _text(row.get(field)) for field in LONG_FORMAT_FIELDS} for row in output]

    def export_long_csv(
        self, destination: str | Path, table_keys: Iterable[tuple[str, str]]
    ) -> int:
        rows = self.export_long_rows(table_keys)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LONG_FORMAT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def put_mapping_cache(self, fingerprint: str, response: Any, status: str) -> None:
        self._put_cache("mapping_cache", fingerprint, response, status)

    def get_mapping_cache(self, fingerprint: str) -> dict[str, Any] | None:
        return self._get_cache("mapping_cache", fingerprint)

    def put_verified_mapping_pattern(
        self,
        signature: str,
        coordinate: Mapping[str, Any],
        *,
        status: str,
        contract_version: str,
        source_measurement_id: str,
        metadata_vintage: str = "",
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        """Store corroborating MATCH evidence for one reusable coordinate.

        A signature is immutable: conflicting coordinates or contract versions
        are rejected instead of silently replacing trusted evidence.
        """
        key = _verified_fingerprint(signature, "mapping_signature")
        _require_match(status)
        contract = _required_text(contract_version, "contract_version").lower()
        source = _required_text(source_measurement_id, "source_measurement_id")
        coordinate_json = _coordinate_json(coordinate)
        timestamp = _now()
        observation_time = _text(verified_at) or timestamp
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM verified_mapping_patterns WHERE mapping_signature=?",
                (key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO verified_mapping_patterns(
                           mapping_signature,contract_version,coordinate_json,status,
                           source_measurement_id,metadata_vintage,verified_at,
                           evidence_count,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        key, contract, coordinate_json, "MATCH", source,
                        _text(metadata_vintage), observation_time, 1, timestamp, timestamp,
                    ),
                )
            else:
                if existing["contract_version"] != contract:
                    raise ValueError("mapping signature has a conflicting contract_version")
                if existing["coordinate_json"] != coordinate_json:
                    raise ValueError("mapping signature has a conflicting coordinate")
                connection.execute(
                    """UPDATE verified_mapping_patterns
                       SET metadata_vintage=CASE WHEN ?='' THEN metadata_vintage ELSE ? END,
                           verified_at=?, evidence_count=evidence_count+1, updated_at=?
                       WHERE mapping_signature=?""",
                    (
                        _text(metadata_vintage), _text(metadata_vintage), observation_time,
                        timestamp, key,
                    ),
                )
        result = self.get_verified_mapping_pattern(key)
        assert result is not None
        return result

    def get_verified_mapping_pattern(self, signature: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM verified_mapping_patterns WHERE mapping_signature=?",
            (_text(signature),),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["coordinate"] = json.loads(result.pop("coordinate_json"))
        return result

    def put_verified_stat_fact(
        self,
        fingerprint: str,
        signature: str,
        coordinate: Mapping[str, Any],
        value: Any,
        *,
        status: str,
        contract_version: str,
        source_measurement_id: str,
        metadata_vintage: str = "",
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        """Store MATCH-only evidence for one exact-period official value."""
        fact_key = _verified_fingerprint(fingerprint, "stat_fact_fingerprint")
        mapping_key = _verified_fingerprint(signature, "mapping_signature")
        _require_match(status)
        contract = _required_text(contract_version, "contract_version").lower()
        source = _required_text(source_measurement_id, "source_measurement_id")
        coordinate_json = _coordinate_json(coordinate)
        value_json = _json(value)
        timestamp = _now()
        observation_time = _text(verified_at) or timestamp
        with self.transaction() as connection:
            pattern = connection.execute(
                "SELECT * FROM verified_mapping_patterns WHERE mapping_signature=?",
                (mapping_key,),
            ).fetchone()
            if pattern is None:
                raise ValueError("verified mapping pattern must exist before a stat fact")
            if pattern["contract_version"] != contract:
                raise ValueError("stat fact has a conflicting contract_version")
            if pattern["coordinate_json"] != coordinate_json:
                raise ValueError("stat fact coordinate conflicts with its mapping pattern")
            existing = connection.execute(
                "SELECT * FROM verified_stat_facts WHERE stat_fact_fingerprint=?",
                (fact_key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO verified_stat_facts(
                           stat_fact_fingerprint,mapping_signature,contract_version,
                           coordinate_json,value_json,status,source_measurement_id,
                           metadata_vintage,verified_at,evidence_count,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fact_key, mapping_key, contract, coordinate_json, value_json,
                        "MATCH", source, _text(metadata_vintage), observation_time,
                        1, timestamp, timestamp,
                    ),
                )
            else:
                conflicts = (
                    existing["mapping_signature"] != mapping_key
                    or existing["contract_version"] != contract
                    or existing["coordinate_json"] != coordinate_json
                    or existing["value_json"] != value_json
                )
                if conflicts:
                    raise ValueError("stat fact fingerprint has conflicting trusted evidence")
                connection.execute(
                    """UPDATE verified_stat_facts
                       SET metadata_vintage=CASE WHEN ?='' THEN metadata_vintage ELSE ? END,
                           verified_at=?, evidence_count=evidence_count+1, updated_at=?
                       WHERE stat_fact_fingerprint=?""",
                    (
                        _text(metadata_vintage), _text(metadata_vintage), observation_time,
                        timestamp, fact_key,
                    ),
                )
        result = self.get_verified_stat_fact(fact_key)
        assert result is not None
        return result

    def get_verified_stat_fact(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM verified_stat_facts WHERE stat_fact_fingerprint=?",
            (_text(fingerprint),),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["coordinate"] = json.loads(result.pop("coordinate_json"))
        result["value"] = json.loads(result.pop("value_json"))
        return result

    def put_verified_match_evidence(
        self,
        fingerprint: str,
        signature: str,
        coordinate: Mapping[str, Any],
        value: Any,
        *,
        contract_version: str,
        source_measurement_id: str,
        metadata_vintage: str = "",
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically store one idempotent MATCH mapping/fact evidence pair."""
        fact_key = _verified_fingerprint(fingerprint, "stat_fact_fingerprint")
        mapping_key = _verified_fingerprint(signature, "mapping_signature")
        contract = _required_text(contract_version, "contract_version").lower()
        source = _required_text(source_measurement_id, "source_measurement_id")
        coordinate_json = _coordinate_json(coordinate)
        value_json = _json(value)
        timestamp = _now()
        observation_time = _text(verified_at) or timestamp
        vintage = _text(metadata_vintage)

        with self.transaction() as connection:
            pattern = connection.execute(
                "SELECT * FROM verified_mapping_patterns WHERE mapping_signature=?",
                (mapping_key,),
            ).fetchone()
            if pattern is not None and (
                pattern["contract_version"] != contract
                or pattern["coordinate_json"] != coordinate_json
            ):
                raise ValueError("mapping signature has conflicting trusted evidence")

            fact = connection.execute(
                "SELECT * FROM verified_stat_facts WHERE stat_fact_fingerprint=?",
                (fact_key,),
            ).fetchone()
            if fact is not None and (
                fact["mapping_signature"] != mapping_key
                or fact["contract_version"] != contract
                or fact["coordinate_json"] != coordinate_json
                or fact["value_json"] != value_json
            ):
                raise ValueError("stat fact fingerprint has conflicting trusted evidence")

            duplicate = connection.execute(
                """SELECT 1 FROM verified_evidence
                   WHERE mapping_signature=? AND stat_fact_fingerprint=?
                     AND source_measurement_id=?""",
                (mapping_key, fact_key, source),
            ).fetchone() is not None
            if duplicate:
                return {"duplicate": True, "stored": False}

            if pattern is None:
                connection.execute(
                    """INSERT INTO verified_mapping_patterns(
                           mapping_signature,contract_version,coordinate_json,status,
                           source_measurement_id,metadata_vintage,verified_at,
                           evidence_count,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mapping_key, contract, coordinate_json, "MATCH", source,
                        vintage, observation_time, 1, timestamp, timestamp,
                    ),
                )
            else:
                connection.execute(
                    """UPDATE verified_mapping_patterns
                       SET metadata_vintage=CASE WHEN ?='' THEN metadata_vintage ELSE ? END,
                           verified_at=?, evidence_count=evidence_count+1, updated_at=?
                       WHERE mapping_signature=?""",
                    (vintage, vintage, observation_time, timestamp, mapping_key),
                )

            if fact is None:
                connection.execute(
                    """INSERT INTO verified_stat_facts(
                           stat_fact_fingerprint,mapping_signature,contract_version,
                           coordinate_json,value_json,status,source_measurement_id,
                           metadata_vintage,verified_at,evidence_count,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fact_key, mapping_key, contract, coordinate_json, value_json,
                        "MATCH", source, vintage, observation_time, 1, timestamp, timestamp,
                    ),
                )
            else:
                connection.execute(
                    """UPDATE verified_stat_facts
                       SET metadata_vintage=CASE WHEN ?='' THEN metadata_vintage ELSE ? END,
                           verified_at=?, evidence_count=evidence_count+1, updated_at=?
                       WHERE stat_fact_fingerprint=?""",
                    (vintage, vintage, observation_time, timestamp, fact_key),
                )

            connection.execute(
                """INSERT INTO verified_evidence(
                       mapping_signature,stat_fact_fingerprint,source_measurement_id,created_at
                   ) VALUES (?,?,?,?)""",
                (mapping_key, fact_key, source, timestamp),
            )
        return {"duplicate": False, "stored": True}

    def put_api_response(
        self, fingerprint: str, response: Any, status: str, *, expires_at: str | None = None
    ) -> None:
        if _contains_api_error(response):
            raise ValueError("KOSIS error responses must not be cached")
        self._put_cache(
            "api_response_cache", fingerprint, response, status, _canonical_expiry(expires_at)
        )

    def get_api_response(self, fingerprint: str) -> dict[str, Any] | None:
        return self._get_cache("api_response_cache", fingerprint)

    def _put_cache(
        self, relation: str, fingerprint: str, response: Any, status: str,
        expires_at: str | None = None,
    ) -> None:
        if relation not in {"mapping_cache", "api_response_cache"}:
            raise ValueError("invalid cache relation")
        key = _text(fingerprint)
        if not key:
            raise ValueError("request fingerprint must not be empty")
        timestamp = _now()
        columns = "request_fingerprint,response_json,status,created_at,updated_at"
        values: tuple[Any, ...] = (key, _json(response), _text(status), timestamp, timestamp)
        extras = ""
        if relation == "api_response_cache":
            columns += ",expires_at"
            values += (expires_at,)
            extras = ",expires_at=excluded.expires_at"
        with self.connection:
            self.connection.execute(
                f"""INSERT INTO {relation}({columns}) VALUES ({','.join('?' for _ in values)})
                    ON CONFLICT(request_fingerprint) DO UPDATE SET
                    response_json=excluded.response_json,status=excluded.status,
                    updated_at=excluded.updated_at{extras}""",
                values,
            )

    def _get_cache(self, relation: str, fingerprint: str) -> dict[str, Any] | None:
        if relation not in {"mapping_cache", "api_response_cache"}:
            raise ValueError("invalid cache relation")
        row = self.connection.execute(
            f"SELECT * FROM {relation} WHERE request_fingerprint=?", (_text(fingerprint),)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if relation == "api_response_cache" and result.get("expires_at"):
            expires = _parse_utc_datetime(result["expires_at"])
            if expires is None or expires <= datetime.now(timezone.utc):
                with self.connection:
                    self.connection.execute(
                        "DELETE FROM api_response_cache WHERE request_fingerprint=?",
                        (_text(fingerprint),),
                    )
                return None
        result["response"] = json.loads(result.pop("response_json"))
        return result


def _contains_api_error(response: Any) -> bool:
    rows = response if isinstance(response, list) else [response]
    return any(
        isinstance(row, Mapping)
        and str(row.get("err") or row.get("ERR") or "").strip()
        for row in rows
    )


def _required_text(value: Any, field: str) -> str:
    result = _text(value)
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _verified_fingerprint(value: Any, field: str) -> str:
    result = _required_text(value, field).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ValueError(f"{field} must be a full SHA256 hex digest")
    return result


def _require_match(status: Any) -> None:
    if _text(status).upper() != "MATCH":
        raise ValueError("only MATCH evidence may enter the verified fact cache")


def _coordinate_json(coordinate: Mapping[str, Any]) -> str:
    if not isinstance(coordinate, Mapping) or not coordinate:
        raise ValueError("coordinate must be a non-empty mapping")
    return _json(dict(coordinate))


class SQLiteAPIResponseCache(MutableMapping[str, Any]):
    """Dict-compatible persistent cache used by validator and verifier."""

    def __init__(
        self, path: str | Path, *, namespace: str = "kosis-api-v1",
        ttl_seconds: int = 86_400, empty_ttl_seconds: int = 900,
    ):
        self.store = KosisMetadataStore(path)
        self.namespace = _text(namespace)
        self.ttl_seconds = int(ttl_seconds)
        self.empty_ttl_seconds = int(empty_ttl_seconds)

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{_text(key)}"

    def __getitem__(self, key: str) -> Any:
        cached = self.store.get_api_response(self._key(key))
        if cached is None or cached.get("status") != "OK":
            raise KeyError(key)
        return cached["response"]

    def __setitem__(self, key: str, value: Any) -> None:
        ttl = self.ttl_seconds if value else self.empty_ttl_seconds
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        self.store.put_api_response(self._key(key), value, "OK", expires_at=expires_at)

    def __delitem__(self, key: str) -> None:
        with self.store.connection:
            cursor = self.store.connection.execute(
                "DELETE FROM api_response_cache WHERE request_fingerprint=?", (self._key(key),)
            )
        if cursor.rowcount == 0:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        rows = self.store.connection.execute(
            """SELECT request_fingerprint FROM api_response_cache
               WHERE status='OK' AND request_fingerprint LIKE ? ORDER BY 1""",
            (f"{self.namespace}:%",),
        )
        prefix = f"{self.namespace}:"
        return iter(row[0][len(prefix):] for row in rows)

    def __len__(self) -> int:
        return int(self.store.connection.execute(
            """SELECT count(*) FROM api_response_cache
               WHERE status='OK' AND request_fingerprint LIKE ?""",
            (f"{self.namespace}:%",),
        ).fetchone()[0])

    def close(self) -> None:
        self.store.close()


__all__ = [
    "KosisMetadataStore", "SQLiteAPIResponseCache", "SQLiteKosisRequestLimiter",
    "DEFAULT_REQUEST_INTERVAL", "DEFAULT_RATE_LIMIT_COOLDOWN",
    "LONG_FORMAT_FIELDS", "SCHEMA_VERSION",
]
