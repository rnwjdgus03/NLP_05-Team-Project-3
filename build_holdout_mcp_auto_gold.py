#!/usr/bin/env python3
"""Build evaluator-compatible auto gold from audited KOSIS MCP results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


GOLD_OBJ_FIELDS = [
    field
    for level in range(1, 9)
    for field in (
        f"gold_obj_l{level}", f"gold_obj_l{level}_name",
        f"gold_obj_l{level}_axis_id", f"gold_obj_l{level}_axis_name",
    )
]
GOLD_FIELDS = [
    "gold_id", "gold_org_id", "gold_tbl_id", "gold_tbl_name",
    *GOLD_OBJ_FIELDS,
    "gold_itm_id", "gold_itm_name", "gold_prd_se", "gold_period",
    "gold_previous_period", "gold_source_value", "gold_source_unit",
    "gold_actual_value", "gold_actual_unit", "gold_coordinate_status", "gold_label_source",
    "gold_evidence_url", "gold_retrieved_at", "human_reviewed",
]
REQUIRED_AUDIT = {
    "claim_measurement_id", "org_id", "tbl_id", "tbl_name", "itm_id",
    "obj_l1", "prd_se", "period", "source_value", "source_unit",
    "actual_value", "evidence_url", "retrieved_at", "mcp_validated",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_audit(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = sorted(REQUIRED_AUDIT - set(row))
            if missing:
                raise ValueError(f"audit line {line_number} missing: {missing}")
            if row["mcp_validated"] is not True:
                raise ValueError(f"audit line {line_number} is not MCP validated")
            rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurements", required=True)
    parser.add_argument("--audit-jsonl", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    measurements_path = Path(args.measurements)
    audit_path = Path(args.audit_jsonl)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest)
    measurements = {
        row["claim_measurement_id"]: row for row in read_csv(measurements_path)
        if row.get("claim_measurement_id")
    }
    audits = read_audit(audit_path)
    duplicate_ids = [key for key, count in Counter(
        str(row["claim_measurement_id"]) for row in audits
    ).items() if count > 1]
    if duplicate_ids:
        raise ValueError(f"duplicate audit ids: {duplicate_ids}")

    rows: list[dict[str, object]] = []
    for index, audit in enumerate(audits, start=1):
        measurement_id = str(audit["claim_measurement_id"])
        if measurement_id not in measurements:
            raise ValueError(f"measurement not found: {measurement_id}")
        row: dict[str, object] = dict(measurements[measurement_id])
        row.update(
            gold_id=f"HOLDOUT-MCP-{index:03d}",
            gold_org_id=audit["org_id"],
            gold_tbl_id=audit["tbl_id"],
            gold_tbl_name=audit["tbl_name"],
            gold_itm_id=audit["itm_id"],
            gold_itm_name=audit.get("itm_name", ""),
            gold_prd_se=audit["prd_se"],
            gold_period=audit["period"],
            gold_previous_period=audit.get("previous_period", "N/A"),
            gold_source_value=audit["source_value"],
            gold_source_unit=audit["source_unit"],
            gold_actual_value=audit["actual_value"],
            gold_actual_unit=audit.get("actual_unit", audit["source_unit"]),
            gold_coordinate_status="MCP_ACTUAL_VALUE_CONFIRMED",
            gold_label_source="KOSIS_MCP_SEARCH_VALIDATE_GET_DATA",
            gold_evidence_url=audit["evidence_url"],
            gold_retrieved_at=audit["retrieved_at"],
            human_reviewed="N",
        )
        for level in range(1, 9):
            row[f"gold_obj_l{level}"] = audit.get(f"obj_l{level}", "N/A")
            row[f"gold_obj_l{level}_name"] = audit.get(f"obj_l{level}_name", "N/A")
            row[f"gold_obj_l{level}_axis_id"] = audit.get(f"obj_l{level}_axis_id", "N/A")
            row[f"gold_obj_l{level}_axis_name"] = audit.get(f"obj_l{level}_axis_name", "N/A")
        rows.append(row)

    source_fields = list(next(iter(measurements.values())).keys()) if measurements else []
    fields = list(dict.fromkeys(source_fields + GOLD_FIELDS))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "unique_measurement_count": len({row["claim_measurement_id"] for row in rows}),
        "human_reviewed": False,
        "label_source": "KOSIS MCP search -> validate -> get_data",
        "measurements": str(measurements_path),
        "measurements_sha256": sha256(measurements_path),
        "audit_jsonl": str(audit_path),
        "audit_sha256": sha256(audit_path),
        "output": str(output_path),
        "output_sha256": sha256(output_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
