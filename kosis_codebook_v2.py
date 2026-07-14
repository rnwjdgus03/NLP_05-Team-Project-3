"""High-precision KOSIS codebook v2 built from the first holdout audit.

The original holdout became development data once its errors were inspected.
This module keeps v1 behavior and adds reusable metric patterns without using
claim IDs. A fresh independent sample is required for the quality gate.
"""

from __future__ import annotations

import re

import expand_kosis_codebook as v1


CACHE_PATH = v1.CACHE_PATH

QUARTER_RE = re.compile(r"(?:(20\d{2})년\s*)?([1-4])\s*분기")
POINT_VALUE_RE = re.compile(r"([-+−–]?\d+(?:\.\d+)?)\s*%\s*(?:포인트|p)", re.IGNORECASE)
COMPARISON_VALUE_RE = re.compile(
    r"(?:전년\s*동월|전년|작년\s*동월|지난해\s*같은\s*달|1년\s*전|전월|전달|직전\s*분기)"
    r"\s*(?:대비|보다)?[^.%]{0,35}?([-+−–]?\d+(?:\.\d+)?)\s*%"
)
METRIC_VALUE_RE = re.compile(
    r"(?:소비자\s*물가|근원물가(?:지수)?|생활\s*물가|가공식품\s*물가(?:\s*상승률)?|"
    r"외식\s*라면\s*물가|휴대전화\s*요금|소매\s*판매(?:액)?(?:\s*지수)?|서비스업\s*생산)"
    r"[^.%]{0,45}?([-+−–]?\d+(?:\.\d+)?)\s*%"
)
RETAIL_REGION_RE = re.compile(
    r"서울|부산|대구|인천|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주|"
    r"경기(?:도|지역|권)|수도권"
)
POPULATION_REGION_CODES = {"서울": "11", "부산": "21", "대구": "22", "인천": "23", "광주": "24", "대전": "25", "울산": "26", "세종": "29"}


def _number(raw):
    return float(raw.replace("−", "-").replace("–", "-"))


def _signed(value, text, match_end):
    tail = text[match_end:match_end + 18]
    if value > 0 and re.search(r"감소|줄|하락|내림|떨어", tail):
        return -value
    return value


def extract_change_target(text, *, point=False):
    pattern = POINT_VALUE_RE if point else COMPARISON_VALUE_RE
    matches = list(pattern.finditer(text))
    if not matches and not point:
        matches = list(METRIC_VALUE_RE.finditer(text))
    if not matches:
        values = list(v1.PERCENT_RE.finditer(text))
        if len(values) != 1:
            return None
        match = values[0]
    else:
        match = matches[-1]
    value = _number(match.group(1))
    return _signed(value, text, match.end())


def infer_month(row, text):
    if "지난달" in text:
        date = v1.article_date(row)
        if date:
            year, month = v1.month_shift(date.year, date.month, -1)
            return f"{year:04d}{month:02d}"

    if re.search(r"전월|전달", text) and v1.MONTH_RE.search(row.get("title", "") or ""):
        probe = dict(row)
        probe["claim_text"] = row.get("title", "") or ""
        period = v1.infer_period(probe, "M")
        if period:
            return period

    probe = dict(row)
    probe["claim_text"] = text
    period = v1.infer_period(probe, "M")
    if period:
        return period

    context = f"{row.get('title', '')} {text}"
    probe["claim_text"] = context
    period = v1.infer_period(probe, "M")
    if period:
        return period

    date = v1.article_date(row)
    if date and re.search(r"전년\s*동월|전월\s*대비|전달보다", text):
        year, month = v1.month_shift(date.year, date.month, -1)
        return f"{year:04d}{month:02d}"
    return ""


def infer_quarter(row, text):
    match = QUARTER_RE.search(text)
    if not match:
        return ""
    date = v1.article_date(row)
    year = int(match.group(1)) if match.group(1) else (date.year if date else 0)
    if not year:
        return ""
    return f"{year:04d}{int(match.group(2)):02d}"


def previous_quarter(period, text):
    year, quarter = int(period[:4]), int(period[4:6])
    if re.search(r"직전\s*분기|전분기", text):
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    else:
        year -= 1
    return f"{year:04d}{quarter:02d}"


def map_price(row, text, context):
    if "수출물가지수" in text:
        target = extract_change_target(text)
        period = infer_month(row, text)
        if target is not None and period and re.search(r"전년\s*대비|전년\s*동월", text):
            return v1.mapping(
                "301", "DT_402Y014", "13102134642ACC_CD.*AA", "13103134642999", "M",
                target, period, "CHANGE_RATE", obj2="13102134642CRR_CTRT_CD.W",
                prev=str(int(period[:4]) - 1) + period[4:], note="원화기준 수출물가 총지수 전년동월비",
            )

    if re.search(r"근원물가(?:지수)?|식료품\s*및\s*에너지\s*제외", text):
        target = extract_change_target(text)
        period = infer_month(row, text)
        if target is not None and period:
            return v1.mapping("101", "DT_1J22042", "4", "T03", "M", target, period, "LEVEL", note="식료품및에너지제외지수 전년동월비")

    if re.search(r"물가\s*상승률", text) and re.search(r"20\d{2}년", text) and "지난달" not in text:
        target = extract_change_target(text) or v1.extract_single_percent(row)
        year_match = re.search(r"(20\d{2})년", text)
        if target is not None and year_match:
            period = year_match.group(1)
            return v1.mapping("101", "DT_1J22003", "T10", "T", "Y", target, period, "CHANGE_RATE", prev=str(int(period) - 1), note="전국 소비자물가 연간 증감률")

    target = extract_change_target(text)
    period = infer_month(row, text)
    if target is None or not period:
        return None

    if "휴대전화" in text and "요금" in text:
        prev = v1.previous_period(period, "M", text)
        return v1.mapping("101", "DT_1J22112", "T10", "T", "M", target, period, "CHANGE_RATE", obj2="E01H03102", prev=prev, note="휴대전화료 지수")
    if "외식" in text and "라면" in text:
        prev = str(int(period[:4]) - 1) + period[4:]
        return v1.mapping("101", "DT_1J22112", "T10", "T", "M", target, period, "CHANGE_RATE", obj2="F01K01126", prev=prev, note="라면(외식) 지수")
    if "가공식품" in text and "물가" in text:
        prev = str(int(period[:4]) - 1) + period[4:]
        return v1.mapping("101", "DT_1J22112", "T10", "T", "M", target, period, "CHANGE_RATE", obj2="B01", prev=prev, note="가공식품 지수")
    if "생활" in text and "물가" in text and re.search(r"전년\s*동월", text):
        return v1.mapping("101", "DT_1J22042", "1", "T03", "M", target, period, "LEVEL", note="생활물가지수 전년동월비")
    if re.search(r"소비자\s*물가", text) and re.search(r"전년\s*동월|작년\s*동월", text):
        return v1.mapping("101", "DT_1J22042", "0", "T03", "M", target, period, "LEVEL", note="소비자물가 총지수 전년동월비")
    return None


def map_employment(row, text):
    if "고용률" not in text or not v1.POINT_RE.search(text):
        return None
    if "취업자" in text:
        return None
    target = extract_change_target(text, point=True)
    period = infer_month(row, text)
    if target is None or not period:
        return None
    if re.search(r"65세\s*이상", text):
        age = "602"
    elif re.search(r"15\s*[~∼-]\s*29세|청년", text):
        age = "75"
    elif re.search(r"20대|20\s*[~∼-]\s*29세", text):
        age = "20"
    else:
        return None
    prev = v1.previous_period(period, "M", text)
    return v1.mapping("101", "DT_1DA7002S", age, "T90", "M", target, period, "POINT_CHANGE", prev=prev, note="연령별 고용률 시점 차이")


def map_trade(row, text):
    if not re.search(r"(?:^|\s)수출은\s*전년\s*동월\s*대비", text):
        return None
    if v1.FOREIGN_RE.search(text) or v1.TRADE_DETAIL_RE.search(text):
        return None
    target = extract_change_target(text)
    period = infer_month(row, text)
    if target is None or not period:
        return None
    prev = str(int(period[:4]) - 1) + period[4:]
    return v1.mapping("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "M", target, period, "CHANGE_RATE", prev=prev, note="통관 총수출 전년동월비")


def map_retail(row, text, context):
    target = extract_change_target(text)
    if target is None:
        return None

    if "서비스업" in text and "생산" in text and re.search(r"전월|전달", text):
        period = infer_month(row, text)
        if not period:
            return None
        prev = v1.previous_period(period, "M", text)
        return v1.mapping("101", "DT_1KC2020", "T", "T3", "M", target, period, "CHANGE_RATE", prev=prev, note="서비스업 계절조정 총지수 전월비")

    retail_signal = re.search(r"소매\s*판매(?:액)?(?:\s*지수)?", context)
    if not retail_signal:
        return None
    if v1.FOREIGN_RE.search(context) or RETAIL_REGION_RE.search(text) or re.search(r"제외한|제외하고", text):
        return None
    obj1 = "G31" if "음식료품" in text else "G0"
    quarter = infer_quarter(row, text)
    if quarter:
        prev = previous_quarter(quarter, text)
        item = "T3" if re.search(r"직전\s*분기|전분기", text) else "T2"
        return v1.mapping("101", "DT_1K41012", obj1, item, "Q", target, quarter, "CHANGE_RATE", prev=prev, note="소매판매 분기 증감률")
    period = infer_month(row, text)
    if period and re.search(r"전월|전달", text):
        prev = v1.previous_period(period, "M", text)
        return v1.mapping("101", "DT_1K41012", obj1, "T3", "M", target, period, "CHANGE_RATE", prev=prev, note="소매판매 계절조정 전월비")
    return None


def parse_korean_count(text):
    match = re.search(r"(\d+)만\s*(\d+)?\s*건", text)
    if not match:
        return None
    return int(match.group(1)) * 10000 + int(match.group(2) or 0)


def map_population(row, text, context):
    if re.search(r"혼인\s*건수와\s*출생아|혼인과\s*출생아", text) or "각각" in text:
        return None

    if re.search(r"전체\s*혼인\s*건수", text):
        target = parse_korean_count(text)
        period = v1.infer_period(row, "Y")
        if target is not None and period:
            return v1.mapping("101", "DT_1B8000F", "41", "T1", "Y", target, period, "LEVEL", note="전국 연간 혼인건수")

    metric = ""
    if "출생아" in text:
        metric = "birth"
    elif "혼인" in text or "결혼" in text:
        metric = "marriage"
    elif "혼인" in (row.get("prev_sentence", "") or ""):
        metric = "marriage"
    if not metric:
        return None

    target = extract_change_target(text)
    period = infer_month(row, text)
    if not period:
        period = infer_month(row, f"{row.get('title', '')} {row.get('prev_sentence', '')}")
    if target is None or not period or not re.search(r"지난해\s*같은\s*달|전년\s*동월|전년\s*같은\s*달", text):
        return None

    region = "00"
    for name, code in POPULATION_REGION_CODES.items():
        if name in text:
            region = code
            break
    table = "DT_1B81A01" if metric == "birth" else "DT_1B83A35"
    item = "T1" if metric == "birth" else "T3"
    prev = str(int(period[:4]) - 1) + period[4:]
    return v1.mapping("101", table, region, item, "M", target, period, "CHANGE_RATE", prev=prev, note="월별 인구동향 전년동월비")


def classify_v2_nonverifiable(row, text, context):
    if re.search(r"소매\s*판매", context) and v1.FOREIGN_RE.search(context):
        return "KOSIS 미제공", "대한민국 KOSIS 범위 밖의 해외 소매 통계"
    if re.search(r"소매\s*판매", text) and re.search(r"제외한|제외하고", text):
        return "정보 부족", "특정 품목 제외 합계를 현재 코드북에서 계산하지 않음"
    if "취업자" in text and "고용률" in text:
        return "정보 부족", "취업자 수와 고용률이 함께 있어 단일 자동 목표로 확정하지 않음"
    if re.search(r"혼인\s*건수와\s*출생아|혼인과\s*출생아", text):
        return "정보 부족", "혼인과 출생아 수치가 함께 있어 단일 자동 목표로 확정하지 않음"
    return None


def map_v2(row):
    text = row.get("claim_text", "") or ""
    context = " ".join(str(row.get(field, "") or "") for field in ("title", "prev_sentence", "claim_text", "next_sentence"))
    for mapper in (
        lambda: map_price(row, text, context),
        lambda: map_employment(row, text),
        lambda: map_trade(row, text),
        lambda: map_retail(row, text, context),
        lambda: map_population(row, text, context),
    ):
        config = mapper()
        if config:
            return config
    return None


def map_by_codebook(row):
    config, exclusion = v1.map_by_codebook(row)
    if config:
        return config, None
    v2_config = map_v2(row)
    if v2_config:
        return v2_config, None
    v2_exclusion = classify_v2_nonverifiable(
        row,
        row.get("claim_text", "") or "",
        " ".join(str(row.get(field, "") or "") for field in ("title", "prev_sentence", "claim_text", "next_sentence")),
    )
    return None, v2_exclusion or exclusion


def read_cache():
    v1.CACHE_PATH = CACHE_PATH
    return v1.read_cache()


def verify(config, cache):
    v1.CACHE_PATH = CACHE_PATH
    return v1.verify(config, cache)
