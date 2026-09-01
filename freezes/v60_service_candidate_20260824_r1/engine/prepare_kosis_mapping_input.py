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
from datetime import datetime, timedelta
from pathlib import Path

from kosis_claim_shape import (claim_shape_exclusion, cumulative_is_answerable,
                               quarter_period)
from kosis_scope_gate import (ARTICLE_SCOPE_CODES, gate_decision, has_own_source,
                              propagate_by_article, starts_with_anaphor)


EMPTY = {"", "-", "nan", "none", "null"}
SUPPORTED_MAPPING_TYPES = {"direct", "rate_from_level", "difference_from_level"}
SKIP_ROLES = {"이전값", "참고값"}
TARGET_ROLES = {"목표값"}


def nz(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in EMPTY else text


def normalize_mapping_type(value) -> str:
    """Treat missing-value spellings as the default direct comparison."""
    text = str(value or "").strip().lower()
    if text in EMPTY:
        return "direct"
    return text if text in SUPPORTED_MAPPING_TYPES else str(value).strip()


def measurement_value(row: dict, measurement_field: str, legacy_field: str) -> str:
    """Read a measurement field without borrowing a claim-level alias.

    Older inputs predate the ``measurement_*`` contract, so they may use the
    legacy field directly.  Once the measurement column exists, however, an
    empty value is meaningful and must be enriched rather than silently filled
    with a claim-level value that may describe a different number in the same
    sentence.
    """
    if measurement_field in row:
        return nz(row.get(measurement_field))
    return nz(row.get(legacy_field))


def claim_value(row: dict, preserved_field: str, source_field: str) -> str:
    """Keep claim-level values stable when normalized CSVs are reprocessed."""
    if preserved_field in row:
        return nz(row.get(preserved_field))
    return nz(row.get(source_field))


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
    raw = measurement_value(row, "measurement_item", "industry_or_item")
    if not _item_key(raw):
        return True   # 대상이 없는 주장은 집계 규칙이 따로 본다
    haystack = _item_key(row.get("claim_text")) + _item_key(
        measurement_value(row, "measurement_indicator", "indicator"))
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
    }
    return aliases.get(raw, raw)


_PERCENT_POINT = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(?:%|％|퍼센트)\s*(?:포인트|p)"
)


def percent_point_measurement(row: dict) -> bool:
    """Return whether this measurement is a percentage-point difference.

    Extractors often preserve ``%포인트`` in ``measurement_text`` but emit the
    unit as plain ``%``.  When the suffix was omitted from the measurement span,
    bind it by numeric value so another percentage-point value in the same
    sentence cannot leak into this measurement.
    """
    measurement_text = nz(row.get("measurement_text"))
    if _PERCENT_POINT.search(measurement_text):
        return True
    target = parse_number(row.get("value"))
    if target is None:
        return False
    for match in _PERCENT_POINT.finditer(nz(row.get("claim_text"))):
        try:
            if abs(float(match.group(1)) - target) <= 1e-12:
                return True
        except ValueError:
            continue
    return False


def canonical_measurement_unit(row: dict) -> str:
    unit = canonicalize_unit(row.get("unit"))
    if unit == "%" and percent_point_measurement(row):
        return "%p"
    return unit


def canonicalize_period(period: str, prd_se: str = "") -> str:
    raw = nz(period)
    periodicity = nz(prd_se).upper()
    if periodicity == "M":
        match = re.search(r"((?:19|20)\d{2})\D*(1[0-2]|0?[1-9])", raw)
        if match:
            return f"{match.group(1)}{int(match.group(2)):02d}"
    if periodicity == "Q":
        match = re.search(r"((?:19|20)\d{2})\D*0?([1-4])(?:\s*(?:/\s*4)?\s*분기)?", raw)
        if match:
            return f"{match.group(1)}{int(match.group(2)):02d}"
    match = re.search(r"(?:19|20)\d{2}", raw)
    return match.group() if match else raw


_ADDITIVE_FLOW_TERMS = (
    "수출액", "수입액", "수출금액", "수입금액", "교역액", "거래액",
    "매출액", "판매액", "생산액", "투자액", "지출액", "수주액",
)


def infer_annual_period_aggregation(row: dict, period: str, prd_se: str) -> str:
    """Infer M/Q summation only for clearly additive annual flow measures."""
    if nz(prd_se).upper() != "Y" or not re.fullmatch(r"(?:19|20)\d{2}", nz(period)):
        return ""
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    blocked = ("증감률", "비율", "비중", "도입률", "평균", "지수", "현재인원", "인력")
    if any(term in indicator for term in blocked):
        return ""
    return "sum" if any(term in indicator for term in _ADDITIVE_FLOW_TERMS) else ""


_EMPLOYEE_SIZE_RANGE = re.compile(
    r"(?<!\d)\d[\d,]*\s*(?:인|명)\s*(?:이상|초과)\s*"
    r"\d[\d,]*\s*(?:인|명)\s*(?:미만|이하)(?!\d)"
)


def explicit_employee_size_targets(row: dict) -> tuple[str, ...]:
    """Preserve explicit employee-count ranges without inventing KOSIS labels."""
    text = " ".join(
        nz(row.get(field))
        for field in ("claim_text", "measurement_indicator", "indicator")
    )
    return tuple(dict.fromkeys(
        re.sub(r"\s+", " ", match.group(0)).strip()
        for match in _EMPLOYEE_SIZE_RANGE.finditer(text)
    ))


def explicit_obj_targets(row: dict) -> tuple[str, ...]:
    """Extract only literal demographic/category targets from claim text."""
    text = nz(row.get("claim_text"))
    values = [
        re.sub(r"\s+", "", match.group(0))
        for match in re.finditer(
            r"(?<!\d)\d{1,3}\s*세\s*(?:이상|이하|미만|초과)", text
        )
    ]
    if re.search(r"아내가\s*연상|여자\s*연상", text):
        values.append("여자연상")
    elif re.search(r"남편이\s*연상|남자\s*연상", text):
        values.append("남자연상")

    # Household-asset tables encode owner occupancy and the asset class on
    # separate OBJ axes.  HCX correctly binds the measurement indicator but
    # often leaves both structured target fields empty.  Recover the official
    # categorical labels only when the sentence explicitly identifies an
    # owner household; a generic mention of real-estate prices/assets must not
    # acquire this scope.
    owner_household = re.search(
        r"(?:자기\s*집을?\s*소유한\s*가구|자기집\s*(?:보유|소유)?\s*가구|"
        r"자가\s*(?:보유|소유)?\s*가구)",
        text,
    )
    if owner_household:
        values.append("자기집")
        indicator = measurement_value(
            row, "measurement_indicator", "indicator"
        )
        if "부동산" in indicator:
            values.append("부동산")
        elif "자산" in indicator:
            values.append("자산")
    return tuple(dict.fromkeys(values))


def grounded_demographic_value(row: dict, field: str) -> str:
    """Drop a demographic label inferred from explanatory tail context."""
    raw = nz(row.get(field))
    if raw.lower() in {"", "-", "nan", "none", "null"}:
        return raw
    text = nz(row.get("claim_text"))
    compact_text = re.sub(r"\s+", "", text)
    compact_raw = re.sub(r"\s+", "", raw)
    target_position = compact_text.find(compact_raw)
    if target_position < 0:
        return "-"
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    indicator_position = compact_text.find(indicator) if indicator else -1
    if indicator_position >= 0 and target_position > indicator_position:
        between = compact_text[indicator_position:target_position]
        if any(cue in between for cue in ("현상의", "상당부분", "원인", "영향", "때문")):
            return "-"
    return raw


def merge_obj_target_terms(existing, additions) -> str:
    values = []
    for raw in (nz(existing), *additions):
        if not raw or raw.lower() in {"-", "nan", "none", "null"}:
            continue
        values.extend(part.strip() for part in raw.split("|") if part.strip())
    return "|".join(dict.fromkeys(values))


def _article_year_month(value: str) -> tuple[int, int] | None:
    match = re.search(r"((?:19|20)\d{2})[-./]?(0[1-9]|1[0-2])[-./]?([0-3]\d)", nz(value))
    if match:
        return int(match.group(1)), int(match.group(2))
    # CSV exports from Excel frequently contain a serial date (for example
    # 45838.0 == 2025-06-30).  Relative-period repair must not silently fail
    # just because the article date was not formatted before export.
    try:
        serial = float(nz(value))
    except ValueError:
        return None
    if not 20_000 <= serial <= 80_000:
        return None
    date = datetime(1899, 12, 30) + timedelta(days=serial)
    return date.year, date.month


_RELATIVE_YEAR = {"작년": -1, "지난해": -1, "올해": 0, "금년": 0}
_CHANGE_DOWN = re.compile(r"감소|줄(?:었|어|었다|었다가|었다고|어든|었다는)?|하락|내려")
_CHANGE_UP = re.compile(r"증가|늘(?:었|어|었다|어난|었다고|었다는)?|상승|올라")


def repair_extracted_contract(row: dict) -> tuple[dict, list[str]]:
    """Repair explicit relative time and change semantics before gating.

    This is deliberately evidence-bound: a relative year/month/quarter must
    appear in the article text/title and a change must have a comparison base
    plus an increase/decrease cue.  It does not infer missing facts from a
    known gold coordinate.
    """
    repaired = dict(row)
    statuses: list[str] = []
    article = _article_year_month(row.get("date"))
    claim_text = nz(row.get("claim_text"))
    title = nz(row.get("title"))
    context = f"{title} {claim_text}"
    period = measurement_value(row, "measurement_period", "period")
    prd_se = measurement_value(row, "measurement_prd_se", "prd_se").upper()

    # Relative quarter sequences often omit the year after the first member:
    # "작년 2분기, 3분기, 4분기".  The last quarter before an "올해"
    # transition binds the final listed measurement.
    if article and prd_se == "Q":
        for label, offset in _RELATIVE_YEAR.items():
            marker = context.find(label)
            if marker < 0:
                continue
            segment = context[marker:]
            if label in {"작년", "지난해"}:
                transition = min(
                    (value for value in (segment.find("올해"), segment.find("금년")) if value > 0),
                    default=len(segment),
                )
                segment = segment[:transition]
            quarters = [int(value) for value in re.findall(r"([1-4])\s*(?:·?4)?분기", segment)]
            if quarters:
                period = f"{article[0] + offset:04d}{quarters[-1]:02d}"
                statuses.append("RELATIVE_QUARTER_FROM_ARTICLE_DATE")
                break

    # A stale extracted year with a matching title month is repaired from the
    # article publication year ("5월 생산" published in June 2025).
    explicit_title_year_month = bool(re.search(
        r"(?<!\d)(?:19|20)\d{2}\s*(?:년|[-./])\s*(?:1[0-2]|0?[1-9])\s*월?",
        title,
    ))
    if (
        article
        and prd_se == "M"
        and re.fullmatch(r"(?:19|20)\d{4}", period)
        and not explicit_title_year_month
    ):
        months = {int(value) for value in re.findall(r"(?<!\d)(1[0-2]|0?[1-9])\s*월", title)}
        if len(months) == 1:
            month = next(iter(months))
            if month == int(period[4:]) and int(period[:4]) != article[0]:
                period = f"{article[0]:04d}{month:02d}"
                statuses.append("TITLE_MONTH_YEAR_FROM_ARTICLE_DATE")

    # A bare annual value introduced by "지난해/올해" is anchored to the
    # article year.  "월평균 임금" describes the metric, not a monthly period.
    if article and re.fullmatch(r"(?:19|20)\d{2}", period):
        labels = [label for label in _RELATIVE_YEAR if label in claim_text]
        if labels and not re.search(r"(?<!\d)(?:1[0-2]|0?[1-9])\s*월", claim_text):
            label = labels[-1]
            period = f"{article[0] + _RELATIVE_YEAR[label]:04d}"
            statuses.append("RELATIVE_YEAR_FROM_ARTICLE_DATE")
            if prd_se == "M":
                prd_se = "Y"
                statuses.append("ANNUAL_METRIC_NOT_MONTHLY_PERIOD")

    if "measurement_period" in repaired:
        repaired["measurement_period"] = period
    else:
        repaired["period"] = period
    if "measurement_prd_se" in repaired:
        repaired["measurement_prd_se"] = prd_se
    else:
        repaired["prd_se"] = prd_se
    # Legacy inputs commonly duplicate the measurement into period/prd_se,
    # but some rows deliberately keep a different claim-level target there.
    # Preserve that explicit distinction unless this function actually
    # recovered a relative/stale period from article evidence.
    original_measurement_period = measurement_value(row, "measurement_period", "period")
    legacy_period = nz(row.get("period"))
    period_repaired = any(status in {
        "RELATIVE_QUARTER_FROM_ARTICLE_DATE",
        "TITLE_MONTH_YEAR_FROM_ARTICLE_DATE",
        "RELATIVE_YEAR_FROM_ARTICLE_DATE",
        "ANNUAL_METRIC_NOT_MONTHLY_PERIOD",
    } for status in statuses)
    if "claim_period" not in repaired and (
        period_repaired or not row.get("measurement_period")
        or legacy_period == original_measurement_period
    ):
        repaired["period"] = period
    original_measurement_prd = measurement_value(
        row, "measurement_prd_se", "prd_se"
    ).upper()
    legacy_prd = nz(row.get("prd_se")).upper()
    if "claim_prd_se" not in repaired and (
        period_repaired or not row.get("measurement_prd_se")
        or legacy_prd == original_measurement_prd
    ):
        repaired["prd_se"] = prd_se

    compact_text = re.sub(r"\s+", "", claim_text)
    change_base = nz(repaired.get("change_base"))
    # The explicit comparison phrase in the bound measurement is authoritative.
    # HCX occasionally emits a stale/default ``전월`` even when the sentence and
    # indicator say ``전년동월비``.  Keeping that contradiction makes the correct
    # official ITEM fail later with CHANGE_BASE_AMBIGUOUS, so repair it here.
    if any(token in compact_text for token in ("전년동월비", "전년동월대비", "전년같은달")):
        if change_base != "전년동월":
            statuses.append("CHANGE_BASE_FROM_EXPLICIT_TEXT")
        change_base = "전년동월"
    elif "전년동기" in compact_text:
        if change_base != "전년동기":
            statuses.append("CHANGE_BASE_FROM_EXPLICIT_TEXT")
        change_base = "전년동기"
    elif "전달보다" in compact_text or "전월비" in compact_text or "전월대비" in compact_text:
        if change_base != "전월":
            statuses.append("CHANGE_BASE_FROM_EXPLICIT_TEXT")
        change_base = "전월"
    elif "전분기" in compact_text:
        if change_base != "전분기":
            statuses.append("CHANGE_BASE_FROM_EXPLICIT_TEXT")
        change_base = "전분기"
    repaired["change_base"] = change_base

    has_change_cue = bool(_CHANGE_DOWN.search(compact_text) or _CHANGE_UP.search(compact_text))
    dimension = unit_dimension(canonical_measurement_unit(repaired))
    if change_base and has_change_cue:
        if dimension == "rate" and nz(repaired.get("value_type")) not in {"비율", "구성비"}:
            repaired["value_type"] = "증감률"
            repaired["measurement_role"] = "증감률"
            statuses.append("CHANGE_RATE_FROM_TEXT")
        elif dimension in {"person_count", "count", "currency"} and (
            any(token in compact_text for token in ("감소폭", "증가폭", "변화", "증감"))
            or any(token in re.sub(r"\s+", "", measurement_value(repaired, "measurement_indicator", "indicator"))
                   for token in ("변화", "증감", "감소", "증가"))
        ):
            repaired["value_type"] = "증감량"
            repaired["measurement_role"] = "증감값"
            statuses.append("ABSOLUTE_CHANGE_FROM_TEXT")
    return repaired, statuses


def _shift_month(period: str, offset: int) -> str:
    if not re.fullmatch(r"(?:19|20)\d{4}", nz(period)):
        return ""
    year, month = int(period[:4]), int(period[4:])
    index = year * 12 + month - 1 + offset
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def recover_relative_measurement_period(row: dict) -> tuple[str, str]:
    """Repair relative month binding in already-extracted HCX CSV rows."""
    original = measurement_value(row, "measurement_period", "period")
    text = nz(row.get("claim_text"))
    measurement = nz(row.get("measurement_text")) or nz(row.get("value"))
    index = text.find(measurement) if measurement else -1
    if index < 0:
        return original, ""
    local = text[max(0, index - 40):index + len(measurement)]
    article = _article_year_month(row.get("date"))
    match = re.findall(r"(작년|지난해|올해|금년)\s*(\d{1,2})\s*월", local)
    resolved = ""
    status = ""
    if match and article:
        label, raw_month = match[-1]
        month = int(raw_month)
        if 1 <= month <= 12:
            year = article[0] - 1 if label in {"작년", "지난해"} else article[0]
            resolved = f"{year:04d}{month:02d}"
            status = "RELATIVE_YEAR_MONTH_FROM_ARTICLE_DATE"
    elif re.search(r"한\s*달\s*전", local):
        anchor = canonicalize_period(
            claim_value(row, "claim_period", "period"),
            claim_value(row, "claim_prd_se", "prd_se"),
        )
        resolved = _shift_month(anchor, -1)
        status = "ONE_MONTH_BEFORE_CLAIM_PERIOD" if resolved else ""
    elif re.search(r"지난\s*달|지난월", local) and article:
        resolved = _shift_month(f"{article[0]:04d}{article[1]:02d}", -1)
        status = "PREVIOUS_MONTH_FROM_ARTICLE_DATE"
    elif article and re.search(r"지난\s*달|지난월", nz(row.get("title"))):
        # A following sentence can inherit the article subject established in
        # the title/lead.  Trust that context only when HCX's own bound month
        # exactly equals the calendar month implied by the publication date.
        # This preserves item-level rows under a ``지난달 생산자물가`` lead
        # without spreading the relative month to historical side facts.
        previous_month = _shift_month(f"{article[0]:04d}{article[1]:02d}", -1)
        if original == previous_month:
            resolved = original
            status = "PREVIOUS_MONTH_FROM_ARTICLE_TITLE"
    return (resolved, status) if resolved else (original, "")


_CALENDAR_MONTH = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*월(?!\s*(?:간|동안|째|차))")
_SPECIFIC_DAY = re.compile(
    r"(?:19|20)\d{2}\s*[-./년]\s*(?:1[0-2]|0?[1-9])\s*[-./월]\s*(?:3[01]|[12]\d|0?[1-9])\s*일?"
)
_MARKET_VALUE_TERMS = ("환율", "주가", "종가", "시세", "코스피", "코스닥", "지수")
_PRICE_TERMS = ("가격", "판매가", "출고가", "정가")
_AGGREGATE_PRICE_TERMS = ("평균", "지수", "물가")
_CURRENCY_AMOUNT = re.compile(
    r"\d[\d,.]*(?:\s*(?:만|억|조)\s*\d[\d,]*)?\s*(?:원|달러|엔|유로)"
)


def recover_single_month_period(row: dict) -> tuple[str, str]:
    """Recover YYYYMM only for an unambiguous calendar month in the sentence."""
    period = measurement_value(row, "measurement_period", "period")
    prd_se = measurement_value(row, "measurement_prd_se", "prd_se").upper()
    year_match = re.fullmatch(r"((?:19|20)\d{2})(?:년)?", period)
    full_month_match = re.fullmatch(r"((?:19|20)\d{2})(0[1-9]|1[0-2])", period)
    if prd_se != "M" or not (year_match or full_month_match):
        return period, ""
    text = nz(row.get("claim_text"))
    months = {int(match.group(1)) for match in _CALENDAR_MONTH.finditer(text)}
    # A point-in-time day is not a monthly observation even when only one month
    # is mentioned. Daily market values are rejected separately below.
    if len(months) != 1 or re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", text):
        return period, ""
    month = next(iter(months))
    if year_match:
        return f"{year_match.group(1)}{month:02d}", "SINGLE_MONTH_FROM_TEXT"

    # For an unqualified calendar month, select the latest non-future month
    # relative to publication.  Do not override explicit/relative year text;
    # that contract is handled by ``recover_relative_measurement_period``.
    if re.search(
        rf"(?:(?:19|20)\d{{2}}\s*년|작년|지난해|올해|금년)\s*{month}\s*월",
        text,
    ):
        return period, ""
    article = _article_year_month(row.get("date"))
    if not article:
        return period, ""
    year = article[0] if month <= article[1] else article[0] - 1
    resolved = f"{year:04d}{month:02d}"
    if resolved == period:
        return period, ""
    return resolved, "UNQUALIFIED_MONTH_FROM_ARTICLE_DATE"


_MONTH_CONTEXT_CUES = ("전월 대비", "전월대비", "전월보다", "전달 대비", "전달보다")
_MONTH_CONTEXT_SUBJECTS = (
    "생산자물가", "소비자물가", "수출", "수입", "고용", "취업", "실업",
    "인구", "출생", "사망", "생산", "판매", "소비", "지수",
)


def recover_contextual_title_month(row: dict) -> tuple[str, str]:
    """Inherit an explicit article-title month for an adjacent monthly change.

    HCX correctly extracts item changes such as ``농산물(-5.8%)`` but can mark
    their period ungrounded when the month appears only in the title/lead.
    The repair is intentionally narrow: the row must be monthly, have no
    period, state a month-over-month comparison, share a statistical subject
    with the title, and the title must contain exactly one calendar month.
    """
    original = measurement_value(row, "measurement_period", "period")
    if nz(original) not in {"", "-"}:
        return original, ""
    periodicity = (
        measurement_value(row, "measurement_prd_se", "prd_se")
        or claim_value(row, "claim_prd_se", "prd_se")
    ).upper()
    if periodicity != "M":
        return original, ""
    text = nz(row.get("claim_text"))
    if not any(cue in text for cue in _MONTH_CONTEXT_CUES):
        return original, ""
    # An explicit month in the sentence belongs to that measurement and must
    # never be overwritten by a different month from the article title.
    if any(_CALENDAR_MONTH.finditer(text)):
        return original, ""
    title = nz(row.get("title"))
    months = {int(match.group(1)) for match in _CALENDAR_MONTH.finditer(title)}
    if len(months) != 1:
        return original, ""
    subject_text = " ".join((text, measurement_value(row, "measurement_indicator", "indicator")))
    if not any(subject in title and subject in subject_text for subject in _MONTH_CONTEXT_SUBJECTS):
        return original, ""
    article = _article_year_month(row.get("date"))
    if not article:
        return original, ""
    month = next(iter(months))
    year = article[0] if month <= article[1] else article[0] - 1
    resolved = f"{year:04d}{month:02d}"
    claim_period = canonicalize_period(
        claim_value(row, "claim_period", "period"),
        claim_value(row, "claim_prd_se", "prd_se"),
    )
    if claim_period and claim_period != resolved:
        return original, ""
    return resolved, "MONTH_FROM_ARTICLE_TITLE_CONTEXT"


def daily_market_measurement(row: dict) -> bool:
    """Detect a market observation bound to a specific calendar day."""
    subject = " ".join((
        measurement_value(row, "measurement_indicator", "indicator"),
        nz(row.get("claim_text")),
    )).lower()
    if not any(term in subject for term in _MARKET_VALUE_TERMS):
        return False
    period = measurement_value(row, "measurement_period", "period")
    return bool(
        re.fullmatch(r"(?:19|20)\d{6}", re.sub(r"\D", "", period))
        or _SPECIFIC_DAY.fullmatch(period)
    )


def market_point_measurement(row: dict) -> bool:
    """Detect a threshold, close, or peak that is not a period average."""
    indicator = measurement_value(row, "measurement_indicator", "indicator")
    compact_indicator = re.sub(r"\s+", "", indicator).lower()
    if not any(term in compact_indicator for term in _MARKET_VALUE_TERMS):
        return False
    if "평균" in compact_indicator:
        return False
    target = parse_number(row.get("value"))
    if target is None:
        return False
    text = nz(row.get("claim_text"))
    for match in re.finditer(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:원|달러)\s*선", text):
        try:
            if abs(float(match.group(1).replace(",", "")) - target) <= 1e-12:
                return True
        except ValueError:
            continue
    point_cues = ("현재", "장중", "종가", "마감", "고점", "저점")
    return any(cue in compact_indicator for cue in point_cues)


def individual_product_price(row: dict, dimension: str) -> bool:
    """Detect a concrete product's retail price rather than a price statistic."""
    if dimension not in {"currency", "rate"}:
        return False
    indicator = measurement_value(row, "measurement_indicator", "indicator")
    item = measurement_value(row, "measurement_item", "industry_or_item")
    compact_indicator = re.sub(r"\s+", "", indicator)
    if not item or not any(term in compact_indicator for term in _PRICE_TERMS):
        return False
    if any(term in compact_indicator for term in _AGGREGATE_PRICE_TERMS):
        return False
    if dimension == "currency" and any(
        term in compact_indicator for term in ("판매가", "출고가", "정가")
    ):
        return True
    text = nz(row.get("claim_text"))
    amounts = list(_CURRENCY_AMOUNT.finditer(text))
    if len(amounts) < 2:
        return False
    between = text[amounts[0].end():amounts[-1].start()]
    endpoint_change = any(
        cue in between or cue in text for cue in ("에서", "으로", "인상", "인하", "올랐", "내렸")
    )
    return endpoint_change


def converted_currency_measurement(row: dict, dimension: str) -> bool:
    """Detect an approximate currency conversion reported beside the source value."""
    if dimension != "currency" or nz(row.get("value_approximate")).upper() != "Y":
        return False
    text = nz(row.get("claim_text"))
    currencies = set()
    if re.search(r"\d[\d,.]*(?:만|억|조)?\s*원", text):
        currencies.add("KRW")
    if re.search(r"\d[\d,.]*(?:만|억|조)?\s*(?:달러|엔|유로)", text):
        currencies.add("FOREIGN")
    return len(currencies) > 1


def contextual_denominator(row: dict, dimension: str) -> bool:
    """Detect a sample/cohort size used only as a denominator for another metric."""
    if dimension not in {"count", "person_count"}:
        return False
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    if not any(token in indicator for token in ("품목수", "표본수", "조사대상수", "대상수")):
        return False
    text = nz(row.get("claim_text"))
    return bool(
        any(cue in text for cue in ("평균", "비율", "비중", "%"))
        and any(cue in text for cue in ("가운데", "중", "품목", "표본", "대상"))
    )


def indicator_unit_conflict(row: dict, dimension: str) -> str:
    """Return a reason when the indicator's value kind contradicts its unit."""
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    if not indicator:
        return ""
    ratio_scope_modifier = bool(re.search(
        r"(?:비율|비중|점유율|구성비)(?:별|구간별|에따른).*(?:금액|수출액|수입액|매출액|예산액|투자액|생산액|판매액|가격|판매가)$",
        indicator,
    ))
    rate_indicator = (
        indicator.endswith(("률", "율"))
        or any(token in indicator for token in ("비율", "비중", "점유율", "구성비"))
    ) and "환율" not in indicator and not ratio_scope_modifier
    count_indicator = any(token in indicator for token in (
        "인원", "인구", "근로자수", "취업자수", "이용객수", "대수", "건수",
        "업체수", "기업수", "품목수",
    ))
    amount_indicator = any(token in indicator for token in (
        "금액", "수출액", "수입액", "매출액", "예산액", "투자액",
        "생산액", "판매액", "가격", "판매가",
    ))
    # The outer value kind wins: "사업체 수 증가율" is a rate, not a count;
    # "수출액 증가율" is a rate, not a currency amount.
    if rate_indicator:
        if dimension != "rate":
            return f"비율 지표에 비율 단위가 아님: {indicator}/{dimension}"
        return ""
    if count_indicator and dimension not in {"count", "person_count"}:
        return f"개수 지표에 개수 단위가 아님: {indicator}/{dimension}"
    if amount_indicator and dimension != "currency":
        return f"금액 지표에 통화 단위가 아님: {indicator}/{dimension}"
    return ""


def indicator_unit_dimensions(row: dict) -> tuple[str, ...]:
    """Return conservative unit dimensions implied by the indicator name."""
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    if not indicator:
        return ()
    ratio_scope_modifier = bool(re.search(
        r"(?:비율|비중|점유율|구성비)(?:별|구간별|에따른).*(?:금액|수출액|수입액|매출액|예산액|투자액|생산액|판매액|가격|판매가)$",
        indicator,
    ))
    rate_indicator = (
        indicator.endswith(("률", "율"))
        or any(token in indicator for token in ("비율", "비중", "점유율", "구성비"))
    ) and "환율" not in indicator and not ratio_scope_modifier
    if rate_indicator:
        return ("rate",)
    if any(token in indicator for token in (
        "인원", "인구", "근로자수", "취업자수", "이용객수",
    )):
        return ("person_count", "count")
    if any(token in indicator for token in (
        "대수", "건수", "업체수", "기업수", "품목수",
    )):
        return ("count", "person_count")
    if any(token in indicator for token in (
        "금액", "수출액", "수입액", "매출액", "예산액", "투자액",
        "생산액", "판매액", "가격", "판매가",
    )):
        return ("currency",)
    return ()


def semantic_query_fallback_eligible(row: dict, dimension: str) -> bool:
    """Whether claim text can safely replace a missing retrieval indicator.

    This does not invent an indicator label. It only lets BGE-M3 use the claim
    sentence after the strict usage, scope, binding, value, period, and unit
    checks earlier in ``exclusion`` have passed.
    """
    text = nz(row.get("claim_text"))
    return bool(
        len(text) >= 8
        and parse_number(row.get("value")) is not None
        and dimension != "unknown"
        and measurement_value(row, "measurement_period", "period")
        and measurement_value(row, "measurement_prd_se", "prd_se")
    )


def derived_trade_balance(row: dict, dimension: str) -> bool:
    """Detect a trade surplus/deficit that requires export minus import."""
    if dimension != "currency":
        return False
    domain = re.sub(r"\s+", "", nz(row.get("metric_domain")))
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    return "무역" in domain and any(token in indicator for token in ("흑자", "적자", "수지"))


def declared_company_aggregate(row: dict) -> bool:
    """Detect an aggregate explicitly reported by a finite company group."""
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    if not any(token in indicator for token in ("판매", "매출", "생산", "수출", "실적")):
        return False
    context = " ".join(
        nz(row.get(field)) for field in ("title", "prev_sentence", "claim_text")
    )
    return bool(
        re.search(r"(?<!\d)\d+\s*사(?:\b|\s|\()", context)
        and any(token in context for token in ("밝혔", "발표", "자체 집계"))
    )


def capital_market_valuation(row: dict) -> bool:
    """Detect IPO/listing valuation metrics outside official KOSIS observations."""
    domain = re.sub(r"\s+", "", nz(row.get("metric_domain")))
    indicator = re.sub(
        r"\s+", "", measurement_value(row, "measurement_indicator", "indicator")
    )
    if "금융" not in domain or "할인율" not in indicator:
        return False
    context = " ".join(
        nz(row.get(field)) for field in ("title", "prev_sentence", "claim_text", "next_sentence")
    )
    return any(token in context for token in ("상장", "공모가", "시가총액", "시총", "밴드"))


def unit_dimension(unit: str) -> str:
    value = canonicalize_unit(unit)
    if not value:
        return "unknown"
    if value in {"%", "%p"}:
        return "rate"
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
    indicator = measurement_value(row, "measurement_indicator", "indicator")
    compact = re.sub(r"\s+", "", indicator)

    if value_type == "순위" or dimension == "rank":
        return "rank"
    if canonical_measurement_unit(row) == "%p":
        return "absolute_change"
    if value_type == "증감률" or role == "증감률" or any(
        token in compact for token in ("증감률", "증가율", "감소율", "상승률", "하락률")
    ):
        return "rate_change"
    if value_type in {"비율", "구성비"} or any(
        token in compact for token in ("비율", "구성비", "점유율")
    ):
        return "rate_level"
    if compact.endswith(("률", "율")) and "환율" not in compact:
        return "rate_level"
    if value_type == "증감량" or any(token in compact for token in (
        "증감량", "증감액", "증감폭", "증가량", "감소량", "증가액", "감소액",
        "증가폭", "감소폭", "상승폭", "하락폭", "변화폭", "차액",
    )) or compact.endswith("증감"):
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
    indicator = measurement_value(row, "measurement_indicator", "indicator")
    item = measurement_value(row, "measurement_item", "industry_or_item")
    text = " ".join((item, nz(row.get("claim_text"))))
    if any(token in indicator for token in ("정비사", "근로자", "취업자", "인구", "사람", "여객", "이용객")):
        return "person"
    if any(token in indicator for token in ("항공사", "기업", "업체", "회사")):
        return "organization"
    if any(token in text for token in ("가구", "세대")):
        return "household"
    if any(token in text for token in ("자동차", "차량", "선박", "항공기")):
        return "vehicle"
    if item:
        return "item"
    return "unspecified"


EXPLICIT_COMPARISON_PATTERNS = (
    r"((?:19|20)\d{2})\s*년\s*(?:[^。.!?\n]{0,18})?(?:기록|수준|실적|최고|최대|기준|값)",
    r"(?:기록|수준|실적|최고|최대|기준|값)\s*\(?\s*((?:19|20)\d{2})\s*년",
    r"((?:19|20)\d{2})\s*년\s*(?:보다|대비|에\s*비해|과\s*비교|를\s*웃|을\s*웃|를\s*밑|을\s*밑)",
    r"(?:기준|비교)\s*(?:시점|연도)?\s*((?:19|20)\d{2})\s*년",
)


def explicit_comparison_period(row: dict, target_value: str = "") -> str:
    text = nz(row.get("claim_text"))
    for pattern in EXPLICIT_COMPARISON_PATTERNS:
        for match in re.finditer(pattern, text):
            value = match.group(1)
            if value and value != target_value:
                return value
    return ""


def comparison_period(row: dict, semantic: str) -> str:
    if semantic not in {"rate_change", "absolute_change"}:
        return ""
    target = nz(row.get("measurement_period"))
    target_match = re.search(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])?", target)
    target_value = target_match.group() if target_match else ""

    # 명시 비교연도는 change_base/default 추론보다 항상 우선한다.
    explicit = explicit_comparison_period(row, target_value)
    if explicit:
        return explicit

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


def measurement_is_first_endpoint_level(row: dict) -> bool:
    """Return whether this measurement is the first level in an A-to-B phrase.

    HCX sometimes labels both endpoint levels as ``증감률``.  For example,
    ``2022년 1.5%에서 2023년 4.4%로 증가`` contains two directly observed
    rate levels; the first one must keep 2022 instead of being rebound to the
    claim-level target year 2023.
    """
    value = nz(row.get("value"))
    unit = nz(row.get("unit")) or nz(row.get("raw_unit"))
    text = nz(row.get("claim_text"))
    if not value or not unit or not text:
        return False
    token = rf"(?<![0-9.]){re.escape(value)}\s*{re.escape(unit)}"
    return bool(re.search(token + r"\s*(?:에서|부터)", text))


def endpoint_level_semantic(dimension: str, row: dict | None = None) -> str:
    if dimension == "rate":
        indicator = measurement_value(
            row or {}, "measurement_indicator", "indicator"
        )
        # A rate can itself be a published change statistic.  Comparing
        # 2024's export growth rate with 2025's forecast does not turn the
        # former into a share/level.  Only ratio/share indicators are
        # reclassified as rate levels.
        if re.search(r"(?:증가|감소|증감|상승|하락|등락|변동)[률율]", indicator):
            return "rate_change"
        return "rate_level"
    return {
        "currency": "amount",
        "person_count": "count",
        "count": "count",
        "multiple": "multiple",
        "quantity": "quantity",
    }.get(dimension, "level")


def align_change_period(row: dict) -> tuple[str, str]:
    """Correct a change measurement that was bound to its comparison period."""
    measurement_period = canonicalize_period(
        measurement_value(row, "measurement_period", "period"),
        measurement_value(row, "measurement_prd_se", "prd_se"),
    )
    claim_period = canonicalize_period(
        claim_value(row, "claim_period", "period"),
        claim_value(row, "claim_prd_se", "prd_se"),
    )
    role = nz(row.get("measurement_role"))
    if role not in {"증감률", "증감값"} or not claim_period:
        return measurement_period, ""
    if measurement_period != claim_period and measurement_is_first_endpoint_level(row):
        return measurement_period, "MEASUREMENT_ENDPOINT_PERIOD_PRESERVED"
    # ``recover_relative_measurement_period`` binds the number to a relative
    # month in the same local phrase (for example, ``지난달 ... -0.1%``).
    # That recovered month is the observation target, even when it happens to
    # equal the comparison month implied by an article-level claim period.
    # Rebinding it to ``claim_period`` used to shift April producer-price
    # changes into May and compare May against April.
    relative_binding = nz(row.get("_relative_measurement_period_status"))
    if measurement_period != claim_period and relative_binding in {
        "PREVIOUS_MONTH_FROM_ARTICLE_DATE",
        "PREVIOUS_MONTH_FROM_ARTICLE_TITLE",
        "RELATIVE_YEAR_MONTH_FROM_ARTICLE_DATE",
        "ONE_MONTH_BEFORE_CLAIM_PERIOD",
    }:
        return measurement_period, "RELATIVE_MEASUREMENT_PERIOD_PRESERVED"
    base_period = expected_base_period(claim_period, row.get("change_base"))
    if base_period and measurement_period == base_period:
        return claim_period, "COMPARISON_PERIOD_TO_TARGET"
    explicit = explicit_comparison_period(row, claim_period)
    if explicit and measurement_period == explicit:
        return claim_period, "EXPLICIT_COMPARISON_PERIOD_TO_TARGET"
    return measurement_period, ""


_CONTEXTUAL_QUANTIFIER = re.compile(
    r"(?:상위|하위)\s*(\d+(?:\.\d+)?)\s*(대|개|명)\s*[0-9A-Za-z가-힣]"
)


def contextual_quantifier(row: dict) -> bool:
    """Whether the extracted number sizes a cohort instead of observing it."""
    measurement = re.sub(r"\s+", "", nz(row.get("measurement_text")))
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(대|개|명)", measurement)
    if not match:
        return False
    return any(
        found.group(1) == match.group(1) and found.group(2) == match.group(2)
        for found in _CONTEXTUAL_QUANTIFIER.finditer(nz(row.get("claim_text")))
    )


_AGE_DECADE = re.compile(r"(?:10|20|30|40|50|60|70|80|90)대")


def demographic_label_measurement(row: dict) -> bool:
    """Detect an age-band label mis-extracted as a count with unit ``대``."""
    measurement = re.sub(r"\s+", "", nz(row.get("measurement_text")))
    item = re.sub(r"\s+", "", measurement_value(row, "measurement_item", "industry_or_item"))
    if not _AGE_DECADE.fullmatch(measurement) or item != measurement:
        return False
    text = nz(row.get("claim_text"))
    age_tokens = _AGE_DECADE.findall(text)
    return bool(
        len(set(age_tokens)) >= 2
        or "연령대" in text
        or "연령별" in text
        or re.search(rf"{re.escape(measurement)}\s*(?:가|는|에서|의|에게)", text)
    )


_BENIGN_BATCH_REVIEW_PREFIXES = {
    "measurement_binding_fallback",
    "measurement_period_ungrounded",
}
_DIRECT_OBSERVED_ROLES = {"현재값", "수준값", "관측값", "직접값"}


def measurement_review_override(row: dict, period_repair_statuses) -> str:
    """Release a direct row from a review flag caused only by sibling rows.

    ``extract_hcx`` records fallback counts at the response-batch level.  One
    fallback condition/previous-value row therefore marks every otherwise
    independent measurement as ``needs_review=Y``.  A row is safe to release
    only when HCX itself bound a high-confidence direct current value and any
    removed period was recovered from explicit article evidence.  This does
    not release rule/claim fallbacks, previous values, missing periods, or an
    unknown review reason.
    """
    if nz(row.get("needs_review")).upper() != "Y":
        return ""
    if nz(row.get("measurement_binding_source")) != "hcx":
        return ""
    if nz(row.get("measurement_role")) not in _DIRECT_OBSERVED_ROLES:
        return ""
    if nz(row.get("extraction_confidence")).lower() != "high":
        return ""
    parts = [value.strip() for value in nz(row.get("review_reason")).split(";") if value.strip()]
    if not parts:
        return ""
    prefixes = {value.split(":", 1)[0] for value in parts}
    if not prefixes <= _BENIGN_BATCH_REVIEW_PREFIXES:
        return ""
    if "measurement_period_ungrounded" in prefixes and not any(period_repair_statuses):
        return ""
    return "DIRECT_ROW_CONFIRMED_DESPITE_BATCH_REVIEW"


def exclusion(row: dict, dimension: str, semantic: str):
    measurement_id = nz(row.get("claim_measurement_id"))
    if not measurement_id:
        return "NO_MEASUREMENT", "측정값 없는 placeholder"
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
    if demographic_label_measurement(row):
        return "DEMOGRAPHIC_LABEL_NOT_VALUE", (
            f"measurement_text={nz(row.get('measurement_text'))} 는 연령 구간 라벨이며 수량이 아님"
        )
    if parse_number(row.get("value")) is None:
        return "VALUE_MISSING", "value가 숫자가 아님"
    if not measurement_value(row, "measurement_indicator", "indicator"):
        return "INDICATOR_MISSING", "measurement indicator 없음"
    if not measurement_value(row, "measurement_period", "period"):
        return "PERIOD_MISSING", "measurement period 없음"
    if not measurement_value(row, "measurement_prd_se", "prd_se"):
        return "PERIODICITY_MISSING", "measurement prd_se 없음"
    if daily_market_measurement(row):
        return "DAILY_MARKET_RATE", "특정일 시장값은 KOSIS 월·분기 평균과 직접 비교할 수 없음"
    if market_point_measurement(row):
        return "MARKET_POINT_VALUE", "시장 임계값·종가·고저점은 KOSIS 기간 평균과 직접 비교할 수 없음"
    period = canonicalize_period(
        measurement_value(row, "measurement_period", "period"),
        measurement_value(row, "measurement_prd_se", "prd_se"),
    )
    if (
        measurement_value(row, "measurement_prd_se", "prd_se").upper() == "M"
        and not re.fullmatch(r"(?:19|20)\d{4}", period)
    ):
        return "MONTHLY_PERIOD_INCOMPLETE", "월간 measurement의 월을 확정할 수 없음"
    if dimension == "unknown":
        return "UNIT_UNSUPPORTED", f"표준화할 수 없는 unit={nz(row.get('unit')) or '-'}"
    unit_conflict = indicator_unit_conflict(row, dimension)
    if unit_conflict:
        return "INDICATOR_UNIT_CONFLICT", unit_conflict
    if semantic in {"rate_change", "rate_level"} and dimension != "rate":
        return "VALUE_TYPE_UNIT_CONFLICT", f"semantic_type={semantic}, unit_dimension={dimension}"
    if individual_product_price(row, dimension):
        return "INDIVIDUAL_PRODUCT_PRICE", "개별 상품의 비평균 소매가격은 KOSIS 품목 통계 직접값이 아님"
    if converted_currency_measurement(row, dimension):
        return "CONVERTED_CURRENCY_VALUE", "다른 통화의 공표값을 근사 환산한 값은 KOSIS 직접값이 아님"
    if contextual_denominator(row, dimension):
        return "CONTEXTUAL_QUANTIFIER", "평균·비율 계산의 조사 집단 크기는 관측 지표값이 아님"
    if derived_trade_balance(row, dimension):
        return "DERIVED_TRADE_BALANCE", "무역 흑자·적자는 수출액과 수입액의 차이로 계산하는 파생값"
    if declared_company_aggregate(row):
        return "DECLARED_COMPANY_AGGREGATE", "유한한 기업 집단이 자체 발표한 실적 합계는 KOSIS 직접값이 아님"
    if capital_market_valuation(row):
        return "CAPITAL_MARKET_VALUATION", "상장·공모 가치평가 할인율은 KOSIS 공식 통계 관측값이 아님"
    if contextual_quantifier(row):
        return "CONTEXTUAL_QUANTIFIER", "상위/하위 집단 크기는 관측값이 아니라 조건값"
    # 증감률·증감량은 두 시점의 수준값으로 계산한 파생값일 수 있다. 선택된 KOSIS
    # ITEM이 직접 공표한 값인지 확인되기 전에는 원자료 직접대조 READY로 보내지 않는다.
    if semantic in {"rate_change", "absolute_change"}:
        return "DERIVED_VALUE_REQUIRES_COMPUTATION", "증감값은 직접 공표 ITEM 확인 또는 수준값 재계산 필요"
    if semantic == "rank":
        return "RANK_NOT_DIRECTLY_COMPARABLE", "순위는 KOSIS 원자료와 직접 비교하지 않음"
    # 값을 비교하기 **전에** 주장의 모양을 본다.
    # 홀드아웃 50건에서 확정 4건이 전부 '불일치' 였고 넷 다 오판이었다 —
    # 분기를 연간으로, 1~11월 누적을 12개월과, 구성비를 수준값 좌표와 대조했다.
    # 차이가 6.1%p~34.5%p 라 extreme_error 문턱(100%p/300%)에 안 걸린다.
    shape_code, shape_reason = claim_shape_exclusion(row, dimension, semantic)
    if shape_code:
        return shape_code, shape_reason
    if (
        nz(row.get("needs_review")).upper() == "Y"
        and not nz(row.get("_measurement_review_override"))
    ):
        return "MEASUREMENT_REVIEW_REQUIRED", (
            f"추출기가 검토 필요로 표시: {nz(row.get('review_reason')) or '사유 미기재'}"
        )
    return "", ""


ENRICHMENT_ACTIONS = {
    "NO_MEASUREMENT": "REEXTRACT_MEASUREMENT",
    "BINDING_NOT_CONFIRMED": "CONFIRM_MEASUREMENT_BINDING",
    "ROLE_NOT_DIRECT_TARGET": "CONFIRM_DIRECT_TARGET_ROLE",
    "VALUE_MISSING": "REEXTRACT_VALUE",
    "INDICATOR_MISSING": "REEXTRACT_INDICATOR",
    "PERIOD_MISSING": "RESOLVE_PERIOD_FROM_CONTEXT",
    "PERIODICITY_MISSING": "RESOLVE_PERIODICITY",
    "MONTHLY_PERIOD_INCOMPLETE": "RESOLVE_MONTH_FROM_CONTEXT",
    "UNIT_UNSUPPORTED": "NORMALIZE_UNIT",
    "VALUE_TYPE_UNIT_CONFLICT": "REPAIR_VALUE_TYPE_OR_UNIT",
    "INDICATOR_UNIT_CONFLICT": "REPAIR_INDICATOR_OR_UNIT",
    "DERIVED_VALUE_REQUIRES_COMPUTATION": "VERIFY_DIRECT_RATE_ITEM_OR_COMPUTE_FROM_LEVELS",
    "CONTEXTUAL_QUANTIFIER": "REEXTRACT_MEASUREMENT",
    "MEASUREMENT_REVIEW_REQUIRED": "REVIEW_MEASUREMENT_EXTRACTION",
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
    if code == "RANK_NOT_DIRECTLY_COMPARABLE":
        return "REJECT", ""
    if code == "TARGET_VALUE_NOT_OBSERVED":
        return "REJECT", ""
    action = ENRICHMENT_ACTIONS.get(code)
    if action:
        return "ENRICH", action
    return "REJECT", ""


def normalize_row(row: dict) -> dict:
    out = dict(row)
    out["mapping_type"] = normalize_mapping_type(row.get("mapping_type"))
    repaired_row, contract_statuses = repair_extracted_contract(row)
    raw_unit = (
        nz(row.get("raw_unit")) if "raw_unit" in row else nz(row.get("unit"))
    )
    canonical_unit = canonical_measurement_unit(repaired_row)
    dimension = unit_dimension(canonical_unit)
    relative_period, relative_status = recover_relative_measurement_period(repaired_row)
    recovery_row = dict(repaired_row)
    if "measurement_period" in repaired_row:
        recovery_row["measurement_period"] = relative_period
    else:
        recovery_row["period"] = relative_period
    recovered_period, recovery_status = recover_single_month_period(recovery_row)
    contextual_row = dict(recovery_row)
    if "measurement_period" in repaired_row:
        contextual_row["measurement_period"] = recovered_period
    else:
        contextual_row["period"] = recovered_period
    contextual_period, contextual_status = recover_contextual_title_month(contextual_row)
    contract_row = dict(contextual_row)
    if "measurement_period" in repaired_row:
        contract_row["measurement_period"] = contextual_period
    else:
        contract_row["period"] = contextual_period
    if contextual_status:
        contextual_prd_se = claim_value(repaired_row, "claim_prd_se", "prd_se")
        if "measurement_prd_se" in repaired_row:
            contract_row["measurement_prd_se"] = contextual_prd_se
        else:
            contract_row["prd_se"] = contextual_prd_se
    contract_row["unit"] = canonical_unit
    contract_row["_relative_measurement_period_status"] = relative_status
    review_override = measurement_review_override(
        contract_row,
        (*contract_statuses, relative_status, recovery_status, contextual_status),
    )
    contract_row["_measurement_review_override"] = review_override
    semantic = semantic_type(contract_row, dimension)
    endpoint_level = measurement_is_first_endpoint_level(contract_row)
    if endpoint_level:
        # HCX may label an endpoint rate/count as a change.  Treat the
        # explicitly observed endpoint as a direct level so no synthetic
        # comparison period or derived computation is created downstream.
        semantic = endpoint_level_semantic(dimension, contract_row)
        # This is a directly stated endpoint level, not a share that must be
        # derived from a numerator and denominator.  The private flag is used
        # only by the claim-shape gate and is not emitted to the output CSV.
        contract_row["_direct_endpoint_level"] = "Y"
    code, reason = exclusion(contract_row, dimension, semantic)
    deferred_code = ""
    deferred_reason = ""
    indicator_fallback_source = ""
    unit_hypotheses = [dimension] if dimension != "unknown" else []
    derived_computation_required = "N"

    if code == "INDICATOR_MISSING" and semantic_query_fallback_eligible(
        contract_row, dimension
    ):
        deferred_code, deferred_reason = code, reason
        indicator_fallback_source = "claim_text"
        code, reason = "", ""
    elif code == "INDICATOR_UNIT_CONFLICT":
        # A published level indicator (for example, an index or headcount)
        # legitimately conflicts with a claim expressed as its change rate or
        # difference.  When both periods are grounded, retrieve the level ITEM
        # and derive the claim instead of freezing the row as a direct mapping.
        if individual_product_price(contract_row, dimension):
            code = "INDIVIDUAL_PRODUCT_PRICE"
            reason = "개별 상품의 비평균 소매가격은 KOSIS 품목 통계 직접값이 아님"
        elif (
            semantic in {"rate_change", "absolute_change"}
            and comparison_period(contract_row, semantic)
        ):
            deferred_code = "DERIVED_VALUE_REQUIRES_COMPUTATION"
            deferred_reason = (
                "지표 수준값의 두 시점에서 기사 증감값을 계산해야 함: " + reason
            )
            derived_computation_required = "Y"
            code, reason = "", ""
        else:
            expected_dimensions = indicator_unit_dimensions(contract_row)
            if expected_dimensions:
                deferred_code, deferred_reason = code, reason
                unit_hypotheses.extend(expected_dimensions)
                code, reason = "", ""
    elif code == "DERIVED_VALUE_REQUIRES_COMPUTATION":
        if comparison_period(contract_row, semantic):
            deferred_code, deferred_reason = code, reason
            derived_computation_required = "Y"
            code, reason = "", ""

    # Preserve claim-level fields while exposing the aliases expected by the
    # feature/model matcher.  The aliases are always measurement-level values.
    out["claim_indicator"] = claim_value(repaired_row, "claim_indicator", "indicator")
    out["claim_industry_or_item"] = claim_value(
        repaired_row, "claim_industry_or_item", "industry_or_item"
    )
    out["claim_period"] = claim_value(repaired_row, "claim_period", "period")
    out["claim_prd_se"] = claim_value(repaired_row, "claim_prd_se", "prd_se")
    out["raw_measurement_period"] = measurement_value(
        row, "measurement_period", "period"
    )
    out["indicator"] = measurement_value(repaired_row, "measurement_indicator", "indicator")
    out["obj_target_terms"] = merge_obj_target_terms(
        repaired_row.get("obj_target_terms"),
        (*explicit_employee_size_targets(repaired_row), *explicit_obj_targets(repaired_row)),
    )
    out["age_group"] = grounded_demographic_value(repaired_row, "age_group")
    out["gender"] = grounded_demographic_value(repaired_row, "gender")
    # 문장에도 지표에도 근거가 없는 대상은 이 measurement 의 것이 아니다.
    # 막지 않고 **지운다** — 그러면 대상 없는 주장이 되어 집계 좌표를 찾게 되고,
    # 그것이 문장이 실제로 말하는 바다.
    # (실측: '전체 수출액 6838억달러' + 대상='반도체' → 지우면 총액 좌표로 일치)
    out["industry_or_item"] = measurement_value(
        repaired_row, "measurement_item", "industry_or_item"
    )
    previously_dropped_item = (
        nz(row.get("dropped_item")) if nz(row.get("item_ungrounded")) == "Y" else ""
    )
    out["item_ungrounded"] = "Y" if previously_dropped_item else "N"
    out["dropped_item"] = previously_dropped_item
    if out["industry_or_item"] and not claim_item_grounded(repaired_row):
        out["item_ungrounded"] = "Y"
        out["dropped_item"] = out["industry_or_item"]
        out["industry_or_item"] = ""
        # measurement_item 도 함께 지워야 한다. claim_item_grounded 는 그쪽을 **먼저** 읽는다:
        #     raw = nz(row.get("measurement_item")) or nz(row.get("industry_or_item"))
        # 한쪽만 지우면 하류 게이트가 여전히 옛 값을 보고 막는다.
        # 2026-08-04 실측: 이것 때문에 확정 3건을 잃었다
        # ('전체 수출액 6838억' 이 UNGROUNDED_CLAIM_ITEM 으로 재차단됨).
        out["measurement_item"] = ""
    out["prd_se"] = measurement_value(repaired_row, "measurement_prd_se", "prd_se")
    if contextual_status and not out["prd_se"]:
        out["prd_se"] = claim_value(repaired_row, "claim_prd_se", "prd_se")
    out["period"], change_alignment_status = align_change_period(contract_row)
    out["period_alignment_status"] = "|".join(
        value for value in (
            *contract_statuses,
            relative_status,
            recovery_status,
            contextual_status,
            change_alignment_status,
        ) if value
    )
    # 누적 기간('1~11월')은 월 자료를 합산하면 답할 수 있다.
    # 연간 좌표로 물어보면 빠진 개월 수만큼 어긋난다 —
    # 실측: 반도체 수출 1~11월 1274억을 12개월치 1420억과 대조해 '불일치'가 났다.
    out["period_span_start"] = ""
    out["period_span_end"] = ""
    out["period_aggregation"] = ""
    span = cumulative_is_answerable({**contract_row, "measurement_period": out["period"]})
    if span:
        out["period_span_start"], out["period_span_end"] = span
        out["prd_se"] = "M"
        out["period"] = span[1]
        out["period_aggregation"] = "sum"
    else:
        # 분기는 빼지 않고 **변환**한다. KOSIS 분기 PRD_DE 는 '202202' 형식이다
        # (실측 DT_1K41012). 연간으로 물어보면 '2022년 2분기 -0.2%' 를
        # 2022년 연간 +5.88% 와 대조해 거짓 불일치가 난다.
        quarter = quarter_period(repaired_row.get("claim_text"), out["period"])
        if quarter:
            out["prd_se"] = "Q"
            out["period"] = quarter
        else:
            out["period_aggregation"] = infer_annual_period_aggregation(
                contract_row, out["period"], out["prd_se"]
            )
    out["raw_unit"] = raw_unit
    out["canonical_unit"] = canonical_unit
    out["unit"] = canonical_unit
    out["unit_dimension"] = dimension
    out["semantic_type"] = semantic
    out["entity_type"] = entity_type(repaired_row)
    out["value_type"] = nz(contract_row.get("value_type"))
    out["measurement_role"] = nz(contract_row.get("measurement_role"))
    out["change_base"] = nz(contract_row.get("change_base"))
    comparison_row = dict(repaired_row)
    comparison_row["measurement_period"] = out["period"]
    comparison_row["measurement_prd_se"] = out["prd_se"]
    out["comparison_period"] = comparison_period(comparison_row, semantic)
    out["retrieval_fallback_code"] = deferred_code
    out["retrieval_fallback_reason"] = deferred_reason
    out["indicator_fallback_source"] = indicator_fallback_source
    out["unit_dimension_hypotheses"] = "|".join(dict.fromkeys(unit_hypotheses))
    out["derived_computation_required"] = derived_computation_required
    out["verification_review_required"] = (
        "Y" if deferred_code in {"INDICATOR_MISSING", "INDICATOR_UNIT_CONFLICT"} else "N"
    )
    out["verification_review_reason"] = {
        "INDICATOR_MISSING": "INDICATOR_FALLBACK_REVIEW_REQUIRED",
        "INDICATOR_UNIT_CONFLICT": "UNIT_HYPOTHESIS_REVIEW_REQUIRED",
    }.get(deferred_code, "")
    out["measurement_review_override"] = review_override
    out["allowed_mapping_types"] = ""
    if derived_computation_required == "Y":
        out["mapping_type"] = ""
        out["allowed_mapping_types"] = (
            "direct|rate_from_level"
            if semantic == "rate_change"
            else "direct|difference_from_level"
        )
    elif deferred_code == "INDICATOR_UNIT_CONFLICT":
        out["allowed_mapping_types"] = "direct"
    # 내용 기반 범위 판정 — HCX 자기 신고 라벨(measurement_usage/claim_domain_scope)만
    # 믿으면 비트코인 시세나 개별 브랜드 판매가도 그대로 통과한다(실측 확인).
    scope = gate_decision({**repaired_row, "unit": out["unit"]})
    out.update(scope)
    scope_review_only = False
    if scope["scope_gate_blocked"] == "Y" and (
        not code or code in ENRICHMENT_ACTIONS
    ):
        code = scope["scope_gate_code"]
        reason = scope["scope_gate_reason"]
    elif not code and scope.get("scope_gate_severity") == "REVIEW":
        code = scope["scope_gate_code"] or "KOSIS_SCOPE_REVIEW"
        reason = scope["scope_gate_reason"] or "KOSIS 수록 범위 확인 필요"
        scope_review_only = True

    out["mapping_eligible"] = "Y" if not code else "N"
    out["in_ready"] = out["mapping_eligible"]
    out["mapping_exclusion_code"] = code
    out["mapping_exclusion_reason"] = reason
    if scope["scope_gate_blocked"] == "Y":
        out["mapping_gate"] = "REJECT"
        out["mapping_gate_reason"] = code
        out["enrichment_actions"] = ""
    elif scope_review_only:
        out["mapping_gate"] = "ENRICH"
        out["mapping_gate_reason"] = code
        out["enrichment_actions"] = "CONFIRM_KOSIS_SCOPE"
    else:
        gate, action = mapping_gate(repaired_row, code)
        out["mapping_gate"] = gate
        out["mapping_gate_reason"] = code or "ELIGIBLE"
        out["enrichment_actions"] = action
    return out


DERIVED_FIELDS = [
    "mapping_type",
    "claim_indicator",
    "claim_industry_or_item",
    "obj_target_terms",
    # 근거 없는 대상을 지웠는지, 무엇을 지웠는지 남긴다(추적용)
    "item_ungrounded",
    "dropped_item",
    "claim_period",
    "claim_prd_se",
    # 누적 기간을 월 합산으로 답할 때 쓰는 구간 (비면 단일 기간)
    "period_span_start",
    "period_span_end",
    "period_aggregation",
    "raw_measurement_period",
    "period_alignment_status",
    "raw_unit",
    "canonical_unit",
    "unit_dimension",
    "semantic_type",
    "entity_type",
    "comparison_period",
    "retrieval_fallback_code",
    "retrieval_fallback_reason",
    "indicator_fallback_source",
    "unit_dimension_hypotheses",
    "derived_computation_required",
    "verification_review_required",
    "verification_review_reason",
    "measurement_review_override",
    "allowed_mapping_types",
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


def apply_article_scope(rows) -> int:
    """출처 귀속 판정을 기사 단위로 전파한다. **여기서 해야 한다.**

    2026-08-04: 깨끗한 재실행에서 드러난 버그.
    전파는 lock_evaluation_set 에만 있었는데, prepare 가 먼저 게이트를 돌려
    **출처를 밝힌 문장을 이미 제거**하기 때문에 lock 은 전파할 출처를 찾지 못한다.
    그래서 '정부의 연간 누적 대출'(한은 제출자료) 같은 후속 문장이 살아남아
    확정까지 가고 '불일치'로 판정됐다 — 범위 밖 주장에 거짓 딱지를 붙인 것이다.

    lock 에도 전파가 남아 있지만 그때는 이미 걸러진 뒤라 무해하다(중복 안전).
    """
    decisions = propagate_by_article(rows)
    changed = 0
    for row, decision in zip(rows, decisions):
        if decision["scope_gate_blocked"] != "Y" or row.get("scope_gate_blocked") == "Y":
            continue
        row.update(decision)
        row["mapping_gate"] = "REJECT"
        row["mapping_gate_reason"] = decision["scope_gate_code"]
        row["mapping_exclusion_code"] = decision["scope_gate_code"]
        row["mapping_exclusion_reason"] = decision["scope_gate_reason"]
        row["mapping_eligible"] = "N"
        row["in_ready"] = "N"
        row["enrichment_actions"] = ""
        changed += 1
    return changed


def apply_orphan_scope(rows) -> int:
    """기사의 다른 측정 문장이 **전부** 범위 밖이고, 남은 문장이 자기 주어가 없으면 뺀다.

    2026-08-04 실측. CES 기사(A0005)에서 네 문장 중 셋이 OUT_OF_KOSIS_SCOPE 로
    거부됐는데 '분야는 생활가전(18%)...' 이 살아남아 평가 집합 88건에 들어와 있었다.
    CES 전시 분야 비중은 미국 CTA 주최 행사 자료라 KOSIS 에 있을 수 없다.

    조건을 셋 다 걸어야 안전하다.
      1. 그 기사에서 거부된 측정 문장이 **하나도 빠짐없이** 범위 코드일 것
      2. 살아남은 문장이 **모두** 앞 문장을 가리키는 말로 시작할 것
      3. 자체 출처가 없을 것 (있으면 그 문장의 출처다 — 로봇산업진흥원 전례)

    전수 측정: 88건 중 4건 제거, **확정 16건은 하나도 안 빠진다.**
    조건을 하나라도 빼면 정당한 문장이 죽는다. 넓히기 전에 다시 측정할 것.
    """
    by_article: dict[str, list] = {}
    for row in rows:
        article = nz(row.get("article_id"))
        if article:
            by_article.setdefault(article, []).append(row)

    changed = 0
    for article, group in by_article.items():
        rejected = [r for r in group if r.get("mapping_eligible") == "N"]
        alive = [r for r in group if r.get("mapping_eligible") != "N"]
        if not rejected or not alive:
            continue
        if any(nz(r.get("mapping_exclusion_code")) not in ARTICLE_SCOPE_CODES
               for r in rejected):
            continue
        if not all(starts_with_anaphor(r.get("claim_text"))
                   and not has_own_source(nz(r.get("claim_text"))) for r in alive):
            continue
        for row in alive:
            row["mapping_gate"] = "REJECT"
            row["mapping_gate_reason"] = "ORPHAN_IN_OUT_OF_SCOPE_ARTICLE"
            row["mapping_exclusion_code"] = "ORPHAN_IN_OUT_OF_SCOPE_ARTICLE"
            row["mapping_exclusion_reason"] = (
                "같은 기사의 다른 측정 문장이 모두 범위 밖이고, "
                "이 문장은 주어가 앞 문장에 있어 단독으로 범위를 알 수 없다")
            row["mapping_eligible"] = "N"
            row["in_ready"] = "N"
            row["enrichment_actions"] = ""
            changed += 1
    return changed


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

    apply_article_scope(normalized)
    apply_orphan_scope(normalized)

    fields = list(dict.fromkeys(source_fields + DERIVED_FIELDS))
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
