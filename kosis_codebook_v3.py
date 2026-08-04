"""KOSIS codebook v3 candidate built from holdout2 P0 errors.

Version 2 remains frozen for reproducing the second independent evaluation.
This module intercepts only the confirmed P0 patterns and delegates every other
claim to v2 until the remaining holdout2 development rules are implemented.
"""

from __future__ import annotations

import re

import kosis_codebook_v2 as v2


CACHE_PATH = v2.CACHE_PATH
PRICE_SIGNAL_RE = re.compile(r"소비자\s*물가|물가\s*상승률|물가상승률")
PRIVATE_CAR_COMPANY_RE = re.compile(r"케이카|K\s*Car", re.IGNORECASE)
PRIVATE_RESULT_RE = re.compile(r"실적|ASP|평균\s*거래가격|판매\s*대수", re.IGNORECASE)


def _percent_values(text):
    values = []
    for raw in v2.v1.PERCENT_RE.findall(text):
        value = v2.v1.to_float(raw.replace("−", "-").replace("–", "-"))
        if value is not None and value not in values:
            values.append(value)
    return values


def is_ambiguous_price_history(text):
    months = set(v2.v1.MONTH_RE.findall(text))
    return PRICE_SIGNAL_RE.search(text) and len(months) >= 2 and len(_percent_values(text)) >= 2


def is_private_car_company_metric(context):
    return PRIVATE_CAR_COMPANY_RE.search(context) and PRIVATE_RESULT_RE.search(context)


def map_domestic_oil_price(row, text):
    if "석유류" not in text or "가격" not in text or "지난달" not in text:
        return None
    target = v2.extract_change_target(text)
    period = v2.infer_month(row, text)
    if target is None or not period:
        return None
    previous = str(int(period[:4]) - 1) + period[4:]
    return v2.v1.mapping(
        "101",
        "DT_1J22112",
        "T10",
        "T",
        "M",
        target,
        period,
        "CHANGE_RATE",
        obj2="B05",
        prev=previous,
        note="석유류 지수 전년동월비",
    )


def map_by_codebook(row):
    text = row.get("claim_text", "") or ""
    context = " ".join(
        str(row.get(field, "") or "")
        for field in ("title", "prev_sentence", "claim_text", "next_sentence")
    )

    if is_ambiguous_price_history(text):
        return None, ("정보 부족", "여러 월과 여러 물가 수치가 함께 있어 단일 검증 목표를 자동 확정하지 않음")
    if is_private_car_company_metric(context):
        return None, ("KOSIS 미제공", "개별 중고차 기업의 거래가격·판매 실적은 KOSIS 국가 소매판매지수와 정의가 다름")

    oil_config = map_domestic_oil_price(row, text)
    if oil_config:
        return oil_config, None
    return v2.map_by_codebook(row)


def read_cache():
    v2.CACHE_PATH = CACHE_PATH
    return v2.read_cache()


def verify(config, cache):
    v2.CACHE_PATH = CACHE_PATH
    return v2.verify(config, cache)
