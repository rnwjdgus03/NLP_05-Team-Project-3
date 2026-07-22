"""HCX 기반 claim 구조화 추출 (measurement-first v5 스키마)

사용법:
  1) .env 에 CLOVA_API_KEY=... 저장 (커밋 금지)
  2) pip install requests python-dotenv
  3) python extract_hcx.py --input hcx_input_100.csv --output hcx_extracted.csv
     [--model HCX-007] [--limit 5]  # --limit 로 소량 먼저 확인 권장

- 중단돼도 재실행하면 이미 처리한 claim_id 는 건너뛴다 (이어받기).
- 수치 추출과 KOSIS 검증 가능성 판정을 분리한다.
- 문장의 수치 후보를 먼저 찾고, 누락 시 HCX 재요청 후 규칙 fallback으로 보존한다.
- 출력은 수치마다 measurement 행을 분리한다.
"""
import argparse
import csv
import json
import os
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from dotenv import load_dotenv

URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"

RESPONSE_SCHEMA = {
  "type": "object",
  "properties": {
    "claim_domain_scope": {"type": "string", "enum": ["국내공식통계","해외통계·정책","개별기업","여론조사·설문","전망·목표","기타"]},
    "is_recurring_series": {"type": "string", "enum": ["Y","N"]},
    "metric_domain": {"type": "string", "enum": ["물가","고용","무역","인구","소득·임금","소매·소비","생산·산업","부동산","금융·금리","재정·조세","보건·복지","에너지·환경","기타"]},
    "indicator": {"type": "string"},
    "keywords": {"type": "string", "description": "통계표명에 나올 법한 단어 2~5개, ; 구분"},
    "region": {"type": "string"}, "age_group": {"type": "string"},
    "gender": {"type": "string", "enum": ["남","여","전체","-"]},
    "industry_or_item": {"type": "string"}, "population_etc": {"type": "string"},
    "origin_country": {"type": "string"}, "destination_country": {"type": "string"},
    "period": {"type": "string", "description": "YYYY, YYYYMM, YYYYQn, YYYYHn, - 중 하나. 예: 202508, 2025Q1, 2024H2"},
    "period_end": {"type": "string"},
    "prd_se": {"type": "string", "enum": ["Y","M","Q","H","-"]},
    "time_resolution_status": {"type": "string", "enum": ["확정","모호","결측","충돌"]},
    "measurements": {"type": "array", "items": {"type": "object", "properties": {
      "measurement_role": {"type": "string", "enum": ["현재값","이전값","증감값","증감률","목표값","참고값"]},
      "measurement_text": {"type": "string", "description": "해당 숫자와 단위를 포함한 원문 표현"},
      "measurement_usage": {"type": "string", "enum": ["KOSIS_VALUE","POLICY_VALUE","CONDITION","CONTEXT"]},
      "measurement_indicator": {"type": "string", "description": "이 값이 나타내는 지표. 예: 수출액, 수출증가율"},
      "measurement_item": {"type": "string", "description": "이 값의 품목·산업·대상. 예: 반도체, 바이오헬스. 없으면 -"},
      "measurement_period": {"type": "string", "description": "이 값 자체의 시점. YYYY, YYYYMM, YYYYQn, YYYYHn, -"},
      "measurement_prd_se": {"type": "string", "enum": ["Y","M","Q","H","-"]},
      "value": {"type": "string", "description": "숫자 문자열. 소수점 반드시 그대로 유지 (1.8%면 '1.8', 2만867이면 '20867')"},
      "value_min": {"type": "string"}, "value_max": {"type": "string"},
      "value_approximate": {"type": "string", "enum": ["Y","N"]},
      "unit": {"type": "string"},
      "value_type": {"type": "string", "enum": ["수준값","증감률","증감량","비중","순위"]},
      "direction": {"type": "string", "enum": ["증가","감소","유지","-"]},
      "change_base": {"type": "string", "enum": ["전년동월","전월","전분기","전년동기","전년","특정시점","-"]}},
      "required": ["measurement_role","measurement_text","measurement_usage","measurement_indicator",
                   "measurement_item","measurement_period","measurement_prd_se",
                   "value","unit","value_type","direction","change_base"]}},
    "evidence_text": {"type": "string", "description": "원문 구절 그대로 발췌, 따옴표 포함 변형 금지"},
    "extraction_confidence": {"type": "string", "enum": ["high","mid","low"]},
    "needs_review": {"type": "string", "enum": ["Y","N"]},
    "review_reason": {"type": "string"}
  },
  "required": ["claim_domain_scope","is_recurring_series","metric_domain","indicator","keywords",
               "region","age_group","gender","period","prd_se","time_resolution_status",
               "measurements","evidence_text","extraction_confidence","needs_review"]
}



SYSTEM_PROMPT = """너는 한국 뉴스 문장에서 통계 주장을 구조화 추출하는 시스템이다. 반드시 JSON만 출력한다.

## 출력 JSON 스키마
{
 "claim_domain_scope": "국내공식통계|해외통계·정책|개별기업|여론조사·설문|전망·목표|기타",
 "is_recurring_series": "Y|N",  // 반복 집계되는 통계 시리즈인가. 일회성 사건·발표는 N
 "metric_domain": "물가|고용|무역|인구|소득·임금|소매·소비|생산·산업|부동산|금융·금리|재정·조세|보건·복지|에너지·환경|기타",
 "indicator": "수식어 포함 지표명 (예: 청년실업률, 근원물가상승률)",
 "keywords": "통계표명에 나올 법한 단어 2~5개, ; 구분",
 "region": "행정구역 정식명. 국내 통계인데 지역 언급 없으면 전국. 해외 국가명 금지. 없으면 -",
 "age_group": "표준 구간 (청년→15~29세, 20대→20~29세, 고령층→65세 이상). 없으면 -",
 "gender": "남|여|전체|-",
 "industry_or_item": "산업/품목명. 없으면 -",
 "population_etc": "기타 대상 집단. 없으면 -",
 "origin_country": "-", "destination_country": "-",  // 무역 claim 한정 수입선/수출선
 "period": "YYYY|YYYYMM|YYYYQn|YYYYHn|-",  // 기사 날짜 기준 상대시점 역산 필수
 "period_end": "구간 주장의 끝. 단일 시점이면 -",
 "prd_se": "Y|M|Q|H|-",  // period 형식과 일관되게
 "time_resolution_status": "확정|모호|결측|충돌",
 "measurements": [  // 의미가 있는 수치마다 하나. KOSIS 검증 불가여도 버리지 않는다
   {"measurement_role": "현재값|이전값|증감값|증감률|목표값|참고값",
    "measurement_text": "원문 숫자+단위 표현",
    "measurement_usage": "KOSIS_VALUE|POLICY_VALUE|CONDITION|CONTEXT",
    "measurement_indicator": "이 값이 나타내는 지표 (예: 수출액, 수출증가율)",
    "measurement_item": "품목·산업·대상 (예: 반도체, 바이오헬스). 없으면 -",
    "measurement_period": "이 값 자체의 YYYY|YYYYMM|YYYYQn|YYYYHn|-",
    "measurement_prd_se": "Y|M|Q|H|-",
    "value": 숫자,  // 한국어 수사 환산: 2만867→20867, 31.2만→312000. 소수점 절대 생략 금지: 1.8%→1.8 (18 아님)
    "value_min": "범위 표현의 하한 (3%대→3). 아니면 -",
    "value_max": "범위 표현의 상한 (3%대→3.9). 아니면 -",
    "value_approximate": "Y|N",  // 약/가량/수준
    "unit": "%|%p|명|원|건|대(수량) 등. %와 %p 반드시 구분. 만명→명으로 환산",
    "value_type": "수준값|증감률|증감량|비중|순위",
    "direction": "증가|감소|유지|-",
    "change_base": "전년동월|전월|전분기|전년동기|전년|특정시점|-"}],
 "evidence_text": "판단 근거 원문 구절 그대로 (요약·변형 금지)",
 "extraction_confidence": "high|mid|low",
 "needs_review": "Y|N", "review_reason": "-"
}

## 판정 규칙
- verifiable(검증가능)은 시스템이 계산하므로 출력하지 않는다. scope와 recurring만 정확히.
- 중의성 주의: '청년'은 연령(년도 아님), 'N대 기업'은 순위(연령 아님), '6만3849대'는 수량, '1분기'는 Q1.
- claim_domain_scope와 is_recurring_series에 관계없이 검증 대상 문장의 의미 있는 수치와 단위를 모두 measurements에 보존한다.
- 같은 의미의 값이 제목형 구절과 본문에 반복되면 한 번만 출력한다.
- 이전값→현재값→증감값/증감률처럼 수치가 여러 개면 각각 별도 measurement로 출력한다.
- measurement_indicator는 지표, measurement_item은 품목·산업·대상으로 분리한다. 예: 반도체 1419억 달러는 indicator=수출액, item=반도체다.
- 한 문장에 여러 품목이 있으면 각 수치를 가까운 품목과 연결한다. 바이오헬스·농수산식품·화장품 값을 하나의 결합 indicator로 묶지 않는다.
- 현재값과 이전값의 연도가 다르면 measurement_period도 각각 다르게 쓴다. 기사 제목과 앞뒤 문장에 명시된 연도를 활용한다.
- 수주·도입·발표·조사 시작 연도처럼 원인이나 배경을 설명하는 연도는 관측값의 measurement_period로 쓰지 않는다. 예: '2021년 수주한 선박이 2024년에 256억 달러 수출'의 수출액 시점은 2024다.
- 기사 작성일은 통계 관측 시점의 근거가 아니다. 제목·현재 문장·앞뒤 문장에서 시점을 확정할 수 없으면 measurement_period와 measurement_prd_se를 -로 두고 추측하지 않는다.
- '처음으로 100억 달러를 돌파'의 100억 달러처럼 실제 관측값이 아니라 돌파 기준인 값은 CONTEXT로 분류한다.
- 정책상 금액·한도는 POLICY_VALUE, 나이·근로시간·소득기준은 CONDITION, 통계 실측값은 KOSIS_VALUE로 분류한다.
- 날짜, 발표일, 단순 목차 번호는 measurement에서 제외한다.
- 아래 사용자 메시지의 수치 후보 중 제외 대상이 아닌 값은 빠짐없이 반영한다."""

USER_TMPL = """기사 제목: {title}
기사 날짜: {date}
이전 문장: {prev}
[검증 대상 문장] {text}
다음 문장: {next}

[규칙 기반 수치·단위 후보]
{numeric_candidates}

위 후보를 참고해 [검증 대상 문장]의 주장을 JSON으로 추출하라. 후보는 검증 보조 정보이며 문맥에 맞게 역할과 용도를 판정하라."""

REPAIR_TMPL = """

[이전 추출 결과 검증 실패]
문제: {issues}
이전 결과: {previous_result}

누락된 수치·단위와 measurement별 지표·품목·시점을 추가하고 measurements를 다시 작성하라. 날짜·목차 번호만 제외할 수 있다."""

OUT_COLS = ["claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
            "claim_text", "prev_sentence", "next_sentence",
            "claim_domain_scope", "is_recurring_series",
            "metric_domain", "indicator", "keywords", "region", "age_group", "gender",
            "industry_or_item", "population_etc", "origin_country", "destination_country",
            "period", "period_end", "prd_se", "time_resolution_status",
            "measurement_text", "measurement_usage", "measurement_source",
            "measurement_indicator", "measurement_item", "measurement_period",
            "measurement_prd_se", "measurement_binding_source",
            "measurement_role", "value", "value_min", "value_max", "value_approximate",
            "unit", "value_type", "direction", "change_base",
            "evidence_text", "extraction_confidence", "needs_review", "review_reason",
            "measurement_repaired", "measurement_fallback_count", "measurement_binding_fallback_count",
            "extraction_model", "prompt_version", "extracted_at"]
PROMPT_VERSION = "v1.5-measurement-binding"

NUMBER_TOKEN = (
    r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"(?:(?:조|억|만|천|백)(?:\d+(?:\.\d+)?)?)*"
)
NUMBER_WITH_UNIT_RE = re.compile(
    rf"(?<![\dA-Za-z])(?P<number>{NUMBER_TOKEN})\s*"
    r"(?P<approx_before>여|가량|정도|쯤|내외)?\s*"
    r"(?P<unit>퍼센트포인트|%p|퍼센트|%|개월|시간|분기|달러|개사|가구|명|원|건|대|세|년|월|일|위|배|개|사)"
    r"(?P<approx_after>가량|정도|쯤|내외)?"
)
NUMBER_LIST_RE = re.compile(
    r"(?P<values>\d+(?:\.\d+)?(?:,\s+\d+(?:\.\d+)?)+)\s*"
    r"(?P<unit>세|명|원|건|대|시간|개월|년|월|일|위|배|가구|개사|개|사)"
)
NUMBER_RANGE_RE = re.compile(
    rf"(?<![\dA-Za-z])(?P<low>{NUMBER_TOKEN})\s*(?:~|∼|-)\s*"
    rf"(?P<high>{NUMBER_TOKEN})\s*"
    r"(?P<unit>퍼센트포인트|%p|퍼센트|%|개월|시간|분기|달러|개사|가구|명|원|건|대|세|년|월|일|위|배|개|사)"
)
MAGNITUDES = {"조": Decimal("1000000000000"), "억": Decimal("100000000"),
              "만": Decimal("10000"), "천": Decimal("1000"), "백": Decimal("100")}
UNIT_MAP = {"퍼센트포인트": "%p", "%p": "%p", "퍼센트": "%", "%": "%"}
POLICY_WORDS = ("급여", "월급", "수당", "지원", "최저임금", "봉급", "보조금", "한도", "소득기준", "장학금", "연금")
INCREASE_WORDS = ("증가", "상승", "인상", "올랐", "오른", "늘었", "늘어난", "확대")
DECREASE_WORDS = ("감소", "하락", "인하", "내렸", "줄었", "줄어든", "축소")


def normalize_number(value):
    """Normalize Korean magnitude notation while preserving decimal precision."""
    text = str(value).replace(",", "").strip()
    if not text:
        return "-"
    try:
        if not any(magnitude in text for magnitude in MAGNITUDES):
            number = Decimal(text)
        else:
            number = Decimal("0")
            position = 0
            for match in re.finditer(r"(\d+(?:\.\d+)?)([조억만천백]?)", text):
                if match.start() != position:
                    raise InvalidOperation
                amount = Decimal(match.group(1))
                number += amount * MAGNITUDES.get(match.group(2), Decimal("1"))
                position = match.end()
            if position != len(text):
                raise InvalidOperation
    except InvalidOperation:
        return text

    normalized = format(number, "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def canonical_unit(unit):
    return UNIT_MAP.get(str(unit).strip(), str(unit).strip())


def _direction(text):
    if any(word in text for word in INCREASE_WORDS):
        return "증가"
    if any(word in text for word in DECREASE_WORDS):
        return "감소"
    return "-"


def _candidate_usage(text, start, end, value, unit):
    before = text[max(0, start - 30):start]
    after = text[end:min(len(text), end + 30)]
    context = before + text[start:end] + after
    if re.match(r"^\s*(?:을|를)?\s*돌파", after):
        return "CONTEXT"
    if re.match(r"^\s*당", after):
        return "CONDITION"
    if unit == "사":
        return "CONTEXT"
    if unit == "개" and re.match(r"^\s*(?:항공사|기업|업체|기관)", after):
        return "CONTEXT"
    if unit == "세":
        return "CONDITION"
    if unit in {"시간", "개월"}:
        return "CONDITION" if any(word in context for word in ("기준", "동안", "기간", "첫")) else "CONTEXT"
    if unit == "년":
        try:
            numeric_value = int(Decimal(value))
        except (InvalidOperation, ValueError):
            numeric_value = 0
        if 1900 <= numeric_value <= 2100:
            return "DATE_OR_ORDER"
        return "CONDITION" if after.lstrip().startswith("간") else "CONTEXT"
    if unit in {"월", "일", "분기"}:
        return "DATE_OR_ORDER"
    if any(word in after[:15] for word in ("이하", "이상", "미만", "초과")):
        return "CONDITION"
    if re.match(r"^\s*(?:을|를)?\s*기준", after):
        return "CONDITION"
    if any(word in text for word in POLICY_WORDS):
        return "POLICY_VALUE"
    return "KOSIS_VALUE"


def _candidate_role(text, start, end, unit, usage):
    before = text[max(0, start - 20):start]
    after = text[end:min(len(text), end + 20)]
    if usage in {"CONDITION", "CONTEXT"}:
        return "참고값"
    if unit in {"%", "%p"} and any(word in text for word in INCREASE_WORDS + DECREASE_WORDS):
        return "증감률" if unit == "%" else "증감값"
    if "기존" in before or "종전" in before or "이전" in before:
        return "이전값"
    between_after = text[end:]
    if between_after.lstrip().startswith("에서"):
        return "이전값"
    if "에서" in before and re.match(r"^\s*(?:으로|로)", after):
        return "현재값"
    if any(word in before for word in ("목표", "최대", "한도")):
        return "목표값"
    return "현재값"


def _candidate_value_type(unit, role):
    if unit == "위":
        return "순위"
    if unit == "%p" or role == "증감값":
        return "증감량"
    if unit == "%":
        return "증감률" if role == "증감률" else "비중"
    return "수준값"


def _make_candidate(text, raw_number, raw_unit, start, end, measurement_text=None,
                    approximate=False):
    approximate = approximate or bool(re.search(r"약\s*$", text[max(0, start - 4):start]))
    value = normalize_number(raw_number)
    unit = canonical_unit(raw_unit)
    usage = _candidate_usage(text, start, end, value, unit)
    role = _candidate_role(text, start, end, unit, usage)
    return {
        "measurement_text": measurement_text or text[start:end],
        "value": value,
        "unit": unit,
        "measurement_usage": usage,
        "measurement_role": role,
        "value_type": _candidate_value_type(unit, role),
        "direction": _direction(text),
        "change_base": "-",
        "value_approximate": "Y" if approximate else "N",
        "start": start,
    }


def extract_numeric_candidates(text):
    """Return deduplicated value/unit candidates with deterministic hints."""
    candidates = []
    for match in NUMBER_WITH_UNIT_RE.finditer(text):
        candidates.append(_make_candidate(
            text, match.group("number"), match.group("unit"),
            match.start(), match.end(), match.group(0),
            bool(match.group("approx_before") or match.group("approx_after")),
        ))

    for match in NUMBER_RANGE_RE.finditer(text):
        for group in ("low", "high"):
            candidates.append(_make_candidate(
                text, match.group(group), match.group("unit"),
                match.start(group), match.end(group),
                f"{match.group(group)}{match.group('unit')}",
            ))

    for match in NUMBER_LIST_RE.finditer(text):
        unit = match.group("unit")
        for value_match in re.finditer(r"\d+(?:\.\d+)?", match.group("values")):
            start = match.start("values") + value_match.start()
            end = match.start("values") + value_match.end()
            candidates.append(_make_candidate(
                text, value_match.group(0), unit, start, end,
                f"{value_match.group(0)}{unit}",
            ))

    candidates.sort(key=lambda item: item["start"])
    deduplicated = []
    seen = set()
    for candidate in candidates:
        if candidate["measurement_usage"] == "DATE_OR_ORDER":
            continue
        key = (candidate["value"], candidate["unit"], candidate["measurement_role"])
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)
    return deduplicated


def prompt_candidates(candidates):
    fields = ("measurement_text", "value", "unit", "measurement_usage",
              "measurement_role", "value_type", "direction", "value_approximate")
    compact = [{field: candidate[field] for field in fields} for candidate in candidates]
    return json.dumps(compact, ensure_ascii=False)


def call_hcx(api_key, model, title, date, text, prev, nxt, candidates, retries=4,
             effort="none", previous_result=None, issues=None):
    user_content = USER_TMPL.format(
        title=title,
        date=date,
        prev=prev,
        text=text,
        next=nxt,
        numeric_candidates=prompt_candidates(candidates),
    )
    if issues:
        user_content += REPAIR_TMPL.format(
            issues="; ".join(issues),
            previous_result=json.dumps(previous_result, ensure_ascii=False),
        )
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0, "topP": 0.8, "seed": 42,
    }
    if model.startswith("HCX-007"):  # 추론 모델: maxTokens 불가, thinking 설정 필요
        body["thinking"] = {"effort": effort}  # Structured Outputs는 추론과 동시 사용 불가
        body["maxCompletionTokens"] = 2000
        body["responseFormat"] = {"type": "json", "schema": RESPONSE_SCHEMA}
    else:
        body["maxTokens"] = 2000
    headers = {"Authorization": f"Bearer {api_key}",
               "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
               "Content-Type": "application/json"}
    for i in range(retries):
        r = requests.post(URL.format(model=model), headers=headers, json=body, timeout=90)
        if r.status_code == 429:
            time.sleep(5 * (i + 1)); continue
        r.raise_for_status()
        return r.json()["result"]["message"]["content"]
    raise RuntimeError("rate limit 재시도 초과")


def parse_json(s):
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("JSON 없음")
    return json.loads(m.group(0))



def norm(x):
    s = str(x).strip() if x is not None else "-"
    return s if s else "-"


def measurement_key(value, unit):
    return normalize_number(value), canonical_unit(unit)


def period_is_grounded(period, claim):
    """Return whether a measurement period is supported by article text context."""
    value = norm(period)
    if value == "-":
        return False
    evidence = " ".join(
        norm(claim.get(field))
        for field in ("title", "claim_text", "prev_sentence", "next_sentence")
    )
    year_match = re.search(r"(?:19|20)\d{2}", value)
    if not year_match:
        return False
    year = int(year_match.group())
    if str(year) in evidence:
        return True

    article_year_match = re.search(r"(?:19|20)\d{2}", norm(claim.get("date")))
    if not article_year_match:
        return False
    article_year = int(article_year_match.group())
    if year == article_year and re.search(r"올해|금년|이번\s*해", evidence):
        return True
    if year == article_year - 1 and re.search(r"지난해|작년|전년", evidence):
        return True
    return False


def apply_local_explicit_years(result, claim):
    """Bind a value to an explicit year immediately surrounding its source text."""
    text = norm(claim.get("claim_text"))
    corrected = 0
    for measurement in result.get("measurements") or []:
        measurement_text = norm(measurement.get("measurement_text"))
        if measurement_text == "-":
            continue
        index = text.find(measurement_text)
        if index < 0:
            continue
        local = text[max(0, index - 20):index + len(measurement_text)]
        years = re.findall(r"((?:19|20)\d{2})\s*년", local)
        if not years:
            continue
        year = years[-1]
        if norm(measurement.get("measurement_period")) != year:
            measurement["measurement_period"] = year
            measurement["measurement_prd_se"] = "Y"
            corrected += 1
    return corrected


def apply_local_explicit_months(result, claim):
    """월간(prd_se=M) 측정값이 연도만 갖고 있을 때, 원문에서 값 바로 앞의 'N월'을 찾아 YYYYMM으로 바인딩한다.

    예: '월간 수출 증가율은 8월(11%), 9월(7.5%), 10월(4.6%)' -> 각 값에 8·9·10월을 매긴다.
    한 문장에 여러 월값이 나열될 때 모두 같은 연도(마지막 달)로 뭉개지는 버그를 방지한다.
    """
    text = norm(claim.get("claim_text"))
    corrected = 0
    search_from = 0
    for measurement in result.get("measurements") or []:
        if norm(measurement.get("measurement_prd_se")) != "M":
            continue
        period = norm(measurement.get("measurement_period"))
        if not re.fullmatch(r"(?:19|20)\d{2}", period):  # 연도만 있는 경우만 대상
            continue
        year = period
        key = norm(measurement.get("measurement_text"))
        if key in ("", "-"):
            key = norm(measurement.get("value"))
        if key in ("", "-"):
            continue
        index = text.find(key, search_from)
        if index < 0:
            index = text.find(key)
        if index < 0:
            continue
        search_from = index + len(key)
        local = text[max(0, index - 12):index]  # 값 바로 앞 창에서 'N월' 탐색
        months = re.findall(r"(\d{1,2})\s*월", local)
        if not months:
            continue
        month = int(months[-1])
        if not 1 <= month <= 12:
            continue
        measurement["measurement_period"] = f"{year}{month:02d}"
        corrected += 1
    return corrected


def remove_ungrounded_measurement_periods(result, claim):
    removed = 0
    for measurement in result.get("measurements") or []:
        period = norm(measurement.get("measurement_period"))
        if period != "-" and not period_is_grounded(period, claim):
            measurement["measurement_period"] = "-"
            measurement["measurement_prd_se"] = "-"
            removed += 1
    return removed


def measurement_issues(result, candidates):
    measurements = result.get("measurements") or []
    issues = []
    actual = set()
    for index, measurement in enumerate(measurements, start=1):
        value = norm(measurement.get("value"))
        unit = norm(measurement.get("unit"))
        if value == "-" or unit == "-":
            issues.append(f"measurement {index} value/unit 누락")
            continue
        if norm(measurement.get("measurement_usage")) == "KOSIS_VALUE":
            for field in ("measurement_indicator",):
                if norm(measurement.get(field)) == "-":
                    issues.append(f"measurement {index} {field} 누락")
        actual.add(measurement_key(value, unit))

    expected = {(candidate["value"], candidate["unit"]) for candidate in candidates}
    missing = sorted(expected - actual)
    if missing:
        issues.append("후보 누락: " + ", ".join(f"{value}{unit}" for value, unit in missing))
    return issues


def normalize_hcx_measurements(result, candidates, text=""):
    candidate_by_key = {
        (candidate["value"], candidate["unit"]): candidate for candidate in candidates
    }
    normalized = []
    seen = set()
    for measurement in result.get("measurements") or []:
        value = norm(measurement.get("value"))
        unit = norm(measurement.get("unit"))
        if value == "-" or unit == "-":
            continue
        key = measurement_key(value, unit)
        candidate = candidate_by_key.get(key, {})
        measurement_text = norm(measurement.get("measurement_text"))
        if not candidate and measurement_text != "-":
            candidate = next(
                (
                    item for item in candidates
                    if item["measurement_text"] in measurement_text
                    or measurement_text in item["measurement_text"]
                ),
                {},
            )
            if candidate:
                key = (candidate["value"], candidate["unit"])
        if not candidate and (measurement_text == "-" or measurement_text not in text):
            continue

        item = dict(measurement)
        item["value"] = key[0]
        item["unit"] = key[1]
        item["measurement_text"] = measurement_text
        if item["measurement_text"] == "-":
            item["measurement_text"] = candidate.get("measurement_text", "-")
        model_usage = norm(item.get("measurement_usage"))
        candidate_usage = candidate.get("measurement_usage", "-")
        if candidate_usage in {"POLICY_VALUE", "CONDITION", "CONTEXT"}:
            item["measurement_usage"] = candidate_usage
        elif model_usage in {"KOSIS_VALUE", "POLICY_VALUE", "CONDITION", "CONTEXT"}:
            item["measurement_usage"] = model_usage
        else:
            item["measurement_usage"] = candidate_usage
        if candidate.get("value_approximate") == "Y":
            item["value_approximate"] = "Y"
        if item["measurement_usage"] == "-":
            item["measurement_usage"] = "CONTEXT"
        item["_source"] = "hcx"
        duplicate_key = (item["value"], item["unit"], norm(item.get("measurement_role")))
        if duplicate_key in seen:
            continue
        seen.add(duplicate_key)
        normalized.append(item)
    result["measurements"] = normalized
    return result


def ensure_measurement_bindings(result):
    """Fill missing measurement bindings from claim-level fields and mark the fallback."""
    fallback_values = {
        "measurement_indicator": norm(result.get("indicator")),
        "measurement_item": norm(result.get("industry_or_item")),
        "measurement_period": norm(result.get("period")),
        "measurement_prd_se": norm(result.get("prd_se")),
    }
    fallback_count = 0
    for measurement in result.get("measurements") or []:
        used_fallback = False
        for field, fallback in fallback_values.items():
            if (field in {"measurement_period", "measurement_prd_se"}
                    and norm(measurement.get("measurement_usage")) == "KOSIS_VALUE"):
                continue
            if norm(measurement.get(field)) == "-" and fallback != "-":
                measurement[field] = fallback
                if field != "measurement_item":
                    used_fallback = True
        if measurement.get("_source") == "rule_fallback":
            measurement["_binding_source"] = "rule_fallback"
        elif used_fallback:
            measurement["_binding_source"] = "claim_fallback"
            fallback_count += 1
        else:
            measurement["_binding_source"] = "hcx"
    return fallback_count


def add_fallback_measurements(result, candidates):
    measurements = result.setdefault("measurements", [])
    existing = {
        measurement_key(item.get("value", "-"), item.get("unit", "-"))
        for item in measurements
        if norm(item.get("value")) != "-" and norm(item.get("unit")) != "-"
    }
    fallback_count = 0
    for candidate in candidates:
        key = (candidate["value"], candidate["unit"])
        if key in existing:
            continue
        measurements.append({
            "measurement_text": candidate["measurement_text"],
            "measurement_usage": candidate["measurement_usage"],
            "measurement_indicator": norm(result.get("indicator")),
            "measurement_item": norm(result.get("industry_or_item")),
            "measurement_period": norm(result.get("period")),
            "measurement_prd_se": norm(result.get("prd_se")),
            "measurement_role": candidate["measurement_role"],
            "value": candidate["value"],
            "value_min": "-",
            "value_max": "-",
            "value_approximate": candidate.get("value_approximate", "N"),
            "unit": candidate["unit"],
            "value_type": candidate["value_type"],
            "direction": candidate["direction"],
            "change_base": candidate["change_base"],
            "_source": "rule_fallback",
            "_binding_source": "rule_fallback",
        })
        existing.add(key)
        fallback_count += 1
    return fallback_count


def extract_claim(api_key, model, claim, effort="none"):
    text = claim.get("claim_text", "")
    candidates = extract_numeric_candidates(text)
    common = {
        "api_key": api_key,
        "model": model,
        "title": claim.get("title", "-"),
        "date": claim.get("date", "-"),
        "text": text,
        "prev": claim.get("prev_sentence", "-"),
        "nxt": claim.get("next_sentence", "-"),
        "candidates": candidates,
        "effort": effort,
    }
    raw = call_hcx(**common)
    result = parse_json(raw)
    issues = measurement_issues(result, candidates)
    repaired = "N"
    if issues:
        repaired = "Y"
        raw = call_hcx(**common, previous_result=result, issues=issues)
        result = parse_json(raw)

    result = normalize_hcx_measurements(result, candidates, text=text)
    apply_local_explicit_years(result, claim)
    apply_local_explicit_months(result, claim)
    period_removed_count = remove_ungrounded_measurement_periods(result, claim)
    binding_fallback_count = ensure_measurement_bindings(result)
    fallback_count = add_fallback_measurements(result, candidates)
    if fallback_count or binding_fallback_count or period_removed_count:
        result["needs_review"] = "Y"
        reason = norm(result.get("review_reason"))
        fallback_reasons = []
        if fallback_count:
            fallback_reasons.append(f"measurement_rule_fallback:{fallback_count}")
        if binding_fallback_count:
            fallback_reasons.append(f"measurement_binding_fallback:{binding_fallback_count}")
        if period_removed_count:
            fallback_reasons.append(f"measurement_period_ungrounded:{period_removed_count}")
        fallback_reason = ";".join(fallback_reasons)
        result["review_reason"] = fallback_reason if reason == "-" else f"{reason};{fallback_reason}"
    result["_measurement_repaired"] = repaired
    result["_measurement_fallback_count"] = str(fallback_count)
    result["_measurement_binding_fallback_count"] = str(binding_fallback_count)
    result["_measurement_period_removed_count"] = str(period_removed_count)
    return result


def to_rows(claim, j, model):
    scope, rec = norm(j.get("claim_domain_scope")), norm(j.get("is_recurring_series"))
    base = {c: norm(claim.get(c)) for c in ["claim_id", "article_id", "title", "date", "url",
                                            "claim_text", "prev_sentence", "next_sentence"]}
    base.update({
        "claim_domain_scope": scope, "is_recurring_series": rec,
        **{k: norm(j.get(k)) for k in ["metric_domain", "indicator", "keywords", "region",
                                       "age_group", "gender", "industry_or_item", "population_etc",
                                       "origin_country", "destination_country", "period", "period_end",
                                       "prd_se", "time_resolution_status", "evidence_text",
                                       "extraction_confidence", "needs_review", "review_reason"]},
        "extraction_model": model, "prompt_version": PROMPT_VERSION,
        "extracted_at": time.strftime("%Y-%m-%d"),
        "measurement_repaired": norm(j.get("_measurement_repaired", "N")),
        "measurement_fallback_count": norm(j.get("_measurement_fallback_count", "0")),
        "measurement_binding_fallback_count": norm(j.get("_measurement_binding_fallback_count", "0")),
    })
    meas = j.get("measurements") or []
    if not meas:
        row = dict(base)
        row.update({c: "-" for c in ["claim_measurement_id", "measurement_text",
                                     "measurement_usage", "measurement_source", "measurement_indicator",
                                     "measurement_item", "measurement_period", "measurement_prd_se",
                                     "measurement_binding_source", "measurement_role",
                                     "value", "value_min", "value_max", "value_approximate", "unit",
                                     "value_type", "direction", "change_base"]})
        return [row]
    rows = []
    for k, m in enumerate(meas, 1):
        row = dict(base)
        row.update({
            "claim_measurement_id": f"{base['claim_id']}-m{k}",
            "measurement_source": norm(m.get("_source", "hcx")),
            "measurement_binding_source": norm(m.get("_binding_source", "hcx")),
            **{f: norm(m.get(f)) for f in ["measurement_text", "measurement_usage",
                                           "measurement_indicator", "measurement_item",
                                           "measurement_period", "measurement_prd_se",
                                           "measurement_role", "value", "value_min", "value_max",
                                           "value_approximate", "unit", "value_type", "direction",
                                           "change_base"]},
        })
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="hcx_input_100.csv")
    ap.add_argument("--output", default="hcx_extracted.csv")
    ap.add_argument("--model", default="HCX-007")
    ap.add_argument("--effort", default="none", choices=["none", "low", "medium"],
                    help="HCX-007 추론 깊이 (구조화 추출은 none 권장)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    load_dotenv()
    key = os.getenv("CLOVA_API_KEY")
    if not key:
        raise SystemExit(".env 에 CLOVA_API_KEY 를 설정하세요")

    with open(a.input, encoding="utf-8-sig") as f:
        claims = list(csv.DictReader(f))
    output_path = Path(a.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if output_path.exists() and not a.overwrite:
        with output_path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != OUT_COLS:
                raise SystemExit(
                    "기존 출력 CSV 스키마가 현재 버전과 다릅니다. "
                    "새 출력 경로를 쓰거나 --overwrite를 지정하세요."
                )
            done = {r["claim_id"] for r in reader}
        print(f"이어받기: {len(done)}건 완료됨")

    mode = "a" if done else "w"
    with output_path.open(mode, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        if mode == "w":
            w.writeheader()
        n = 0
        for c in claims:
            if c["claim_id"] in done:
                continue
            if a.limit and n >= a.limit:
                break
            try:
                result = extract_claim(key, a.model, c, effort=a.effort)
                rows = to_rows(c, result, a.model)
                w.writerows(rows); f.flush()
                repaired = result.get("_measurement_repaired", "N")
                fallback = result.get("_measurement_fallback_count", "0")
                binding = result.get("_measurement_binding_fallback_count", "0")
                period_removed = result.get("_measurement_period_removed_count", "0")
                print(f"[{c['claim_id']}] ok ({len(rows)} 행, repair={repaired}, fallback={fallback}, binding={binding}, period_removed={period_removed})")
            except Exception as e:
                print(f"[{c['claim_id']}] 실패: {type(e).__name__}: {e}")
            n += 1
            time.sleep(a.sleep)
    print("완료 →", a.output)


if __name__ == "__main__":
    main()
