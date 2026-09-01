#!/usr/bin/env python3
"""Add only KOSIS-API VERIFIED_MATCH coordinates as development alternates."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def coordinate_key(row: dict, gold: bool) -> tuple[str, ...]:
    prefix = "gold_" if gold else ""
    values = [str(row.get(prefix + name) or "") for name in ("org_id", "tbl_id")]
    values.append(str(row.get("gold_itm_id" if gold else "selected_itm_id") or ""))
    for level in range(1, 9):
        values.append(str(row.get(f"gold_obj_l{level}" if gold else f"selected_obj_l{level}") or ""))
    return tuple(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--verified", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    with args.gold.open(encoding="utf-8-sig", newline="") as handle:
        original = list(csv.DictReader(handle))
    fieldnames = list(original[0])
    by_claim = {row["claim_measurement_id"]: row for row in original}
    rows = list(original)
    seen = {(row["claim_measurement_id"], coordinate_key(row, True)) for row in rows}
    alternates = 0
    match_candidates = 0
    with args.verified.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            verified = json.loads(line)
            if verified.get("decision_status") != "VERIFIED_MATCH" or verified.get("verdict_code") != "MATCH":
                continue
            if not verified.get("coordinate_preflight_valid") or verified.get("period_alignment_state") != "exact":
                continue
            match_candidates += 1
            claim_id = str(verified.get("claim_measurement_id") or "")
            base = by_claim.get(claim_id)
            if base is None:
                continue
            key = (claim_id, coordinate_key(verified, False))
            if key in seen:
                continue
            seen.add(key)
            row = dict(base)
            row.update({
                "gold_org_id": str(verified.get("org_id") or ""),
                "gold_tbl_id": str(verified.get("tbl_id") or ""),
                "gold_tbl_name": str(verified.get("official_table_name") or verified.get("tbl_name") or ""),
                "gold_itm_id": str(verified.get("selected_itm_id") or ""),
                "gold_itm_name": str(verified.get("official_item_name") or verified.get("selected_itm_name") or ""),
                "gold_prd_se": str(verified.get("kosis_prd_se") or verified.get("api_prd_se") or ""),
                "gold_period": str(verified.get("kosis_period_used") or verified.get("normalized_target_period") or ""),
                "gold_source_value": str(verified.get("kosis_actual_raw") or ""),
                "gold_source_unit": str(verified.get("kosis_unit") or verified.get("official_item_unit") or ""),
                "gold_actual_value": str(verified.get("kosis_actual_value") or ""),
                "gold_coordinate_status": "ALTERNATE_RESOLVED",
                "gold_confidence": "HIGH",
                "gold_reason": "KOSIS API exact-period/value/unit MATCH; candidate-discovered development alternate",
                "gold_evidence_url": "https://kosis.kr/",
                "gold_label_source": "KOSIS_OPEN_API_VERIFIED_ALTERNATE_DEVELOPMENT",
                "human_reviewed": "N",
            })
            for level in range(1, 9):
                row[f"gold_obj_l{level}"] = str(verified.get(f"selected_obj_l{level}") or "")
                row[f"gold_obj_l{level}_name"] = str(verified.get(f"selected_obj_l{level}_name") or "")
            rows.append(row)
            alternates += 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(rows)
    manifest = {
        "schema_version": "v34-development-api-alternate-gold-v1",
        "development_only": True,
        "not_blind_evidence": True,
        "original_claims": len(original),
        "match_candidate_rows": match_candidates,
        "alternate_rows_added": alternates,
        "total_gold_rows": len(rows),
        "policy": "Only exact-period VERIFIED_MATCH rows with valid PostgreSQL preflight; no mismatch/review rows.",
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
