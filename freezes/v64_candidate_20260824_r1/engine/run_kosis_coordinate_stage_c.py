#!/usr/bin/env python3
"""Stage C: OBJ-aware rerank with Local Top-3 and rank 4-5 fallback."""

from __future__ import annotations

import argparse
import re
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
from kosis_meta_coordinates import (
    is_aggregate_name,
    target_scope_exact_match,
    target_terms_match_text,
)
from kosis_semantic_search import TransformerReranker
from run_kosis_postgres_coordinate_top3 import (
    coordinate_from_component_row,
    local_suggestion_packet,
)


DEFAULT_OBJ_SCOPE_BONUS = 0.10
DEFAULT_ITEM_EXACT_BONUS = 0.12
LOCAL_FALLBACK_SOURCE = "local_reranker_fallback"


def coordinate_scope_exact_match(
    targets: list[str], item_name: str, obj_names: list[str],
) -> bool:
    """Require every named target and forbid unexplained detail OBJ values.

    Some KOSIS tables encode sex or another slice in ITEM (for example
    ``남자인구수``), while others encode it in OBJ.  Either representation is
    valid, but an unrelated detail OBJ such as ``강남구`` must not hitchhike on
    an ITEM match. Remaining OBJ axes may only use official aggregate values.
    """
    if not targets:
        return all(is_aggregate_name(value) for value in obj_names)
    for target in targets:
        if target_terms_match_text([target], [item_name]):
            continue
        if any(target_terms_match_text([target], [value]) for value in obj_names):
            continue
        return False
    for value in obj_names:
        if is_aggregate_name(value):
            continue
        if not any(target_terms_match_text([target], [value]) for target in targets):
            return False
    return True


def item_indicator_exact_match(
    claim: Mapping[str, Any], item_name: str, targets: list[str],
) -> bool:
    """Match an official ITEM after removing only explicit scope modifiers."""
    def compact(value: Any) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()

    item = compact(item_name)
    if len(item) < 2:
        return False
    target_tokens = [compact(value) for value in targets if compact(value)]
    for field in ("measurement_indicator", "indicator", "claim_indicator"):
        indicator = compact(claim.get(field))
        for token in target_tokens:
            indicator = indicator.replace(token, "")
        indicator = re.sub(r"^(?:평균|전체)", "", indicator)
        if indicator == item:
            return True
    return False


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


def item_preserving_top_k(
    rows: list[dict[str, Any]], final_top_k: int, exact_slots: int,
) -> list[dict[str, Any]]:
    """Reserve bounded, table-diverse exact ITEM matches before backfill."""
    if exact_slots <= 0:
        return diverse_table_top_k(rows, final_top_k)
    exact = [row for row in rows if bool(row.get("item_indicator_exact_match"))]
    selected = diverse_table_top_k(exact, min(exact_slots, final_top_k))
    selected_ids = {str(row.get("coordinate_id") or id(row)) for row in selected}
    selected_tables = {
        (str(row.get("org_id") or ""), str(row.get("tbl_id") or ""))
        for row in selected
    }
    for row in rows:
        coordinate_id = str(row.get("coordinate_id") or id(row))
        table = (str(row.get("org_id") or ""), str(row.get("tbl_id") or ""))
        if coordinate_id in selected_ids or table in selected_tables:
            continue
        selected.append(row)
        selected_ids.add(coordinate_id)
        selected_tables.add(table)
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


def evidence_preserving_top_k(
    rows: list[dict[str, Any]], final_top_k: int, *, exact_slots: int,
    stage_a_table_slots: int, item_component_slots: int,
) -> list[dict[str, Any]]:
    """Reserve bounded Stage-A table and Stage-B ITEM evidence before fill.

    The cross-encoder remains the primary ranker.  These slots only prevent a
    strong upstream table/ITEM hypothesis from disappearing completely in
    Stage C.  Selection is label-free and uses ranks already emitted by Stage
    A/B; no gold coordinate or KOSIS value is consulted.
    """
    if final_top_k <= 0:
        return []
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def coordinate_id(row: Mapping[str, Any]) -> str:
        return str(row.get("coordinate_id") or id(row))

    def add(row: dict[str, Any]) -> bool:
        key = coordinate_id(row)
        if key in selected_ids or len(selected) >= final_top_k:
            return False
        selected.append(row)
        selected_ids.add(key)
        return True

    exact = [row for row in rows if bool(row.get("item_indicator_exact_match"))]
    for row in diverse_table_top_k(exact, min(exact_slots, final_top_k)):
        add(row)

    item_leaders: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("org_id") or ""), str(row.get("tbl_id") or ""),
            str(row.get("selected_itm_id") or row.get("selected_itm_name") or ""),
        )
        item_leaders.setdefault(key, row)
    ranked_items = sorted(item_leaders.values(), key=lambda row: (
        int(row.get("item_component_rank") or 10**9),
        -float(row.get("item_component_score") or 0.0),
        int(row.get("table_rank") or 10**9),
        -float(row.get("final_rank_score") or 0.0),
        coordinate_id(row),
    ))
    item_added = 0
    for row in ranked_items:
        if add(row):
            item_added += 1
        if item_added >= item_component_slots or len(selected) >= final_top_k:
            break

    table_leaders: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("org_id") or ""), str(row.get("tbl_id") or "")
        incumbent = table_leaders.get(key)
        if incumbent is None or float(row.get("final_rank_score") or 0.0) > float(
            incumbent.get("final_rank_score") or 0.0
        ):
            table_leaders[key] = row
    ranked_tables = sorted(table_leaders.values(), key=lambda row: (
        int(row.get("table_rank") or 10**9),
        -float(row.get("final_rank_score") or 0.0),
        coordinate_id(row),
    ))
    table_added = 0
    for row in ranked_tables:
        if add(row):
            table_added += 1
        if table_added >= stage_a_table_slots or len(selected) >= final_top_k:
            break

    for row in diverse_table_top_k(rows, final_top_k):
        add(row)
    for row in rows:
        add(row)
    return selected


def locked_incumbent_top_k(
    rows: list[dict[str, Any]], final_top_k: int,
) -> list[dict[str, Any]]:
    """Lock incumbent ranks 1-3 and use expanded ranks only for the tail."""
    incumbent_rows = [
        (position, row) for position, row in enumerate(rows)
        if str(row.get("stage_a_channel") or "") != "ITEM_RECALL_FALLBACK"
    ]
    # ``rows`` is already in Stage-C reranker order.  The old implementation
    # therefore relocked the new reranker Top-3 rather than the Stage-B
    # incumbents promised by the policy.  Prefer the immutable Stage-B global
    # rank when present, and retain list order for legacy packets/tests.
    incumbent_rows.sort(key=lambda pair: (
        int(pair[1].get("global_candidate_rank") or 10**9), pair[0],
    ))
    incumbent_rows = [row for _, row in incumbent_rows]
    locked = diverse_table_top_k(incumbent_rows, min(3, final_top_k))
    if final_top_k <= 3:
        return locked
    expanded = diverse_table_top_k(rows, final_top_k)
    selected_ids = {
        str(row.get("coordinate_id") or id(row)) for row in locked
    }
    # Match the evaluated policy: expanded candidates may enter only through
    # the branch's own ranks 4-5, never by displacing incumbent Top-3.
    tail = []
    for row in expanded[3:]:
        coordinate_id = str(row.get("coordinate_id") or id(row))
        if coordinate_id in selected_ids:
            continue
        tail.append(row)
        selected_ids.add(coordinate_id)
        if len(locked) + len(tail) == final_top_k:
            break
    if len(locked) + len(tail) < final_top_k:
        for row in rows:
            coordinate_id = str(row.get("coordinate_id") or id(row))
            if coordinate_id in selected_ids:
                continue
            tail.append(row)
            selected_ids.add(coordinate_id)
            if len(locked) + len(tail) == final_top_k:
                break
    return locked + tail


def rerank_coordinate_record(
    record: Mapping[str, Any], reranker: Any, *, final_top_k: int = 3,
    obj_scope_bonus: float = DEFAULT_OBJ_SCOPE_BONUS,
    item_exact_bonus: float = DEFAULT_ITEM_EXACT_BONUS,
    item_exact_slots: int = 0,
    stage_a_table_slots: int = 0,
    item_component_slots: int = 0,
    lock_incumbent_top3: bool = False,
    return_all_ranked: bool = False,
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
            "mandatory_target_default": bool(row.get("mandatory_target_default")),
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
        coordinate_scope_exact = coordinate_scope_exact_match(
            targets, str(row.get("selected_itm_name") or ""), selected_obj_names,
        )
        applied_obj_bonus = obj_scope_bonus if coordinate_scope_exact else 0.0
        item_exact_match = item_indicator_exact_match(
            claim, str(row.get("selected_itm_name") or ""), targets,
        )
        applied_item_bonus = item_exact_bonus if item_exact_match else 0.0
        row.update({
            "reranker_score": candidate["reranker_score"],
            "table_prior_score": candidate["table_prior_score"],
            "coordinate_score": candidate["coordinate_score"],
            "structural_bonus": candidate["structural_bonus"],
            "fallback_penalty": candidate["fallback_penalty"],
            "base_final_rank_score": candidate["final_rank_score"],
            "obj_scope_exact": obj_scope_exact,
            "coordinate_scope_exact": coordinate_scope_exact,
            "obj_scope_bonus": applied_obj_bonus,
            "item_indicator_exact_match": item_exact_match,
            "item_exact_bonus": applied_item_bonus,
            "final_rank_score": (
                candidate["final_rank_score"] + applied_obj_bonus + applied_item_bonus
            ),
        })
    explicit_targets = any(
        str(row.get("claim_target_terms") or "").strip() for row in rows
    )
    exact_rows = [
        row for row in rows
        if bool(row.get("coordinate_scope_exact"))
        and (
            not explicit_targets
            or str(row.get("target_match_state") or "") == "exact"
        )
    ]
    # A named target without an exact coordinate, or a target-free aggregate
    # claim with only unexplained detail OBJ values, must remain UNRESOLVED.
    if not exact_rows:
        return []
    rows = exact_rows
    rows.sort(key=lambda row: (
        -int(bool(row.get("mandatory_target_default"))),
        -int(bool(row.get("mandatory_aggregate"))),
        -float(row["final_rank_score"]), str(row.get("coordinate_id") or ""),
    ))
    if return_all_ranked:
        return rows
    if lock_incumbent_top3 and final_top_k > 3:
        return locked_incumbent_top_k(rows, final_top_k)
    if stage_a_table_slots > 0 or item_component_slots > 0:
        return evidence_preserving_top_k(
            rows, final_top_k, exact_slots=item_exact_slots,
            stage_a_table_slots=stage_a_table_slots,
            item_component_slots=item_component_slots,
        )
    return item_preserving_top_k(rows, final_top_k, item_exact_slots)


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
    if len(rows) > 2:
        raise ValueError("local rank 4-5 fallback accepts at most two candidates")
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
    parser.add_argument("--ranked-pool-output", type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument(
        "--obj-scope-bonus", type=float, default=DEFAULT_OBJ_SCOPE_BONUS,
    )
    parser.add_argument(
        "--item-exact-bonus", type=float, default=DEFAULT_ITEM_EXACT_BONUS,
    )
    parser.add_argument("--item-exact-slots", type=int, default=0)
    parser.add_argument("--stage-a-table-slots", type=int, default=0)
    parser.add_argument("--item-component-slots", type=int, default=0)
    parser.add_argument(
        "--lock-incumbent-top3", action="store_true",
        help="Select ranks 1-3 only from incumbent Stage A tables; allow the "
             "expanded ITEM channel to affect ranks 4-5 only.",
    )
    args = parser.parse_args()
    if args.state_output is None:
        args.state_output = args.output.with_name(args.output.stem + ".state.jsonl")
    source = JsonlCheckpoint(args.beam_pool)
    output = JsonlCheckpoint(args.output)
    fallback = JsonlCheckpoint(args.fallback_output) if args.fallback_output else None
    state = JsonlCheckpoint(args.state_output)
    ranked_pool = (
        JsonlCheckpoint(args.ranked_pool_output) if args.ranked_pool_output else None
    )
    assert_resume_compatible(source.records, state.records)
    source_by_id = {
        record["claim_measurement_id"]: record for record in source.records
    }
    # Recover the narrow crash window after suggestion fsync but before state fsync.
    fully_written = set(output.completed_ids)
    if fallback is not None:
        fully_written &= fallback.completed_ids
    if ranked_pool is not None:
        fully_written &= ranked_pool.completed_ids
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
        elif ranked_pool is not None and claim_id not in ranked_pool.completed_ids:
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
        ranked = rerank_coordinate_record(
            record, reranker, final_top_k=requested_top_k,
            obj_scope_bonus=args.obj_scope_bonus,
            item_exact_bonus=args.item_exact_bonus,
            item_exact_slots=args.item_exact_slots,
            stage_a_table_slots=args.stage_a_table_slots,
            item_component_slots=args.item_component_slots,
            lock_incumbent_top3=args.lock_incumbent_top3,
            return_all_ranked=ranked_pool is not None,
        )
        if ranked_pool is not None:
            selected = evidence_preserving_top_k(
                ranked, requested_top_k, exact_slots=args.item_exact_slots,
                stage_a_table_slots=args.stage_a_table_slots,
                item_component_slots=args.item_component_slots,
            )
            if record["claim_measurement_id"] not in ranked_pool.completed_ids:
                ranked_pool.append({
                    "schema_version": "kosis-stage-c-ranked-pool-v1",
                    "claim_measurement_id": record["claim_measurement_id"],
                    "claim_fingerprint": record["claim_fingerprint"],
                    "claim": record["claim"],
                    "metadata_snapshot_id": record["metadata_snapshot_id"],
                    "table_pool_count": int(record["table_pool_count"]),
                    "complete_table_count": int(record["complete_table_count"]),
                    "ranked_candidates": ranked,
                })
        else:
            selected = ranked
        status = "coordinate_ready" if selected else "coordinate_abstention"
        if record["claim_measurement_id"] not in output.completed_ids:
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
                "lock_incumbent_top3": args.lock_incumbent_top3,
                "stage_a_table_slots": args.stage_a_table_slots,
                "item_component_slots": args.item_component_slots,
            })
        print(
            f"[stage_c] {index}/{len(pending)} claim={record['claim_measurement_id']} "
            f"status={status} selected={min(3, len(selected))} "
            f"fallback={max(0, min(2, len(selected) - 3))} "
            f"elapsed={time.perf_counter() - started:.1f}s", flush=True,
        )


if __name__ == "__main__":
    main()
