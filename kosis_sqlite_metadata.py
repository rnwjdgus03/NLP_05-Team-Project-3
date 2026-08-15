#!/usr/bin/env python3
"""Build and query an exact SQLite store for KOSIS tables, ITEMs and OBJ axes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from kosis_meta_coordinates import normalize_obj_name, normalize_periodicity
from prepare_kosis_mapping_input import canonicalize_unit, unit_dimension


SCHEMA_VERSION = "kosis-sqlite-metadata-v1"


def clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def normalized_name(value: object) -> str:
    return normalize_obj_name(unicodedata.normalize("NFKC", clean(value)))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> Iterable[dict[str, str]]:
    csv.field_size_limit(2 ** 31 - 1)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def axis_order(row: Mapping[str, str]) -> int | None:
    raw = clean(row.get("axis_order") or row.get("OBJ_ID_SN") or row.get("obj_level"))
    try:
        value = int(float(raw))
    except ValueError:
        return None
    return value if 1 <= value <= 8 else None


def is_item(row: Mapping[str, str]) -> bool:
    marker = clean(row.get("is_item") or row.get("IS_ITEM")).upper()
    axis_id = clean(row.get("axis_id") or row.get("OBJ_ID")).upper()
    return marker in {"Y", "TRUE", "1"} or axis_id == "ITEM"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS kosis_tables (
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            tbl_name TEXT NOT NULL DEFAULT '',
            normalized_tbl_name TEXT NOT NULL DEFAULT '',
            stat_id TEXT NOT NULL DEFAULT '',
            category_path TEXT NOT NULL DEFAULT '',
            organization_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (org_id, tbl_id)
        );

        CREATE TABLE IF NOT EXISTS kosis_items (
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            itm_id TEXT NOT NULL,
            itm_name TEXT NOT NULL DEFAULT '',
            normalized_itm_name TEXT NOT NULL DEFAULT '',
            unit_id TEXT NOT NULL DEFAULT '',
            unit_name TEXT NOT NULL DEFAULT '',
            canonical_unit TEXT NOT NULL DEFAULT '',
            unit_dimension TEXT NOT NULL DEFAULT '',
            parent_itm_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (org_id, tbl_id, itm_id),
            FOREIGN KEY (org_id, tbl_id) REFERENCES kosis_tables(org_id, tbl_id)
        );

        CREATE TABLE IF NOT EXISTS kosis_axes (
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            axis_order INTEGER NOT NULL,
            axis_id TEXT NOT NULL DEFAULT '',
            axis_name TEXT NOT NULL DEFAULT '',
            normalized_axis_name TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (org_id, tbl_id, axis_order),
            FOREIGN KEY (org_id, tbl_id) REFERENCES kosis_tables(org_id, tbl_id)
        );

        CREATE TABLE IF NOT EXISTS kosis_axis_values (
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            axis_order INTEGER NOT NULL,
            obj_code TEXT NOT NULL,
            obj_name TEXT NOT NULL DEFAULT '',
            normalized_obj_name TEXT NOT NULL DEFAULT '',
            parent_obj_code TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (org_id, tbl_id, axis_order, obj_code),
            FOREIGN KEY (org_id, tbl_id, axis_order)
                REFERENCES kosis_axes(org_id, tbl_id, axis_order)
        );

        CREATE TABLE IF NOT EXISTS kosis_periodicities (
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            prd_se TEXT NOT NULL,
            prd_range TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (org_id, tbl_id, prd_se),
            FOREIGN KEY (org_id, tbl_id) REFERENCES kosis_tables(org_id, tbl_id)
        );

        CREATE TABLE IF NOT EXISTS api_cache (
            request_hash TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            itm_id TEXT NOT NULL,
            obj_json TEXT NOT NULL,
            prd_se TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            response_json TEXT NOT NULL,
            response_sha256 TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS verified_mapping_cache (
            mapping_key TEXT PRIMARY KEY,
            claim_signature TEXT NOT NULL,
            org_id TEXT NOT NULL,
            tbl_id TEXT NOT NULL,
            itm_id TEXT NOT NULL,
            obj_json TEXT NOT NULL,
            prd_se TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            verified_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metadata_imports (
            source_sha256 TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            row_count INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tables_name ON kosis_tables(normalized_tbl_name);
        CREATE INDEX IF NOT EXISTS idx_items_name ON kosis_items(normalized_itm_name);
        CREATE INDEX IF NOT EXISTS idx_axis_values_name ON kosis_axis_values(normalized_obj_name);
        CREATE INDEX IF NOT EXISTS idx_axis_name ON kosis_axes(normalized_axis_name);
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata_info(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    connection.commit()


def upsert_table(connection: sqlite3.Connection, row: Mapping[str, str]) -> tuple[str, str] | None:
    org_id = clean(row.get("org_id") or row.get("ORG_ID") or row.get("OrgId"))
    tbl_id = clean(row.get("tbl_id") or row.get("TBL_ID") or row.get("TblId"))
    if not org_id or not tbl_id:
        return None
    tbl_name = clean(row.get("tbl_name") or row.get("TBL_NM") or row.get("TBL_NM_KOR"))
    category = clean(row.get("category_path") or row.get("path"))
    stat_id = clean(row.get("stat_id") or row.get("STAT_ID"))
    organization = clean(row.get("organization_name") or row.get("ORG_NM"))
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO kosis_tables(
            org_id, tbl_id, tbl_name, normalized_tbl_name, stat_id,
            category_path, organization_name, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(org_id, tbl_id) DO UPDATE SET
            tbl_name=CASE WHEN excluded.tbl_name != '' THEN excluded.tbl_name ELSE kosis_tables.tbl_name END,
            normalized_tbl_name=CASE WHEN excluded.normalized_tbl_name != '' THEN excluded.normalized_tbl_name ELSE kosis_tables.normalized_tbl_name END,
            stat_id=CASE WHEN excluded.stat_id != '' THEN excluded.stat_id ELSE kosis_tables.stat_id END,
            category_path=CASE WHEN excluded.category_path != '' THEN excluded.category_path ELSE kosis_tables.category_path END,
            organization_name=CASE WHEN excluded.organization_name != '' THEN excluded.organization_name ELSE kosis_tables.organization_name END,
            updated_at=excluded.updated_at
        """,
        (org_id, tbl_id, tbl_name, normalized_name(tbl_name), stat_id, category, organization, now),
    )
    return org_id, tbl_id


def import_table_index(connection: sqlite3.Connection, path: Path) -> int:
    count = 0
    for row in read_csv(path):
        if upsert_table(connection, row):
            count += 1
    connection.commit()
    return count


def upsert_meta_rows(
    connection: sqlite3.Connection, rows: Iterable[Mapping[str, str]]
) -> int:
    """Upsert already-normalized KOSIS metadata rows into the exact store.

    Keeping the row-level import separate from the CSV checkpoint importer lets
    online metadata hydration commit one table at a time without repeatedly
    hashing and re-importing a growing checkpoint file.
    """
    count = 0
    periodicities: set[tuple[str, str, str, str]] = set()
    for row in rows:
        table_key = upsert_table(connection, row)
        if not table_key:
            continue
        org_id, tbl_id = table_key
        code_id = clean(row.get("code_id") or row.get("ITM_ID") or row.get("itm_id"))
        code_name = clean(row.get("code_name") or row.get("ITM_NM") or row.get("itm_name"))
        if not code_id:
            continue
        if is_item(row):
            unit_name = clean(row.get("unit_name") or row.get("UNIT_NM") or row.get("unit"))
            canonical = canonicalize_unit(unit_name)
            connection.execute(
                """
                INSERT INTO kosis_items(
                    org_id, tbl_id, itm_id, itm_name, normalized_itm_name,
                    unit_id, unit_name, canonical_unit, unit_dimension, parent_itm_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, tbl_id, itm_id) DO UPDATE SET
                    itm_name=excluded.itm_name,
                    normalized_itm_name=excluded.normalized_itm_name,
                    unit_id=excluded.unit_id,
                    unit_name=excluded.unit_name,
                    canonical_unit=excluded.canonical_unit,
                    unit_dimension=excluded.unit_dimension,
                    parent_itm_id=excluded.parent_itm_id
                """,
                (
                    org_id, tbl_id, code_id, code_name, normalized_name(code_name),
                    clean(row.get("unit_id") or row.get("UNIT_ID")), unit_name, canonical,
                    unit_dimension(canonical),
                    clean(row.get("parent_code_id") or row.get("UP_ITM_ID")),
                ),
            )
        else:
            order = axis_order(row)
            if order is None:
                continue
            axis_id = clean(row.get("axis_id") or row.get("OBJ_ID"))
            axis_name = clean(row.get("axis_name") or row.get("OBJ_NM"))
            connection.execute(
                """
                INSERT INTO kosis_axes(
                    org_id, tbl_id, axis_order, axis_id, axis_name, normalized_axis_name
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, tbl_id, axis_order) DO UPDATE SET
                    axis_id=CASE WHEN excluded.axis_id != '' THEN excluded.axis_id ELSE kosis_axes.axis_id END,
                    axis_name=CASE WHEN excluded.axis_name != '' THEN excluded.axis_name ELSE kosis_axes.axis_name END,
                    normalized_axis_name=CASE WHEN excluded.normalized_axis_name != '' THEN excluded.normalized_axis_name ELSE kosis_axes.normalized_axis_name END
                """,
                (org_id, tbl_id, order, axis_id, axis_name, normalized_name(axis_name)),
            )
            connection.execute(
                """
                INSERT INTO kosis_axis_values(
                    org_id, tbl_id, axis_order, obj_code, obj_name,
                    normalized_obj_name, parent_obj_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, tbl_id, axis_order, obj_code) DO UPDATE SET
                    obj_name=excluded.obj_name,
                    normalized_obj_name=excluded.normalized_obj_name,
                    parent_obj_code=excluded.parent_obj_code
                """,
                (
                    org_id, tbl_id, order, code_id, code_name, normalized_name(code_name),
                    clean(row.get("parent_code_id") or row.get("UP_ITM_ID")),
                ),
            )
        ranges = clean(row.get("prd_ranges"))
        for raw in clean(row.get("prd_se_list")).split("|"):
            prd_se = normalize_periodicity(raw)
            if prd_se:
                periodicities.add((org_id, tbl_id, prd_se, ranges))
        count += 1

    connection.executemany(
        """
        INSERT INTO kosis_periodicities(org_id, tbl_id, prd_se, prd_range)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(org_id, tbl_id, prd_se) DO UPDATE SET prd_range=excluded.prd_range
        """,
        sorted(periodicities),
    )
    connection.commit()
    return count


def import_meta_index(connection: sqlite3.Connection, path: Path) -> int:
    source_hash = sha256(path)
    existing = connection.execute(
        "SELECT row_count FROM metadata_imports WHERE source_sha256=?", (source_hash,)
    ).fetchone()
    if existing:
        return int(existing["row_count"])

    count = upsert_meta_rows(connection, read_csv(path))
    connection.execute(
        "INSERT INTO metadata_imports(source_sha256, source_path, imported_at, row_count) VALUES (?, ?, ?, ?)",
        (source_hash, str(path), datetime.now(timezone.utc).isoformat(), count),
    )
    connection.commit()
    return count


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = (
        "kosis_tables", "kosis_items", "kosis_axes", "kosis_axis_values",
        "kosis_periodicities", "api_cache", "verified_mapping_cache", "metadata_imports",
    )
    result = {
        name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        for name in names
    }
    result.update({
        "tables_with_items": int(connection.execute(
            "SELECT COUNT(DISTINCT org_id || ':' || tbl_id) FROM kosis_items"
        ).fetchone()[0]),
        "tables_with_axes": int(connection.execute(
            "SELECT COUNT(DISTINCT org_id || ':' || tbl_id) FROM kosis_axes"
        ).fetchone()[0]),
        "tables_with_periodicity": int(connection.execute(
            "SELECT COUNT(DISTINCT org_id || ':' || tbl_id) FROM kosis_periodicities"
        ).fetchone()[0]),
    })
    return result


def write_manifest(db_path: Path, sources: list[Path], connection: sqlite3.Connection) -> Path:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path),
        "database_sha256": sha256(db_path),
        "sources": {str(path): sha256(path) for path in sources},
        "counts": counts(connection),
    }
    path = db_path.with_suffix(db_path.suffix + ".manifest.json")
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--table-index", type=Path)
    parser.add_argument("--meta-index", type=Path, action="append", default=[])
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.reset and args.db.exists():
        args.db.unlink()
    connection = connect(args.db)
    create_schema(connection)
    sources: list[Path] = []
    if args.table_index:
        import_table_index(connection, args.table_index)
        sources.append(args.table_index)
    for path in args.meta_index:
        import_meta_index(connection, path)
        sources.append(path)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    manifest = write_manifest(args.db, sources, connection)
    print(json.dumps({"db": str(args.db), "manifest": str(manifest), "counts": counts(connection)},
                     ensure_ascii=False, indent=2))
    connection.close()


if __name__ == "__main__":
    main()
