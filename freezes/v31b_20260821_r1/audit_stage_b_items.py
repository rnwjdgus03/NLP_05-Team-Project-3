#!/usr/bin/env python3
"""Print compact Stage-B coordinate candidates for selected claims/tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-b", required=True, type=Path)
    parser.add_argument("--claim", action="append", default=[])
    parser.add_argument("--table", action="append", default=[])
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    claims = set(args.claim)
    tables = set(args.table)
    for line in args.stage_b.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        claim_id = str(record.get("claim_measurement_id") or "")
        if claims and claim_id not in claims:
            continue
        rows = []
        for row in record.get("coordinate_candidates") or []:
            if tables and str(row.get("tbl_id") or "") not in tables:
                continue
            rows.append({
                "global_rank": row.get("global_candidate_rank"),
                "table_rank": row.get("table_rank"),
                "table": f"{row.get('tbl_id')} {row.get('tbl_name')}",
                "item": f"{row.get('selected_itm_id')} {row.get('selected_itm_name')}",
                "item_unit": row.get("selected_itm_unit"),
                "objects": [
                    str(row.get(f"selected_obj_l{level}_name") or "")
                    for level in range(1, 9)
                    if str(row.get(f"selected_obj_l{level}") or "")
                ],
                "dense": row.get("dense_score"),
                "item_component": row.get("item_component_score"),
                "table_prior": row.get("table_prior_score"),
                "unit_state": row.get("unit_structural_state"),
                "mandatory_aggregate": row.get("mandatory_aggregate"),
            })
            if len(rows) >= args.limit:
                break
        print(json.dumps({"claim": claim_id, "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
