#!/usr/bin/env python3
"""Build a lossless ITEM/OBJ component index from KOSIS metadata.

The index deliberately stores components, not pre-expanded coordinates.  This
keeps every ITEM and every OBJ value while avoiding the ITEM x OBJ1 x ...
cartesian product.  ``embedding_row`` in each parquet file is the exact row in
the corresponding NumPy matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from kosis_meta_coordinates import (
    _axis_order,
    _first,
    _is_item,
    is_aggregate_name,
    read_csv_rows,
)
from kosis_semantic_search import DEFAULT_EMBEDDING_MODEL, file_sha256
from prepare_kosis_mapping_input import canonicalize_unit, unit_dimension


SCHEMA_VERSION = "kosis-component-index-v2"
MANIFEST_NAME = "component_manifest.json"
ITEMS_NAME = "items.parquet"
OBJECTS_NAME = "obj_values.parquet"
ITEM_EMBEDDINGS_NAME = "item_embeddings.npy"
OBJECT_EMBEDDINGS_NAME = "obj_embeddings.npy"
QUARANTINE_NAME = "quarantine.parquet"
BUILD_STATE_NAME = "component_build_state.json"

ITEM_COLUMNS = (
    "component_id", "embedding_row", "org_id", "tbl_id", "tbl_name", "category_path",
    "itm_id", "itm_name", "unit", "canonical_unit", "unit_dimension",
    "parent_code_id", "prd_se",
)
OBJ_COLUMNS = (
    "component_id", "embedding_row", "org_id", "tbl_id", "tbl_name", "category_path",
    "axis_order", "axis_id", "axis_name", "obj_code", "obj_name",
    "parent_code_id", "is_aggregate", "prd_se",
)
QUARANTINE_COLUMNS = (
    "source_row", "reason", "org_id", "tbl_id", "tbl_name", "axis_id",
    "axis_name", "axis_order_raw", "code_id", "code_name", "is_item",
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def component_id(kind: str, *parts: Any) -> str:
    payload = "|".join((kind, *(_text(part) for part in parts)))
    return f"{kind}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:20]}"


def load_prd_se_by_table(path: str | Path | None) -> dict[tuple[str, str], str]:
    """Load optional table periodicity using the same common field aliases."""
    if not path:
        return {}
    result: dict[tuple[str, str], str] = {}
    for row in read_csv_rows(path):
        org_id = _text(row.get("org_id") or row.get("ORG_ID"))
        tbl_id = _text(row.get("tbl_id") or row.get("TBL_ID"))
        prd_se = _text(
            row.get("prd_se_list") or row.get("PRD_SE_LIST")
            or row.get("prd_se") or row.get("PRD_SE")
        )
        if org_id and tbl_id and prd_se:
            result.setdefault((org_id, tbl_id), prd_se)
    return result


def normalize_components(
    meta_rows: Iterable[Mapping[str, Any]],
    *,
    prd_se_by_table: Mapping[tuple[str, str], str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Backward-compatible ITEM/OBJ-only view of :func:`classify_components`."""
    items, objects, _, _ = classify_components(
        meta_rows, prd_se_by_table=prd_se_by_table,
    )
    return items, objects


def classify_components(
    meta_rows: Iterable[Mapping[str, Any]],
    *,
    prd_se_by_table: Mapping[tuple[str, str], str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Classify every source row without axis loss.

    Duplicate component rows are counted separately because the parquet files
    intentionally contain unique components. Malformed rows and OBJ rows whose
    axis is missing/outside 1..8 are retained in quarantine.
    """
    source_rows = list(meta_rows)
    periods = prd_se_by_table or {}
    items: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    duplicate_count = 0
    seen_items: set[tuple[str, str, str]] = set()
    seen_objects: set[tuple[str, str, int, str]] = set()

    for source_row, source in enumerate(source_rows):
        row = dict(source)
        org_id = _first(row, "org_id", "ORG_ID")
        tbl_id = _first(row, "tbl_id", "TBL_ID")
        code_id = _first(row, "code_id", "ITM_ID", "itm_id", "code")
        table_key = (org_id, tbl_id)
        common = {
            "org_id": org_id,
            "tbl_id": tbl_id,
            "tbl_name": _first(row, "tbl_name", "TBL_NM"),
            "category_path": _first(row, "category_path", "path"),
            "parent_code_id": _first(
                row, "parent_code_id", "PARENT_CODE_ID", "parent_id"
            ),
            "prd_se": _text(
                periods.get(table_key)
                or row.get("prd_se_list") or row.get("PRD_SE_LIST")
                or row.get("prd_se") or row.get("PRD_SE")
            ),
        }
        quarantine_base = {
            "source_row": source_row,
            "org_id": org_id,
            "tbl_id": tbl_id,
            "tbl_name": common["tbl_name"],
            "axis_id": _first(row, "axis_id", "OBJ_ID", "obj_id"),
            "axis_name": _first(row, "axis_name", "OBJ_NM", "obj_nm"),
            "axis_order_raw": _first(row, "axis_order", "OBJ_ID_SN", "obj_id_sn", "obj_level"),
            "code_id": code_id,
            "code_name": _first(row, "code_name", "ITM_NM", "itm_nm", "name"),
            "is_item": _first(row, "is_item", "IS_ITEM"),
        }
        if not (org_id and tbl_id and code_id):
            quarantine.append({**quarantine_base, "reason": "MISSING_CORE_FIELD"})
            continue

        if _is_item(row):
            dedupe_key = (org_id, tbl_id, code_id)
            if dedupe_key in seen_items:
                duplicate_count += 1
                continue
            seen_items.add(dedupe_key)
            unit = _first(row, "unit_name", "UNIT_NM", "unit")
            canonical_unit = canonicalize_unit(unit)
            items.append({
                **common,
                "component_id": component_id("item", org_id, tbl_id, code_id),
                "itm_id": code_id,
                "itm_name": quarantine_base["code_name"],
                "unit": unit,
                "canonical_unit": canonical_unit,
                "unit_dimension": unit_dimension(canonical_unit),
            })
            continue

        axis_order = _axis_order(row)
        if axis_order is None:
            raw = quarantine_base["axis_order_raw"]
            reason = "MISSING_AXIS_ORDER" if not raw else "AXIS_ORDER_OUT_OF_RANGE"
            quarantine.append({**quarantine_base, "reason": reason})
            continue
        # KOSIS can expose alternative OBJ_ID definitions in the same objL slot.
        dedupe_key = (
            org_id, tbl_id, axis_order, quarantine_base["axis_id"], code_id,
        )
        if dedupe_key in seen_objects:
            duplicate_count += 1
            continue
        seen_objects.add(dedupe_key)
        objects.append({
            **common,
            "component_id": component_id(
                "obj", org_id, tbl_id, axis_order,
                quarantine_base["axis_id"], code_id,
            ),
            "axis_order": axis_order,
            "axis_id": quarantine_base["axis_id"],
            "axis_name": quarantine_base["axis_name"],
            "obj_code": code_id,
            "obj_name": quarantine_base["code_name"],
            "is_aggregate": is_aggregate_name(quarantine_base["code_name"]),
        })

    for embedding_row, row in enumerate(items):
        row["embedding_row"] = embedding_row
    for embedding_row, row in enumerate(objects):
        row["embedding_row"] = embedding_row
    return items, objects, quarantine, duplicate_count


def validate_conservation(
    *, source_row_count: int, item_count: int, obj_count: int,
    quarantine_count: int, duplicate_count: int,
) -> None:
    """Assert that every source row has exactly one terminal classification."""
    accounted = item_count + obj_count + quarantine_count + duplicate_count
    if source_row_count != accounted:
        raise ValueError(
            f"source-row conservation failed: source={source_row_count} accounted={accounted} "
            f"(items={item_count}, objects={obj_count}, quarantine={quarantine_count}, "
            f"duplicates={duplicate_count})"
        )


def item_document(row: Mapping[str, Any]) -> str:
    fields = (
        ("통계표", row.get("tbl_name")),
        ("분류 경로", row.get("category_path")),
        ("항목", row.get("itm_name")),
        ("단위", row.get("canonical_unit") or row.get("unit")),
        ("수록주기", row.get("prd_se")),
    )
    return " | ".join(f"{label}: {_text(value)}" for label, value in fields if _text(value))


def obj_document(row: Mapping[str, Any]) -> str:
    fields = (
        ("통계표", row.get("tbl_name")),
        ("분류 경로", row.get("category_path")),
        ("분류축", row.get("axis_name")),
        ("분류값", row.get("obj_name")),
        ("수록주기", row.get("prd_se")),
    )
    return " | ".join(f"{label}: {_text(value)}" for label, value in fields if _text(value))


def attach_embedding_rows(rows: Sequence[Mapping[str, Any]], vectors: np.ndarray) -> None:
    """Validate the parquet-row/embedding-row contract before persistence."""
    if vectors.ndim != 2:
        raise ValueError(f"embeddings must be 2-D, got shape={vectors.shape}")
    if len(rows) != vectors.shape[0]:
        raise ValueError(f"row/vector mismatch: rows={len(rows)} vectors={vectors.shape[0]}")
    expected = list(range(len(rows)))
    actual = [int(row.get("embedding_row", -1)) for row in rows]
    if actual != expected:
        raise ValueError("embedding_row must be contiguous and match parquet row order")


def build_manifest(
    *,
    embedding_model: str,
    embedding_dimension: int,
    source_meta_file: str | Path,
    source_meta_sha256: str,
    source_row_count: int,
    table_count: int,
    item_count: int,
    obj_count: int,
    quarantine_count: int,
    duplicate_count: int,
    embedding_dtype: str,
    checksums: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "embedding_model": embedding_model,
        "embedding_dimension": int(embedding_dimension),
        "normalized": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_meta_file": str(source_meta_file),
        "source_meta_sha256": source_meta_sha256,
        "source_row_count": int(source_row_count),
        "table_count": int(table_count),
        "item_count": int(item_count),
        "obj_count": int(obj_count),
        "quarantine_count": int(quarantine_count),
        "duplicate_count": int(duplicate_count),
        "embedding_dtype": embedding_dtype,
        "files": {
            "items": ITEMS_NAME,
            "obj_values": OBJECTS_NAME,
            "item_embeddings": ITEM_EMBEDDINGS_NAME,
            "obj_embeddings": OBJECT_EMBEDDINGS_NAME,
            "quarantine": QUARANTINE_NAME,
        },
        "sha256": dict(checksums or {}),
    }


def artifact_checksums(output_dir: str | Path) -> dict[str, str]:
    root = Path(output_dir)
    return {
        name: file_sha256(root / name)
        for name in (
            ITEMS_NAME, OBJECTS_NAME, QUARANTINE_NAME,
            ITEM_EMBEDDINGS_NAME, OBJECT_EMBEDDINGS_NAME,
        )
    }


def reusable_manifest(
    output_dir: str | Path, *, source_sha256: str,
    embedding_model: str, embedding_dtype: str,
) -> dict[str, Any] | None:
    """Return a manifest only when every persisted artifact still verifies."""
    root = Path(output_dir)
    path = root / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != SCHEMA_VERSION
            or manifest.get("source_meta_sha256") != source_sha256
            or manifest.get("embedding_model") != embedding_model
            or manifest.get("embedding_dtype") != embedding_dtype
        ):
            return None
        expected = manifest.get("sha256") or {}
        return manifest if expected == artifact_checksums(root) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Parquet 저장에는 pandas와 pyarrow가 필요합니다.") from exc
    return pd


def _encode_to_npy(
    embedder,
    rows: Sequence[Mapping[str, Any]],
    document_builder,
    output_path: str | Path,
    *,
    batch_size: int,
    dtype: str,
    resume: bool = False,
) -> np.ndarray:
    """Encode bounded batches directly into an atomic NumPy memmap."""
    if not rows:
        raise ValueError("임베딩할 구성요소가 0개입니다.")
    output = Path(output_path)
    partial = output.with_name(output.name + ".partial")
    progress_path = output.with_name(output.name + ".progress.json")
    if output.exists():
        existing = np.load(output, mmap_mode="r", allow_pickle=False)
        if existing.ndim == 2 and existing.shape[0] == len(rows) and str(existing.dtype) == dtype:
            return existing
        if not resume:
            output.unlink()
        else:
            raise ValueError(f"completed embedding file is incompatible: {output}")
    if not resume:
        partial.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)
    matrix = None
    dimension = 0
    start_row = 0
    if resume and partial.exists() and progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        matrix = np.load(partial, mmap_mode="r+", allow_pickle=False)
        start_row = int(progress.get("completed_rows") or 0)
        if (
            matrix.ndim != 2
            or matrix.shape[0] != len(rows)
            or str(matrix.dtype) != dtype
            or not 0 <= start_row <= len(rows)
        ):
            raise ValueError(f"partial embedding checkpoint is incompatible: {partial}")
        dimension = int(matrix.shape[1])
        print(f"resume={output.name} rows={start_row}/{len(rows)}", flush=True)
    try:
        for start in range(start_row, len(rows), max(1, batch_size)):
            stop = min(len(rows), start + max(1, batch_size))
            documents = [document_builder(row) for row in rows[start:stop]]
            vectors = np.asarray(
                embedder.encode(
                    documents,
                    batch_size=max(1, batch_size),
                    show_progress_bar=False,
                ),
                dtype=dtype,
            )
            if vectors.ndim != 2 or vectors.shape[0] != len(documents):
                raise ValueError(
                    f"unexpected embedding shape={vectors.shape}; documents={len(documents)}"
                )
            if matrix is None:
                dimension = int(vectors.shape[1])
                matrix = np.lib.format.open_memmap(
                    partial,
                    mode="w+",
                    dtype=dtype,
                    shape=(len(rows), dimension),
                )
            elif vectors.shape[1] != dimension:
                raise ValueError(
                    f"embedding dimension changed: expected={dimension} got={vectors.shape[1]}"
                )
            matrix[start:stop] = vectors
            matrix.flush()
            progress_tmp = progress_path.with_suffix(progress_path.suffix + ".tmp")
            progress_tmp.write_text(
                json.dumps({"completed_rows": stop, "row_count": len(rows), "dtype": dtype}),
                encoding="utf-8",
            )
            progress_tmp.replace(progress_path)
            print(f"embedding={output.name} rows={stop}/{len(rows)}", flush=True)
        del matrix
        partial.replace(output)
        progress_path.unlink(missing_ok=True)
    except Exception:
        if not resume:
            partial.unlink(missing_ok=True)
            progress_path.unlink(missing_ok=True)
        raise
    return np.load(output, mmap_mode="r", allow_pickle=False)


def _parquet_schema(columns: Sequence[str]):
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Parquet 저장에는 pyarrow가 필요합니다.") from exc
    integer_columns = {"embedding_row", "axis_order", "source_row"}
    boolean_columns = {"is_aggregate"}
    return pa.schema([
        pa.field(
            column,
            pa.int64() if column in integer_columns
            else pa.bool_() if column in boolean_columns
            else pa.string(),
            nullable=False,
        )
        for column in columns
    ])


def _write_parquet_rows(
    output: Path, columns: Sequence[str], batches: Iterable[Sequence[Mapping[str, Any]]],
) -> int:
    """Write deterministic row batches without retaining the full dataset in RAM."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Parquet 저장에는 pyarrow가 필요합니다.") from exc
    partial = output.with_name(output.name + ".partial")
    partial.unlink(missing_ok=True)
    schema = _parquet_schema(columns)
    count = 0
    writer = pq.ParquetWriter(partial, schema, compression="zstd")
    try:
        for rows in batches:
            normalized = [
                {
                    column: (
                        int(row.get(column) or 0)
                        if column in {"embedding_row", "axis_order", "source_row"}
                        else bool(row.get(column))
                        if column == "is_aggregate"
                        else _text(row.get(column))
                    )
                    for column in columns
                }
                for row in rows
            ]
            if not normalized:
                continue
            writer.write_table(pa.Table.from_pylist(normalized, schema=schema))
            count += len(normalized)
    except Exception:
        writer.close()
        partial.unlink(missing_ok=True)
        raise
    writer.close()
    partial.replace(output)
    return count


def _query_batches(
    connection: sqlite3.Connection, query: str, transform,
    *, batch_size: int = 20_000,
) -> Iterable[list[dict[str, Any]]]:
    cursor = connection.execute(query)
    embedding_row = 0
    while True:
        source = cursor.fetchmany(batch_size)
        if not source:
            break
        output = []
        for raw in source:
            row = transform(dict(raw), embedding_row)
            output.append(row)
            embedding_row += 1
        yield output


def _encode_parquet_to_npy(
    embedder, parquet_path: Path, document_builder, output_path: Path,
    *, row_count: int, batch_size: int, dtype: str, resume: bool,
) -> np.ndarray:
    """Encode a Parquet dataset batchwise while enforcing its embedding_row contract."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Parquet 검색에는 pyarrow가 필요합니다.") from exc
    output = Path(output_path)
    partial = output.with_name(output.name + ".partial")
    progress_path = output.with_name(output.name + ".progress.json")
    if output.exists():
        existing = np.load(output, mmap_mode="r", allow_pickle=False)
        if existing.ndim == 2 and existing.shape[0] == row_count and str(existing.dtype) == dtype:
            return existing
        if resume:
            raise ValueError(f"completed embedding file is incompatible: {output}")
        output.unlink()
    if not resume:
        partial.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)
    matrix = None
    completed = 0
    dimension = 0
    if resume and partial.exists() and progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        matrix = np.load(partial, mmap_mode="r+", allow_pickle=False)
        completed = int(progress.get("completed_rows") or 0)
        if (
            matrix.ndim != 2 or matrix.shape[0] != row_count
            or str(matrix.dtype) != dtype or not 0 <= completed <= row_count
        ):
            raise ValueError(f"partial embedding checkpoint is incompatible: {partial}")
        dimension = int(matrix.shape[1])
        print(f"resume={output.name} rows={completed}/{row_count}", flush=True)
    current = 0
    parquet = pq.ParquetFile(parquet_path)
    for record_batch in parquet.iter_batches(batch_size=max(1, batch_size)):
        rows = record_batch.to_pylist()
        batch_start = current
        batch_stop = current + len(rows)
        current = batch_stop
        if batch_stop <= completed:
            continue
        if batch_start < completed:
            rows = rows[completed - batch_start:]
            batch_start = completed
        expected_rows = list(range(batch_start, batch_start + len(rows)))
        actual_rows = [int(row.get("embedding_row", -1)) for row in rows]
        if actual_rows != expected_rows:
            raise ValueError("Parquet embedding_row order does not match physical row order")
        documents = [document_builder(row) for row in rows]
        vectors = np.asarray(
            embedder.encode(
                documents, batch_size=max(1, batch_size), show_progress_bar=False,
            ),
            dtype=dtype,
        )
        if vectors.ndim != 2 or vectors.shape[0] != len(rows):
            raise ValueError(f"unexpected embedding shape={vectors.shape}")
        if matrix is None:
            dimension = int(vectors.shape[1])
            matrix = np.lib.format.open_memmap(
                partial, mode="w+", dtype=dtype, shape=(row_count, dimension),
            )
        elif vectors.shape[1] != dimension:
            raise ValueError("embedding dimension changed during build")
        matrix[batch_start:batch_stop] = vectors
        matrix.flush()
        progress_tmp = progress_path.with_suffix(progress_path.suffix + ".tmp")
        progress_tmp.write_text(
            json.dumps({"completed_rows": batch_stop, "row_count": row_count, "dtype": dtype}),
            encoding="utf-8",
        )
        progress_tmp.replace(progress_path)
        print(f"embedding={output.name} rows={batch_stop}/{row_count}", flush=True)
    if current != row_count or matrix is None:
        raise ValueError(f"Parquet row count changed: expected={row_count} actual={current}")
    del matrix
    partial.replace(output)
    progress_path.unlink(missing_ok=True)
    return np.load(output, mmap_mode="r", allow_pickle=False)


def build_component_index_from_sqlite(
    sqlite_meta_db: str | Path,
    output_dir: str | Path,
    *,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    device: str | None = None,
    batch_size: int = 128,
    embedding_dtype: str = "float16",
    reset: bool = False,
    resume: bool = False,
    embedder=None,
) -> dict[str, Any]:
    """Build the component index from a normalized SQLite DB with bounded RAM."""
    if embedding_dtype not in {"float16", "float32"}:
        raise ValueError("embedding_dtype must be float16 or float32")
    source = Path(sqlite_meta_db)
    destination = Path(output_dir)
    if not source.is_file():
        raise FileNotFoundError(source)
    if reset and destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        state_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta_csv_import_state'"
        ).fetchone()
        if state_table is None:
            raise ValueError("SQLite DB was not created by the streaming metadata importer")
        state = connection.execute(
            "SELECT * FROM meta_csv_import_state WHERE singleton=1"
        ).fetchone()
        if state is None or not int(state["completed"]):
            raise ValueError("metadata CSV import is incomplete; resume the importer first")
        source_sha256 = str(state["source_sha256"])
        source_rows = int(state["completed_rows"])
        cached = reusable_manifest(
            destination, source_sha256=source_sha256,
            embedding_model=embedding_model, embedding_dtype=embedding_dtype,
        )
        if cached is not None:
            return cached
        item_count = int(connection.execute("SELECT count(*) FROM items").fetchone()[0])
        obj_count = int(connection.execute("SELECT count(*) FROM axis_values").fetchone()[0])
        quarantine_count = int(
            connection.execute("SELECT count(*) FROM meta_csv_quarantine").fetchone()[0]
        )
        duplicate_count = source_rows - item_count - obj_count - quarantine_count
        if duplicate_count < 0:
            raise ValueError("source-row conservation failed for imported SQLite metadata")
        item_query = """
            SELECT i.*,t.tbl_name,t.category_path,
                   COALESCE((SELECT group_concat(prd_se,'|') FROM
                     (SELECT prd_se FROM periodicities p WHERE p.org_id=i.org_id
                      AND p.tbl_id=i.tbl_id ORDER BY prd_se)), '') AS prd_se
            FROM items i JOIN tables t USING(org_id,tbl_id)
            ORDER BY i.org_id,i.tbl_id,i.item_id
        """
        obj_query = """
            SELECT v.*,a.axis_name,a.axis_order,t.tbl_name,t.category_path,
                   COALESCE((SELECT group_concat(prd_se,'|') FROM
                     (SELECT prd_se FROM periodicities p WHERE p.org_id=v.org_id
                      AND p.tbl_id=v.tbl_id ORDER BY prd_se)), '') AS prd_se
            FROM axis_values v JOIN axes a USING(org_id,tbl_id,axis_id)
            JOIN tables t USING(org_id,tbl_id)
            ORDER BY v.org_id,v.tbl_id,a.axis_order,v.axis_id,v.value_id
        """

        def item_transform(row: dict[str, Any], embedding_row: int) -> dict[str, Any]:
            canonical_unit = canonicalize_unit(row.get("unit_name"))
            return {
                "component_id": component_id("item", row["org_id"], row["tbl_id"], row["item_id"]),
                "embedding_row": embedding_row, "org_id": row["org_id"],
                "tbl_id": row["tbl_id"], "tbl_name": row["tbl_name"],
                "category_path": row["category_path"], "itm_id": row["item_id"],
                "itm_name": row["item_name"], "unit": row["unit_name"],
                "canonical_unit": canonical_unit,
                "unit_dimension": unit_dimension(canonical_unit),
                "parent_code_id": row["parent_item_id"], "prd_se": row["prd_se"],
            }

        def obj_transform(row: dict[str, Any], embedding_row: int) -> dict[str, Any]:
            return {
                "component_id": component_id(
                    "obj", row["org_id"], row["tbl_id"], row["axis_order"],
                    row["axis_id"], row["value_id"],
                ),
                "embedding_row": embedding_row, "org_id": row["org_id"],
                "tbl_id": row["tbl_id"], "tbl_name": row["tbl_name"],
                "category_path": row["category_path"], "axis_order": row["axis_order"],
                "axis_id": row["axis_id"], "axis_name": row["axis_name"],
                "obj_code": row["value_id"], "obj_name": row["value_name"],
                "parent_code_id": row["parent_value_id"],
                "is_aggregate": is_aggregate_name(row["value_name"]), "prd_se": row["prd_se"],
            }

        written_items = _write_parquet_rows(
            destination / ITEMS_NAME, ITEM_COLUMNS,
            _query_batches(connection, item_query, item_transform),
        )
        written_objects = _write_parquet_rows(
            destination / OBJECTS_NAME, OBJ_COLUMNS,
            _query_batches(connection, obj_query, obj_transform),
        )
        quarantine_query = """
            SELECT source_row,reason,org_id,tbl_id,tbl_name,axis_id,axis_name,
                   axis_order_raw,code_id,code_name,is_item
            FROM meta_csv_quarantine ORDER BY source_row
        """
        _write_parquet_rows(
            destination / QUARANTINE_NAME, QUARANTINE_COLUMNS,
            _query_batches(connection, quarantine_query, lambda row, _: row),
        )
        if written_items != item_count or written_objects != obj_count:
            raise ValueError("SQLite/Parquet component row counts differ")
        table_count = int(connection.execute(
            """SELECT count(*) FROM tables t WHERE EXISTS
               (SELECT 1 FROM items i WHERE i.org_id=t.org_id AND i.tbl_id=t.tbl_id)
               OR EXISTS (SELECT 1 FROM axes a WHERE a.org_id=t.org_id AND a.tbl_id=t.tbl_id)"""
        ).fetchone()[0])

    build_state = {
        "schema_version": SCHEMA_VERSION, "source_meta_sha256": source_sha256,
        "embedding_model": embedding_model, "embedding_dtype": embedding_dtype,
        "item_count": item_count, "obj_count": obj_count,
    }
    state_path = destination / BUILD_STATE_NAME
    if resume and state_path.exists():
        if json.loads(state_path.read_text(encoding="utf-8")) != build_state:
            raise ValueError("component build checkpoint does not match current input/config")
    state_path.write_text(json.dumps(build_state, ensure_ascii=False, indent=2), encoding="utf-8")
    if embedder is None:
        from kosis_semantic_search import SentenceTransformerEmbedder
        embedder = SentenceTransformerEmbedder(embedding_model, device=device)
    item_vectors = _encode_parquet_to_npy(
        embedder, destination / ITEMS_NAME, item_document,
        destination / ITEM_EMBEDDINGS_NAME, row_count=item_count,
        batch_size=batch_size, dtype=embedding_dtype, resume=resume,
    )
    obj_vectors = _encode_parquet_to_npy(
        embedder, destination / OBJECTS_NAME, obj_document,
        destination / OBJECT_EMBEDDINGS_NAME, row_count=obj_count,
        batch_size=batch_size, dtype=embedding_dtype, resume=resume,
    )
    if item_vectors.shape[1] != obj_vectors.shape[1]:
        raise ValueError("ITEM and OBJ embedding dimensions differ")
    manifest = build_manifest(
        embedding_model=embedding_model, embedding_dimension=item_vectors.shape[1],
        source_meta_file=source, source_meta_sha256=source_sha256,
        source_row_count=source_rows, table_count=table_count, item_count=item_count,
        obj_count=obj_count, quarantine_count=quarantine_count,
        duplicate_count=duplicate_count, embedding_dtype=embedding_dtype,
        checksums=artifact_checksums(destination),
    )
    manifest["build_mode"] = "streaming_sqlite"
    (destination / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    state_path.unlink(missing_ok=True)
    return manifest


def build_component_index(
    meta_index: str | Path,
    output_dir: str | Path,
    *,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    device: str | None = None,
    batch_size: int = 64,
    embedding_dtype: str = "float16",
    prd_se_source: str | Path | None = None,
    reset: bool = False,
    resume: bool = False,
    embedder=None,
) -> dict[str, Any]:
    if embedding_dtype not in {"float16", "float32"}:
        raise ValueError("embedding_dtype must be float16 or float32")
    source = Path(meta_index)
    destination = Path(output_dir)
    source_sha256 = file_sha256(source)
    if reset and destination.exists():
        shutil.rmtree(destination)
    if destination.exists() and any(destination.iterdir()):
        if not reset:
            cached = reusable_manifest(
                destination,
                source_sha256=source_sha256,
                embedding_model=embedding_model,
                embedding_dtype=embedding_dtype,
            )
            if cached is not None:
                return cached
        if not reset and not resume:
            raise FileExistsError(
                f"output directory is not empty or failed checksum validation: {destination}; "
                "use --resume or --reset"
            )
    destination.mkdir(parents=True, exist_ok=True)

    meta_rows = read_csv_rows(source)
    items, objects, quarantine, duplicate_count = classify_components(
        meta_rows,
        prd_se_by_table=load_prd_se_by_table(prd_se_source),
    )
    if not items or not objects:
        raise ValueError(f"ITEM/OBJ 구성요소가 부족합니다: items={len(items)} objects={len(objects)}")
    validate_conservation(
        source_row_count=len(meta_rows), item_count=len(items), obj_count=len(objects),
        quarantine_count=len(quarantine), duplicate_count=duplicate_count,
    )
    build_state_path = destination / BUILD_STATE_NAME
    build_state = {
        "schema_version": SCHEMA_VERSION,
        "source_meta_sha256": source_sha256,
        "embedding_model": embedding_model,
        "embedding_dtype": embedding_dtype,
        "item_count": len(items),
        "obj_count": len(objects),
    }
    if resume and build_state_path.exists():
        existing_state = json.loads(build_state_path.read_text(encoding="utf-8"))
        if existing_state != build_state:
            raise ValueError("component build checkpoint does not match current input/config")
    build_state_path.write_text(
        json.dumps(build_state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if embedder is None:
        from kosis_semantic_search import SentenceTransformerEmbedder
        embedder = SentenceTransformerEmbedder(embedding_model, device=device)

    item_vectors = _encode_to_npy(
        embedder, items, item_document, destination / ITEM_EMBEDDINGS_NAME,
        batch_size=batch_size, dtype=embedding_dtype, resume=resume,
    )
    obj_vectors = _encode_to_npy(
        embedder, objects, obj_document, destination / OBJECT_EMBEDDINGS_NAME,
        batch_size=batch_size, dtype=embedding_dtype, resume=resume,
    )
    if item_vectors.shape[1] != obj_vectors.shape[1]:
        raise ValueError("ITEM and OBJ embedding dimensions differ")
    attach_embedding_rows(items, item_vectors)
    attach_embedding_rows(objects, obj_vectors)

    pd = _require_pandas()
    pd.DataFrame(items, columns=ITEM_COLUMNS).to_parquet(
        destination / ITEMS_NAME, index=False, engine="pyarrow",
    )
    pd.DataFrame(objects, columns=OBJ_COLUMNS).to_parquet(
        destination / OBJECTS_NAME, index=False, engine="pyarrow",
    )
    pd.DataFrame(quarantine, columns=QUARANTINE_COLUMNS).to_parquet(
        destination / QUARANTINE_NAME, index=False, engine="pyarrow",
    )
    table_count = len({(row["org_id"], row["tbl_id"]) for row in (*items, *objects)})
    checksums = artifact_checksums(destination)
    manifest = build_manifest(
        embedding_model=embedding_model,
        embedding_dimension=item_vectors.shape[1],
        source_meta_file=source,
        source_meta_sha256=source_sha256,
        source_row_count=len(meta_rows),
        table_count=table_count,
        item_count=len(items),
        obj_count=len(objects),
        quarantine_count=len(quarantine),
        duplicate_count=duplicate_count,
        embedding_dtype=embedding_dtype,
        checksums=checksums,
    )
    (destination / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    build_state_path.unlink(missing_ok=True)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a lossless KOSIS ITEM/OBJ component index")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--meta-index")
    source.add_argument("--sqlite-meta-db")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--embedding-dtype", choices=("float16", "float32"), default="float16")
    parser.add_argument("--prd-se-source", default=None)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    common = {
        "embedding_model": args.embedding_model, "device": args.device,
        "batch_size": args.batch_size, "embedding_dtype": args.embedding_dtype,
        "reset": args.reset, "resume": args.resume,
    }
    if args.sqlite_meta_db:
        manifest = build_component_index_from_sqlite(
            args.sqlite_meta_db, args.output_dir, **common,
        )
    else:
        manifest = build_component_index(
            args.meta_index, args.output_dir,
            prd_se_source=args.prd_se_source, **common,
        )
    print(
        f"saved={args.output_dir} tables={manifest['table_count']} "
        f"items={manifest['item_count']} objects={manifest['obj_count']} "
        f"dimension={manifest['embedding_dimension']} dtype={manifest['embedding_dtype']}"
    )


if __name__ == "__main__":
    main()
