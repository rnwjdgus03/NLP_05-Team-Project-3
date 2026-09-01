#!/usr/bin/env python3
"""Build a bounded Stage-C rank tail for API-unresolved claims only."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from kosis_coordinate_low_memory import JsonlCheckpoint
from kosis_coordinate_merge import validate_suggestion_packet
from run_kosis_coordinate_stage_c import (
    evidence_preserving_top_k,
    local_fallback_suggestion_packet,
)
from run_kosis_postgres_coordinate_top3 import local_suggestion_packet


def index_jsonl(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[str(row["claim_measurement_id"])] = row
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranked-pool", type=Path, required=True)
    parser.add_argument("--primary-decisions", type=Path, required=True)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--output-primary", type=Path, required=True)
    parser.add_argument("--output-fallback", type=Path, required=True)
    parser.add_argument("--output-claims", type=Path, required=True)
    parser.add_argument("--start-rank", type=int, default=6)
    parser.add_argument("--end-rank", type=int, default=10)
    parser.add_argument("--item-exact-slots", type=int, default=2)
    parser.add_argument("--stage-a-table-slots", type=int, default=1)
    parser.add_argument("--item-component-slots", type=int, default=1)
    args = parser.parse_args()
    if not (1 <= args.start_rank <= args.end_rank):
        raise ValueError("rank bounds must satisfy 1 <= start <= end")

    decisions = index_jsonl(args.primary_decisions)
    unresolved = {
        claim_id for claim_id, row in decisions.items()
        if row.get("claim_decision") != "VERIFIED_MATCH"
    }
    args.output_primary.parent.mkdir(parents=True, exist_ok=True)
    primary = JsonlCheckpoint(args.output_primary)
    fallback = JsonlCheckpoint(args.output_fallback)
    tail_width = args.end_rank - args.start_rank + 1
    with args.ranked_pool.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            claim_id = str(record["claim_measurement_id"])
            if claim_id not in unresolved:
                continue
            selected_all = evidence_preserving_top_k(
                list(record.get("ranked_candidates") or []), args.end_rank,
                exact_slots=args.item_exact_slots,
                stage_a_table_slots=args.stage_a_table_slots,
                item_component_slots=args.item_component_slots,
            )
            selected = selected_all[args.start_rank - 1:args.end_rank]
            if len(selected) > tail_width:
                raise AssertionError("tail selection exceeded its bound")
            packet = local_suggestion_packet(
                claim_id, record["claim"], selected[:3],
                metadata_snapshot_id=record["metadata_snapshot_id"],
                table_pool_count=int(record["table_pool_count"]),
                complete_table_count=int(record["complete_table_count"]),
            )
            validate_suggestion_packet(packet)
            primary.append(packet)
            packet = local_fallback_suggestion_packet(
                claim_id, record["claim"], selected[3:5],
                metadata_snapshot_id=record["metadata_snapshot_id"],
                table_pool_count=int(record["table_pool_count"]),
                complete_table_count=int(record["complete_table_count"]),
            )
            validate_suggestion_packet(packet)
            fallback.append(packet)

    with args.claims.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = [row for row in reader if row["claim_measurement_id"] in unresolved]
        fields = reader.fieldnames
    with args.output_claims.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({
        "primary_unresolved": len(unresolved),
        "tail_packets": len(primary.completed_ids),
        "start_rank": args.start_rank,
        "end_rank": args.end_rank,
    }))


if __name__ == "__main__":
    main()
