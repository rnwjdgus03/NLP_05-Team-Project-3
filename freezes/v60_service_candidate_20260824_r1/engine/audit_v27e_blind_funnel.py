#!/usr/bin/env python3
"""Read-only audit of the v27e blind Stage A/B/C funnel."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def jsonl_by_id(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[str(row["claim_measurement_id"])] = row
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    args = parser.parse_args()

    with args.gold.open(encoding="utf-8-sig", newline="") as handle:
        gold = {row["claim_measurement_id"]: row for row in csv.DictReader(handle)}
    stage_a = jsonl_by_id(args.run_dir / "stage_a_table_pool.jsonl")
    stage_b = jsonl_by_id(args.run_dir / "stage_b_coordinate_beam.jsonl")
    local = jsonl_by_id(args.run_dir / "local_coordinate_top3.jsonl")
    fallback = jsonl_by_id(args.run_dir / "local_coordinate_rank4_5_fallback.jsonl")

    per_table: dict[str, Counter] = defaultdict(Counter)
    reason_counts: Counter = Counter()
    details = []
    for claim_id, expected in gold.items():
        table_key = f'{expected["gold_org_id"]}/{expected["gold_tbl_id"]}'
        expected_table = (expected["gold_org_id"], expected["gold_tbl_id"])
        a_tables = [
            (str(row.get("org_id") or ""), str(row.get("tbl_id") or ""))
            for row in stage_a[claim_id].get("table_candidates") or []
        ]
        a_rank = a_tables.index(expected_table) + 1 if expected_table in a_tables else None
        candidates = stage_b[claim_id].get("coordinate_candidates") or []
        gold_b = [
            row for row in candidates
            if str(row.get("org_id") or "") == expected["gold_org_id"]
            and str(row.get("tbl_id") or "") == expected["gold_tbl_id"]
            and str(row.get("selected_itm_id") or "") == expected["gold_itm_id"]
        ]
        suggestions = (local[claim_id].get("suggestions") or []) + (
            fallback[claim_id].get("suggestions") or []
        )
        selected_table = [
            row for row in suggestions
            if str((row.get("coordinate") or {}).get("org_id") or "") == expected["gold_org_id"]
            and str((row.get("coordinate") or {}).get("tbl_id") or "") == expected["gold_tbl_id"]
        ]
        selected_full = [
            row for row in selected_table
            if str((row.get("coordinate") or {}).get("itm_id") or "") == expected["gold_itm_id"]
            and str((row.get("coordinate") or {}).get("obj_values") or "") == expected["gold_obj_values"]
        ]
        per_table[table_key]["rows"] += 1
        per_table[table_key]["stage_a_top10"] += int(a_rank is not None and a_rank <= 10)
        per_table[table_key]["stage_b_gold_item_present"] += int(bool(gold_b))
        per_table[table_key]["stage_c_table_top5"] += int(bool(selected_table))
        per_table[table_key]["stage_c_coordinate_top5"] += int(bool(selected_full))

        if a_rank is None:
            reason = "STAGE_A_MISS"
        elif not gold_b:
            reason = "STAGE_B_GOLD_ITEM_MISS"
        elif not suggestions:
            states = Counter(str(row.get("target_match_state") or "") for row in gold_b)
            reason = "STAGE_C_ABSTAIN:" + ",".join(f"{k}={v}" for k, v in states.items())
        elif not selected_table:
            reason = "STAGE_C_DROPPED_GOLD_TABLE"
        elif not selected_full:
            reason = "STAGE_C_WRONG_ITEM_OR_OBJ"
        else:
            reason = "HIT"
        reason_counts[reason] += 1
        details.append({
            "claim_id": claim_id,
            "gold_table": table_key,
            "stage_a_rank": a_rank,
            "stage_b_gold_item_rows": len(gold_b),
            "gold_item_target_states": dict(Counter(
                str(row.get("target_match_state") or "") for row in gold_b
            )),
            "selected_count": len(suggestions),
            "reason": reason,
        })

    print(json.dumps({
        "reason_counts": reason_counts,
        "per_table": per_table,
        "details": details,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
