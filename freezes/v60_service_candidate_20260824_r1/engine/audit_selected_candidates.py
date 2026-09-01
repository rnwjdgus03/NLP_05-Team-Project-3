#!/usr/bin/env python3
"""Print selected Stage-C coordinates for chosen claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict[str, dict]:
    return {
        row["claim_measurement_id"]: row
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        for row in [json.loads(line)]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--claim", action="append", default=[])
    args = parser.parse_args()
    primary = load(args.run_dir / "local_coordinate_top3.jsonl")
    fallback = load(args.run_dir / "local_coordinate_rank4_5_fallback.jsonl")
    for claim_id in args.claim:
        rows = (primary[claim_id].get("suggestions") or []) + (
            fallback[claim_id].get("suggestions") or []
        )
        print(json.dumps({
            "claim": claim_id,
            "suggestions": [{
                "rank": rank,
                "coordinate": row.get("coordinate"),
                "table": (row.get("evidence") or {}).get("tbl_name"),
                "item": (row.get("evidence") or {}).get("item_name"),
                "objects": (row.get("evidence") or {}).get("objects"),
                "table_rank": (row.get("evidence") or {}).get("table_rank"),
                "scope_exact": (row.get("evidence") or {}).get("coordinate_scope_exact"),
                "score": (row.get("evidence") or {}).get("final_rank_score"),
            } for rank, row in enumerate(rows, 1)],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
