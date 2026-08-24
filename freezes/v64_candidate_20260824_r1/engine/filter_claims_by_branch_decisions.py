#!/usr/bin/env python3
"""Keep claims lacking VERIFIED_MATCH in every supplied decision file."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def matched(path: Path) -> set[str]:
    result = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if row.get("claim_decision") == "VERIFIED_MATCH":
                    result.add(str(row["claim_measurement_id"]))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    excluded = set().union(*(matched(path) for path in args.decisions))
    with args.claims.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = [row for row in reader if row["claim_measurement_id"] not in excluded]
        fields = reader.fieldnames
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps({"excluded_api_matches": len(excluded), "remaining_claims": len(rows)}))


if __name__ == "__main__":
    main()
