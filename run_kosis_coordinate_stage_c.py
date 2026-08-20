#!/usr/bin/env python3
"""Stage C: OBJ-aware rerank with Local Top-3 and rank 4-5 fallback."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Mapping

from kosis_component_search import (
    apply_candidate_scores,
    build_coordinate_query,
)
from kosis_coordinate_low_memory import (
    BEAM_POOL_SCHEMA,
    JsonlCheckpoint,
    assert_resume_compatible,
    claim_fingerprint,
    require_schema,
)
from kosis_coordinate_merge import validate_suggestion_packet
from kosis_meta_coordinates import target_scope_exact_match
from kosis_semantic_search import TransformerReranker
from run_kosis_postgres_coordinate_top3 import (
    coordinate_from_component_row,
    local_suggestion_packet,
)


DEFAULT_OBJ_SCOPE_BONUS = 0.10
LOCAL_FALLBACK_SOURCE = "local_reranker_fallback"


def diverse_table_top_k(
    rows: list[dict[str, Any]], final_top_k: int,
) -> list[dict[str, Any]]:
    """Reserve one coordinate per table before filling remaining slots."""
    if final_top_k <= 0:
        return []
    selected: list[dict[str, Any]] = []
    selected_ids = set()
    seen_tables = set()
    for row in rows:
        table = (str(row.get("org_id") or ""), str(row.get("tbl_id") or ""))
        if table in seen_tables:
            continue
        seen_tables.add(table)
        selected.append(row)
        selected_ids.add(str(row.get("coordinate_id") or id(row)))
        if len(selected) == final_top_k:
            return selected
    for row in rows:
        coordinate_id = str(row.get("coordinate_id") or id(row))
        if coordinate_id in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(coordinate_id)
        if len(selected) == final_top_k:
            break
    return selected


def rerank_coordinate_record(
    record: Mapping[str, Any], reranker: Any, *, final_top_k: int = 3,
    obj_scope_bonus: float = DEFAULT_OBJ_SCOPE_BONUS,
) -> list[dict[str, Any]]:
    require_schema(record, BEAM_POOL_SCHEMA)
    claim = dict(record["claim"])
    if claim_fingerprint(claim) != record["claim_fingerprint"]:
        raise ValueError("stage B claim fingerprint does not match its payload")
    rows = [dict(row) for row in record.get("coordinate_candidates") or []]
    if not rows:
        return []
    scores = reranker.score(
        build_coordinate_query(claim), [row["rerank_document"] for row in rows],
    )
    if len(scores) != len(rows):
        raise ValueError("coordinate reranker score count does not match beam pool")
    for row, score in zip(rows, scores):
        candidate = {
            "component_score": row.get("dense_score"),
            "mandatory_aggregate": bool(row.get("mandatory_aggregate")),
            "target_match_state": row.get("target_match_state"),
            "structural_match_state": row.get("structural_match_state"),
            "table": {
                "candidate_score": row.get("candidate_score"),
                "rank": row.get("table_rank"),
            },
        }
        apply_candidate_scores(candidate, score)
        selected_obj_names = [
            str(row.get(f"selected_obj_l{level}_name") or "").strip()
            for level in range(1, 9)
            if str(row.get(f"selected_obj_l{level}") or "").strip()
        ]
        targets = [
            value.strip()
            for value in str(row.get("claim_target_terms") or "").split("|")
            if value.strip()
        ]
        obj_scope_exact = target_scope_exact_match(targets, selected_obj_names)
        applied_obj_bonus = obj_scope_bonus if obj_scope_exact else 0.0
        row.update({
            "reranker_score": candidate["reranker_score"],
            "table_prior_score": candidate["table_prior_score"],
            "coordinate_score": candidate["coordinate_score"],
            "structural_bonus": candidate["structural_bonus"],
            "fallback_penalty": candidate["fallback_penalty"],
            "base_final_rank_score": candidate["final_rank_score"],
            "obj_scope_exact": obj_scope_exact,
            "obj_scope_bonus": applied_obj_bonus,
            "final_rank_score": candidate["final_rank_score"] + applied_obj_bonus,
        })
    rows.sort(key=lambda row: (
        -float(row["final_rank_score"]), str(row.get("coordinate_id") or ""),
    ))
    return diverse_table_top_k(rows, final_top_k)


def local_fallback_suggestion_packet(
    claim_id: str,
    claim: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    *,
    metadata_snapshot_id: str,
    table_pool_count: int,
    complete_table_count: int,
) -> dict[str, Any]:
    """Serialize absolute Stage C ranks 4-5 as a separate local branch."""
    if len(rows) != 2:
        raise ValueError("local rank 4-5 fallback requires exactly two candidates")
    suggestions = []
    for fallback_rank, row in enumerate(rows, 1):
        absolute_rank = fallback_rank + 3
        objects = [
            {
                "axis_order": level,
                "axis_id": str(row.get(f"selected_obj_l{level}_axis_id") or "").strip(),
                "axis_name": str(row.get(f"selected_obj_l{level}_axis_name") or "").strip(),
                "value_id": str(row.get(f"selected_obj_l{level}") or "").strip(),
                "value_name": str(row.get(f"selected_obj_l{level}_name") or "").strip(),
            }
            for level in range(1, 9)
            if str(row.get(f"selected_obj_l{level}") or "").strip()
        ]
        suggestions.append({
            "source": LOCAL_FALLBACK_SOURCE,
            "source_rank": fallback_rank,
            "coordinate": coordinate_from_component_row(row, claim),
            "score": float(row["reranker_score"]),
            "rationale": " | ".join(filter(None, (
                str(row.get("tbl_name") or "").strip(),
                str(row.get("selected_itm_name") or "").strip(),
                ", ".join(value["value_name"] for value in objects),
            ))),
            "evidence": {
                "tbl_name": str(row.get("tbl_name") or "").strip(),
                "item_name": str(row.get("selected_itm_name") or "").strip(),
                "unit": str(row.get("selected_itm_unit") or "").strip(),
                "objects": objects,
                "table_rank": row.get("table_rank"),
                "coordinate_reranker_score": row.get("reranker_score"),
                "base_final_rank_score": row.get("base_final_rank_score"),
                "obj_scope_exact": bool(row.get("obj_scope_exact")),
                "obj_scope_bonus": row.get("obj_scope_bonus"),
                "final_rank_score": row.get("final_rank_score"),
                "stage_c_absolute_rank": absolute_rank,
                "mapping_type": str(row.get("mapping_type") or "").strip(),
                "target_match_state": str(row.get("target_match_state") or "").strip(),
                "structural_match_state": str(row.get("structural_match_state") or "").strip(),
                "verification_review_required": str(
                    row.get("verification_review_required") or ""
                ).strip(),
                "verification_review_reason": str(
                    row.get("verification_review_reason") or ""
                ).strip(),
                "fallback_penalty": row.get("fallback_penalty"),
                "metadata_snapshot_id": metadata_snapshot_id,
                "table_pool_count": table_pool_count,
                "complete_table_count": complete_table_count,
            },
        })
    return {
        "schema_version": "kosis-coordinate-suggestions-v1",
        "claim_measurement_id": claim_id,
        "source": LOCAL_FALLBACK_SOURCE,
        "suggestions": suggestions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beam-pool", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fallback-output", type=Path)
    parser.add_argument("--state-output", type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument(
        "--obj-scope-bonus", type=float, default=DEFAULT_OBJ_SCOPE_BONUS,
    )
    args = parser.parse_args()
    if args.state_output is None:
        args.state_output = args.output.with_name(args.output.stem + ".state.jsonl")
    source = JsonlCheckpoint(args.beam_pool)
    output = JsonlCheckpoint(args.output)
    fallback = JsonlCheckpoint(args.fallback_output) if args.fallback_output else None
    state = JsonlCheckpoint(args.state_output)
    assert_resume_compatible(source.records, state.records)
    source_by_id = {
        record["claim_measurement_id"]: record for record in source.records
    }
    # Recover the narrow crash window after suggestion fsync but before state fsync.
    fully_written = set(output.completed_ids)
    if fallback is not None:
        fully_written &= fallback.completed_ids
    for claim_id in sorted(fully_written - state.completed_ids):
        source_record = source_by_id.get(claim_id)
        if source_record is None:
            raise ValueError(f"suggestion output contains unknown claim ID: {claim_id}")
        state.append({
            "claim_measurement_id": claim_id,
            "claim_fingerprint": source_record["claim_fingerprint"],
            "status": "coordinate_ready",
            "beam_candidate_count": len(
                source_record.get("coordinate_candidates") or []
            ),
            "selected_coordinate_count": 3,
            "fallback_coordinate_count": 2 if fallback is not None else 0,
            "recovered_after_output_fsync": True,
        })
    pending = []
    for record in source.records:
        claim_id = record["claim_measurement_id"]
        if claim_id not in output.completed_ids:
            pending.append(record)
        elif fallback is not None and claim_id not in fallback.completed_ids:
            pending.append(record)
        elif claim_id not in state.completed_ids:
            pending.append(record)
    print(
        f"[stage_c] pending={len(pending)} suggestions={len(output.completed_ids)} "
        f"fallback={len(fallback.completed_ids) if fallback else 0} "
        f"terminal={len(state.completed_ids)}", flush=True,
    )
    if not pending:
        return
    reranker = TransformerReranker(
        device=args.device, batch_size=args.reranker_batch_size,
    )
    for index, record in enumerate(pending, 1):
        started = time.perf_counter()
        requested_top_k = 5 if fallback is not None else 3
        selected = rerank_coordinate_record(
            record, reranker, final_top_k=requested_top_k,
            obj_scope_bonus=args.obj_scope_bonus,
        )
        status = "coordinate_ready" if len(selected) >= 3 else record.get(
            "status", "coordinate_abstention"
        )
        if len(selected) >= 3 and record["claim_measurement_id"] not in output.completed_ids:
            packet = local_suggestion_packet(
                record["claim_measurement_id"], record["claim"], selected[:3],
                metadata_snapshot_id=record["metadata_snapshot_id"],
                table_pool_count=int(record["table_pool_count"]),
                complete_table_count=int(record["complete_table_count"]),
            )
            validate_suggestion_packet(packet)
            output.append(packet)
        if (
            fallback is not None
            and len(selected) >= 5
            and record["claim_measurement_id"] not in fallback.completed_ids
        ):
            fallback_packet = local_fallback_suggestion_packet(
                record["claim_measurement_id"], record["claim"], selected[3:5],
                metadata_snapshot_id=record["metadata_snapshot_id"],
                table_pool_count=int(record["table_pool_count"]),
                complete_table_count=int(record["complete_table_count"]),
            )
            validate_suggestion_packet(fallback_packet)
            fallback.append(fallback_packet)
        if record["claim_measurement_id"] not in state.completed_ids:
            state.append({
                "claim_measurement_id": record["claim_measurement_id"],
                "claim_fingerprint": record["claim_fingerprint"],
                "status": status,
                "beam_candidate_count": len(record.get("coordinate_candidates") or []),
                "selected_coordinate_count": min(3, len(selected)),
                "fallback_coordinate_count": max(0, min(2, len(selected) - 3)),
                "obj_scope_bonus": args.obj_scope_bonus,
            })
        print(
            f"[stage_c] {index}/{len(pending)} claim={record['claim_measurement_id']} "
            f"status={status} selected={min(3, len(selected))} "
            f"fallback={max(0, min(2, len(selected) - 3))} "
            f"elapsed={time.perf_counter() - started:.1f}s", flush=True,
        )


if __name__ == "__main__":
    main()
