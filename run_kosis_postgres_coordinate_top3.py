#!/usr/bin/env python3
"""Build PostgreSQL-backed ITEM/OBJ coordinate Top-3 suggestions.

This is the local branch of the 3+2 contract. It retrieves a broad table pool,
hydrates exact components from PostgreSQL, dynamically embeds and combines
ITEM/OBJ values, and emits exactly three coordinate suggestions only when the
local branch has enough evidence. KOSIS MCP is intentionally not called here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from kosis_build_component_index import item_document, obj_document
from kosis_component_search import (
    build_coordinate_query,
    search_components_for_claim,
)
from kosis_coordinate_merge import validate_suggestion_packet
from kosis_hybrid_top3 import HybridTop3Retriever, read_csv
from kosis_postgres_store import PostgresKosisMetadataStore
from kosis_semantic_search import SemanticSearchRuntime


SCHEMA_VERSION = "kosis-coordinate-suggestions-v1"
SOURCE = "local_reranker"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def stable_claim_id(claim: Mapping[str, Any], row_number: int) -> str:
    existing = _text(claim.get("claim_measurement_id") or claim.get("claim_id"))
    if existing and existing != "-":
        return existing
    identity = json.dumps(
        {key: _text(value) for key, value in sorted(claim.items())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"KOSIS-ROW-{row_number:06d}-{digest}"


def embed_component_rows(
    rows: Sequence[Mapping[str, Any]],
    document_builder: Any,
    embedder: Any,
    cache: dict[str, np.ndarray],
    *,
    batch_size: int,
) -> np.ndarray:
    """Embed only unseen components and return vectors in current row order."""
    missing_rows = [
        row for row in rows if _text(row.get("component_id")) not in cache
    ]
    if missing_rows:
        vectors = np.asarray(embedder.encode(
            [document_builder(row) for row in missing_rows],
            batch_size=batch_size,
        ), dtype=np.float32)
        if vectors.ndim != 2 or len(vectors) != len(missing_rows):
            raise ValueError("component embedder returned an invalid matrix")
        for row, vector in zip(missing_rows, vectors):
            cache[_text(row["component_id"])] = vector
    if not rows:
        return np.empty((0, 0), dtype=np.float32)
    return np.stack([
        cache[_text(row["component_id"])] for row in rows
    ]).astype(np.float32, copy=False)


def coordinate_from_component_row(
    row: Mapping[str, Any], claim: Mapping[str, Any],
) -> dict[str, Any]:
    axes = []
    for axis_order in range(1, 9):
        value_id = _text(row.get(f"selected_obj_l{axis_order}"))
        if not value_id:
            continue
        axis_id = _text(row.get(f"selected_obj_l{axis_order}_axis_id"))
        if not axis_id:
            raise ValueError(f"coordinate axis {axis_order} has no official axis_id")
        axes.append({
            "axis_order": axis_order,
            "axis_id": axis_id,
            "value_id": value_id,
        })
    return {
        "org_id": _text(row.get("org_id")),
        "tbl_id": _text(row.get("tbl_id")),
        "item_id": _text(row.get("selected_itm_id")),
        "axis_values": axes,
        "prd_se": _text(
            claim.get("prd_se")
            or row.get("coordinate_prd_se")
            or claim.get("measurement_prd_se")
        ).upper(),
        "target_period": _text(
            claim.get("period") or claim.get("measurement_period")
        ),
        "previous_period": _text(
            claim.get("comparison_period") or claim.get("previous_period")
        ),
        "aggregation": _text(claim.get("period_aggregation")).lower(),
    }


def local_suggestion_packet(
    claim_id: str,
    claim: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    metadata_snapshot_id: str,
    table_pool_count: int,
    complete_table_count: int,
) -> dict[str, Any]:
    if len(rows) != 3:
        raise ValueError("local coordinate packet requires exactly three candidates")
    suggestions = []
    for source_rank, row in enumerate(rows, 1):
        objects = [
            {
                "axis_order": axis_order,
                "axis_id": _text(row.get(f"selected_obj_l{axis_order}_axis_id")),
                "axis_name": _text(row.get(f"selected_obj_l{axis_order}_axis_name")),
                "value_id": _text(row.get(f"selected_obj_l{axis_order}")),
                "value_name": _text(row.get(f"selected_obj_l{axis_order}_name")),
            }
            for axis_order in range(1, 9)
            if _text(row.get(f"selected_obj_l{axis_order}"))
        ]
        score = row.get("reranker_score")
        if score in (None, ""):
            score = row.get("final_rank_score")
        suggestions.append({
            "source": SOURCE,
            "source_rank": source_rank,
            "coordinate": coordinate_from_component_row(row, claim),
            "score": float(score) if score not in (None, "") else None,
            "rationale": " | ".join(filter(None, (
                _text(row.get("tbl_name")),
                _text(row.get("selected_itm_name")),
                ", ".join(value["value_name"] for value in objects),
            ))),
            "evidence": {
                "tbl_name": _text(row.get("tbl_name")),
                "item_name": _text(row.get("selected_itm_name")),
                "unit": _text(row.get("selected_itm_unit")),
                "objects": objects,
                "table_rank": row.get("table_rank"),
                "table_reranker_score": row.get("candidate_score"),
                "coordinate_reranker_score": row.get("reranker_score"),
                "base_final_rank_score": row.get("base_final_rank_score"),
                "obj_scope_exact": bool(row.get("obj_scope_exact")),
                "obj_scope_bonus": row.get("obj_scope_bonus"),
                "final_rank_score": row.get("final_rank_score"),
                "mapping_type": _text(row.get("mapping_type")),
                "target_match_state": _text(row.get("target_match_state")),
                "structural_match_state": _text(row.get("structural_match_state")),
                "verification_review_required": _text(
                    row.get("verification_review_required")
                ),
                "verification_review_reason": _text(
                    row.get("verification_review_reason")
                ),
                "fallback_penalty": row.get("fallback_penalty"),
                "metadata_snapshot_id": metadata_snapshot_id,
                "table_pool_count": table_pool_count,
                "complete_table_count": complete_table_count,
            },
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "claim_measurement_id": claim_id,
        "source": SOURCE,
        "suggestions": suggestions,
    }


def diagnostic_packet(
    claim_id: str,
    *,
    status: str,
    table_pool_count: int,
    complete_table_count: int,
    incomplete_tables: Sequence[Mapping[str, Any]],
    coordinate_count: int,
    trace: Mapping[str, Any],
    elapsed_ms: float,
    error: str = "",
) -> dict[str, Any]:
    return {
        "claim_measurement_id": claim_id,
        "status": status,
        "table_pool_count": table_pool_count,
        "complete_table_count": complete_table_count,
        "incomplete_table_count": len(incomplete_tables),
        "incomplete_tables": list(incomplete_tables),
        "coordinate_count": coordinate_count,
        "component_trace": dict(trace),
        "elapsed_ms": round(elapsed_ms, 3),
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--semantic-index", required=True, type=Path)
    parser.add_argument("--postgres-dsn", default=os.environ.get("KOSIS_POSTGRES_DSN"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--diagnostics-output", required=True, type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--dense-top-k", type=int, default=50)
    parser.add_argument("--table-rerank-top-k", type=int, default=50)
    parser.add_argument("--table-pool-top-k", type=int, default=50)
    parser.add_argument("--item-top-k", type=int, default=10)
    parser.add_argument("--axis-top-k", type=int, default=20)
    parser.add_argument("--beam-width", type=int, default=200)
    parser.add_argument("--embedding-batch-size", type=int, default=128)
    parser.add_argument("--start-row", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or KOSIS_POSTGRES_DSN is required")
    if args.table_pool_top_k > args.table_rerank_top_k:
        parser.error("--table-pool-top-k cannot exceed --table-rerank-top-k")

    if args.start_row <= 0:
        parser.error("--start-row must be positive")
    indexed_claims = list(enumerate(read_csv(args.claims), 1))
    indexed_claims = [row for row in indexed_claims if row[0] >= args.start_row]
    if args.limit:
        indexed_claims = indexed_claims[:args.limit]
    print(
        f"[coordinate_top3] selected_claims={len(indexed_claims)} "
        f"start_row={args.start_row} limit={args.limit}",
        flush=True,
    )
    tables = read_csv(args.semantic_index / "tables.csv")
    runtime = SemanticSearchRuntime(
        args.semantic_index, device=args.device, reranker_batch_size=32,
    )
    retriever = HybridTop3Retriever(
        tables,
        runtime,
        lexical_top_k=args.lexical_top_k,
        dense_top_k=args.dense_top_k,
        rerank_top_k=args.table_rerank_top_k,
        final_top_k=3,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.diagnostics_output.parent.mkdir(parents=True, exist_ok=True)

    with PostgresKosisMetadataStore(args.postgres_dsn) as store:
        with store.metadata_read_guard() as snapshot:
            snapshot_id = _text(snapshot["snapshot_id"])
            component_embedding_cache: dict[str, np.ndarray] = {}
            with args.output.open("w", encoding="utf-8") as output, args.diagnostics_output.open(
                "w", encoding="utf-8"
            ) as diagnostics:
                for processed, (row_number, original_claim) in enumerate(
                    indexed_claims, 1
                ):
                    started = time.perf_counter()
                    claim = dict(original_claim)
                    claim_id = stable_claim_id(claim, row_number)
                    claim["claim_measurement_id"] = claim_id
                    trace: dict[str, Any] = {}
                    table_pool_count = complete_table_count = coordinate_count = 0
                    incomplete_tables: list[dict[str, Any]] = []
                    try:
                        table_pool = retriever.retrieve_reranked_pool(
                            claim, top_k=args.table_pool_top_k,
                        )
                        table_pool_count = len(table_pool)
                        bundle = store.hydrate_component_bundle(table_pool)
                        complete_table_count = len(bundle["tables"])
                        incomplete_tables = list(bundle["incomplete_tables"])
                        item_rows = bundle["items"]
                        object_rows = bundle["objects"]
                        if item_rows and object_rows:
                            embedder = runtime.index.embedder
                            item_vectors = embed_component_rows(
                                item_rows, item_document, embedder,
                                component_embedding_cache,
                                batch_size=args.embedding_batch_size,
                            )
                            object_vectors = embed_component_rows(
                                object_rows, obj_document, embedder,
                                component_embedding_cache,
                                batch_size=args.embedding_batch_size,
                            )
                            query_vector = embedder.encode([
                                build_coordinate_query(claim)
                            ])[0]
                            component_rows = search_components_for_claim(
                                claim,
                                bundle["tables"],
                                item_rows,
                                object_rows,
                                item_vectors,
                                object_vectors,
                                query_vector,
                                item_top_k=args.item_top_k,
                                axis_top_k=args.axis_top_k,
                                beam_width=args.beam_width,
                                final_top_k=3,
                                per_table_minimum=0,
                                reranker=runtime._reranker,
                                trace=trace,
                            )
                        else:
                            component_rows = []
                        coordinate_count = len(component_rows)
                        if coordinate_count == 3:
                            packet = local_suggestion_packet(
                                claim_id,
                                claim,
                                component_rows,
                                metadata_snapshot_id=snapshot_id,
                                table_pool_count=table_pool_count,
                                complete_table_count=complete_table_count,
                            )
                            validate_suggestion_packet(packet)
                            output.write(json.dumps(packet, ensure_ascii=False) + "\n")
                            output.flush()
                            status = "coordinate_ready"
                        elif incomplete_tables:
                            status = "metadata_hydration_required"
                        else:
                            status = "coordinate_abstention"
                        diagnostic = diagnostic_packet(
                            claim_id,
                            status=status,
                            table_pool_count=table_pool_count,
                            complete_table_count=complete_table_count,
                            incomplete_tables=incomplete_tables,
                            coordinate_count=coordinate_count,
                            trace=trace,
                            elapsed_ms=(time.perf_counter() - started) * 1000,
                        )
                    except Exception as error:
                        diagnostic = diagnostic_packet(
                            claim_id,
                            status="technical_failure",
                            table_pool_count=table_pool_count,
                            complete_table_count=complete_table_count,
                            incomplete_tables=incomplete_tables,
                            coordinate_count=coordinate_count,
                            trace=trace,
                            elapsed_ms=(time.perf_counter() - started) * 1000,
                            error=f"{type(error).__name__}:{error}",
                        )
                    diagnostics.write(json.dumps(diagnostic, ensure_ascii=False) + "\n")
                    diagnostics.flush()
                    if processed == 1 or processed % 10 == 0 or processed == len(indexed_claims):
                        print(
                            f"[coordinate_top3] processed={processed}/{len(indexed_claims)} "
                            f"source_row={row_number} "
                            f"status={diagnostic['status']} "
                            f"coordinates={diagnostic['coordinate_count']}",
                            flush=True,
                        )


if __name__ == "__main__":
    main()
