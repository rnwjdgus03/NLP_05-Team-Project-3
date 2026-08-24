#!/usr/bin/env python3
"""Merge protected semantic/legacy slots with balanced structured recall."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_packets(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def table_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("org_id") or ""), str(row.get("tbl_id") or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", required=True, type=Path)
    parser.add_argument("--balanced", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--legacy-slots", type=int, default=7)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if not 0 <= args.legacy_slots <= args.top_k:
        parser.error("legacy slots must be within final top-k")

    legacy = read_packets(args.legacy)
    balanced_by_id = {
        str(packet.get("claim_measurement_id") or ""): packet
        for packet in read_packets(args.balanced)
    }
    output: list[dict[str, Any]] = []
    for primary in legacy:
        claim_id = str(primary.get("claim_measurement_id") or "")
        secondary = balanced_by_id.pop(claim_id, None)
        if secondary is None:
            raise ValueError(f"balanced packet missing: {claim_id}")
        if primary.get("claim_fingerprint") != secondary.get("claim_fingerprint"):
            raise ValueError(f"claim fingerprint mismatch: {claim_id}")
        legacy_rows = list(primary.get("table_candidates") or [])
        balanced_rows = list(secondary.get("table_candidates") or [])
        selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def append(rows: list[dict[str, Any]], limit: int, source: str) -> None:
            for raw in rows:
                key = table_key(raw)
                if not all(key) or key in seen:
                    continue
                row = dict(raw)
                row["stage_a_merge_source"] = source
                selected.append(row)
                seen.add(key)
                if len(selected) >= limit:
                    break

        append(legacy_rows[:args.legacy_slots], args.legacy_slots, "LEGACY_PROTECTED")
        append(balanced_rows, args.top_k, "BALANCED_STRUCTURED")
        append(legacy_rows, args.top_k, "LEGACY_BACKFILL")
        selected = [
            {**row, "rank": rank, "table_family_rank": rank}
            for rank, row in enumerate(selected[:args.top_k], 1)
        ]
        output.append({
            **primary,
            "schema_version": primary.get("schema_version"),
            "item_recall_policy": "legacy7_balanced_tail",
            "stage_a_merge_legacy_slots": args.legacy_slots,
            "table_candidates": selected,
        })
    if balanced_by_id:
        raise ValueError(
            "legacy packets missing: " + ",".join(sorted(balanced_by_id)[:5])
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output),
        encoding="utf-8",
    )
    print(f"merged_packets={len(output)} output={args.output}")


if __name__ == "__main__":
    main()
