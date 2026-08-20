#!/usr/bin/env python3
"""Verify every blind-gold coordinate/value with the live KOSIS Open API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path("/home/ubuntu/kosis-project"))
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    project = args.project_root.resolve()
    sys.path.insert(0, str(project / "app"))
    from dotenv import load_dotenv
    load_dotenv(project / ".env")
    from kosis_api_test import get_stat_data

    rows = read_csv(args.input)
    failures = []
    now = datetime.now(timezone.utc).isoformat()
    for index, row in enumerate(rows, 1):
        api_rows = get_stat_data(
            row["gold_org_id"], row["gold_tbl_id"], row["gold_obj_l1"],
            row["gold_itm_id"], row["gold_prd_se"], 1,
            startPrdDe=row["gold_period"], endPrdDe=row["gold_period"],
        )
        exact = [item for item in api_rows if (
            str(item.get("ORG_ID", "")) == row["gold_org_id"]
            and str(item.get("TBL_ID", "")) == row["gold_tbl_id"]
            and str(item.get("ITM_ID", "")) == row["gold_itm_id"]
            and str(item.get("C1", "")) == row["gold_obj_l1"]
            and str(item.get("PRD_SE", "")) == row["gold_prd_se"]
            and str(item.get("PRD_DE", "")) == row["gold_period"]
        )]
        if len(exact) != 1:
            failures.append({"id": row["claim_measurement_id"], "reason": f"exact_rows={len(exact)}"})
            continue
        actual = exact[0]
        try:
            expected_value = float(row["gold_source_value"].replace(",", ""))
            actual_value = float(str(actual.get("DT", "")).replace(",", ""))
        except ValueError:
            failures.append({"id": row["claim_measurement_id"], "reason": "non_numeric_value"})
            continue
        tolerance = 0.051 if row["gold_source_unit"] == "%" else 0.51
        error = abs(expected_value - actual_value)
        value_ok = math.isfinite(actual_value) and error <= tolerance
        row.update({
            "gold_actual_value": str(actual_value),
            "gold_source_unit": str(actual.get("UNIT_NM") or row["gold_source_unit"]),
            "gold_ready": "Y" if value_ok else "N",
            "gold_verdict": "MATCH" if value_ok else "SOURCE_VALUE_MISMATCH",
            "gold_coordinate_status": "UNIQUE_LIVE_KOSIS_API" if value_ok else "FAILED_VALUE_CHECK",
            "gold_confidence": "HIGH" if value_ok else "LOW",
            "gold_reason": (
                f"KOSIS Open API exact coordinate returned one row; abs_error={error:g}; "
                f"tolerance={tolerance:g}"
            ),
            "gold_retrieved_at": now,
        })
        if not value_ok:
            failures.append({
                "id": row["claim_measurement_id"], "reason": "value_mismatch",
                "source": expected_value, "actual": actual_value, "error": error,
            })
        print(f"[{index}/{len(rows)}] {row['claim_measurement_id']} ready={row['gold_ready']} actual={actual_value}", flush=True)
        if index < len(rows):
            time.sleep(args.delay)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, rows)
    ready = sum(row["gold_ready"] == "Y" for row in rows)
    manifest = {
        "schema_version": "blind-coordinate-gold-lock-v1",
        "locked_before_prediction": True,
        "source_unverified_sha256": sha256(args.input),
        "locked_gold_sha256": sha256(args.output),
        "rows": len(rows), "ready_rows": ready, "failures": failures,
        "retrieval_time_utc": now,
        "verification": "KOSIS Open API exact org/table/item/obj/period row and value tolerance",
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if failures or ready != len(rows):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
