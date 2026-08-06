"""Prepare measurement-level HCX output for KOSIS candidate matching.

The handoff contract is deliberately stricter than ``is_claim=True``.  Only a
measurement that already has a grounded value, semantic binding, and period is
allowed into table discovery.  Rejected rows are retained with stable reason
codes so a real ``UNVERIFIABLE`` result is distinguishable from bad input.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from kosis_scope_gate import gate_decision


EMPTY = {"", "-", "nan", "none", "null"}
SKIP_ROLES = {"이전값", "참고값"}
TARGET_ROLES = {"목표값"}

PREV_SENTENCE_ALIASES = ("prev_sentence", "전_문장", "이전_문장")
PREV_PREV_SENTENCE_ALIASES = (
    "prev_prev_sentence",
    "pre_prev_sentence",
    "전전_문장",
    "이전이전_문장",
)
NEXT_SENTENCE_ALIASES = ("next_sentence", "다음_문장")

OBSERVED_TYPES = {
    "OBSERVED",
    "FORECAST",
    "TARGET",
    "FORECAST_REVISION",
    "FORECAST_THRESHOLD",
    "COMPANY_REPORTED",
    "DERIVED_RATIO",
}

SOURCE_SCOPES = {
    "DOMESTIC_OFFICIAL",
    "COMPANY",
    "POLICY_FORECAST",
    "FOREIGN_OR_MARKET",
    "UNCONFIRMED",
}

FORECAST_TERMS = (
    "전망", "예측", "예상", "내다봤", "내다본", "전망해", "전망했다",
    "것으로 봤", "것으로 예상", "우려", "관측", "추정",
)
FORECAST_COMPACT_TERMS = (
    "전망", "예측", "예상", "내다봤", "내다본", "전망해", "전망했다",
    "것으로봤", "것으로예상", "우려", "관측", "추정",
)
TARGET_TERMS = ("목표", "목표치", "목표로")
TARGET_COMPACT_TERMS = ("목표", "목표치", "목표로")
COMPANY_REPORTED_TERMS = ("회사 측은 밝혔다", "회사측은 밝혔다", "관계자는 밝혔다", "측은 밝혔다")
COMPANY_REPORTED_COMPACT_TERMS = ("회사측은밝혔다", "관계자는밝혔다", "측은밝혔다")
COMPANY_REPORTED_PATTERN = re.compile(r"(?:회사측|회사|관계자|[가-힣A-Za-z0-9]+측)은.{0,80}밝혔")
FOREIGN_MARKET_SOURCES = (
    "WSTS", "세계반도체시장통계기구", "가트너", "IDC", "S&P", "블룸버그",
    "로이터", "IMF", "OECD", "세계은행",
)
POLICY_FORECAST_SOURCES = ("정부", "기재부", "한국은행", "한은", "KDI")


def nz(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in EMPTY else text


def first_context_value(row: dict, aliases: tuple[str, ...]) -> str:
    for field in aliases:
        value = nz(row.get(field))
        if value:
            return value
    return ""


def compact_text(*values) -> str:
    return re.sub(r"\s+", "", " ".join(str(v or "") for v in values))


def has_company_reported_pattern(*values) -> bool:
    raw = " ".join(str(v or "") for v in values)
    compacted = compact_text(raw)
    return (
        any(term in raw for term in COMPANY_REPORTED_TERMS)
        or any(term in compacted for term in COMPANY_REPORTED_COMPACT_TERMS)
        or bool(COMPANY_REPORTED_PATTERN.search(compacted))
    )


def infer_measurement_observation_type(row: dict) -> str:
    explicit = nz(row.get("measurement_observation_type"))
    if explicit in OBSERVED_TYPES:
        return explicit
    text = compact_text(
        row.get("claim_text"),
        row.get("prev_sentence"),
        row.get("next_sentence"),
        row.get("measurement_text"),
        row.get("measurement_indicator"),
        row.get("measurement_role"),
    )
    indicator = compact_text(row.get("measurement_indicator"), row.get("indicator"))
    role = nz(row.get("measurement_role"))
    unit = canonicalize_unit(nz(row.get("unit")))
    if role == "목표값" or any(term in text for term in TARGET_COMPACT_TERMS):
        return "TARGET"
    if has_company_reported_pattern(
        row.get("claim_text"),
        row.get("prev_sentence"),
        row.get("next_sentence"),
        row.get("measurement_text"),
    ):
        return "COMPANY_REPORTED"
    if any(term in text for term in FORECAST_COMPACT_TERMS):
        if any(term in indicator for term in ("차이", "감소분", "하향", "상향", "전망치차이")):
            return "FORECAST_REVISION"
        if any(term in text for term in ("돌파우려", "넘을우려", "밑돌우려", "웃돌우려")):
            return "FORECAST_THRESHOLD"
        return "FORECAST"
    if unit in {"명/대", "대당명"} or any(term in text for term in ("대당", "명/대")):
        return "DERIVED_RATIO"
    return "OBSERVED"


def infer_source_scope(row: dict, observation_type: str) -> str:
    explicit = nz(row.get("source_scope"))
    if explicit in SOURCE_SCOPES:
        return explicit
    text = compact_text(
        row.get("claim_text"),
        row.get("prev_sentence"),
        row.get("next_sentence"),
        row.get("measurement_source"),
        row.get("source_org_raw"),
        row.get("measurement_indicator"),
        row.get("measurement_item"),
    )
    scope = nz(row.get("claim_domain_scope"))
    if observation_type == "COMPANY_REPORTED" or has_company_reported_pattern(
        row.get("claim_text"),
        row.get("prev_sentence"),
        row.get("next_sentence"),
        row.get("measurement_text"),
    ):
        return "COMPANY"
    if any(term.lower() in text.lower() for term in FOREIGN_MARKET_SOURCES):
        return "FOREIGN_OR_MARKET"
    if observation_type in {"FORECAST", "TARGET", "FORECAST_REVISION", "FORECAST_THRESHOLD"}:
        if any(term in text for term in POLICY_FORECAST_SOURCES):
            return "POLICY_FORECAST"
        return "UNCONFIRMED"
    if scope == "국내공식통계":
        return "DOMESTIC_OFFICIAL"
    if scope in {"개별기업"}:
        return "COMPANY"
    if scope in {"해외통계·정책", "전망·목표"}:
        return "FOREIGN_OR_MARKET"
    return "UNCONFIRMED"


def normalize_relative_date(row: dict) -> tuple[str, str]:
    """Normalize explicit relative calendar expressions without changing period.

    Only handles cases where the article date and the relative expression pin a
    calendar day, e.g. article date 2025-01-02 + "지난달 말(30일)" -> 20241230.
    """
    article_date = nz(row.get("date"))
    text = compact_text(row.get("claim_text"), row.get("measurement_text"))
    match = re.search(r"지난달말\((\d{1,2})일\)", text)
    if not match:
        return "", ""
    try:
        base = date.fromisoformat(article_date[:10])
        day = int(match.group(1))
        first_this_month = base.replace(day=1)
        previous_month_last = first_this_month - timedelta(days=1)
        normalized = previous_month_last.replace(day=day)
        return normalized.strftime("%Y%m%d"), "ARTICLE_DATE_RELATIVE_EXPLICIT_DAY"
    except Exception:
        return "", "RELATIVE_DATE_NORMALIZATION_FAILED"


# 대상을 여러 개 붙여 쓰는 경우: 'LCC, 대형항공사', '포카리스웨트, 데미소다'
_ITEM_SPLIT = re.compile(r"[,·/、]|및|와\s|과\s")
# 파생어 꼬리. '조선업'은 문장의 '조선 산업기술인력'에서 온 정당한 대상이다.
_ITEM_SUFFIXES = ("업체", "산업", "부문", "분야", "업", "류", "군")


def _item_key(value) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def claim_item_grounded(row) -> bool:
    """주장 대상이 그 문장이나 지표에 근거를 두는가.

    2026-08-02 실측: '작년 한 해 전체 수출액이 6838억달러' 문장의 measurement_item 이
    '반도체'였다. 기사 전체가 반도체를 다뤄 HCX 가 measurement 단위로 그렇게 붙였다
    (상속 문제가 아니라 추출 자체의 문제다 — measurement_item 이 직접 '반도체'였다).
    그 결과 전체 수출액(6,838억)을 반도체 수출액(1,420억)과 비교해 '불일치'라고 단언했다.

    검사 설계:
      · 쉼표·및 로 나눈다 — 'LCC, 대형항공사'를 통째로 찾으면 둘 다 있어도 실패한다
      · 꼬리를 떼며 어간을 본다 — '조선업'은 문장의 '조선 산업기술인력'에서 왔다
      · 지표도 근거로 인정한다 — 앞 문장에서 대상을 이어받는 정당한 생략이 있다
    실측 오탐: 통째 27/91 → 분할·어간 21 → 지표 포함 12.
    """
    raw = nz(row.get("measurement_item")) or nz(row.get("industry_or_item"))
    if not _item_key(raw):
        return True   # 대상이 없는 주장은 집계 규칙이 따로 본다
    haystack = _item_key(row.get("claim_text")) + _item_key(
        nz(row.get("measurement_indicator")) or nz(row.get("indicator")))
    if not haystack:
        return True
    for part in _ITEM_SPLIT.split(str(raw)):
        token = _item_key(part)
        if not token:
            continue
        if token in haystack:
            return True
        for suffix in _ITEM_SUFFIXES:
            stem = token[:-len(suffix)] if token.endswith(suffix) else ""
            if len(stem) >= 2 and stem in haystack:
                return True
    return False


def parse_number(value):
    text = nz(value).replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def canonicalize_unit(unit: str) -> str:
    raw = re.sub(r"\s+", "", nz(unit)).replace("％", "%")
    raw = re.sub(r"(?i)u\.?s\.?\$", "달러", raw)
    raw = re.sub(r"(?i)usd", "달러", raw)
    # KOSIS 는 단위를 '천$' / '백만$' 처럼 기호로 쓰는 표가 많다. 'US$' 만 처리하면
    # 이런 표기가 차원 미확정으로 떨어져 값 비교 자체를 못 한다(실측 확인).
    raw = raw.replace("＄", "$").replace("$", "달러")
    aliases = {
        "퍼센트": "%",
        "프로": "%",
        "퍼센트포인트": "%p",
        "%포인트": "%p",
        "퍼센트p": "%p",
        "불": "달러",
        "미달러": "달러",
        "미화달러": "달러",
        "개사": "개",
        "사": "개",
        "곳": "개",
        "인": "명",
        "사람": "명",
        "대당명": "명/대",
        "명/대": "명/대",
    }
    return aliases.get(raw, raw)


def canonicalize_period(period: str, prd_se: str = "") -> str:
    raw = nz(period)
    periodicity = nz(prd_se).upper()
    if periodicity == "M":
        match = re.search(r"((?:19|20)\d{2})\D*(1[0-2]|0?[1-9])", raw)
        if match:
            return f"{match.group(1)}{int(match.group(2)):02d}"
    match = re.search(r"(?:19|20)\d{2}", raw)
    return match.group() if match else raw


def unit_dimension(unit: str) -> str:
    value = canonicalize_unit(unit)
    if not value:
        return "unknown"
    if value in {"%", "%p"}:
        return "rate"
    if value in {"명/대"}:
        return "ratio"
    if any(token in value for token in ("원", "달러", "엔", "유로")):
        return "currency"
    if value in {"명", "천명", "만명", "백만명"}:
        return "person_count"
    if value in {"개", "대", "건", "가구", "세대"}:
        return "count"
    if value in {"세", "살"}:
        return "age"
    if value in {"년", "개월", "월", "주", "일", "시간", "분", "초"}:
        return "duration"
    if value in {"배", "배수"}:
        return "multiple"
    if any(token in value for token in ("톤", "kg", "킬로그램", "ha", "헥타르")):
        return "quantity"
    if value in {"위"}:
        return "rank"
    return "unknown"


def semantic_type(row: dict, dimension: str) -> str:
    value_type = nz(row.get("value_type"))
    role = nz(row.get("measurement_role"))
    indicator = nz(row.get("measurement_indicator")) or nz(row.get("indicator"))
    compact = re.sub(r"\s+", "", indicator)

    if value_type == "순위" or dimension == "rank":
        return "rank"
    if value_type == "증감률" or role == "증감률" or any(
        token in compact for token in ("증감률", "증가율", "감소율", "상승률", "하락률")
    ):
        return "rate_change"
    if value_type in {"비율", "구성비"} or any(
        token in compact for token in ("비율", "구성비", "점유율")
    ):
        return "rate_level"
    if value_type == "증감량":
        return "absolute_change"
    if dimension == "currency":
        return "amount"
    if dimension in {"person_count", "count"}:
        return "count"
    if dimension == "multiple":
        return "multiple"
    if dimension in {"age", "duration"}:
        return "condition"
    return "level"


def entity_type(row: dict) -> str:
    indicator = nz(row.get("measurement_indicator"))
    text = " ".join(nz(row.get(key)) for key in ("measurement_item", "claim_text"))
    if any(token in indicator for token in ("정비사", "근로자", "취업자", "인구", "사람", "여객", "이용객")):
        return "person"
    if any(token in indicator for token in ("항공사", "기업", "업체", "회사")):
        return "organization"
    if any(token in text for token in ("가구", "세대")):
        return "household"
    if any(token in text for token in ("자동차", "차량", "선박", "항공기")):
        return "vehicle"
    if nz(row.get("measurement_item")):
        return "item"
    return "unspecified"


def comparison_period(row: dict, semantic: str) -> str:
    if semantic not in {"rate_change", "absolute_change"}:
        return ""
    target = nz(row.get("measurement_period"))
    target_match = re.search(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])?", target)
    target_value = target_match.group() if target_match else ""
    text = nz(row.get("claim_text"))

    explicit_patterns = [
        r"((?:19|20)\d{2})\s*년\s*(?:보다|대비|에\s*비해|과\s*비교)",
        r"(?:기준|비교)\s*(?:시점|연도)?\s*((?:19|20)\d{2})\s*년",
    ]
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1)
            if value != target_value:
                return value

    base = nz(row.get("change_base"))
    if target_value and "전년" in base:
        if len(target_value) == 6:
            return str(int(target_value[:4]) - 1) + target_value[4:]
        return str(int(target_value[:4]) - 1)
    if len(target_value) == 6 and "전월" in base:
        year, month = int(target_value[:4]), int(target_value[4:])
        if month == 1:
            return f"{year - 1}12"
        return f"{year}{month - 1:02d}"
    return ""


def expected_base_period(target_period: str, change_base: str) -> str:
    """Return the comparison period implied by a target period and change base."""
    target = nz(target_period)
    base = nz(change_base)
    if not target or not base:
        return ""
    if base in {"전년동월", "전년동기"} and re.fullmatch(r"(?:19|20)\d{4}", target):
        return str(int(target[:4]) - 1) + target[4:]
    if base == "전월" and re.fullmatch(r"(?:19|20)\d{4}", target):
        year, month = int(target[:4]), int(target[4:])
        return f"{year - 1}12" if month == 1 else f"{year}{month - 1:02d}"
    if base == "전년" and re.fullmatch(r"(?:19|20)\d{2}", target):
        return str(int(target) - 1)
    return ""


def align_change_period(row: dict) -> tuple[str, str]:
    """Correct a change measurement that was bound to its comparison period."""
    measurement_period = canonicalize_period(
        row.get("measurement_period"),
        row.get("measurement_prd_se"),
    )
    claim_period = canonicalize_period(row.get("period"), row.get("prd_se"))
    role = nz(row.get("measurement_role"))
    if role not in {"증감률", "증감값"} or not claim_period:
        return measurement_period, ""
    base_period = expected_base_period(claim_period, row.get("change_base"))
    if base_period and measurement_period == base_period:
        return claim_period, "COMPARISON_PERIOD_TO_TARGET"
    return measurement_period, ""


def exclusion(row: dict, dimension: str, semantic: str):
    measurement_id = nz(row.get("claim_measurement_id"))
    if not measurement_id:
        return "NO_MEASUREMENT", "측정값 없는 placeholder"
    observation_type = infer_measurement_observation_type(row)
    source_scope = infer_source_scope(row, observation_type)
    if observation_type != "OBSERVED":
        return f"{observation_type}_NOT_OBSERVED", f"measurement_observation_type={observation_type}"
    if source_scope != "DOMESTIC_OFFICIAL":
        return f"SOURCE_SCOPE_{source_scope}", f"source_scope={source_scope}"
    usage = nz(row.get("measurement_usage"))
    if usage != "KOSIS_VALUE":
        return "NOT_KOSIS_VALUE", f"measurement_usage={usage or '-'}"
    scope = nz(row.get("claim_domain_scope"))
    if scope != "국내공식통계":
        return "OUT_OF_KOSIS_SCOPE", f"claim_domain_scope={scope or '-'}"
    source = nz(row.get("measurement_binding_source"))
    if source != "hcx":
        return "BINDING_NOT_CONFIRMED", f"measurement_binding_source={source or '-'}"
    role = nz(row.get("measurement_role"))
    if role in TARGET_ROLES:
        return "TARGET_VALUE_NOT_OBSERVED", f"measurement_role={role}"
    if role in SKIP_ROLES:
        return "ROLE_NOT_DIRECT_TARGET", f"measurement_role={role}"
    if parse_number(row.get("value")) is None:
        return "VALUE_MISSING", "value가 숫자가 아님"
    if not (nz(row.get("measurement_indicator")) or nz(row.get("indicator"))):
        return "INDICATOR_MISSING", "measurement indicator 없음"
    if not nz(row.get("measurement_period")):
        return "PERIOD_MISSING", "measurement period 없음"
    if not nz(row.get("measurement_prd_se")):
        return "PERIODICITY_MISSING", "measurement prd_se 없음"
    if dimension == "unknown":
        return "UNIT_UNSUPPORTED", f"표준화할 수 없는 unit={nz(row.get('unit')) or '-'}"
    if semantic in {"rate_change", "rate_level"} and dimension != "rate":
        return "VALUE_TYPE_UNIT_CONFLICT", f"semantic_type={semantic}, unit_dimension={dimension}"
    if semantic == "rank":
        return "RANK_NOT_DIRECTLY_COMPARABLE", "순위는 KOSIS 원자료와 직접 비교하지 않음"
    return "", ""


ENRICHMENT_ACTIONS = {
    "NO_MEASUREMENT": "REEXTRACT_MEASUREMENT",
    "BINDING_NOT_CONFIRMED": "CONFIRM_MEASUREMENT_BINDING",
    "ROLE_NOT_DIRECT_TARGET": "CONFIRM_DIRECT_TARGET_ROLE",
    "VALUE_MISSING": "REEXTRACT_VALUE",
    "INDICATOR_MISSING": "REEXTRACT_INDICATOR",
    "PERIOD_MISSING": "RESOLVE_PERIOD_FROM_CONTEXT",
    "PERIODICITY_MISSING": "RESOLVE_PERIODICITY",
    "UNIT_UNSUPPORTED": "NORMALIZE_UNIT",
    "VALUE_TYPE_UNIT_CONFLICT": "REPAIR_VALUE_TYPE_OR_UNIT",
    "INTRADAY_MARKET_RATE": "CONFIRM_DAILY_OR_INTRADAY_OFFICIAL_TABLE",
    "DAILY_MARKET_RATE": "CONFIRM_DAILY_OR_INTRADAY_OFFICIAL_TABLE",
}


def mapping_gate(row: dict, code: str) -> tuple[str, str]:
    """Classify strict eligibility failures into recoverable vs hard reject."""
    if not code:
        return "READY", ""
    if code == "OUT_OF_KOSIS_SCOPE":
        scope = nz(row.get("claim_domain_scope"))
        if not scope or scope == "기타":
            return "ENRICH", "CONFIRM_KOSIS_SCOPE"
        return "REJECT", ""
    if code == "NOT_KOSIS_VALUE":
        if not nz(row.get("measurement_usage")):
            return "ENRICH", "CLASSIFY_MEASUREMENT_USAGE"
        return "REJECT", ""
    if code.endswith("_NOT_OBSERVED") or code.startswith("SOURCE_SCOPE_"):
        return "REJECT", ""
    if code == "RANK_NOT_DIRECTLY_COMPARABLE":
        return "REJECT", ""
    if code == "TARGET_VALUE_NOT_OBSERVED":
        return "REJECT", ""
    action = ENRICHMENT_ACTIONS.get(code)
    if action:
        return "ENRICH", action
    return "REJECT", ""


def normalize_row(row: dict) -> dict:
    normalized_row = dict(row)
    normalized_row["prev_sentence"] = first_context_value(row, PREV_SENTENCE_ALIASES)
    normalized_row["prev_prev_sentence"] = first_context_value(
        row, PREV_PREV_SENTENCE_ALIASES
    )
    normalized_row["next_sentence"] = first_context_value(row, NEXT_SENTENCE_ALIASES)
    for field in (
        set(PREV_SENTENCE_ALIASES)
        | set(PREV_PREV_SENTENCE_ALIASES)
        | set(NEXT_SENTENCE_ALIASES)
    ):
        if field not in {"prev_sentence", "prev_prev_sentence", "next_sentence"}:
            normalized_row.pop(field, None)

    row = normalized_row
    out = dict(row)

    raw_unit = nz(row.get("unit"))
    canonical_unit = canonicalize_unit(raw_unit)
    if canonical_unit == "명" and re.search(r"대당|명\s*/\s*대", nz(row.get("claim_text")) + nz(row.get("measurement_text"))):
        canonical_unit = "명/대"
    dimension = unit_dimension(canonical_unit)
    semantic = semantic_type(row, dimension)
    code, reason = exclusion(row, dimension, semantic)
    observation_type = infer_measurement_observation_type({**row, "unit": canonical_unit})
    source_scope = infer_source_scope(row, observation_type)
    normalized_relative_date, relative_date_status = normalize_relative_date(row)

    # Preserve claim-level fields while exposing the aliases expected by the
    # feature/model matcher.  The aliases are always measurement-level values.
    out["claim_indicator"] = nz(row.get("indicator"))
    out["claim_industry_or_item"] = nz(row.get("industry_or_item"))
    out["claim_period"] = nz(row.get("period"))
    out["claim_prd_se"] = nz(row.get("prd_se"))
    out["raw_measurement_period"] = nz(row.get("measurement_period"))
    out["indicator"] = nz(row.get("measurement_indicator")) or nz(row.get("indicator"))
    # 문장에도 지표에도 근거가 없는 대상은 이 measurement 의 것이 아니다.
    # 막지 않고 **지운다** — 그러면 대상 없는 주장이 되어 집계 좌표를 찾게 되고,
    # 그것이 문장이 실제로 말하는 바다.
    # (실측: '전체 수출액 6838억달러' + 대상='반도체' → 지우면 총액 좌표로 일치)
    out["industry_or_item"] = nz(row.get("measurement_item")) or nz(row.get("industry_or_item"))
    out["item_ungrounded"] = "N"
    if out["industry_or_item"] and not claim_item_grounded(row):
        out["item_ungrounded"] = "Y"
        out["dropped_item"] = out["industry_or_item"]
        out["industry_or_item"] = ""
    out["prd_se"] = nz(row.get("measurement_prd_se"))
    out["period"], out["period_alignment_status"] = align_change_period(row)
    out["raw_unit"] = raw_unit
    out["canonical_unit"] = canonical_unit
    out["unit"] = canonical_unit
    out["unit_dimension"] = dimension
    out["measurement_observation_type"] = observation_type
    out["source_scope"] = source_scope
    out["measurement_period_normalized"] = normalized_relative_date
    out["relative_date_status"] = relative_date_status
    out["semantic_type"] = semantic
    out["entity_type"] = entity_type(row)
    comparison_row = dict(row)
    comparison_row["measurement_period"] = out["period"]
    comparison_row["measurement_prd_se"] = out["prd_se"]
    out["comparison_period"] = comparison_period(comparison_row, semantic)
    # 내용 기반 범위 판정 — HCX 자기 신고 라벨(measurement_usage/claim_domain_scope)만
    # 믿으면 비트코인 시세나 개별 브랜드 판매가도 그대로 통과한다(실측 확인).
    scope = gate_decision({**row, "unit": out["unit"]})
    out.update(scope)
    if not code and scope["scope_gate_blocked"] == "Y":
        code = scope["scope_gate_code"]
        reason = scope["scope_gate_reason"]
    if (
        not code
        and scope["scope_gate_severity"] == "REVIEW"
        and scope["scope_gate_code"] in {"INTRADAY_MARKET_RATE", "DAILY_MARKET_RATE"}
    ):
        code = scope["scope_gate_code"]
        reason = scope["scope_gate_reason"]

    out["mapping_eligible"] = "Y" if not code else "N"
    out["in_ready"] = out["mapping_eligible"]
    out["mapping_exclusion_code"] = code
    out["mapping_exclusion_reason"] = reason
    if scope["scope_gate_blocked"] == "Y":
        out["mapping_gate"] = "REJECT"
        out["mapping_gate_reason"] = code
        out["enrichment_actions"] = ""
    else:
        gate, action = mapping_gate(row, code)
        out["mapping_gate"] = gate
        out["mapping_gate_reason"] = code or "ELIGIBLE"
        out["enrichment_actions"] = action
    return out


DERIVED_FIELDS = [
    "claim_indicator",
    "claim_industry_or_item",
    # 근거 없는 대상을 지웠는지, 무엇을 지웠는지 남긴다(추적용)
    "item_ungrounded",
    "dropped_item",
    "claim_period",
    "claim_prd_se",
    "raw_measurement_period",
    "period_alignment_status",
    "raw_unit",
    "canonical_unit",
    "unit_dimension",
    "measurement_observation_type",
    "source_scope",
    "measurement_period_normalized",
    "relative_date_status",
    "semantic_type",
    "entity_type",
    "comparison_period",
    "mapping_eligible",
    "in_ready",
    "mapping_exclusion_code",
    "mapping_exclusion_reason",
    "mapping_gate",
    "mapping_gate_reason",
    "enrichment_actions",
    # 내용 기반 범위 판정 (kosis_scope_gate)
    "scope_gate_code",
    "scope_gate_reason",
    "scope_gate_severity",
    "scope_gate_blocked",
]


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prepare(
    input_path: Path,
    output_path: Path,
    rejected_path: Path | None = None,
    enrich_path: Path | None = None,
    all_output_path: Path | None = None,
):
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source_fields = list(reader.fieldnames or [])
        normalized = [normalize_row(row) for row in reader]

    context_fields = (
        set(PREV_SENTENCE_ALIASES)
        | set(PREV_PREV_SENTENCE_ALIASES)
        | set(NEXT_SENTENCE_ALIASES)
    )
    fields = [field for field in source_fields if field not in context_fields]
    context_insert_at = fields.index("claim_text") + 1 if "claim_text" in fields else len(fields)
    fields[context_insert_at:context_insert_at] = [
        "prev_sentence",
        "prev_prev_sentence",
        "next_sentence",
    ]
    fields = list(dict.fromkeys(fields + DERIVED_FIELDS))
    accepted = [row for row in normalized if row["mapping_eligible"] == "Y"]
    rejected = [row for row in normalized if row["mapping_eligible"] != "Y"]
    enrich = [row for row in normalized if row["mapping_gate"] == "ENRICH"]
    hard_rejected = [row for row in normalized if row["mapping_gate"] == "REJECT"]
    write_csv(output_path, accepted, fields)
    if rejected_path:
        # Legacy calls receive every non-READY row. New three-way calls that
        # also provide enrich_path receive only hard rejects here.
        write_csv(rejected_path, hard_rejected if enrich_path else rejected, fields)
    if enrich_path:
        write_csv(enrich_path, enrich, fields)
    if all_output_path:
        write_csv(all_output_path, normalized, fields)
    return accepted, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rejected-output", default="")
    parser.add_argument("--enrich-output", default="")
    parser.add_argument("--all-output", default="")
    parser.add_argument("--expect-ready", type=int, default=0)
    args = parser.parse_args()

    accepted, rejected = prepare(
        Path(args.input),
        Path(args.output),
        Path(args.rejected_output) if args.rejected_output else None,
        Path(args.enrich_output) if args.enrich_output else None,
        Path(args.all_output) if args.all_output else None,
    )
    counts = Counter(row["mapping_exclusion_code"] for row in rejected)
    gate_counts = Counter(
        ["READY"] * len(accepted) + [row["mapping_gate"] for row in rejected]
    )
    print(f"input={len(accepted) + len(rejected)} ready={len(accepted)} rejected={len(rejected)}")
    print("gate_counts=" + ", ".join(f"{key}:{value}" for key, value in gate_counts.most_common()))
    print("rejection_counts=" + ", ".join(f"{key}:{value}" for key, value in counts.most_common()))
    print(f"saved={args.output}")
    if args.rejected_output:
        print(f"rejected={args.rejected_output}")
    if args.enrich_output:
        print(f"enrich={args.enrich_output}")
    if args.all_output:
        print(f"all={args.all_output}")
    if args.expect_ready and len(accepted) != args.expect_ready:
        raise SystemExit(f"expected {args.expect_ready} ready rows, got {len(accepted)}")


if __name__ == "__main__":
    main()
