#!/usr/bin/env python3
"""Build a reproducible v23 -> v24 A/B and residual-failure audit."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def hit_at_5(row: dict[str, str]) -> bool:
    value = (row.get("full_rank") or "").strip()
    return bool(value) and int(value) <= 5


def table_identity(candidate: dict) -> tuple[str, str]:
    table = candidate.get("table") or candidate
    return str(table.get("org_id", "")), str(table.get("tbl_id", ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--stage-a", type=Path, required=True)
    parser.add_argument("--v23-details", type=Path, required=True)
    parser.add_argument("--period-details", type=Path, required=True)
    parser.add_argument("--final-details", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    gold = {row["claim_measurement_id"]: row for row in read_csv(args.gold)}
    stage_a = {
        row["claim_measurement_id"]: row for row in read_jsonl(args.stage_a)
    }
    v23 = {row["claim_measurement_id"]: row for row in read_csv(args.v23_details)}
    period = {
        row["claim_measurement_id"]: row for row in read_csv(args.period_details)
    }
    final_rows = read_csv(args.final_details)
    final = {row["claim_measurement_id"]: row for row in final_rows}

    period_recovered = sorted(
        claim_id for claim_id in final
        if not hit_at_5(v23[claim_id]) and hit_at_5(period[claim_id])
    )
    stage_b_recovered = sorted(
        claim_id for claim_id in final
        if not hit_at_5(period[claim_id]) and hit_at_5(final[claim_id])
    )

    residual = []
    for prediction in final_rows:
        claim_id = prediction["claim_measurement_id"]
        if hit_at_5(prediction):
            continue
        label = gold[claim_id]
        gold_table = (label["gold_org_id"], label["gold_tbl_id"])
        candidates = stage_a.get(claim_id, {}).get("table_candidates", [])
        stage_a_rank = next(
            (
                rank for rank, candidate in enumerate(candidates, 1)
                if table_identity(candidate) == gold_table
            ),
            None,
        )
        top_tables = []
        for candidate in candidates[:5]:
            table = candidate.get("table") or {}
            top_tables.append(
                f"{table.get('org_id', '')}/{table.get('tbl_id', '')}:"
                f"{table.get('tbl_name', '')}"
            )
        residual.append({
            "claim_measurement_id": claim_id,
            "failure_stage": "STAGE_A" if stage_a_rank is None else "STAGE_BC",
            "stage_a_gold_table_rank": stage_a_rank or "",
            "full_rank": prediction.get("full_rank", ""),
            "coordinate_rank": prediction.get("coordinate_rank", ""),
            "gold_org_id": label["gold_org_id"],
            "gold_tbl_id": label["gold_tbl_id"],
            "gold_tbl_name": label["gold_tbl_name"],
            "gold_itm_id": label["gold_itm_id"],
            "gold_itm_name": label["gold_itm_name"],
            "claim_text": label["claim_text"],
            "measurement_indicator": label["measurement_indicator"],
            "measurement_item": label["measurement_item"],
            "gold_period": label["gold_period"],
            "stage_a_top5_tables": " | ".join(top_tables),
        })

    residual_path = args.out_dir / "v24_residual_failures.csv"
    with residual_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(residual[0]))
        writer.writeheader()
        writer.writerows(residual)

    summary = {
        "schema_version": "v24-residual-audit-v1",
        "eligible": len(final_rows),
        "v23_full_top5": sum(hit_at_5(row) for row in v23.values()),
        "period_only_full_top5": sum(hit_at_5(row) for row in period.values()),
        "v24_final_full_top5": sum(hit_at_5(row) for row in final.values()),
        "period_recovered_claims": period_recovered,
        "stage_b_slot_recovered_claims": stage_b_recovered,
        "residual_failures": len(residual),
        "residual_stage_a": sum(row["failure_stage"] == "STAGE_A" for row in residual),
        "residual_stage_bc": sum(row["failure_stage"] == "STAGE_BC" for row in residual),
        "residual_claims": [row["claim_measurement_id"] for row in residual],
    }
    summary_path = args.out_dir / "v24_residual_failure_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
