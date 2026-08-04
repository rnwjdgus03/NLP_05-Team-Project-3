#!/usr/bin/env python3
"""Build audit reports from an already-run feasibility regression.

This script does not run search, metadata collection, validation, verification,
or any KOSIS API call.  It only normalizes period strings for reporting and
joins existing validated/verified CSV files.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: Sequence[Mapping[str, str]], fields: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_measurement_year(value: str) -> str:
    """Extract a year without rewriting the original period value.

    Examples:
      2025    -> 2025
      202501  -> 2025
      2025-01 -> 2025
      2025Q1  -> 2025
      2025년  -> 2025
    """
    match = re.search(r"(20\d{2})", str(value or "").strip())
    return match.group(1) if match else ""


def selected_obj_codes(row: Mapping[str, str]) -> str:
    return "|".join(row.get(f"selected_obj_l{level}", "") for level in range(1, 9) if row.get(f"selected_obj_l{level}", ""))


def selected_obj_names(row: Mapping[str, str]) -> str:
    return "|".join(row.get(f"selected_obj_l{level}_name", "") for level in range(1, 9) if row.get(f"selected_obj_l{level}_name", ""))


def top_tables(rows: Sequence[Mapping[str, str]], limit: int = 5) -> str:
    def rank(row: Mapping[str, str]) -> int:
        try:
            return int(float(str(row.get("candidate_rank", "999"))))
        except ValueError:
            return 999
    ordered = sorted(rows, key=rank)[:limit]
    return " | ".join(
        f"{row.get('candidate_rank','')}:{row.get('tbl_id','')}:{row.get('tbl_name','')}:{row.get('candidate_score','')}"
        for row in ordered
    )


def rank1(rows: Sequence[Mapping[str, str]]) -> Mapping[str, str]:
    if not rows:
        return {}
    def rank(row: Mapping[str, str]) -> int:
        try:
            return int(float(str(row.get("candidate_rank", "999"))))
        except ValueError:
            return 999
    return sorted(rows, key=rank)[0]


def classify_dev_root_cause(row: Mapping[str, str]) -> str:
    for key in ("root_cause",):
        if row.get(key):
            return row[key]
    reason = " ".join([row.get("review_reason", ""), row.get("mapping_reason", ""), row.get("semantic_gate_reason", "")])
    feasibility = row.get("mapping_feasibility", "")
    if row.get("measurement_structure_valid") == "N":
        return "MEASUREMENT_EXTRACTION_ERROR"
    if "TABLE_CAPABILITY_UNREVIEWED" in reason:
        return "TABLE_CAPABILITY_UNREVIEWED"
    if row.get("semantic_mismatch_code"):
        return "TABLE_SEMANTIC_MISMATCH"
    if feasibility == "PERIOD_SCOPE_MISMATCH":
        return "PERIOD_SCOPE_MISMATCH"
    if row.get("formula_valid") == "N" or feasibility.startswith("DERIVED"):
        return "DERIVED_FORMULA_INCOMPLETE"
    if "NO_COMPATIBLE_ITEM" in reason:
        return "ITEM_SEMANTIC_MISMATCH"
    if "OBJ_UNRESOLVED" in reason:
        return "OBJ_SEMANTIC_MISMATCH"
    if "UNIT_MISMATCH" in reason:
        return "UNIT_MISMATCH"
    if "API" in reason:
        return "API_ERROR"
    if row.get("final_status") == "NOT_KOSIS":
        return "UNSUPPORTED_BY_KOSIS"
    return "TABLE_RETRIEVAL_ERROR" if not row.get("tbl_id") else "KOSIS_SCOPE_UNCONFIRMED"


def build_reports(output_dir: Path, previous_dir: Path, capability_path: Path, input_path: Path) -> dict[str, object]:
    old_validated, _ = read_csv(previous_dir / "kosis_mapping_ready_500_real_kosis_validated_mappings.csv")
    validated, validated_fields = read_csv(output_dir / "kosis_mapping_ready_500_real_kosis_validated_mappings.csv")
    verified, _ = read_csv(output_dir / "kosis_mapping_ready_500_real_kosis_verified.csv")
    ready_audit_path = previous_dir / "manual_audit_ready_21.csv"
    if ready_audit_path.exists():
        ready21, _ = read_csv(ready_audit_path)
    else:
        ready21 = [row for row in old_validated if row.get("final_status") == "READY"]
    capabilities, _ = read_csv(capability_path)
    input_rows, _ = read_csv(input_path) if input_path.exists() else ([], [])

    old_by_key = {(row.get("claim_measurement_id", ""), row.get("tbl_id") or row.get("selected_tbl_id", "")): row for row in old_validated}
    new_by_key = {(row.get("claim_measurement_id", ""), row.get("tbl_id") or row.get("selected_tbl_id", "")): row for row in validated}
    verified_by_id = {row.get("claim_measurement_id", ""): row for row in verified}
    capability_by_tbl = {row.get("tbl_id", ""): row for row in capabilities}
    input_by_id = {row.get("claim_measurement_id", ""): row for row in input_rows}

    comparison = []
    for source in ready21:
        claim_measurement_id = source.get("claim_measurement_id", "")
        table_id = source.get("selected_tbl_id") or source.get("tbl_id", "")
        new = new_by_key.get((claim_measurement_id, table_id), {})
        old = old_by_key.get((claim_measurement_id, table_id), {})
        verdict = verified_by_id.get(claim_measurement_id, {})
        comparison.append({
            "claim_measurement_id": claim_measurement_id,
            "claim_text": source.get("claim_text", ""),
            "measurement_indicator": source.get("measurement_indicator", ""),
            "selected_tbl_id": table_id,
            "selected_itm_id": new.get("selected_itm_id") or source.get("selected_itm_id", ""),
            "selected_obj_codes": selected_obj_codes(new) or selected_obj_codes(source),
            "old_final_status": old.get("final_status") or source.get("final_status", "READY"),
            "new_final_status": new.get("final_status", ""),
            "mapping_feasibility": new.get("mapping_feasibility", ""),
            "table_can_represent_claim": new.get("table_can_represent_claim", ""),
            "formula_valid": new.get("formula_valid", ""),
            "period_scope_valid": new.get("period_scope_valid", ""),
            "classification_alignment": new.get("classification_alignment", ""),
            "codeset_valid": new.get("codeset_valid", ""),
            "capability_review_status": new.get("capability_review_status", ""),
            "review_reason": new.get("review_reason", ""),
            "verdict": verdict.get("verdict", ""),
        })
    write_csv(output_dir / "ready_21_before_after_feasibility.csv", comparison)

    ready_rows = [row for row in validated if row.get("final_status") == "READY"]
    ready_detail = []
    blank_review_fields = {
        "gold_measurement_correct": "", "gold_tbl_correct": "", "gold_item_correct": "",
        "gold_obj_correct": "", "gold_period_correct": "", "gold_formula_correct": "",
        "gold_final_ready": "", "manual_reason": "", "reviewer": "", "reviewed_at": "",
    }
    for row in ready_rows:
        verdict = verified_by_id.get(row.get("claim_measurement_id", ""), {})
        verdict_code = verdict.get("verdict_code", "")
        category = ""
        if verdict_code == "VALUE_MISMATCH":
            category = "A_COORDINATE_EXACT_VALUE_MISMATCH"
        elif verdict_code == "WITHIN_UNCERTAINTY_BAND":
            category = "B_UNCERTAINTY_OR_ROUNDING_BAND"
        elif verdict_code == "LIKELY_MISMAPPING":
            category = "C_VERIFICATION_MAPPING_RISK"
        audit_row = {
            "claim_measurement_id": row.get("claim_measurement_id", ""),
            "claim_text": row.get("claim_text", ""),
            "measurement_indicator": row.get("measurement_indicator") or row.get("indicator", ""),
            "measurement_role": row.get("measurement_role", ""),
            "value": row.get("value", ""),
            "unit": row.get("unit", ""),
            "measurement_period": row.get("measurement_period") or row.get("period", ""),
            "selected_tbl_id": row.get("tbl_id", ""),
            "selected_tbl_name": row.get("tbl_name", ""),
            "selected_itm_id": row.get("selected_itm_id", ""),
            "selected_itm_name": row.get("selected_itm_name", ""),
            "selected_obj_codes": selected_obj_codes(row),
            "selected_obj_names": selected_obj_names(row),
            "final_status": row.get("final_status", ""),
            "verdict": verdict.get("verdict", ""),
            "verdict_code": verdict_code,
            "review_reason": row.get("review_reason", ""),
            "verification_reason": verdict.get("verdict_reason", ""),
            "diagnosis_category": category,
            "recommended_final_status": "REVIEW" if verdict_code == "LIKELY_MISMAPPING" else row.get("final_status", ""),
            "recommended_reason": "VERIFICATION_MAPPING_RISK" if verdict_code == "LIKELY_MISMAPPING" else "",
            "kosis_actual_value": verdict.get("kosis_actual_value", ""),
            "kosis_period_used": verdict.get("kosis_period_used", ""),
            "kosis_unit": verdict.get("kosis_unit", ""),
            "capability_source": row.get("capability_source", ""),
            "capability_review_status": row.get("capability_review_status", ""),
            "evidence_url": row.get("evidence_url", ""),
            "evidence_note": row.get("evidence_note", ""),
            "mapping_feasibility": row.get("mapping_feasibility", ""),
            "representation_reason": row.get("representation_reason", ""),
        }
        audit_row.update(blank_review_fields)
        ready_detail.append(audit_row)
    write_csv(output_dir / "manual_audit_feasibility_ready.csv", ready_detail)
    write_csv(output_dir / "ready_10_verifier_consistency.csv", ready_detail)

    input_2025_ids = []
    for source in input_rows:
        period_raw = source.get("measurement_period") or source.get("period", "")
        if normalize_measurement_year(period_raw) == "2025" and source.get("claim_measurement_id", ""):
            input_2025_ids.append(source.get("claim_measurement_id", ""))
    input_2025_ids = sorted(dict.fromkeys(input_2025_ids))

    rows_2025 = []
    seen_2025_ids = set()
    for row in validated:
        period_raw = row.get("measurement_period") or row.get("period", "")
        year = normalize_measurement_year(period_raw)
        if year == "2025":
            out = dict(row)
            verdict = verified_by_id.get(row.get("claim_measurement_id", ""), {})
            out["measurement_period_raw"] = period_raw
            out["measurement_year_normalized"] = year
            out["is_2025_measurement"] = "Y"
            out["verdict"] = verdict.get("verdict", "")
            out["verdict_code"] = verdict.get("verdict_code", "")
            out["kosis_actual_value"] = verdict.get("kosis_actual_value", "")
            rows_2025.append(out)
            seen_2025_ids.add(row.get("claim_measurement_id", ""))

    for missing_id in input_2025_ids:
        if missing_id in seen_2025_ids:
            continue
        source = input_by_id.get(missing_id, {})
        period_raw = source.get("measurement_period") or source.get("period", "")
        rows_2025.append({
            **source,
            "measurement_period_raw": period_raw,
            "measurement_year_normalized": normalize_measurement_year(period_raw),
            "is_2025_measurement": "Y",
            "candidate_rank": "",
            "tbl_id": "",
            "tbl_name": "",
            "mapping_status": "NO_CANDIDATE",
            "mapping_reason": "NO_TABLE_CANDIDATE_AFTER_SEARCH",
            "final_status": "REVIEW",
            "review_reason": "NO_TABLE_CANDIDATE_AFTER_SEARCH",
            "mapping_feasibility": "",
            "root_cause": "TABLE_RETRIEVAL_ERROR",
            "measurement_structure_valid": "",
            "measurement_structure_issue": "",
            "recommended_upstream_fix": "",
            "verdict": "판단불가",
            "verdict_code": "NO_TABLE_CANDIDATE_AFTER_SEARCH",
            "kosis_actual_value": "",
        })
    write_csv(
        output_dir / "feasibility_results_2025.csv",
        rows_2025,
        list(dict.fromkeys(validated_fields + [
            "measurement_period_raw", "measurement_year_normalized", "is_2025_measurement",
            "verdict", "verdict_code", "kosis_actual_value",
        ])),
    )

    by_tbl: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows_2025:
        by_tbl[row.get("tbl_id", "")].append(row)
    priority = []
    for table_id, rows in by_tbl.items():
        capability = capability_by_tbl.get(table_id, {})
        feasibility_counts = Counter(row.get("mapping_feasibility", "") for row in rows)
        measurement_count = len({row.get("claim_measurement_id", "") for row in rows})
        direct_count = feasibility_counts.get("DIRECT_COORDINATE", 0)
        non_direct_count = sum(value for key, value in feasibility_counts.items() if key != "DIRECT_COORDINATE")
        priority.append({
            "tbl_id": table_id,
            "tbl_name": rows[0].get("tbl_name", ""),
            "measurement_count": str(measurement_count),
            "candidate_row_count": str(len(rows)),
            "measurement_indicators": "|".join(sorted({row.get("measurement_indicator") or row.get("indicator", "") for row in rows})),
            "mapping_feasibility_counts": json.dumps(dict(feasibility_counts), ensure_ascii=False),
            "capability_source": capability.get("capability_source", ""),
            "capability_review_status": capability.get("capability_review_status", ""),
            "_sort": (measurement_count, direct_count, 1 if capability.get("capability_review_status") == "OFFICIAL_REVIEWED" else 0, -non_direct_count),
        })
    priority.sort(key=lambda row: row["_sort"], reverse=True)
    for index, row in enumerate(priority, 1):
        row["review_priority"] = str(index)
        row.pop("_sort", None)
    write_csv(output_dir / "feasibility_2025_table_review_priority.csv", priority)

    bugs = []
    for row in ready_rows:
        text = " ".join([row.get("claim_text", ""), row.get("measurement_indicator", ""), row.get("indicator", "")])
        claim_measurement_id = row.get("claim_measurement_id", "")
        if "무역수지" in text:
            bugs.append((claim_measurement_id, "trade_balance_ready"))
        if ("증감률" in text or "증가율" in text) and row.get("required_period_count") == "2" and not row.get("comparison_period"):
            bugs.append((claim_measurement_id, "rate_without_base_period_ready"))
        if re.search(r"1\s*[~\-∼]\s*9월|상반기|하반기|[1-4]\s*분기", text) and row.get("period_scope_valid") != "Y":
            bugs.append((claim_measurement_id, "partial_period_annual_ready"))
        if row.get("requires_codeset") == "Y" and row.get("codeset_valid") != "Y":
            bugs.append((claim_measurement_id, "codeset_required_single_obj_ready"))
        if any(token in text for token in ("순위", "전망", "목표치")) and row.get("mapping_feasibility") == "UNSUPPORTED_BY_TABLE":
            bugs.append((claim_measurement_id, "rank_forecast_ready"))

    old_by_measurement: dict[str, list[dict[str, str]]] = defaultdict(list)
    new_by_measurement: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in old_validated:
        old_by_measurement[row.get("claim_measurement_id", "")].append(row)
    for row in validated:
        new_by_measurement[row.get("claim_measurement_id", "")].append(row)

    dev_rows = []
    measurement_ids_2025 = input_2025_ids
    for cmid in measurement_ids_2025:
        source = input_by_id.get(cmid, {})
        new_rows = new_by_measurement.get(cmid, [])
        old_rows = old_by_measurement.get(cmid, [])
        new_rank1 = rank1(new_rows)
        old_rank1 = rank1(old_rows)
        verdict = verified_by_id.get(cmid, {})
        period_raw = source.get("measurement_period") or source.get("period") or new_rank1.get("measurement_period") or new_rank1.get("period", "")
        root_cause = classify_dev_root_cause(new_rank1) if new_rank1 else "TABLE_RETRIEVAL_ERROR"
        dev_rows.append({
            "evaluation_role": "DEV_REGRESSION_ONLY",
            "eligible_for_final_holdout": "N",
            "claim_measurement_id": cmid,
            "claim_text": source.get("claim_text") or new_rank1.get("claim_text", ""),
            "prev_sentence": source.get("prev_sentence", ""),
            "next_sentence": source.get("next_sentence", ""),
            "measurement_indicator": source.get("measurement_indicator") or source.get("indicator") or new_rank1.get("measurement_indicator") or new_rank1.get("indicator", ""),
            "measurement_role": source.get("measurement_role") or new_rank1.get("measurement_role", ""),
            "measurement_value": source.get("value") or new_rank1.get("value", ""),
            "measurement_unit": source.get("unit") or new_rank1.get("unit", ""),
            "measurement_period_raw": period_raw,
            "measurement_year_normalized": normalize_measurement_year(period_raw),
            "measurement_periodicity": source.get("measurement_prd_se") or source.get("prd_se") or new_rank1.get("prd_se", ""),
            "change_type": source.get("value_type") or new_rank1.get("value_type", ""),
            "source_org_raw": source.get("source_org_raw") or source.get("measurement_source") or new_rank1.get("source_org_raw", ""),
            "old_rank1_tbl_id": old_rank1.get("tbl_id", ""),
            "old_rank1_tbl_name": old_rank1.get("tbl_name", ""),
            "old_final_status": old_rank1.get("final_status", ""),
            "new_rank1_tbl_id": new_rank1.get("tbl_id", ""),
            "new_rank1_tbl_name": new_rank1.get("tbl_name", ""),
            "new_top5_tables": top_tables(new_rows),
            "current_top5_tables": top_tables(new_rows),
            "current_ITEM_OBJ_candidates": " | ".join(
                f"{r.get('candidate_rank','')}:{r.get('selected_itm_id','')}:{r.get('selected_itm_name','')}:"
                f"{selected_obj_codes(r)}:{selected_obj_names(r)}"
                for r in sorted(new_rows, key=lambda x: int(float(str(x.get('candidate_rank','999')))))[:5]
            ),
            "current_review_reason": new_rank1.get("review_reason", "") if new_rank1 else "NO_TABLE_CANDIDATE_AFTER_SEARCH",
            "new_final_status": new_rank1.get("final_status", "") if new_rank1 else "REVIEW",
            "new_review_reason": new_rank1.get("review_reason", "") if new_rank1 else "NO_TABLE_CANDIDATE_AFTER_SEARCH",
            "new_mapping_feasibility": new_rank1.get("mapping_feasibility", ""),
            "root_cause": root_cause,
            "measurement_structure_valid": new_rank1.get("measurement_structure_valid", ""),
            "measurement_structure_issue": new_rank1.get("measurement_structure_issue", ""),
            "recommended_upstream_fix": new_rank1.get("recommended_upstream_fix", ""),
            "semantic_mismatch_code": new_rank1.get("semantic_mismatch_code", ""),
            "capability_source": new_rank1.get("capability_source", ""),
            "capability_review_status": new_rank1.get("capability_review_status", ""),
            "verdict": verdict.get("verdict", ""),
            "verdict_code": verdict.get("verdict_code", ""),
            "improvement": (
                "no_new_candidate" if not new_rank1 else (
                    "rank1_changed" if old_rank1.get("tbl_id", "") != new_rank1.get("tbl_id", "")
                    else ("status_changed" if old_rank1.get("final_status", "") != new_rank1.get("final_status", "") else "same")
                )
            ),
        })
    write_csv(output_dir / "dev_2025_before_after.csv", dev_rows)

    metrics = {
        "old_final_status": dict(Counter(row.get("final_status", "") for row in old_validated)),
        "new_final_status": dict(Counter(row.get("final_status", "") for row in validated)),
        "mapping_feasibility": dict(Counter(row.get("mapping_feasibility", "") for row in validated)),
        "ready10_verdict": dict(Counter(row.get("verdict", "") for row in ready_detail)),
        "rows_2025_candidate": len(rows_2025),
        "rows_2025_unique_measurements": len({row.get("claim_measurement_id", "") for row in rows_2025}),
        "rows_2025_final_status": dict(Counter(row.get("final_status", "") for row in rows_2025)),
        "rows_2025_feasibility": dict(Counter(row.get("mapping_feasibility", "") for row in rows_2025)),
        "rows_2025_verdict": dict(Counter(row.get("verdict", "") for row in rows_2025)),
        "ready_safety_bugs": bugs,
        "dev_2025_unique_measurements": len(dev_rows),
        "dev_2025_root_cause": dict(Counter(row.get("root_cause", "") for row in dev_rows)),
        "evaluation_role": "DEV_REGRESSION_ONLY",
        "eligible_for_final_holdout": "N",
    }
    (output_dir / "feasibility_regression_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Build feasibility regression audit reports")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--previous-dir", required=True)
    parser.add_argument("--capability-profile", default="data/claims/kosis_table_capabilities.csv")
    parser.add_argument("--input", default="data/claims/kosis_mapping_ready_500_real.csv")
    args = parser.parse_args()
    metrics = build_reports(Path(args.output_dir), Path(args.previous_dir), Path(args.capability_profile), Path(args.input))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
