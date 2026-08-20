"""PostgreSQL exact-metadata storage for the KOSIS Top-3 handoff."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any

try:  # PostgreSQL is optional for local schema and normalization tests.
    import psycopg
except ImportError:  # pragma: no cover - depends on deployment extras
    psycopg = None


SCHEMA_PATH = Path(__file__).with_name("sql") / "kosis_metadata_schema.sql"
RELATION_COLUMNS = {
    "tables": (
        "org_id", "tbl_id", "tbl_name", "category_path", "search_document",
        "unit_hints", "metadata_version", "updated_at",
    ),
    "items": (
        "org_id", "tbl_id", "item_id", "item_name", "parent_item_id",
        "unit_id", "unit_name", "unit_eng_name",
    ),
    "axes": ("org_id", "tbl_id", "axis_id", "axis_name", "axis_order"),
    "axis_values": (
        "org_id", "tbl_id", "axis_id", "value_id", "value_name",
        "parent_value_id",
    ),
    "periodicities": ("org_id", "tbl_id", "prd_se", "range_text"),
}
POSTGRES_RELATIONS = {name: f"kosis_{name}" for name in RELATION_COLUMNS}
CONFLICT_KEYS = {
    "tables": ("org_id", "tbl_id"),
    "items": ("org_id", "tbl_id", "item_id"),
    "axes": ("org_id", "tbl_id", "axis_id"),
    "axis_values": ("org_id", "tbl_id", "axis_id", "value_id"),
    "periodicities": ("org_id", "tbl_id", "prd_se"),
}
RELATION_ORDER = ("tables", "items", "axes", "axis_values", "periodicities")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ADVISORY_LOCK_NAME = "kosis_metadata_snapshot"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_schema_sql(path: str | Path = SCHEMA_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def normalize_sqlite_row(relation: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a SQLite metadata row into the PostgreSQL contract."""
    if relation not in RELATION_COLUMNS:
        raise ValueError(f"unsupported relation: {relation}")
    source = dict(row)
    if relation == "tables":
        org_id = _text(source.get("org_id"))
        tbl_id = _text(source.get("tbl_id"))
        if not org_id or not tbl_id:
            raise ValueError("missing tables key column(s): org_id, tbl_id")
        table_name = _text(source.get("tbl_name"))
        category = _text(source.get("category_path"))
        unit_hints = source.get("unit_hints", [])
        if isinstance(unit_hints, str):
            unit_hints = [part.strip() for part in unit_hints.split("|") if part.strip()]
        return {
            "org_id": org_id,
            "tbl_id": tbl_id,
            "tbl_name": table_name,
            "category_path": category,
            "search_document": _text(source.get("search_document"))
            or " ".join(part for part in (table_name, category) if part),
            "unit_hints": sorted({_text(value) for value in unit_hints if _text(value)}),
            "metadata_version": _text(source.get("metadata_version")),
            "updated_at": source.get("updated_at") or _utc_now(),
        }
    normalized = {
        column: source.get(column) for column in RELATION_COLUMNS[relation]
    }
    for column, value in tuple(normalized.items()):
        if column == "axis_order":
            try:
                normalized[column] = int(float(value))
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid axis_order: {value!r}") from error
        else:
            normalized[column] = _text(value)
    required = CONFLICT_KEYS[relation]
    missing = [column for column in required if not normalized[column]]
    if missing:
        raise ValueError(f"missing {relation} key column(s): {', '.join(missing)}")
    return normalized


def build_insert_sql(relation: str, *, target: str | None = None) -> str:
    """Build a plain insert used by snapshot staging, where duplicates are errors."""
    if relation not in RELATION_COLUMNS:
        raise ValueError(f"unsupported relation: {relation}")
    columns = RELATION_COLUMNS[relation]
    destination = target or POSTGRES_RELATIONS[relation]
    return (
        f"INSERT INTO {destination} ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))})"
    )


def _validate_sha256(value: str, label: str) -> str:
    digest = _text(value).lower()
    if not SHA256_PATTERN.fullmatch(digest):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return digest


def _batches(rows: Iterable[Mapping[str, Any]], size: int):
    iterator = iter(rows)
    while batch := list(islice(iterator, size)):
        yield batch


HYDRATE_TOP3_SQL = """
SELECT jsonb_build_object(
    'rank', candidate.rank,
    'org_id', snapshot_table.org_id,
    'tbl_id', snapshot_table.tbl_id,
    'tbl_name', snapshot_table.tbl_name,
    'category_path', snapshot_table.category_path,
    'scores', jsonb_build_object(
        'lexical_rank', candidate.lexical_rank,
        'dense_rank', candidate.dense_rank,
        'fusion_score', candidate.fusion_score,
        'reranker_score', candidate.reranker_score
    ) || candidate.score_json,
    'periodicities', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'prd_se', p.prd_se, 'range_text', p.range_text
        ) ORDER BY p.prd_se)
        FROM kosis_periodicities p
        WHERE pinned_snapshot.is_active
          AND p.org_id = snapshot_table.org_id AND p.tbl_id = snapshot_table.tbl_id
    ), '[]'::jsonb),
    'items', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'item_id', i.item_id, 'item_name', i.item_name,
            'parent_item_id', i.parent_item_id, 'unit_id', i.unit_id,
            'unit_name', i.unit_name, 'unit_eng_name', i.unit_eng_name
        ) ORDER BY i.item_id)
        FROM kosis_items i
        WHERE pinned_snapshot.is_active
          AND i.org_id = snapshot_table.org_id AND i.tbl_id = snapshot_table.tbl_id
    ), '[]'::jsonb),
    'axes', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'axis_id', axis.axis_id, 'axis_name', axis.axis_name,
            'axis_order', axis.axis_order, 'values', COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'value_id', value.value_id, 'value_name', value.value_name,
                    'parent_value_id', value.parent_value_id
                ) ORDER BY value.value_id)
                FROM kosis_axis_values value
                WHERE value.org_id = axis.org_id AND value.tbl_id = axis.tbl_id
                  AND value.axis_id = axis.axis_id
            ), '[]'::jsonb)
        ) ORDER BY axis.axis_order, axis.axis_id)
        FROM kosis_axes axis
        WHERE pinned_snapshot.is_active
          AND axis.org_id = snapshot_table.org_id AND axis.tbl_id = snapshot_table.tbl_id
    ), '[]'::jsonb),
    'metadata_complete', component_state.is_complete,
    'metadata_status', CASE
        WHEN component_state.is_complete THEN 'complete'
        WHEN NOT component_state.has_items
         AND NOT component_state.has_axes
         AND NOT component_state.has_periodicities THEN 'catalog_only'
        ELSE 'partial'
    END,
    'missing_sections', to_jsonb(array_remove(ARRAY[
        CASE WHEN NOT component_state.has_items THEN 'items' END,
        CASE WHEN NOT component_state.has_axes THEN 'axes' END,
        CASE WHEN NOT component_state.axes_have_values THEN 'axis_values' END,
        CASE WHEN NOT component_state.has_periodicities THEN 'periodicities' END,
        CASE WHEN NOT pinned_snapshot.is_active
             THEN 'normalized_detail_snapshot_inactive' END
    ]::TEXT[], NULL))
) AS candidate_json
FROM retrieval_candidates candidate
JOIN retrieval_runs retrieval_run
  ON retrieval_run.run_id = candidate.run_id
 AND retrieval_run.query_id = candidate.query_id
JOIN kosis_metadata_snapshots pinned_snapshot
  ON pinned_snapshot.snapshot_id = retrieval_run.snapshot_id
 AND pinned_snapshot.snapshot_id = candidate.snapshot_id
JOIN kosis_snapshot_tables snapshot_table
  ON snapshot_table.snapshot_id = candidate.snapshot_id
 AND snapshot_table.org_id = candidate.org_id
 AND snapshot_table.tbl_id = candidate.tbl_id
CROSS JOIN LATERAL (
    SELECT
        pinned_snapshot.is_active AND EXISTS (
            SELECT 1 FROM kosis_items i
            WHERE i.org_id = snapshot_table.org_id
              AND i.tbl_id = snapshot_table.tbl_id
        ) AS has_items,
        pinned_snapshot.is_active AND EXISTS (
            SELECT 1 FROM kosis_axes a
            WHERE a.org_id = snapshot_table.org_id
              AND a.tbl_id = snapshot_table.tbl_id
        ) AS has_axes,
        pinned_snapshot.is_active
        AND EXISTS (
            SELECT 1 FROM kosis_axes a
            WHERE a.org_id = snapshot_table.org_id
              AND a.tbl_id = snapshot_table.tbl_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM kosis_axes required_axis
            WHERE required_axis.org_id = snapshot_table.org_id
              AND required_axis.tbl_id = snapshot_table.tbl_id
              AND NOT EXISTS (
                  SELECT 1 FROM kosis_axis_values required_value
                  WHERE required_value.org_id = required_axis.org_id
                    AND required_value.tbl_id = required_axis.tbl_id
                    AND required_value.axis_id = required_axis.axis_id
              )
        ) AS axes_have_values,
        pinned_snapshot.is_active AND EXISTS (
            SELECT 1 FROM kosis_periodicities p
            WHERE p.org_id = snapshot_table.org_id
              AND p.tbl_id = snapshot_table.tbl_id
        ) AS has_periodicities
) presence
CROSS JOIN LATERAL (
    SELECT presence.*,
           presence.has_items AND presence.has_axes
           AND presence.axes_have_values AND presence.has_periodicities
           AS is_complete
) component_state
WHERE candidate.run_id = %s AND candidate.query_id = %s
ORDER BY candidate.rank
LIMIT 3
"""


HYDRATE_COMPONENT_BUNDLE_SQL = """
WITH requested(input_order, org_id, tbl_id) AS (
    VALUES {requested_values}
)
SELECT requested.input_order,
       jsonb_build_object(
           'org_id', snapshot_table.org_id,
           'tbl_id', snapshot_table.tbl_id,
           'tbl_name', snapshot_table.tbl_name,
           'category_path', snapshot_table.category_path,
           'periodicities', COALESCE((
               SELECT jsonb_agg(jsonb_build_object(
                   'prd_se', periodicity.prd_se,
                   'range_text', periodicity.range_text
               ) ORDER BY periodicity.prd_se)
               FROM kosis_periodicities periodicity
               WHERE periodicity.org_id = requested.org_id
                 AND periodicity.tbl_id = requested.tbl_id
           ), '[]'::jsonb),
           'items', COALESCE((
               SELECT jsonb_agg(jsonb_build_object(
                   'item_id', item.item_id,
                   'item_name', item.item_name,
                   'parent_item_id', item.parent_item_id,
                   'unit_id', item.unit_id,
                   'unit_name', item.unit_name,
                   'unit_eng_name', item.unit_eng_name
               ) ORDER BY item.item_id)
               FROM kosis_items item
               WHERE item.org_id = requested.org_id
                 AND item.tbl_id = requested.tbl_id
           ), '[]'::jsonb),
           'axes', COALESCE((
               SELECT jsonb_agg(jsonb_build_object(
                   'axis_id', axis.axis_id,
                   'axis_name', axis.axis_name,
                   'axis_order', axis.axis_order,
                   'values', COALESCE((
                       SELECT jsonb_agg(jsonb_build_object(
                           'value_id', axis_value.value_id,
                           'value_name', axis_value.value_name,
                           'parent_value_id', axis_value.parent_value_id
                       ) ORDER BY axis_value.value_id)
                       FROM kosis_axis_values axis_value
                       WHERE axis_value.org_id = axis.org_id
                         AND axis_value.tbl_id = axis.tbl_id
                         AND axis_value.axis_id = axis.axis_id
                   ), '[]'::jsonb)
               ) ORDER BY axis.axis_order, axis.axis_id)
               FROM kosis_axes axis
               WHERE axis.org_id = requested.org_id
                 AND axis.tbl_id = requested.tbl_id
           ), '[]'::jsonb)
       ) AS component_bundle_json
FROM requested
LEFT JOIN kosis_snapshot_tables snapshot_table
  ON snapshot_table.snapshot_id = %s
 AND snapshot_table.org_id = requested.org_id
 AND snapshot_table.tbl_id = requested.tbl_id
ORDER BY requested.input_order
"""


class PostgresKosisMetadataStore:
    """Small psycopg-compatible store for migration and MCP handoff hydration."""

    def __init__(
        self, dsn: str | None = None, *, connection: Any | None = None,
        connect_timeout: int = 10,
    ):
        self._metadata_guard_depth = 0
        self._guard_snapshot: dict[str, Any] | None = None
        if connection is not None:
            self.connection = connection
            self._owns_connection = False
        else:
            if psycopg is None:
                raise RuntimeError(
                    "psycopg is required for PostgreSQL connections; install psycopg[binary]"
                )
            if not dsn:
                raise ValueError("dsn is required when connection is not supplied")
            self.connection = psycopg.connect(dsn, connect_timeout=connect_timeout)
            self._owns_connection = True

    def __enter__(self) -> "PostgresKosisMetadataStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def apply_schema(self, path: str | Path = SCHEMA_PATH) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(load_schema_sql(path))
        self.connection.commit()

    def replace_metadata_snapshot(
        self,
        rows_by_relation: Mapping[str, Iterable[Mapping[str, Any]]],
        *,
        source_sqlite_sha256: str,
        semantic_tables_sha256: str,
        collected_at: str | datetime,
        migrated_at: str | datetime | None = None,
        snapshot_id: str | uuid.UUID | None = None,
        batch_size: int = 2000,
        row_count_details: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        """Atomically replace all active metadata and record its exact provenance."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        missing = set(RELATION_ORDER) - set(rows_by_relation)
        if missing:
            raise ValueError(f"snapshot relations missing: {', '.join(sorted(missing))}")
        sqlite_digest = _validate_sha256(source_sqlite_sha256, "source_sqlite_sha256")
        semantic_digest = _validate_sha256(
            semantic_tables_sha256, "semantic_tables_sha256"
        )
        identifier = str(snapshot_id or uuid.uuid4())
        migration_time = migrated_at or _utc_now()
        row_counts = {relation: 0 for relation in RELATION_ORDER}
        details = dict(row_count_details or {})
        reserved = set(RELATION_ORDER) & set(details)
        if reserved:
            raise ValueError(
                "row_count_details cannot replace relation counts: "
                + ", ".join(sorted(reserved))
            )
        for label, value in details.items():
            if not isinstance(label, str) or not label.strip():
                raise ValueError("row_count_details keys must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"row_count_details[{label!r}] must be a non-negative integer"
                )
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (ADVISORY_LOCK_NAME,),
                )
                for relation in RELATION_ORDER:
                    live = POSTGRES_RELATIONS[relation]
                    staging = f"stage_{live}"
                    cursor.execute(
                        f"CREATE TEMP TABLE {staging} "
                        f"(LIKE {live} INCLUDING DEFAULTS INCLUDING CONSTRAINTS) "
                        "ON COMMIT DROP"
                    )
                    columns = RELATION_COLUMNS[relation]
                    for batch in _batches(rows_by_relation[relation], batch_size):
                        normalized = [
                            normalize_sqlite_row(relation, row) for row in batch
                        ]
                        parameters = [
                            tuple(row[column] for column in columns) for row in normalized
                        ]
                        cursor.executemany(
                            build_insert_sql(relation, target=staging), parameters
                        )
                        row_counts[relation] += len(parameters)

                row_counts.update(details)

                # Store immutable labels before replacing the normalized active view.
                cursor.execute(
                    """INSERT INTO kosis_metadata_snapshots
                       (snapshot_id,source_sqlite_sha256,semantic_tables_sha256,
                        collected_at,migrated_at,row_counts,is_active)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb,FALSE)""",
                    (
                        identifier, sqlite_digest, semantic_digest, collected_at,
                        migration_time, json.dumps(row_counts, sort_keys=True),
                    ),
                )
                cursor.execute(
                    """INSERT INTO kosis_snapshot_tables
                       (snapshot_id,org_id,tbl_id,tbl_name,category_path,
                        search_document,unit_hints,metadata_version,updated_at)
                       SELECT %s,org_id,tbl_id,tbl_name,category_path,
                              search_document,unit_hints,metadata_version,updated_at
                       FROM stage_kosis_tables""",
                    (identifier,),
                )

                # Old retrieval evidence remains pinned to its immutable catalog.
                cursor.execute("DELETE FROM kosis_tables")
                for relation in RELATION_ORDER:
                    live = POSTGRES_RELATIONS[relation]
                    cursor.execute(f"INSERT INTO {live} SELECT * FROM stage_{live}")
                cursor.execute(
                    "UPDATE kosis_metadata_snapshots SET is_active=FALSE WHERE is_active"
                )
                cursor.execute(
                    "UPDATE kosis_metadata_snapshots SET is_active=TRUE "
                    "WHERE snapshot_id=%s",
                    (identifier,),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {
            "snapshot_id": identifier,
            "source_sqlite_sha256": sqlite_digest,
            "semantic_tables_sha256": semantic_digest,
            "collected_at": collected_at,
            "migrated_at": migration_time,
            "row_counts": row_counts,
        }

    def active_snapshot(self) -> dict[str, Any] | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """SELECT snapshot_id,source_sqlite_sha256,semantic_tables_sha256,
                          collected_at,migrated_at,row_counts
                   FROM kosis_metadata_snapshots WHERE is_active"""
            )
            row = cursor.fetchone()
        if row is None:
            return None
        columns = (
            "snapshot_id", "source_sqlite_sha256", "semantic_tables_sha256",
            "collected_at", "migrated_at", "row_counts",
        )
        value = dict(row) if isinstance(row, Mapping) else dict(zip(columns, row))
        if isinstance(value["row_counts"], str):
            value["row_counts"] = json.loads(value["row_counts"])
        return value

    def assert_active_semantic_tables_hash(self, expected_sha256: str) -> dict[str, Any]:
        expected = _validate_sha256(expected_sha256, "expected_sha256")
        snapshot = self.active_snapshot()
        if snapshot is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        actual = _text(snapshot["semantic_tables_sha256"]).lower()
        if actual != expected:
            raise RuntimeError(
                "active semantic tables hash mismatch: "
                f"expected={expected} actual={actual}"
            )
        return snapshot

    @contextmanager
    def metadata_read_guard(self, expected_semantic_tables_sha256: str | None = None):
        """Pin one active metadata snapshot against replacement for a complete run."""
        outermost = self._metadata_guard_depth == 0
        if outermost:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_lock_shared(hashtext(%s))",
                    (ADVISORY_LOCK_NAME,),
                )
            try:
                snapshot = (
                    self.assert_active_semantic_tables_hash(
                        expected_semantic_tables_sha256
                    )
                    if expected_semantic_tables_sha256 is not None
                    else self.active_snapshot()
                )
                if snapshot is None:
                    raise RuntimeError("no active KOSIS metadata snapshot")
                self._guard_snapshot = snapshot
            except Exception:
                with self.connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock_shared(hashtext(%s))",
                        (ADVISORY_LOCK_NAME,),
                    )
                raise
        self._metadata_guard_depth += 1
        try:
            yield dict(self._guard_snapshot or {})
        finally:
            self._metadata_guard_depth -= 1
            if outermost:
                try:
                    with self.connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_unlock_shared(hashtext(%s))",
                            (ADVISORY_LOCK_NAME,),
                        )
                finally:
                    self._guard_snapshot = None

    def record_retrieval(
        self,
        query_id: str,
        query: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        *,
        retrieval_config: Mapping[str, Any] | None = None,
        run_id: str | uuid.UUID | None = None,
        snapshot_id: str | uuid.UUID | None = None,
    ) -> str:
        if self._metadata_guard_depth == 0:
            with self.metadata_read_guard():
                return self.record_retrieval(
                    query_id,
                    query,
                    candidates,
                    retrieval_config=retrieval_config,
                    run_id=run_id,
                    snapshot_id=snapshot_id,
                )
        if len(candidates) > 3:
            raise ValueError("the MCP handoff accepts at most three table candidates")
        identifier = str(run_id or uuid.uuid4())
        active = self._guard_snapshot or self.active_snapshot()
        if active is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        active_snapshot_id = _text(active["snapshot_id"])
        pinned_snapshot_id = _text(snapshot_id) or active_snapshot_id
        if pinned_snapshot_id != active_snapshot_id:
            raise RuntimeError(
                "retrieval snapshot mismatch: "
                f"active={active_snapshot_id} requested={pinned_snapshot_id}"
            )
        seen: set[tuple[str, str]] = set()
        rows = []
        for fallback_rank, candidate in enumerate(candidates, 1):
            key = (_text(candidate.get("org_id")), _text(candidate.get("tbl_id")))
            if not all(key) or key in seen:
                raise ValueError(f"invalid or duplicate table candidate: {key}")
            seen.add(key)
            rank = int(candidate.get("rank") or fallback_rank)
            if rank != fallback_rank:
                raise ValueError("candidate ranks must be contiguous and start at one")
            scores = dict(candidate.get("scores") or {})
            reranker_score = scores.pop(
                "reranker_score", candidate.get("reranker_score")
            )
            if reranker_score is None:
                raise ValueError(f"candidate rank {rank} has no reranker_score")
            rows.append((
                identifier, _text(query_id), pinned_snapshot_id, rank, *key,
                scores.pop("lexical_rank", candidate.get("lexical_rank")),
                scores.pop("dense_rank", candidate.get("dense_rank")),
                scores.pop("fusion_score", candidate.get("fusion_score")),
                reranker_score,
                json.dumps(scores, ensure_ascii=False),
            ))
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO retrieval_runs
                       (run_id,snapshot_id,query_id,query_json,retrieval_config)
                       VALUES (%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    (
                        identifier, pinned_snapshot_id, _text(query_id),
                        json.dumps(dict(query), ensure_ascii=False),
                        json.dumps(dict(retrieval_config or {}), ensure_ascii=False),
                    ),
                )
                if rows:
                    cursor.executemany(
                        """INSERT INTO retrieval_candidates
                           (run_id,query_id,snapshot_id,rank,org_id,tbl_id,
                            lexical_rank,dense_rank,
                            fusion_score,reranker_score,score_json)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                        rows,
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return identifier

    def missing_table_keys(
        self, candidates: Sequence[Mapping[str, Any]],
    ) -> list[tuple[str, str]]:
        keys = [(_text(row.get("org_id")), _text(row.get("tbl_id"))) for row in candidates]
        if not keys:
            return []
        if any(not all(key) for key in keys):
            raise ValueError("candidate org_id and tbl_id are required")
        placeholders = ",".join(["(%s,%s)"] * len(keys))
        parameters = tuple(value for key in keys for value in key)
        sql = f"""
            SELECT requested.org_id, requested.tbl_id
            FROM (VALUES {placeholders}) AS requested(org_id, tbl_id)
            LEFT JOIN kosis_snapshot_tables table_meta
              ON table_meta.snapshot_id = %s
             AND table_meta.org_id = requested.org_id
             AND table_meta.tbl_id = requested.tbl_id
            WHERE table_meta.tbl_id IS NULL
            ORDER BY requested.org_id, requested.tbl_id
        """
        snapshot = self._guard_snapshot or self.active_snapshot()
        if snapshot is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (*parameters, _text(snapshot["snapshot_id"])))
            rows = cursor.fetchall()
        return [
            (_text(row[0]), _text(row[1])) if not isinstance(row, Mapping)
            else (_text(row["org_id"]), _text(row["tbl_id"]))
            for row in rows
        ]

    def incomplete_component_keys(
        self, candidates: Sequence[Mapping[str, Any]],
    ) -> list[tuple[str, str]]:
        """Return candidate tables without a complete local ITEM/OBJ contract."""
        keys = sorted({
            (_text(row.get("org_id")), _text(row.get("tbl_id")))
            for row in candidates
        })
        if not keys:
            return []
        if any(not all(key) for key in keys):
            raise ValueError("candidate org_id and tbl_id are required")
        placeholders = ",".join(["(%s,%s)"] * len(keys))
        parameters = tuple(value for key in keys for value in key)
        sql = f"""
            SELECT requested.org_id, requested.tbl_id
            FROM (VALUES {placeholders}) AS requested(org_id, tbl_id)
            WHERE NOT EXISTS (
                      SELECT 1 FROM kosis_items item
                      WHERE item.org_id=requested.org_id
                        AND item.tbl_id=requested.tbl_id
                  )
               OR NOT EXISTS (
                      SELECT 1 FROM kosis_axes axis
                      WHERE axis.org_id=requested.org_id
                        AND axis.tbl_id=requested.tbl_id
                  )
               OR EXISTS (
                      SELECT 1 FROM kosis_axes axis
                      WHERE axis.org_id=requested.org_id
                        AND axis.tbl_id=requested.tbl_id
                        AND NOT EXISTS (
                            SELECT 1 FROM kosis_axis_values value
                            WHERE value.org_id=axis.org_id
                              AND value.tbl_id=axis.tbl_id
                              AND value.axis_id=axis.axis_id
                        )
                  )
               OR NOT EXISTS (
                      SELECT 1 FROM kosis_periodicities period
                      WHERE period.org_id=requested.org_id
                        AND period.tbl_id=requested.tbl_id
                  )
            ORDER BY requested.org_id, requested.tbl_id
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            rows = cursor.fetchall()
        return [
            (_text(row[0]), _text(row[1])) if not isinstance(row, Mapping)
            else (_text(row["org_id"]), _text(row["tbl_id"]))
            for row in rows
        ]

    def table_rerank_metadata(
        self, candidates: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Read lightweight period/catalog metadata before the table reranker.

        This deliberately avoids ITEM/OBJ payloads. Stage A may inspect dozens
        of tables per claim, so loading the Cartesian component metadata here
        would defeat the low-memory split between table and coordinate search.
        """
        if not candidates:
            return []
        if self._metadata_guard_depth == 0:
            with self.metadata_read_guard():
                return self.table_rerank_metadata(candidates)
        requested = []
        seen = set()
        for input_order, candidate in enumerate(candidates, 1):
            key = (_text(candidate.get("org_id")), _text(candidate.get("tbl_id")))
            if not all(key):
                raise ValueError("candidate org_id and tbl_id are required")
            if key in seen:
                raise ValueError(f"duplicate table candidate: {key}")
            seen.add(key)
            requested.append((input_order, *key))
        snapshot = self._guard_snapshot or self.active_snapshot()
        if snapshot is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        values_sql = ",".join(["(%s,%s,%s)"] * len(requested))
        parameters = tuple(value for row in requested for value in row)
        sql = f"""
            WITH requested(input_order, org_id, tbl_id) AS (
                VALUES {values_sql}
            )
            SELECT requested.input_order,
                   requested.org_id,
                   requested.tbl_id,
                   COALESCE(table_meta.tbl_name, ''),
                   COALESCE(table_meta.category_path, ''),
                   COALESCE(table_meta.search_document, ''),
                   COALESCE(table_meta.unit_hints, ARRAY[]::TEXT[]),
                   COALESCE((
                       SELECT array_agg(period.prd_se ORDER BY period.prd_se)
                       FROM kosis_periodicities period
                       WHERE period.org_id=requested.org_id
                         AND period.tbl_id=requested.tbl_id
                   ), ARRAY[]::TEXT[]),
                   table_meta.tbl_id IS NOT NULL AS catalog_present,
                   EXISTS (
                       SELECT 1 FROM kosis_items item
                       WHERE item.org_id=requested.org_id
                         AND item.tbl_id=requested.tbl_id
                   )
                   AND EXISTS (
                       SELECT 1 FROM kosis_axes axis
                       WHERE axis.org_id=requested.org_id
                         AND axis.tbl_id=requested.tbl_id
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM kosis_axes axis
                       WHERE axis.org_id=requested.org_id
                         AND axis.tbl_id=requested.tbl_id
                         AND NOT EXISTS (
                             SELECT 1 FROM kosis_axis_values value
                             WHERE value.org_id=axis.org_id
                               AND value.tbl_id=axis.tbl_id
                               AND value.axis_id=axis.axis_id
                         )
                   )
                   AND EXISTS (
                       SELECT 1 FROM kosis_periodicities period
                       WHERE period.org_id=requested.org_id
                         AND period.tbl_id=requested.tbl_id
                   ) AS metadata_complete
            FROM requested
            LEFT JOIN kosis_snapshot_tables table_meta
              ON table_meta.snapshot_id=%s
             AND table_meta.org_id=requested.org_id
             AND table_meta.tbl_id=requested.tbl_id
            ORDER BY requested.input_order
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (*parameters, _text(snapshot["snapshot_id"])))
            rows = cursor.fetchall()
        output = []
        for row in rows:
            if isinstance(row, Mapping):
                get = row.__getitem__
                values = (
                    get("input_order"), get("org_id"), get("tbl_id"),
                    get("tbl_name"), get("category_path"), get("search_document"),
                    get("unit_hints"),
                    get("periodicities"), get("catalog_present"),
                    get("metadata_complete"),
                )
            else:
                values = row
            output.append({
                "input_order": int(values[0]),
                "org_id": _text(values[1]),
                "tbl_id": _text(values[2]),
                "tbl_name": _text(values[3]),
                "category_path": _text(values[4]),
                "search_document": _text(values[5]),
                "unit_hints": sorted({_text(value) for value in (values[6] or []) if _text(value)}),
                "periodicities": sorted({_text(value).upper() for value in (values[7] or []) if _text(value)}),
                "catalog_present": bool(values[8]),
                "metadata_complete": bool(values[9]),
            })
        return output

    def apply_component_hydration_snapshot(
        self,
        rows_by_relation: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        hydration_sha256: str,
        hydrated_table_keys: Sequence[tuple[str, str]],
        migrated_at: str | datetime | None = None,
        snapshot_id: str | uuid.UUID | None = None,
        batch_size: int = 2000,
    ) -> dict[str, Any]:
        """Atomically replace detail rows for selected tables and rotate snapshot.

        The complete table catalog is copied to the new immutable snapshot. Only
        normalized ITEM/OBJ/periodicity rows for successfully fetched tables are
        replaced, so a partial network run cannot erase previously valid detail.
        """
        required = {"items", "axes", "axis_values", "periodicities"}
        missing = required - set(rows_by_relation)
        if missing:
            raise ValueError(f"hydration relations missing: {', '.join(sorted(missing))}")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        hydration_digest = _validate_sha256(hydration_sha256, "hydration_sha256")
        keys = sorted({(_text(org), _text(table)) for org, table in hydrated_table_keys})
        if not keys or any(not all(key) for key in keys):
            raise ValueError("at least one valid hydrated table key is required")
        expected_keys = set(keys)
        for relation in required:
            for row in rows_by_relation[relation]:
                key = (_text(row.get("org_id")), _text(row.get("tbl_id")))
                if key not in expected_keys:
                    raise ValueError(f"unexpected {relation} table key: {key}")
        item_keys = {
            (_text(row.get("org_id")), _text(row.get("tbl_id")))
            for row in rows_by_relation["items"]
        }
        axis_keys = {
            (_text(row.get("org_id")), _text(row.get("tbl_id")))
            for row in rows_by_relation["axes"]
        }
        period_keys = {
            (_text(row.get("org_id")), _text(row.get("tbl_id")))
            for row in rows_by_relation["periodicities"]
        }
        if item_keys != expected_keys or axis_keys != expected_keys or period_keys != expected_keys:
            raise ValueError("every hydrated table must contain ITEM, OBJ and periodicity rows")
        value_axes_by_table: dict[tuple[str, str], set[str]] = {}
        for row in rows_by_relation["axis_values"]:
            key = (_text(row.get("org_id")), _text(row.get("tbl_id")))
            value_axes_by_table.setdefault(key, set()).add(_text(row.get("axis_id")))
        for row in rows_by_relation["axes"]:
            key = (_text(row.get("org_id")), _text(row.get("tbl_id")))
            if _text(row.get("axis_id")) not in value_axes_by_table.get(key, set()):
                raise ValueError(f"hydrated OBJ axis has no values: {key}/{row.get('axis_id')}")
        for relation in required:
            seen_keys: set[tuple[Any, ...]] = set()
            for row in rows_by_relation[relation]:
                normalized = normalize_sqlite_row(relation, row)
                key = tuple(normalized[column] for column in CONFLICT_KEYS[relation])
                if key in seen_keys:
                    raise ValueError(f"duplicate {relation} primary key: {key}")
                seen_keys.add(key)

        active = self.active_snapshot()
        if active is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        identifier = str(snapshot_id or uuid.uuid4())
        migration_time = migrated_at or _utc_now()
        source_digest = _validate_sha256(
            str(active["source_sqlite_sha256"]), "active source_sqlite_sha256"
        )
        table_placeholders = ",".join(["(%s,%s)"] * len(keys))
        key_parameters = tuple(value for key in keys for value in key)
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (ADVISORY_LOCK_NAME,),
                )
                cursor.execute(
                    "SELECT snapshot_id FROM kosis_metadata_snapshots "
                    "WHERE is_active FOR UPDATE"
                )
                locked = cursor.fetchone()
                if locked is None or _text(locked[0]) != _text(active["snapshot_id"]):
                    raise RuntimeError("active metadata snapshot changed during hydration")

                for relation in ("axis_values", "axes", "items", "periodicities"):
                    cursor.execute(
                        f"DELETE FROM {POSTGRES_RELATIONS[relation]} live USING "
                        f"(VALUES {table_placeholders}) requested(org_id,tbl_id) "
                        "WHERE live.org_id=requested.org_id AND live.tbl_id=requested.tbl_id",
                        key_parameters,
                    )
                for relation in ("items", "axes", "axis_values", "periodicities"):
                    columns = RELATION_COLUMNS[relation]
                    for batch in _batches(rows_by_relation[relation], batch_size):
                        normalized = [normalize_sqlite_row(relation, row) for row in batch]
                        cursor.executemany(
                            build_insert_sql(relation),
                            [tuple(row[column] for column in columns) for row in normalized],
                        )

                row_counts: dict[str, int] = {}
                for relation in RELATION_ORDER:
                    cursor.execute(f"SELECT count(*) FROM {POSTGRES_RELATIONS[relation]}")
                    row_counts[relation] = int(cursor.fetchone()[0])
                row_counts.update({
                    "hydrated_tables_this_run": len(keys),
                    "hydration_payload_rows": sum(
                        len(rows_by_relation[name]) for name in required
                    ),
                })
                cursor.execute(
                    """INSERT INTO kosis_metadata_snapshots
                       (snapshot_id,source_sqlite_sha256,semantic_tables_sha256,
                        collected_at,migrated_at,row_counts,parent_snapshot_id,
                        hydration_sha256,source_kind,is_active)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,
                               'selective_hydration',FALSE)""",
                    (
                        identifier, source_digest, active["semantic_tables_sha256"],
                        migration_time, migration_time,
                        json.dumps(row_counts, sort_keys=True),
                        active["snapshot_id"], hydration_digest,
                    ),
                )
                cursor.execute(
                    """INSERT INTO kosis_snapshot_tables
                       (snapshot_id,org_id,tbl_id,tbl_name,category_path,
                        search_document,unit_hints,metadata_version,updated_at)
                       SELECT %s,org_id,tbl_id,tbl_name,category_path,
                              search_document,unit_hints,metadata_version,updated_at
                       FROM kosis_snapshot_tables WHERE snapshot_id=%s""",
                    (identifier, active["snapshot_id"]),
                )
                cursor.execute("UPDATE kosis_metadata_snapshots SET is_active=FALSE WHERE is_active")
                cursor.execute(
                    "UPDATE kosis_metadata_snapshots SET is_active=TRUE WHERE snapshot_id=%s",
                    (identifier,),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {
            "snapshot_id": identifier,
            "source_sqlite_sha256": source_digest,
            "semantic_tables_sha256": active["semantic_tables_sha256"],
            "hydration_sha256": hydration_digest,
            "hydrated_tables": len(keys),
            "row_counts": row_counts,
        }

    def hydrate_top3(self, run_id: str | uuid.UUID, query_id: str) -> list[dict[str, Any]]:
        if self._metadata_guard_depth == 0:
            with self.metadata_read_guard():
                return self.hydrate_top3(run_id, query_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """SELECT snapshot.snapshot_id
                   FROM retrieval_runs retrieval_run
                   JOIN kosis_metadata_snapshots snapshot
                     ON snapshot.snapshot_id = retrieval_run.snapshot_id
                   WHERE retrieval_run.run_id=%s AND retrieval_run.query_id=%s""",
                (str(run_id), _text(query_id)),
            )
            state = cursor.fetchone()
            if state is None:
                raise KeyError(f"retrieval run not found: {run_id}/{query_id}")
            cursor.execute(HYDRATE_TOP3_SQL, (str(run_id), _text(query_id)))
            rows = cursor.fetchall()
        output = []
        for row in rows:
            value = row[0] if not isinstance(row, Mapping) else row["candidate_json"]
            output.append(json.loads(value) if isinstance(value, str) else dict(value))
        return output

    def hydrate_component_bundle(
        self, candidates: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Read active PostgreSQL metadata for an arbitrary reranked table pool.

        Unlike :meth:`hydrate_top3`, this method neither reads nor writes the
        retrieval audit tables and therefore has no rank-1..3 restriction.
        Only tables with ITEMs, periodicities, and a value for every official
        axis enter the coordinate-search component lists. Incomplete catalog
        entries remain visible in ``incomplete_tables`` for later hydration.
        """
        if not candidates:
            return {
                "tables": [], "items": [], "objects": [],
                "incomplete_tables": [],
            }
        if self._metadata_guard_depth == 0:
            with self.metadata_read_guard():
                return self.hydrate_component_bundle(candidates)

        # Keep metadata migration usable with requirements-postgres alone;
        # component normalization is loaded only by the coordinate-search path.
        from kosis_build_component_index import (
            canonicalize_unit,
            component_id,
            is_aggregate_name,
            unit_dimension,
        )

        requested: list[tuple[int, str, str]] = []
        source_by_order: dict[int, dict[str, Any]] = {}
        seen: set[tuple[str, str]] = set()
        for input_order, candidate in enumerate(candidates, 1):
            key = (_text(candidate.get("org_id")), _text(candidate.get("tbl_id")))
            if not all(key):
                raise ValueError("candidate org_id and tbl_id are required")
            if key in seen:
                raise ValueError(f"duplicate table candidate: {key}")
            seen.add(key)
            requested.append((input_order, *key))
            source_by_order[input_order] = dict(candidate)

        snapshot = self._guard_snapshot or self.active_snapshot()
        if snapshot is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        values_sql = ",".join(["(%s,%s,%s)"] * len(requested))
        parameters = tuple(value for row in requested for value in row)
        sql = HYDRATE_COMPONENT_BUNDLE_SQL.format(requested_values=values_sql)
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (*parameters, _text(snapshot["snapshot_id"])))
            rows = cursor.fetchall()

        tables: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        objects: list[dict[str, Any]] = []
        incomplete: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, Mapping):
                input_order = int(row["input_order"])
                value = row["component_bundle_json"]
            else:
                input_order = int(row[0])
                value = row[1]
            hydrated = json.loads(value) if isinstance(value, str) else dict(value)
            source = source_by_order[input_order]
            org_id = _text(hydrated.get("org_id"))
            tbl_id = _text(hydrated.get("tbl_id"))
            raw_items = list(hydrated.get("items") or [])
            raw_axes = list(hydrated.get("axes") or [])
            periodicity_rows = list(hydrated.get("periodicities") or [])
            missing_sections = []
            if not (org_id and tbl_id):
                missing_sections.append("table")
                org_id = _text(source.get("org_id"))
                tbl_id = _text(source.get("tbl_id"))
            if not raw_items:
                missing_sections.append("items")
            if not raw_axes:
                missing_sections.append("axes")
            elif any(not list(axis.get("values") or []) for axis in raw_axes):
                missing_sections.append("axis_values")
            if not periodicity_rows:
                missing_sections.append("periodicities")

            table_rank = int(source.get("rank") or input_order)
            source_scores = dict(source.get("scores") or {})
            reranker_score = source_scores.get(
                "reranker_score", source.get("reranker_score")
            )
            table = {
                "rank": table_rank,
                "org_id": org_id,
                "tbl_id": tbl_id,
                "tbl_name": _text(hydrated.get("tbl_name")),
                "category_path": _text(hydrated.get("category_path")),
                "candidate_score": reranker_score,
                "table_reranker_score": reranker_score,
                "reranker_score": reranker_score,
                "lexical_rank": source_scores.get(
                    "lexical_rank", source.get("lexical_rank")
                ),
                "dense_rank": source_scores.get(
                    "dense_rank", source.get("dense_rank")
                ),
                "rrf_score": source_scores.get(
                    "rrf_score", source.get("rrf_score")
                ),
                "prd_se": "|".join(sorted({
                    _text(periodicity.get("prd_se"))
                    for periodicity in periodicity_rows
                    if _text(periodicity.get("prd_se"))
                })),
                "periodicities": [dict(value) for value in periodicity_rows],
            }
            if missing_sections:
                incomplete.append({
                    **table,
                    "metadata_status": (
                        "table_missing" if "table" in missing_sections
                        else "catalog_only" if {
                            "items", "axes", "periodicities",
                        }.issubset(missing_sections)
                        else "partial"
                    ),
                    "missing_sections": missing_sections,
                })
                continue

            tables.append(table)
            common = {
                "org_id": org_id,
                "tbl_id": tbl_id,
                "tbl_name": table["tbl_name"],
                "category_path": table["category_path"],
                "prd_se": table["prd_se"],
            }
            for item in sorted(raw_items, key=lambda value: _text(value.get("item_id"))):
                itm_id = _text(item.get("item_id"))
                unit = _text(item.get("unit_name"))
                canonical_unit = canonicalize_unit(unit)
                items.append({
                    **common,
                    "component_id": component_id("item", org_id, tbl_id, itm_id),
                    "itm_id": itm_id,
                    "itm_name": _text(item.get("item_name")),
                    "unit": unit,
                    "canonical_unit": canonical_unit,
                    "unit_dimension": unit_dimension(canonical_unit),
                    "parent_code_id": _text(item.get("parent_item_id")),
                })
            for axis in sorted(
                raw_axes,
                key=lambda value: (
                    int(value.get("axis_order") or 0), _text(value.get("axis_id")),
                ),
            ):
                axis_order = int(axis["axis_order"])
                axis_id = _text(axis.get("axis_id"))
                axis_name = _text(axis.get("axis_name"))
                for axis_value in sorted(
                    axis.get("values") or [],
                    key=lambda value: _text(value.get("value_id")),
                ):
                    obj_code = _text(axis_value.get("value_id"))
                    obj_name = _text(axis_value.get("value_name"))
                    objects.append({
                        **common,
                        "component_id": component_id(
                            "obj", org_id, tbl_id, axis_order, axis_id, obj_code,
                        ),
                        "axis_order": axis_order,
                        "axis_id": axis_id,
                        "axis_name": axis_name,
                        "obj_code": obj_code,
                        "obj_name": obj_name,
                        "parent_code_id": _text(axis_value.get("parent_value_id")),
                        "is_aggregate": is_aggregate_name(obj_name),
                    })

        tables.sort(key=lambda row: (int(row["rank"]), row["org_id"], row["tbl_id"]))
        table_ranks = {
            (table["org_id"], table["tbl_id"]): int(table["rank"])
            for table in tables
        }
        items.sort(key=lambda row: (
            table_ranks[(row["org_id"], row["tbl_id"])],
            row["org_id"], row["tbl_id"], row["itm_id"],
        ))
        objects.sort(key=lambda row: (
            table_ranks[(row["org_id"], row["tbl_id"])],
            row["org_id"], row["tbl_id"], row["axis_order"],
            row["axis_id"], row["obj_code"],
        ))
        for embedding_row, item in enumerate(items):
            item["embedding_row"] = embedding_row
        for embedding_row, obj in enumerate(objects):
            obj["embedding_row"] = embedding_row
        incomplete.sort(key=lambda row: (
            int(row["rank"]), row["org_id"], row["tbl_id"],
        ))
        return {
            "tables": tables,
            "items": items,
            "objects": objects,
            "incomplete_tables": incomplete,
        }
