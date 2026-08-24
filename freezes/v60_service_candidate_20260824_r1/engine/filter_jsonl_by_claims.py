#!/usr/bin/env python3
"""Filter a JSONL checkpoint to the claim IDs present in a CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    with args.claims.open(encoding="utf-8-sig", newline="") as handle:
        claim_ids = {str(row["claim_measurement_id"]) for row in csv.DictReader(handle)}
    rows = []
    with args.input.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("claim_measurement_id") or "") in claim_ids:
                rows.append(row)
    output_ids = {str(row["claim_measurement_id"]) for row in rows}
    missing = claim_ids - output_ids
    if missing and args.require_all:
        raise ValueError(f"missing claim IDs in JSONL: {sorted(missing)[:10]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({
        "requested_claims": len(claim_ids), "output_rows": len(rows),
        "missing_in_jsonl": len(missing),
    }))


if __name__ == "__main__":
    main()
