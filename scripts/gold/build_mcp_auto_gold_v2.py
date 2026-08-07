"""Build a larger, tiered automatic gold set for the news fact-check pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE100 = ROOT / "outputs" / "gold" / "gold_measurement_in_ready_Y_top100_merged.csv"
FULL_GOLD = ROOT / "data" / "gold" / "mcp_auto_gold_v1.csv"
READY177 = ROOT / "data" / "shared_20260802" / "05_hcx_measurements_kosis_ready.csv"
OUTPUT = ROOT / "data" / "gold" / "mcp_auto_gold_v2.csv"
MANIFEST = ROOT / "data" / "gold" / "mcp_auto_gold_v2_manifest.json"


FIELDS = [
    "claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
    "claim_text", "measurement_text", "measurement_usage", "claim_domain_scope",
    "measurement_binding_source", "measurement_role", "measurement_indicator",
    "measurement_item", "value", "unit", "measurement_period",
    "measurement_prd_se", "gold_verifiable", "gold_measurement_correct",
    "gold_ready", "gold_label_tier", "gold_org_id", "gold_tbl_id",
    "gold_tbl_name", "gold_itm_id", "gold_itm_name", "gold_obj_l1",
    "gold_obj_l1_name", "gold_prd_se", "gold_period", "gold_previous_period",
    "gold_value_type", "gold_derivation_method", "gold_source_unit",
    "gold_source_value", "gold_source_previous_value", "gold_actual_value",
    "gold_claim_signed_value", "gold_abs_error", "gold_relative_error_pct",
    "gold_tolerance", "gold_verdict", "gold_coordinate_status",
    "gold_confidence", "gold_reason", "gold_evidence_url", "gold_retrieved_at",
    "gold_label_source", "human_reviewed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def empty_row() -> dict[str, object]:
    return {field: "" for field in FIELDS}


def copy_fields(target: dict[str, object], source: dict[str, str], names: list[str]) -> None:
    for name in names:
        target[name] = source.get(name, "")


COMMON = [
    "claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
    "claim_text", "measurement_text", "measurement_usage", "claim_domain_scope",
    "measurement_binding_source", "measurement_role", "measurement_indicator",
    "measurement_item", "value", "unit", "measurement_period", "measurement_prd_se",
]


def base_row(source: dict[str, str]) -> dict[str, object]:
    row = empty_row()
    copy_fields(row, source, COMMON)
    verifiable = source.get("gold_verifiable", "")
    measurement_correct = source.get("gold_measurement_correct", "")
    ready = "Y" if verifiable == "Y" and measurement_correct == "Y" else "N"
    if verifiable == "N":
        tier = "AUTO_NEGATIVE"
        coordinate_status = "NOT_APPLICABLE"
        confidence = "MEDIUM"
        reason = "자동 범위·측정 규칙에서 KOSIS 검증 불가로 라벨"
    else:
        tier = "AUTO_POSITIVE"
        coordinate_status = "UNRESOLVED"
        confidence = "MEDIUM"
        reason = "자동 규칙에서 KOSIS 검증 가능으로 라벨; 좌표·값은 미확정"
    row.update(
        gold_verifiable=verifiable,
        gold_measurement_correct=measurement_correct,
        gold_ready=ready,
        gold_label_tier=tier,
        gold_coordinate_status=coordinate_status,
        gold_confidence=confidence,
        gold_reason=reason,
        gold_label_source="AUTO_RULE_LABEL_V2",
        human_reviewed="N",
    )
    return row


FULL_FIELDS = [
    "gold_org_id", "gold_tbl_id", "gold_tbl_name", "gold_itm_id",
    "gold_itm_name", "gold_obj_l1", "gold_obj_l1_name", "gold_prd_se",
    "gold_period", "gold_previous_period", "gold_value_type",
    "gold_derivation_method", "gold_source_unit", "gold_source_value",
    "gold_source_previous_value", "gold_actual_value", "gold_claim_signed_value",
    "gold_abs_error", "gold_relative_error_pct", "gold_tolerance", "gold_verdict",
    "gold_coordinate_status", "gold_confidence", "gold_evidence_url",
    "gold_retrieved_at", "gold_label_source", "human_reviewed",
]


def full_row(source: dict[str, str], metadata: dict[str, str]) -> dict[str, object]:
    row = empty_row()
    copy_fields(row, metadata, COMMON)
    row["claim_measurement_id"] = source["claim_measurement_id"]
    row["claim_text"] = source["claim_text"]
    row["value"] = source["claim_value"]
    row["unit"] = source["claim_unit"]
    row["gold_verifiable"] = source["gold_verifiable"]
    row["gold_measurement_correct"] = source["gold_measurement_correct"]
    row["gold_ready"] = source["gold_ready"]
    row["gold_label_tier"] = "FULL_KOSIS"
    copy_fields(row, source, FULL_FIELDS)
    row["gold_reason"] = source.get("gold_canonical_reason", "")
    return row


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = read_csv(BASE100)
    full = read_csv(FULL_GOLD)
    ready = {row["claim_measurement_id"]: row for row in read_csv(READY177)}

    base_ids = {row["claim_measurement_id"] for row in base}
    full_ids = {row["claim_measurement_id"] for row in full}
    if base_ids & full_ids:
        raise ValueError(f"base/full overlap: {sorted(base_ids & full_ids)}")
    missing_metadata = sorted(full_ids - set(ready))
    if missing_metadata:
        raise ValueError(f"full rows missing metadata: {missing_metadata}")

    rows = [base_row(row) for row in base]
    rows.extend(full_row(row, ready[row["claim_measurement_id"]]) for row in full)
    rows.sort(key=lambda row: str(row["claim_measurement_id"]))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    tier_counts: dict[str, int] = {}
    for row in rows:
        tier = str(row["gold_label_tier"])
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    manifest = {
        "dataset": "mcp_auto_gold_v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "unique_measurement_count": len({row["claim_measurement_id"] for row in rows}),
        "tier_counts": tier_counts,
        "gold_verifiable_counts": {
            "Y": sum(row["gold_verifiable"] == "Y" for row in rows),
            "N": sum(row["gold_verifiable"] == "N" for row in rows),
        },
        "human_reviewed": False,
        "sources": {
            str(BASE100.relative_to(ROOT)).replace("\\", "/"): sha256(BASE100),
            str(FULL_GOLD.relative_to(ROOT)).replace("\\", "/"): sha256(FULL_GOLD),
            str(READY177.relative_to(ROOT)).replace("\\", "/"): sha256(READY177),
        },
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(OUTPUT),
        "tier_meaning": {
            "FULL_KOSIS": "MCP table/meta/data checked; coordinate and actual value fixed",
            "AUTO_POSITIVE": "automatically labeled verifiable; coordinate/value unresolved",
            "AUTO_NEGATIVE": "automatically labeled outside KOSIS verification target",
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
