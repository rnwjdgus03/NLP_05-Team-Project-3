#!/usr/bin/env python3
"""Claim-to-KOSIS-table representation feasibility checks.

This module is intentionally conservative.  It does not change search scores,
thresholds, overrides, or HCX behaviour.  It only answers a narrower question:
can the selected KOSIS table structure represent the claim as a single direct
coordinate, or does it need a formula, multiple periods, a codeset, or a
different source/definition?
"""
from __future__ import annotations

import re
from typing import Any, Mapping


DIRECT_COORDINATE = "DIRECT_COORDINATE"
DERIVED_FROM_PERIODS = "DERIVED_FROM_PERIODS"
DERIVED_FROM_ITEMS = "DERIVED_FROM_ITEMS"
DERIVED_FROM_ITEMS_AND_PERIODS = "DERIVED_FROM_ITEMS_AND_PERIODS"
CODESET_AGGREGATION = "CODESET_AGGREGATION"
SOURCE_OR_DEFINITION_MISMATCH = "SOURCE_OR_DEFINITION_MISMATCH"
PERIOD_SCOPE_MISMATCH = "PERIOD_SCOPE_MISMATCH"
UNSUPPORTED_BY_TABLE = "UNSUPPORTED_BY_TABLE"

TABLE_SEMANTIC_MISMATCH = "TABLE_SEMANTIC_MISMATCH"
MEASUREMENT_EXTRACTION_ERROR = "MEASUREMENT_EXTRACTION_ERROR"
DERIVED_FORMULA_INCOMPLETE = "DERIVED_FORMULA_INCOMPLETE"
KOSIS_SCOPE_UNCONFIRMED = "KOSIS_SCOPE_UNCONFIRMED"

EXACT_SINGLE_CODE = "EXACT_SINGLE_CODE"
VALIDATED_CODESET = "VALIDATED_CODESET"
PARTIAL_SUBSET = "PARTIAL_SUBSET"
BROADER_THAN_KOSIS_CODE = "BROADER_THAN_KOSIS_CODE"
CROSS_CLASSIFICATION_MISMATCH = "CROSS_CLASSIFICATION_MISMATCH"
UNKNOWN = "UNKNOWN"

FEASIBILITY_VALUES = {
    DIRECT_COORDINATE,
    DERIVED_FROM_PERIODS,
    DERIVED_FROM_ITEMS,
    DERIVED_FROM_ITEMS_AND_PERIODS,
    CODESET_AGGREGATION,
    SOURCE_OR_DEFINITION_MISMATCH,
    PERIOD_SCOPE_MISMATCH,
    UNSUPPORTED_BY_TABLE,
    TABLE_SEMANTIC_MISMATCH,
}

BROAD_CATEGORY_TERMS = (
    "자동차", "화장품", "바이오헬스", "농수산식품", "IT 품목", "완성차",
)

RANK_OR_FORECAST_TERMS = (
    "세계 수출순위", "수출순위", "상위 10대 수출국", "순위", "전망", "목표치", "정책 목표",
)

PARTIAL_PERIOD_PATTERNS = (
    r"1\s*[~\-∼]\s*9월", r"1월\s*[-~∼]\s*9월", r"상반기", r"하반기",
    r"[1-4]\s*분기", r"전년\s*동월", r"전월\s*대비", r"\d{6}",
)



ROOT_CAUSE_VALUES = {
    MEASUREMENT_EXTRACTION_ERROR,
    "TABLE_RETRIEVAL_ERROR",
    TABLE_SEMANTIC_MISMATCH,
    "TABLE_CAPABILITY_UNREVIEWED",
    "ITEM_SEMANTIC_MISMATCH",
    "OBJ_SEMANTIC_MISMATCH",
    PERIOD_SCOPE_MISMATCH,
    "UNIT_MISMATCH",
    DERIVED_FORMULA_INCOMPLETE,
    KOSIS_SCOPE_UNCONFIRMED,
    UNSUPPORTED_BY_TABLE,
    "API_ERROR",
}


def _compact_text(*values: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣%]+", "", " ".join(str(v or "") for v in values)).lower()


def _table_text(row: Mapping[str, Any]) -> str:
    return _compact_text(
        _first(row, "tbl_name", "selected_tbl_name"),
        _first(row, "category_path"),
        _first(row, "stat_name", "stat_id"),
        _first(row, "selected_itm_name"),
        _selected_obj_names(row),
    )


def _claim_text_for_semantics(row: Mapping[str, Any]) -> str:
    return _compact_text(
        _first(row, "claim_text"),
        _first(row, "prev_sentence"),
        _first(row, "next_sentence"),
        _first(row, "indicator", "measurement_indicator"),
        _first(row, "industry_or_item", "measurement_item"),
        _first(row, "source_org_raw", "source_org"),
        _first(row, "value_type"),
        _first(row, "measurement_role"),
    )


def diagnose_measurement_structure(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Detect upstream measurement issues without rewriting the claim."""
    text = _claim_text_for_semantics(row)
    indicator = _compact_text(_first(row, "indicator", "measurement_indicator"))
    role = _first(row, "measurement_role")
    issue = ""
    fix = ""
    valid = "Y"
    if role == "목표값" or any(term in text for term in ("목표", "목표치", "전망", "예상", "예측", "내다봤", "전망했다")):
        valid = "N"
        issue = "FORECAST_OR_TARGET_NOT_OBSERVED_VALUE"
        fix = "목표·전망·예측 수치는 관측 KOSIS 값이 아니므로 measurement_role/usage를 REVIEW 또는 NOT_KOSIS 후보로 분리"
    elif any(term in indicator for term in ("증가폭", "증감액", "변화폭")) and not _first(row, "comparison_period", "change_base"):
        valid = "N"
        issue = "CHANGE_AMOUNT_BASE_PERIOD_MISSING"
        fix = "증가폭·증감액은 현재기간과 기준기간을 모두 구조화"
    elif any(term in indicator for term in ("증가율", "증감률", "상승률", "하락률")) and not _first(row, "comparison_period", "change_base"):
        valid = "N"
        issue = "RATE_BASE_PERIOD_MISSING"
        fix = "증감률은 현재기간과 기준기간 또는 전년/전월 기준을 명시"
    return valid, issue, fix


def diagnose_semantic_mismatch(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """General claim/table semantic mismatch rules. No claim-id hardcoding."""
    claim_text = _claim_text_for_semantics(row)
    table_text = _table_text(row)
    indicator = _compact_text(_first(row, "indicator", "measurement_indicator"))

    if any(term in indicator for term in ("소비자물가", "물가상승", "물가상승률", "소비자물가상승률")):
        if any(term in table_text for term in ("관광", "만족도", "평가", "여행", "관광객")):
            return TABLE_SEMANTIC_MISMATCH, "consumer price inflation cannot be represented by tourism satisfaction/evaluation tables", "CPI_TOURISM_TABLE_MISMATCH"

    if any(term in indicator or term in claim_text for term in ("환율", "원달러", "달러원", "원화환율", "달러당원화")):
        if any(term in table_text for term in ("대출", "예금", "수신", "금리", "이자", "여신")):
            return TABLE_SEMANTIC_MISMATCH, "exchange-rate claim cannot be represented by loan/deposit/interest-rate tables", "EXCHANGE_RATE_LOAN_TABLE_MISMATCH"

    if any(term in indicator or term in claim_text for term in ("매출", "매출액", "성장세", "시장전망", "wsts")):
        if any(term in table_text for term in ("수출", "수입", "무역")):
            return KOSIS_SCOPE_UNCONFIRMED, "revenue/market forecast claim is not the same as KOSIS export/import statistics", "REVENUE_EXPORT_SOURCE_MISMATCH"

    if "정비사" in indicator or "정비사" in claim_text:
        if not any(term in table_text for term in ("정비", "항공사", "직무별", "종사자")):
            return TABLE_SEMANTIC_MISMATCH, "mechanic-count claim requires aircraft/job/population-compatible table", "MECHANIC_POPULATION_TABLE_MISMATCH"
        if any(term in claim_text for term in ("제주항공", "대한항공", "아시아나", "항공사")) and not any(term in table_text for term in ("항공사", "업체", "사업체", "직무별")):
            return TABLE_SEMANTIC_MISMATCH, "company/airline mechanic scope is not confirmed by this table", "MECHANIC_COMPANY_SCOPE_UNCONFIRMED"

    if any(term in indicator for term in ("취업자수증가폭", "취업자증가폭", "취업자수증감", "취업자증감")):
        if not any(term in table_text for term in ("취업", "경제활동", "고용")):
            return TABLE_SEMANTIC_MISMATCH, "employment increase amount requires employment/economically-active population table", "EMPLOYMENT_INCREASE_TABLE_MISMATCH"

    return "", "", ""


def _first(row: Mapping[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def _text(row: Mapping[str, Any]) -> str:
    return " ".join(
        _first(row, key)
        for key in (
            "claim_text", "indicator", "measurement_indicator", "industry_or_item",
            "measurement_item", "value_type", "measurement_role", "change_base",
        )
    )


def _period_text(row: Mapping[str, Any]) -> str:
    return " ".join(
        _first(row, key)
        for key in (
            "claim_text", "period", "measurement_period", "comparison_period", "change_base",
        )
    )


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"y", "yes", "true", "1"}


def _selected_obj_names(row: Mapping[str, Any]) -> str:
    return " ".join(_first(row, f"selected_obj_l{i}_name") for i in range(1, 9))


def _selected_obj_codes(row: Mapping[str, Any]) -> list[str]:
    return [_first(row, f"selected_obj_l{i}") for i in range(1, 9) if _first(row, f"selected_obj_l{i}")]


def period_scope(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """Return current/base period bounds and exactness flag.

    We do not infer missing dates here.  If a partial-period expression exists
    but selected period is a single year, exactness is N.
    """
    text = _period_text(row)
    period = _first(row, "period", "measurement_period")
    comparison = _first(row, "comparison_period")
    current_start = current_end = period
    base_start = base_end = comparison
    partial = any(re.search(pattern, text) for pattern in PARTIAL_PERIOD_PATTERNS)
    if partial and re.fullmatch(r"\d{4}", period or ""):
        return current_start, current_end, base_start, base_end, "N"
    return current_start, current_end, base_start, base_end, "Y"


def classify_obj_alignment(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Classify whether the selected OBJ code can represent the claim scope."""
    text = _text(row)
    obj_names = _selected_obj_names(row)
    obj_codes = _selected_obj_codes(row)
    tbl_id = _first(row, "tbl_id", "selected_tbl_id")
    category_path = _first(row, "category_path")
    kosis_system = "SITC 품목분류" if tbl_id == "DT_1R11001_FRM101" or "SITC" in category_path else "KOSIS 공식 메타 분류"
    claim_system = "뉴스 산업/품목 표현"

    broad_terms = [term for term in BROAD_CATEGORY_TERMS if term in text]
    if not broad_terms:
        return EXACT_SINGLE_CODE if obj_codes else UNKNOWN, claim_system, kosis_system

    # A single detailed SITC/industry code is not automatically the same as a
    # broad news category unless the object name is exactly the same aggregate.
    if len(obj_codes) == 1:
        for term in broad_terms:
            if term in obj_names and obj_names.strip() in {term, f"{term} 전체"}:
                return EXACT_SINGLE_CODE, claim_system, kosis_system
        return BROADER_THAN_KOSIS_CODE, claim_system, kosis_system
    return VALIDATED_CODESET if _is_truthy(row.get("codeset_valid")) else UNKNOWN, claim_system, kosis_system


def classify_mapping_feasibility(row: Mapping[str, Any]) -> dict[str, str]:
    """Return feasibility and audit columns for a selected table/candidate row."""
    text = _text(row)
    indicator = _first(row, "indicator", "measurement_indicator")
    unit = _first(row, "unit")
    tbl_id = _first(row, "tbl_id", "selected_tbl_id")
    selected_item_name = _first(row, "selected_itm_name")
    mapping_type = _first(row, "mapping_type", default="direct") or "direct"
    current_start, current_end, base_start, base_end, period_exact = period_scope(row)
    classification_alignment, claim_system, kosis_system = classify_obj_alignment(row)
    measurement_structure_valid, measurement_structure_issue, recommended_upstream_fix = diagnose_measurement_structure(row)
    semantic_mismatch, semantic_mismatch_reason, semantic_mismatch_code = diagnose_semantic_mismatch(row)

    required_item_count = "1"
    required_period_count = "1"
    required_formula = ""
    feasibility = DIRECT_COORDINATE
    reason = "single ITEM/OBJ/period can represent claim"
    direct_or_derived = "direct"
    formula_valid = "Y"
    requires_codeset = "N"
    codeset_valid = "Y" if classification_alignment in {EXACT_SINGLE_CODE, VALIDATED_CODESET} else "N"

    if any(term in indicator or term in text for term in ("취업자 수 증가폭", "취업자수 증가폭", "취업자 증가폭", "취업자수증가폭", "취업자증가폭")):
        feasibility = DERIVED_FROM_PERIODS
        direct_or_derived = "derived"
        required_period_count = "2"
        required_formula = "EMPLOYMENT_ABSOLUTE_CHANGE=current_employed-base_employed"
        reason = "employment increase amount requires current and base employment levels"
        formula_valid = "Y" if mapping_type in {"difference_from_level", "absolute_change"} else "N"

    elif semantic_mismatch:
        feasibility = SOURCE_OR_DEFINITION_MISMATCH if semantic_mismatch == KOSIS_SCOPE_UNCONFIRMED else UNSUPPORTED_BY_TABLE
        reason = semantic_mismatch_reason
        formula_valid = "N"

    elif any(term in text for term in RANK_OR_FORECAST_TERMS):
        feasibility = UNSUPPORTED_BY_TABLE
        reason = "rank/forecast/target claim requires a ranking or forecast source, not a commodity value coordinate"
        formula_valid = "N"

    elif "무역수지" in indicator or "무역수지" in text:
        direct_or_derived = "derived"
        if "증감" in indicator or "증감" in text or "차이" in text:
            feasibility = DERIVED_FROM_ITEMS_AND_PERIODS
            required_item_count = "2"
            required_period_count = "2"
            required_formula = "TRADE_BALANCE_CHANGE=(current_export-current_import)-(base_export-base_import)"
            reason = "trade balance change requires export/import for current and base periods"
        else:
            feasibility = DERIVED_FROM_ITEMS
            required_item_count = "2"
            required_period_count = "1"
            required_formula = "TRADE_BALANCE=export_value-import_value"
            reason = "trade balance requires both export and import items; single 수출액/수입액 is insufficient"
        formula_valid = "Y" if mapping_type in {"trade_balance", "trade_balance_change"} else "N"

    elif "증감액" in indicator or "증감액" in text or mapping_type == "difference_from_level":
        feasibility = DERIVED_FROM_PERIODS
        direct_or_derived = "derived"
        required_period_count = "2"
        required_formula = "ABSOLUTE_CHANGE=current_value-base_value"
        reason = "absolute change requires current and base periods"
        formula_valid = "Y" if mapping_type in {"difference_from_level", "absolute_change"} else "N"

    elif "증가율" in indicator or "증감률" in indicator or unit == "%" or mapping_type == "rate_from_level":
        feasibility = DERIVED_FROM_PERIODS
        direct_or_derived = "derived"
        required_period_count = "2"
        required_formula = "RATE_CHANGE=(current_value-base_value)/base_value*100"
        reason = "rate/change claim requires current and base periods on the same coordinate"
        formula_valid = "Y" if mapping_type == "rate_from_level" else "N"

    if period_exact != "Y" and feasibility not in {UNSUPPORTED_BY_TABLE, SOURCE_OR_DEFINITION_MISMATCH}:
        feasibility = PERIOD_SCOPE_MISMATCH
        reason = "partial/monthly/quarterly scope cannot be replaced by annual full-year values"

    if classification_alignment not in {EXACT_SINGLE_CODE, VALIDATED_CODESET, UNKNOWN}:
        requires_codeset = "Y"
        if feasibility not in {SOURCE_OR_DEFINITION_MISMATCH, PERIOD_SCOPE_MISMATCH, UNSUPPORTED_BY_TABLE}:
            feasibility = CODESET_AGGREGATION
            if required_period_count == "2":
                reason = "broad news category requires a validated OBJ codeset before derived period comparison"
            else:
                reason = "broad news category requires a validated OBJ codeset, not one selected code"
        codeset_valid = "N"

    table_can_represent = "Y"
    if feasibility in {SOURCE_OR_DEFINITION_MISMATCH, PERIOD_SCOPE_MISMATCH, UNSUPPORTED_BY_TABLE}:
        table_can_represent = "N"
    elif requires_codeset == "Y" and codeset_valid != "Y":
        table_can_represent = "N"
    elif feasibility in {DERIVED_FROM_ITEMS, DERIVED_FROM_ITEMS_AND_PERIODS} and formula_valid != "Y":
        table_can_represent = "N"
    elif feasibility == DERIVED_FROM_PERIODS and required_period_count == "2" and not _first(row, "comparison_period"):
        table_can_represent = "N"

    if not selected_item_name and indicator and table_can_represent == "Y":
        table_can_represent = "N"
        reason = "ITEM coordinate is not selected"

    capability_source = _first(row, "capability_source", default="AUTO_INFERRED") or "AUTO_INFERRED"
    capability_review_status = _first(row, "capability_review_status", default="UNREVIEWED") or "UNREVIEWED"
    evidence_url = _first(row, "evidence_url")
    evidence_note = _first(row, "evidence_note", "evidence_source")

    return {
        "mapping_feasibility": feasibility,
        "table_can_represent_claim": table_can_represent,
        "representation_reason": reason,
        "required_item_count": required_item_count,
        "required_period_count": required_period_count,
        "requires_codeset": requires_codeset,
        "required_formula": required_formula,
        "claim_classification_system": claim_system,
        "kosis_classification_system": kosis_system,
        "classification_alignment": classification_alignment,
        "direct_or_derived": direct_or_derived,
        "formula_valid": formula_valid,
        "period_scope_valid": period_exact,
        "codeset_valid": codeset_valid,
        "current_period_start": current_start,
        "current_period_end": current_end,
        "base_period_start": base_start,
        "base_period_end": base_end,
        "period_scope_exact_match": period_exact,
        "capability_source": capability_source,
        "capability_review_status": capability_review_status,
        "evidence_url": evidence_url,
        "evidence_note": evidence_note,
        "direct_coordinate_official_meta_evidence": "Y" if (
            feasibility == DIRECT_COORDINATE
            and table_can_represent == "Y"
            and selected_item_name
            and bool(_selected_obj_codes(row))
        ) else "N",
        "measurement_structure_valid": measurement_structure_valid,
        "measurement_structure_issue": measurement_structure_issue,
        "recommended_upstream_fix": recommended_upstream_fix,
        "semantic_mismatch_code": semantic_mismatch_code,
        "root_cause": (
            MEASUREMENT_EXTRACTION_ERROR if measurement_structure_valid == "N"
            else semantic_mismatch or (
                DERIVED_FORMULA_INCOMPLETE if formula_valid == "N" and feasibility.startswith("DERIVED")
                else (PERIOD_SCOPE_MISMATCH if period_exact != "Y" else "")
            )
        ),
    }
