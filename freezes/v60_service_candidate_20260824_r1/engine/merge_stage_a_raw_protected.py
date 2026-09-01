#!/usr/bin/env python3
"""Merge Stage A channels with bounded raw-recall protection (no gold input)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> dict[str, dict[str, Any]]:
    return {
        row["claim_measurement_id"]: row
        for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    }


def key(row: dict[str, Any]) -> tuple[str, str]:
    table = row.get("table") or row
    return str(row.get("org_id") or table.get("org_id") or ""), str(
        row.get("tbl_id") or table.get("tbl_id") or ""
    )


def interleave(left: list[dict], right: list[dict]) -> list[dict]:
    rows = []
    for index in range(max(len(left), len(right))):
        if index < len(left):
            rows.append(left[index])
        if index < len(right):
            rows.append(right[index])
    return rows


def append(selected: list[dict], seen: set, rows: list[dict], limit: int, source: str) -> None:
    for raw in rows:
        if len(selected) >= limit:
            return
        table_key = key(raw)
        if not all(table_key) or table_key in seen:
            continue
        selected.append({**raw, "stage_a_merge_source": source})
        seen.add(table_key)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--balanced", type=Path, required=True)
    parser.add_argument("--legacy-raw", type=Path, required=True)
    parser.add_argument("--balanced-raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-slots", type=int, default=7)
    parser.add_argument("--raw-slots", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    sources = [read(path) for path in (args.legacy, args.balanced, args.legacy_raw, args.balanced_raw)]
    claim_ids = list(sources[0])
    if any(set(source) != set(claim_ids) for source in sources[1:]):
        raise ValueError("Stage A channel claim sets differ")
    packets = []
    for claim_id in claim_ids:
        legacy, balanced, legacy_raw, balanced_raw = (source[claim_id] for source in sources)
        selected, seen = [], set()
        reranked_limit = args.top_k - args.raw_slots
        append(selected, seen, list(legacy.get("table_candidates") or [])[:args.legacy_slots],
               min(args.legacy_slots, reranked_limit), "LEGACY_PROTECTED")
        append(selected, seen, list(balanced.get("table_candidates") or []),
               reranked_limit, "BALANCED_STRUCTURED")
        append(selected, seen, list(legacy.get("table_candidates") or []),
               reranked_limit, "LEGACY_BACKFILL")
        raw = interleave(list(legacy_raw.get("candidates") or []), list(balanced_raw.get("candidates") or []))
        append(selected, seen, raw, args.top_k, "RAW_RECALL_PROTECTED")
        append(selected, seen, interleave(list(legacy.get("table_candidates") or []),
                                          list(balanced.get("table_candidates") or [])),
               args.top_k, "RERANK_BACKFILL")
        selected = [{**row, "rank": rank, "table_family_rank": rank}
                    for rank, row in enumerate(selected[:args.top_k], 1)]
        packets.append({
            **legacy,
            "item_recall_policy": "v34_legacy7_raw3_protected",
            "stage_a_merge_legacy_slots": args.legacy_slots,
            "stage_a_merge_raw_slots": args.raw_slots,
            "table_candidates": selected,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in packets), encoding="utf-8")
    print(f"merged_packets={len(packets)} policy=legacy{args.legacy_slots}_raw{args.raw_slots}")


if __name__ == "__main__":
    main()
