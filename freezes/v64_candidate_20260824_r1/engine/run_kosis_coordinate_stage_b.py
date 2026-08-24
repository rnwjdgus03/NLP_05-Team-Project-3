#!/usr/bin/env python3
"""Stage B: hydrate PostgreSQL components and build a BGE beam pool."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from kosis_build_component_index import item_document, obj_document
from kosis_component_search import build_coordinate_query, search_components_for_claim
from kosis_coordinate_low_memory import (
    BEAM_POOL_SCHEMA,
    JsonlCheckpoint,
    TABLE_POOL_SCHEMA,
    assert_resume_compatible,
    claim_fingerprint,
    coordinate_document_from_row,
    require_schema,
)
from kosis_postgres_store import PostgresKosisMetadataStore
from kosis_semantic_search import SentenceTransformerEmbedder
from run_kosis_postgres_coordinate_top3 import embed_component_rows


def json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def build_beam_packet(
    record: dict[str, Any], store: Any, embedder: Any, *,
    item_top_k: int, axis_top_k: int, beam_width: int,
    coordinate_pool_top_k: int, embedding_batch_size: int,
    preserve_table_fallback: bool,
    snapshot_id: str,
) -> dict[str, Any]:
    require_schema(record, TABLE_POOL_SCHEMA)
    claim = dict(record["claim"])
    if claim_fingerprint(claim) != record["claim_fingerprint"]:
        raise ValueError("stage A claim fingerprint does not match its payload")
    bundle = store.hydrate_component_bundle(record.get("table_candidates") or [])
    item_rows = bundle["items"]
    object_rows = bundle["objects"]
    trace: dict[str, Any] = {}
    component_rows: list[dict[str, Any]] = []
    if item_rows and object_rows:
        # Per-claim caches bound memory and disappear when this stage exits.
        component_cache: dict[str, np.ndarray] = {}
        item_vectors = embed_component_rows(
            item_rows, item_document, embedder, component_cache,
            batch_size=embedding_batch_size,
        )
        object_vectors = embed_component_rows(
            object_rows, obj_document, embedder, component_cache,
            batch_size=embedding_batch_size,
        )
        query_vector = np.asarray(embedder.encode(
            [build_coordinate_query(claim)], batch_size=1,
        ), dtype=np.float32)[0]
        component_rows = search_components_for_claim(
            claim, bundle["tables"], item_rows, object_rows,
            item_vectors, object_vectors, query_vector,
            item_top_k=item_top_k, axis_top_k=axis_top_k,
            beam_width=beam_width, final_top_k=coordinate_pool_top_k,
            per_table_minimum=1, reranker=None, trace=trace,
            preserve_table_fallback=preserve_table_fallback,
        )
    candidates = []
    for row in component_rows:
        candidate = dict(row)
        candidate["rerank_document"] = coordinate_document_from_row(row)
        candidates.append(json_value(candidate))
    status = "beam_ready" if len(candidates) >= 3 else (
        "metadata_hydration_required" if bundle["incomplete_tables"]
        else "coordinate_abstention"
    )
    return {
        "schema_version": BEAM_POOL_SCHEMA,
        "claim_measurement_id": record["claim_measurement_id"],
        "claim_fingerprint": record["claim_fingerprint"],
        "claim": claim,
        "metadata_snapshot_id": snapshot_id,
        "status": status,
        "table_pool_count": len(record.get("table_candidates") or []),
        "complete_table_count": len(bundle["tables"]),
        "incomplete_tables": json_value(bundle["incomplete_tables"]),
        "component_trace": json_value(trace),
        "coordinate_candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-pool", required=True, type=Path)
    parser.add_argument("--postgres-dsn", default=os.environ.get("KOSIS_POSTGRES_DSN"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--item-top-k", type=int, default=10)
    parser.add_argument("--axis-top-k", type=int, default=20)
    parser.add_argument("--beam-width", type=int, default=200)
    parser.add_argument("--coordinate-pool-top-k", type=int, default=200)
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    parser.add_argument(
        "--preserve-table-fallback", action="store_true",
        help="Keep one complete review-only coordinate when a Stage A table "
             "would otherwise have no Stage B coordinate.",
    )
    args = parser.parse_args()
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or KOSIS_POSTGRES_DSN is required")
    source = JsonlCheckpoint(args.table_pool)
    output = JsonlCheckpoint(args.output)
    assert_resume_compatible(source.records, output.records)
    pending = [record for record in source.records
               if record["claim_measurement_id"] not in output.completed_ids]
    print(f"[stage_b] pending={len(pending)} completed={len(output.completed_ids)}", flush=True)
    if not pending:
        return
    with PostgresKosisMetadataStore(args.postgres_dsn) as store:
        with store.metadata_read_guard() as snapshot:
            snapshot_id = str(snapshot["snapshot_id"])
            previous_snapshots = {
                str(record.get("metadata_snapshot_id") or "")
                for record in output.records
            }
            previous_snapshots.discard("")
            if previous_snapshots and previous_snapshots != {snapshot_id}:
                raise ValueError(
                    "active PostgreSQL metadata snapshot changed during resume: "
                    f"checkpoint={sorted(previous_snapshots)} active={snapshot_id}"
                )
            embedder = SentenceTransformerEmbedder(device=args.device)
            for index, record in enumerate(pending, 1):
                started = time.perf_counter()
                packet = build_beam_packet(
                    record, store, embedder,
                    item_top_k=args.item_top_k, axis_top_k=args.axis_top_k,
                    beam_width=args.beam_width,
                    coordinate_pool_top_k=args.coordinate_pool_top_k,
                    embedding_batch_size=args.embedding_batch_size,
                    preserve_table_fallback=args.preserve_table_fallback,
                    snapshot_id=snapshot_id,
                )
                output.append(packet)
                print(
                    f"[stage_b] {index}/{len(pending)} "
                    f"claim={packet['claim_measurement_id']} status={packet['status']} "
                    f"tables={packet['complete_table_count']}/{packet['table_pool_count']} "
                    f"beam={len(packet['coordinate_candidates'])} "
                    f"elapsed={time.perf_counter() - started:.1f}s", flush=True,
                )


if __name__ == "__main__":
    main()
