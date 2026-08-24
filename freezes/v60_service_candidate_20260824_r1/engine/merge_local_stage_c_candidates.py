#!/usr/bin/env python3
"""Merge Local Top-3 and rank-4/5 packets for coordinate regression."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kosis_coordinate_merge import merge_fallback_coordinate_packets


def read_jsonl(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return {row["claim_measurement_id"]: row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", required=True, type=Path)
    parser.add_argument("--fallback", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    primary = read_jsonl(args.primary)
    fallback = read_jsonl(args.fallback)
    claim_ids = sorted(set(primary) | set(fallback))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for claim_id in claim_ids:
            packet = merge_fallback_coordinate_packets(
                primary.get(claim_id), None, fallback.get(claim_id),
            )
            handle.write(json.dumps(packet, ensure_ascii=False) + "\n")
    print(f"merged_local_packets={len(claim_ids)} output={args.output}")


if __name__ == "__main__":
    main()
