#!/usr/bin/env python3
"""Validate period binding + Stage B table slots together on locked gold30."""

from __future__ import annotations

import json
import os
import sys

from run_v24_separated_ab import (
    APP,
    GOLD,
    OUT,
    PATCH,
    POSTGRES_DSN,
    PYTHON,
    V23,
    read_csv,
    read_jsonl,
    run,
    write_jsonl,
)


def main() -> None:
    experiment_name = os.environ.get(
        "V24_AB_NAME", "combined_period_stage_b_slots_v3_final"
    )
    preserve_table_fallback = (
        os.environ.get("V24_PRESERVE_TABLE_FALLBACK", "1") != "0"
    )
    root = OUT / experiment_name
    root.mkdir(parents=True, exist_ok=True)
    eligible = {
        row["claim_measurement_id"]
        for row in read_csv(V23 / "coordinate_topk_actual_gold_details.csv")
    }
    prepared = {
        row["claim_measurement_id"]: row
        for row in read_csv(
            OUT.parent / "v24_ready55_audit_v2" / "all.csv"
        )
        if row.get("claim_measurement_id") in eligible
    }

    sys.path.insert(0, str(APP))
    from kosis_coordinate_low_memory import claim_fingerprint
    from kosis_coordinate_merge import merge_fallback_coordinate_packets

    stage_a_packets = []
    for packet in read_jsonl(V23 / "stage_a_table_pool.jsonl"):
        claim_id = packet.get("claim_measurement_id")
        if claim_id not in eligible:
            continue
        updated = dict(packet)
        updated["claim"] = prepared[claim_id]
        updated["claim_fingerprint"] = claim_fingerprint(prepared[claim_id])
        stage_a_packets.append(updated)
    stage_a = root / "stage_a_with_v24_periods.jsonl"
    write_jsonl(stage_a, stage_a_packets)

    beam = root / "stage_b_table_slot_beam.jsonl"
    stage_b_command = [
        PYTHON, "-u", PATCH / "run_kosis_coordinate_stage_b.py",
        "--table-pool", stage_a,
        "--postgres-dsn", POSTGRES_DSN,
        "--output", beam,
        "--device", "cuda",
        "--item-top-k", "10",
        "--axis-top-k", "20",
        "--beam-width", "200",
        "--coordinate-pool-top-k", "200",
        "--embedding-batch-size", "16",
    ]
    if preserve_table_fallback:
        stage_b_command.append("--preserve-table-fallback")
    run(stage_b_command)
    primary = root / "local_top3.jsonl"
    fallback = root / "local_rank4_5.jsonl"
    run([
        PYTHON, "-u", APP / "run_kosis_coordinate_stage_c.py",
        "--beam-pool", beam,
        "--output", primary,
        "--fallback-output", fallback,
        "--state-output", root / "stage_c_state.jsonl",
        "--device", "cuda",
        "--reranker-batch-size", "32",
        "--obj-scope-bonus", "0.10",
    ])

    primary_by_id = {row["claim_measurement_id"]: row for row in read_jsonl(primary)}
    fallback_by_id = {row["claim_measurement_id"]: row for row in read_jsonl(fallback)}
    merged = [
        merge_fallback_coordinate_packets(
            primary_by_id.get(claim_id), None, fallback_by_id.get(claim_id)
        )
        for claim_id in sorted(eligible)
    ]
    merged_path = root / "merged_local_top5.jsonl"
    write_jsonl(merged_path, merged)
    summary_path = root / "coordinate_topk_summary.json"
    run([
        PYTHON, "-u", APP / "evaluate_coordinate_topk.py",
        "--predictions", merged_path,
        "--gold", GOLD,
        "--summary", summary_path,
        "--details", root / "coordinate_topk_details.csv",
    ])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    result = {
        "schema_version": "v24-combined-coordinate-ab-v1",
        "experiment_name": experiment_name,
        "preserve_table_fallback": preserve_table_fallback,
        "coordinate": summary["metrics"]["coordinate"],
        "full": summary["metrics"]["full"],
        "target_coordinate_top5": 22,
        "target_full_top5": 22,
        "coordinate_target_met": summary["metrics"]["coordinate"]["hit_at_5"] >= 22,
        "full_target_met": summary["metrics"]["full"]["hit_at_5"] >= 22,
    }
    (root / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("V24 COMBINED COORDINATE AB COMPLETE")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
