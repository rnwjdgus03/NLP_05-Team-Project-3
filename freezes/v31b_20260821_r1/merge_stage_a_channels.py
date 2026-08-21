#!/usr/bin/env python3
"""Preserve incumbent Stage A tables and append bounded ITEM-channel fallbacks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def table_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("org_id") or ""), str(row.get("tbl_id") or "")


def merge_packet(
    baseline: Mapping[str, Any], expanded: Mapping[str, Any],
    *, baseline_top_k: int = 10, fallback_slots: int = 2,
) -> dict[str, Any]:
    if baseline.get("claim_measurement_id") != expanded.get("claim_measurement_id"):
        raise ValueError("claim id mismatch")
    if baseline.get("claim_fingerprint") != expanded.get("claim_fingerprint"):
        raise ValueError(
            f"claim fingerprint mismatch: {baseline.get('claim_measurement_id')}"
        )
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in list(baseline.get("table_candidates") or [])[:baseline_top_k]:
        row = dict(raw)
        key = table_key(row)
        if not all(key) or key in seen:
            continue
        row["stage_a_channel"] = "INCUMBENT_BASELINE"
        row["stage_a_channel_rank"] = int(raw.get("rank") or len(selected) + 1)
        selected.append(row)
        seen.add(key)
    appended = 0
    for raw in expanded.get("table_candidates") or []:
        key = table_key(raw)
        if not all(key) or key in seen:
            continue
        row = dict(raw)
        row["stage_a_channel"] = "ITEM_RECALL_FALLBACK"
        row["stage_a_channel_rank"] = int(raw.get("rank") or 0)
        row["verification_review_required"] = True
        row["verification_review_reason"] = "stage_a_item_recall_fallback"
        selected.append(row)
        seen.add(key)
        appended += 1
        if appended >= fallback_slots:
            break
    for rank, row in enumerate(selected, 1):
        row["rank"] = rank
    return {
        **dict(expanded),
        "table_candidates": selected,
        "incumbent_table_count": min(baseline_top_k, len(baseline.get("table_candidates") or [])),
        "item_fallback_table_count": appended,
        "stage_a_merge_policy": "INCUMBENT_TOP10_PLUS_ITEM_FALLBACK",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--expanded", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline-top-k", type=int, default=10)
    parser.add_argument("--fallback-slots", type=int, default=2)
    args = parser.parse_args()
    baseline = {row["claim_measurement_id"]: row for row in read_jsonl(args.baseline)}
    expanded = {row["claim_measurement_id"]: row for row in read_jsonl(args.expanded)}
    if set(baseline) != set(expanded):
        raise ValueError("baseline and expanded claim sets differ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for claim_id in baseline:
            packet = merge_packet(
                baseline[claim_id], expanded[claim_id],
                baseline_top_k=args.baseline_top_k,
                fallback_slots=args.fallback_slots,
            )
            handle.write(json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"merged_claims={len(baseline)} output={args.output}")


if __name__ == "__main__":
    main()
