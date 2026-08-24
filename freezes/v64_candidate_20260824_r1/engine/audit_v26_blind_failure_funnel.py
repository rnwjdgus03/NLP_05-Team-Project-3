#!/usr/bin/env python3
"""Audit the opened v26 blind run as a Stage A/B/C/safety failure funnel.

This script is intentionally read-only.  It joins the locked coordinate gold with
the one-shot artifacts and emits claim-level evidence plus aggregate summaries.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def index(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(key, "")): row for row in rows}


def norm(value: Any) -> str:
    return str(value or "").strip()


def coordinate_parts(candidate: dict[str, Any]) -> tuple[str, str, str, tuple[str, ...], str, str]:
    coordinate = candidate.get("coordinate") if isinstance(candidate.get("coordinate"), dict) else candidate
    org = norm(coordinate.get("org_id"))
    table = norm(coordinate.get("tbl_id"))
    item = norm(coordinate.get("item_id") or coordinate.get("selected_itm_id"))
    axis_values: list[str] = []
    raw_axis = coordinate.get("axis_values")
    if isinstance(raw_axis, list):
        for axis in raw_axis:
            if isinstance(axis, dict):
                axis_values.append(norm(axis.get("value_id") or axis.get("value")))
    if not axis_values:
        for order in range(1, 9):
            value = norm(coordinate.get(f"selected_obj_l{order}"))
            if value:
                axis_values.append(value)
    period = norm(coordinate.get("target_period") or coordinate.get("period"))
    periodicity = norm(coordinate.get("prd_se") or coordinate.get("coordinate_prd_se"))
    return org, table, item, tuple(axis_values), periodicity, period


def gold_parts(row: dict[str, str]) -> tuple[str, str, str, tuple[str, ...], str, str]:
    axes = tuple(
        norm(row.get(f"gold_obj_l{order}"))
        for order in range(1, 9)
        if norm(row.get(f"gold_obj_l{order}"))
    )
    return (
        norm(row.get("gold_org_id")),
        norm(row.get("gold_tbl_id")),
        norm(row.get("gold_itm_id")),
        axes,
        norm(row.get("gold_prd_se")),
        norm(row.get("gold_period")),
    )


def first_rank(candidates: list[dict[str, Any]], gold: tuple[str, str, str, tuple[str, ...], str, str], level: str) -> int | None:
    g_org, g_table, g_item, g_axes, g_prd, g_period = gold
    for rank, candidate in enumerate(candidates, 1):
        org, table, item, axes, prd, period = coordinate_parts(candidate)
        table_ok = (org, table) == (g_org, g_table)
        item_ok = table_ok and item == g_item
        coord_ok = item_ok and axes == g_axes
        full_ok = coord_ok and prd == g_prd and period == g_period
        if {"table": table_ok, "item": item_ok, "coordinate": coord_ok, "full": full_ok}[level]:
            return rank
    return None


def matching_candidate(
    candidates: list[dict[str, Any]],
    gold: tuple[str, str, str, tuple[str, ...], str, str],
    level: str,
) -> dict[str, Any]:
    rank = first_rank(candidates, gold, level)
    return candidates[rank - 1] if rank is not None else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    gold_rows = read_csv(args.gold)
    stage_a = index(read_jsonl(args.run_dir / "stage_a_table_pool.jsonl"), "claim_measurement_id")
    stage_b = index(read_jsonl(args.run_dir / "stage_b_coordinate_beam.jsonl"), "claim_measurement_id")
    top3 = index(read_jsonl(args.run_dir / "local_coordinate_top3.jsonl"), "claim_measurement_id")
    rank45 = index(read_jsonl(args.run_dir / "local_coordinate_rank4_5_fallback.jsonl"), "claim_measurement_id")
    decisions = index(read_jsonl(args.run_dir / "claim_decisions.jsonl"), "claim_measurement_id")
    verified_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(args.run_dir / "verified_candidates.jsonl"):
        verified_by_claim[norm(row.get("claim_measurement_id"))].append(row)

    audit_rows: list[dict[str, Any]] = []
    for gold_row in gold_rows:
        claim_id = norm(gold_row.get("claim_measurement_id"))
        gold = gold_parts(gold_row)
        a = stage_a.get(claim_id, {})
        a_tables = a.get("table_candidates") or []
        a_rank = next(
            (
                rank
                for rank, candidate in enumerate(a_tables, 1)
                if (norm(candidate.get("org_id")), norm(candidate.get("tbl_id"))) == gold[:2]
            ),
            None,
        )
        b = stage_b.get(claim_id, {})
        b_candidates = b.get("coordinate_candidates") or []
        c_candidates = list((top3.get(claim_id, {}).get("suggestions") or []))
        c_candidates.extend(rank45.get(claim_id, {}).get("suggestions") or [])
        decision = decisions.get(claim_id, {})
        verified = verified_by_claim.get(claim_id, [])
        verdict_counts = Counter(norm(row.get("verdict_code")) for row in verified)

        indicator = norm(gold_row.get("indicator"))
        change_base = norm(gold_row.get("change_base"))
        expected_base = "전년동월" if "전년동월" in indicator else ("전월" if "전월" in indicator else "")
        contract_error = bool(expected_base and change_base != expected_base)

        a_hit10 = a_rank is not None and a_rank <= 10
        b_table_rank = first_rank(b_candidates, gold, "table")
        b_item_rank = first_rank(b_candidates, gold, "item")
        b_coord_rank = first_rank(b_candidates, gold, "coordinate")
        b_item_candidate = matching_candidate(b_candidates, gold, "item")
        b_coord_candidate = matching_candidate(b_candidates, gold, "coordinate")
        c_table_rank = first_rank(c_candidates, gold, "table")
        c_item_rank = first_rank(c_candidates, gold, "item")
        c_coord_rank = first_rank(c_candidates, gold, "coordinate")
        c_full_rank = first_rank(c_candidates, gold, "full")

        if not a_hit10:
            failure_stage = "STAGE_A_TABLE_MISS"
        elif b_table_rank is None:
            failure_stage = "STAGE_B_TABLE_DROPPED"
        elif b_item_rank is None:
            failure_stage = "STAGE_B_ITEM_MISS"
        elif b_coord_rank is None:
            failure_stage = "STAGE_B_OBJ_MISS"
        elif c_table_rank is None:
            failure_stage = "STAGE_C_TABLE_DROPPED"
        elif c_item_rank is None:
            failure_stage = "STAGE_C_ITEM_DROPPED"
        elif c_coord_rank is None:
            failure_stage = "STAGE_C_OBJ_DROPPED"
        elif c_full_rank is None:
            failure_stage = "STAGE_C_PERIOD_DROPPED"
        else:
            failure_stage = "FULL_COORDINATE_PRESENT"

        audit_rows.append(
            {
                "claim_measurement_id": claim_id,
                "metric_domain": norm(gold_row.get("metric_domain")),
                "indicator": indicator,
                "target": norm(gold_row.get("industry_or_item")),
                "gold_tbl_id": gold[1],
                "gold_itm_id": gold[2],
                "gold_obj_values": "|".join(gold[3]),
                "input_change_base": change_base,
                "expected_change_base": expected_base,
                "input_contract_error": "Y" if contract_error else "N",
                "stage_a_table_rank": a_rank or "",
                "stage_a_top10": " || ".join(
                    f"{norm(candidate.get('tbl_id'))}:{norm((candidate.get('table') or {}).get('tbl_name') if isinstance(candidate.get('table'), dict) else candidate.get('tbl_name'))}"
                    for candidate in a_tables[:10]
                ),
                "stage_b_table_rank": b_table_rank or "",
                "stage_b_item_rank": b_item_rank or "",
                "stage_b_coordinate_rank": b_coord_rank or "",
                "stage_b_correct_item_name": norm(b_item_candidate.get("selected_itm_name")),
                "stage_b_correct_item_target_state": norm(b_item_candidate.get("target_match_state")),
                "stage_b_correct_item_structural_state": norm(b_item_candidate.get("structural_match_state")),
                "stage_b_correct_item_global_rank": norm(b_item_candidate.get("global_candidate_rank")),
                "stage_b_correct_item_stage_a_channel": norm(b_item_candidate.get("stage_a_channel")),
                "stage_b_correct_item_table_rank": norm(b_item_candidate.get("table_rank")),
                "stage_b_correct_item_component_rank": norm(b_item_candidate.get("item_component_rank")),
                "stage_b_correct_coord_target_state": norm(b_coord_candidate.get("target_match_state")),
                "stage_b_correct_coord_final_score": norm(b_coord_candidate.get("final_rank_score")),
                "stage_c_table_rank": c_table_rank or "",
                "stage_c_item_rank": c_item_rank or "",
                "stage_c_coordinate_rank": c_coord_rank or "",
                "stage_c_full_rank": c_full_rank or "",
                "failure_stage": failure_stage,
                "claim_decision": norm(decision.get("claim_decision")) or "MISSING_PREDICTION",
                "candidate_verdict_counts": json.dumps(dict(verdict_counts), ensure_ascii=False, sort_keys=True),
            }
        )

    detail_path = args.out_dir / "v26_blind_failure_funnel.csv"
    with detail_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)

    def at_k(field: str, k: int) -> int:
        return sum(bool(row[field]) and int(row[field]) <= k for row in audit_rows)

    summary = {
        "schema_version": "v26-blind-failure-funnel-v1",
        "gold_rows": len(audit_rows),
        "input_contract_errors": sum(row["input_contract_error"] == "Y" for row in audit_rows),
        "failure_stage_counts": dict(Counter(row["failure_stage"] for row in audit_rows)),
        "decision_counts": dict(Counter(row["claim_decision"] for row in audit_rows)),
        "all_gold_denominator_metrics": {
            "stage_a_table_top10": at_k("stage_a_table_rank", 10),
            "stage_b_table_top5": at_k("stage_b_table_rank", 5),
            "stage_b_item_top5": at_k("stage_b_item_rank", 5),
            "stage_b_coordinate_top5": at_k("stage_b_coordinate_rank", 5),
            "stage_c_table_top5": at_k("stage_c_table_rank", 5),
            "stage_c_item_top5": at_k("stage_c_item_rank", 5),
            "stage_c_coordinate_top5": at_k("stage_c_coordinate_rank", 5),
            "stage_c_full_top5": at_k("stage_c_full_rank", 5),
        },
        "false_value_mismatch_claims": [
            row["claim_measurement_id"]
            for row in audit_rows
            if row["claim_decision"] == "MISMATCH_EVIDENCE_REVIEW_REQUIRED"
        ],
    }
    summary_path = args.out_dir / "v26_blind_failure_funnel_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(detail_path)


if __name__ == "__main__":
    main()
