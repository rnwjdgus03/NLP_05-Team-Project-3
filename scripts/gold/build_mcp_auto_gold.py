"""Build the KOSIS-MCP-backed automatic gold set.

The input rows were previously confirmed by value reproduction.  This builder
locks the coordinates and values re-fetched through the KOSIS MCP on
2026-08-05, resolves duplicate tables to one canonical coordinate, and emits
a compact measurement-level gold CSV plus a hash manifest.

This is intentionally an automatic gold set: human_reviewed is always N.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "shared_20260802" / "gold_confirmed_v3.csv"
OUTPUT = ROOT / "data" / "gold" / "mcp_auto_gold_v1.csv"
MANIFEST = ROOT / "data" / "gold" / "mcp_auto_gold_v1_manifest.json"
RETRIEVED_AT = "2026-08-05T00:00:00+09:00"


def evidence_url(org_id: str, tbl_id: str) -> str:
    return (
        "https://kosis.kr/statHtml/statHtml.do?"
        f"orgId={org_id}&tblId={tbl_id}&vw_cd=MT_ZTITLE"
    )


# Values below are the exact values returned by KOSIS MCP kosis_get_data.
# raw/current and raw/previous retain the unit supplied by KOSIS.
EVIDENCE = {
    "A0006-SP270B11DBD0-m1": {
        "org": "127", "tbl": "DT_092_115_2009_S023",
        "tbl_name": "IT산업별/월별 수출 현황",
        "itm": "13103131003T1", "itm_name": "IT산업별/월별 수출 현황",
        "obj1": "13102131003A.AF11100000", "obj1_name": "반도체",
        "prd": "M", "period": "202412", "previous": "202312",
        "raw": 14511028387.0, "raw_previous": 11066415208.0,
        "source_unit": "달러", "factor": 1.0,
        "value_type": "증감률", "method": "YOY_FROM_LEVEL",
        "canonical_reason": "MCP 검색 1위이며 반도체 분류 코드가 직접 존재",
    },
    "A0006-SP270B11DBD0-m2": {
        "org": "127", "tbl": "DT_092_115_2009_S023",
        "tbl_name": "IT산업별/월별 수출 현황",
        "itm": "13103131003T1", "itm_name": "IT산업별/월별 수출 현황",
        "obj1": "13102131003A.AF11100000", "obj1_name": "반도체",
        "prd": "M", "period": "202412", "previous": "",
        "raw": 14511028387.0, "raw_previous": None,
        "source_unit": "달러", "factor": 1.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 검색 1위이며 반도체 분류 코드가 직접 존재",
    },
    "A0006-SP382DCE21AF-m1": {
        "org": "360", "tbl": "DT_1R11001_FRM101",
        "tbl_name": "품목별 수출액 수입액",
        "itm": "13103112831T1", "itm_name": "수출액",
        "obj1": "13102112831A.A", "obj1_name": "총액",
        "prd": "Y", "period": "2024", "previous": "",
        "raw": 683609488.0, "raw_previous": None,
        "source_unit": "천달러", "factor": 1000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 총수출액 검색 1위; 국가별 표의 계와 값이 같은 공식 대체 좌표",
    },
    "A0006-SP9282109973-m2": {
        "org": "127", "tbl": "DT_127005_005",
        "tbl_name": "수출 및 수입액",
        "itm": "T001", "itm_name": "수출액",
        "obj1": "A020101", "obj1_name": "반도체",
        "prd": "Y", "period": "2024", "previous": "",
        "raw": 142086.0, "raw_previous": None,
        "source_unit": "백만US$", "factor": 1_000_000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 메타에 반도체와 수출액 코드가 직접 존재",
    },
    "A0006-SP9461F3F4FE-m2": {
        "org": "360", "tbl": "DT_1R11001_FRM101",
        "tbl_name": "품목별 수출액 수입액",
        "itm": "13103112831T1", "itm_name": "수출액",
        "obj1": "13102112831A.A", "obj1_name": "총액",
        "prd": "M", "period": "202412", "previous": "202312",
        "raw": 61359250.0, "raw_previous": 57573193.0,
        "source_unit": "천달러", "factor": 1000.0,
        "value_type": "증감률", "method": "YOY_FROM_LEVEL",
        "canonical_reason": "기사의 지난 12월을 202412로 정규화하고 전년동월 값으로 계산",
    },
    "A0006-SPA4FBC97BC2-m5": {
        "org": "145", "tbl": "DT_145011_A006",
        "tbl_name": "화장품 수입 및 수출액 현황",
        "itm": "T002", "itm_name": "수출액",
        "obj1": "DATA", "obj1_name": "데이터",
        "prd": "Y", "period": "2024", "previous": "",
        "raw": 10177312.0, "raw_previous": None,
        "source_unit": "천$", "factor": 1000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 검증에서 화장품산업현황의 수출액 항목으로 확인",
    },
    "A0018-SP2F67F9842A-m1": {
        "org": "127", "tbl": "DT_127005_005",
        "tbl_name": "수출 및 수입액",
        "itm": "T001", "itm_name": "수출액",
        "obj1": "A020101", "obj1_name": "반도체",
        "prd": "Y", "period": "2024", "previous": "",
        "raw": 142086.0, "raw_previous": None,
        "source_unit": "백만US$", "factor": 1_000_000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 메타에 반도체와 수출액 코드가 직접 존재",
    },
    "A0018-SP32C9008706-m1": {
        "org": "360", "tbl": "DT_1R11001_FRM101",
        "tbl_name": "품목별 수출액 수입액",
        "itm": "13103112831T1", "itm_name": "수출액",
        "obj1": "13102112831A.A", "obj1_name": "총액",
        "prd": "Y", "period": "2024", "previous": "",
        "raw": 683609488.0, "raw_previous": None,
        "source_unit": "천달러", "factor": 1000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 총수출액 검색 1위",
    },
    "A0018-SP33EC69A061-m2": {
        "org": "360", "tbl": "DT_1R11001_FRM101",
        "tbl_name": "품목별 수출액 수입액",
        "itm": "13103112831T2", "itm_name": "수입액",
        "obj1": "13102112831A.A", "obj1_name": "총액",
        "prd": "Y", "period": "2024", "previous": "",
        "raw": 631767209.0, "raw_previous": None,
        "source_unit": "천달러", "factor": 1000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 메타의 수입액·총액 코드와 직접 일치",
    },
    "A0018-SP6C1F318589-m1": {
        "org": "360", "tbl": "DT_1R11001_FRM101",
        "tbl_name": "품목별 수출액 수입액",
        "itm": "13103112831T1", "itm_name": "수출액",
        "obj1": "13102112831A.A", "obj1_name": "총액",
        "prd": "M", "period": "202412", "previous": "",
        "raw": 61359250.0, "raw_previous": None,
        "source_unit": "천달러", "factor": 1000.0,
        "value_type": "수준값", "method": "DIRECT",
        "canonical_reason": "MCP 월별 총수출액 원자료와 직접 일치",
    },
    "A0018-SP6C1F318589-m2": {
        "org": "360", "tbl": "DT_1R11001_FRM101",
        "tbl_name": "품목별 수출액 수입액",
        "itm": "13103112831T1", "itm_name": "수출액",
        "obj1": "13102112831A.A", "obj1_name": "총액",
        "prd": "M", "period": "202412", "previous": "202312",
        "raw": 61359250.0, "raw_previous": 57573193.0,
        "source_unit": "천달러", "factor": 1000.0,
        "value_type": "증감률", "method": "YOY_FROM_LEVEL",
        "canonical_reason": "MCP 월별 총수출액의 전년동월비로 재계산",
    },
    "A0046-SPD2EDAD8C3F-m2": {
        "org": "343", "tbl": "DT_343_2010_S0065",
        "tbl_name": "코스닥 지수",
        "itm": "13103792840T1", "itm_name": "코스닥지수",
        "obj1": "13102792840A.02", "obj1_name": "연월말",
        "prd": "Y", "period": "2024", "previous": "2023",
        "raw": 678.19, "raw_previous": 866.57,
        "source_unit": "지수", "factor": 1.0,
        "value_type": "증감률", "method": "YOY_FROM_LEVEL",
        "canonical_reason": "MCP 연말 코스닥지수의 2023→2024 증감률로 재계산",
    },
}


FIELDS = [
    "claim_measurement_id", "claim_text", "claim_value", "claim_unit",
    "gold_verifiable", "gold_measurement_correct", "gold_ready",
    "gold_org_id", "gold_tbl_id", "gold_tbl_name", "gold_itm_id",
    "gold_itm_name", "gold_obj_l1", "gold_obj_l1_name", "gold_prd_se",
    "gold_period", "gold_previous_period", "gold_value_type",
    "gold_derivation_method", "gold_source_unit", "gold_source_value",
    "gold_source_previous_value", "gold_actual_value", "gold_claim_signed_value",
    "gold_abs_error", "gold_relative_error_pct", "gold_tolerance",
    "gold_verdict", "gold_coordinate_status", "gold_confidence",
    "gold_canonical_reason", "gold_evidence_url", "gold_retrieved_at",
    "gold_label_source", "human_reviewed",
]


def to_float(value: str) -> float:
    return float(str(value).replace(",", ""))


def build_row(source: dict[str, str], evidence: dict[str, object]) -> dict[str, object]:
    claim = to_float(source["value"])
    raw = float(evidence["raw"])
    previous = evidence["raw_previous"]
    method = str(evidence["method"])

    if method == "DIRECT":
        actual = raw * float(evidence["factor"])
        signed_claim = claim
        abs_error = abs(actual - signed_claim)
        rel_error = abs_error / max(abs(signed_claim), 1e-12) * 100
        tolerance = "relative_error<=0.5%"
        matched = rel_error <= 0.5
    else:
        if previous is None:
            raise ValueError(f"previous value missing for {source['claim_measurement_id']}")
        actual = (raw / float(previous) - 1.0) * 100.0
        direction_down = any(token in source["claim_text"] for token in ("하락", "감소", "줄"))
        signed_claim = -abs(claim) if direction_down else claim
        abs_error = abs(actual - signed_claim)
        rel_error = abs_error / max(abs(signed_claim), 1e-12) * 100
        tolerance = "absolute_error<=0.5%p"
        matched = abs_error <= 0.5

    if not matched:
        raise ValueError(
            f"automatic-gold tolerance failed: {source['claim_measurement_id']} "
            f"claim={signed_claim} actual={actual}"
        )

    original_alternates = int(source.get("alternate_count") or 0)
    return {
        "claim_measurement_id": source["claim_measurement_id"],
        "claim_text": source["claim_text"],
        "claim_value": claim,
        "claim_unit": source["unit"],
        "gold_verifiable": "Y",
        "gold_measurement_correct": "Y",
        "gold_ready": "Y",
        "gold_org_id": evidence["org"],
        "gold_tbl_id": evidence["tbl"],
        "gold_tbl_name": evidence["tbl_name"],
        "gold_itm_id": evidence["itm"],
        "gold_itm_name": evidence["itm_name"],
        "gold_obj_l1": evidence["obj1"],
        "gold_obj_l1_name": evidence["obj1_name"],
        "gold_prd_se": evidence["prd"],
        "gold_period": evidence["period"],
        "gold_previous_period": evidence["previous"],
        "gold_value_type": evidence["value_type"],
        "gold_derivation_method": method,
        "gold_source_unit": evidence["source_unit"],
        "gold_source_value": raw,
        "gold_source_previous_value": "" if previous is None else previous,
        "gold_actual_value": actual,
        "gold_claim_signed_value": signed_claim,
        "gold_abs_error": abs_error,
        "gold_relative_error_pct": rel_error,
        "gold_tolerance": tolerance,
        "gold_verdict": "일치",
        "gold_coordinate_status": (
            "ALTERNATE_RESOLVED" if original_alternates > 1 else "UNIQUE"
        ),
        "gold_confidence": "HIGH",
        "gold_canonical_reason": evidence["canonical_reason"],
        "gold_evidence_url": evidence_url(str(evidence["org"]), str(evidence["tbl"])),
        "gold_retrieved_at": RETRIEVED_AT,
        "gold_label_source": "KOSIS_MCP_AUTO_V1",
        "human_reviewed": "N",
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    source_by_id = {row["claim_measurement_id"]: row for row in source_rows}
    missing = sorted(set(EVIDENCE) - set(source_by_id))
    extra = sorted(set(source_by_id) - set(EVIDENCE))
    if missing or extra:
        raise ValueError(f"source/evidence mismatch: missing={missing} extra={extra}")

    rows = [build_row(source_by_id[key], EVIDENCE[key]) for key in sorted(EVIDENCE)]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "dataset": "mcp_auto_gold_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kosis_retrieved_at": RETRIEVED_AT,
        "row_count": len(rows),
        "match_count": sum(row["gold_verdict"] == "일치" for row in rows),
        "human_reviewed": False,
        "label_source": "KOSIS_MCP_AUTO_V1",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": sha256(SOURCE),
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(OUTPUT),
        "acceptance_rules": {
            "direct": "relative_error <= 0.5%",
            "derived_rate": "absolute_error <= 0.5 percentage point",
            "coordinate": "KOSIS MCP search + validate + exact item/obj/period data retrieval",
        },
        "known_limitation": (
            "Labels are automatically generated from current KOSIS values and were not human-reviewed."
        ),
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
