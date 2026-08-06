#!/usr/bin/env python3
"""주장 내용으로 KOSIS 검증 가능 범위를 직접 판정한다 (LLM 자기 신고 라벨을 신뢰하지 않는다).

기존 게이트는 `measurement_usage == "KOSIS_VALUE"` 와
`claim_domain_scope == "국내공식통계"` 라는 **HCX 가 스스로 붙인 라벨만** 봤다.
독립 검증이 없어서, 비트코인 시세나 롤렉스 판매가도 라벨만 맞으면 통과했다.

실측 근거 (silver_coordinates.csv, 177 measurement):
  후보 좌표 5~12개를 전부 KOSIS 에 조회했는데 값이 재현된 건 8건뿐이고,
  NO_MATCH 약 121건 중 상당수가 **KOSIS 에 존재할 수 없는 주장**이었다.

설계 원칙
  - 오탐(정상 주장을 버리는 것)이 미탐보다 나쁘다. 확신이 서는 것만 REJECT.
  - 애매하면 REVIEW 로 남겨 사람이 본다. 조용히 통과시키지 않는다.
  - 키워드 목록은 **관측된 사례에서 뽑은 것이라 불완전하다.** 확장 전제로 짠다.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

REJECT = "REJECT"
REVIEW = "REVIEW"

# --------------------------------------------------------------------------
# 관측된 범위 밖 사례 (silver NO_MATCH 에서 추출). 목록은 계속 늘어난다.
# --------------------------------------------------------------------------

# 해외 자산·지수: KOSIS 는 국내 공식통계라 애초에 없다.
FOREIGN_MARKET = ("비트코인", "이더리움", "가상자산", "가상화폐", "암호화폐", "코인시세",
                  "나스닥", "s&p", "에스앤피", "다우존스", "다우지수", "니케이", "항셍",
                  "월가", "뉴욕증시")

# 세계 '집계값' — 국내 통계에 존재하지 않는다.
GLOBAL_AGGREGATE = ("세계 평균", "세계평균", "글로벌 평균", "주요국 평균",
                    "oecd 평균", "국제 평균", "세계 전체", "전 세계 합계")
# 세계 '맥락' — 한국 실적을 세계와 견주는 문장일 수 있으므로 버리지 않는다.
GLOBAL_CONTEXT = ("전 세계", "전세계", "세계 각국", "글로벌", "국제 사회")

# 전망·계획·목표: 아직 일어나지 않은 값이라 실적통계와 대조할 수 없다.
FORECAST = ("전망", "예상", "추정", "내다봤", "관측", "예측", "잠재 성장률", "잠재성장률")
# 미래 의지 표현만 넣는다. '확대했다/적용했다' 같은 완료형은 계획이 아니라
# 이미 시행된 제도이므로 POLICY_PARAMETER 가 판정해야 한다.
PLAN = ("하겠다", "겠다고", "계획", "목표로", "추진하기로", "집행하겠")

# 제도·정책 파라미터: 통계가 아니라 규정값.
POLICY_PARAM = ("세율", "개별소비세", "관세율", "부가세율", "법인세율", "소득세율",
                "정원", "허용 비율", "한도", "요율", "공제율", "지원 비율")

# 두 항목의 연산으로만 얻어지는 지표. 우리 파이프라인은 '한 좌표 = 한 값' 구조라
# 표현할 수 없다 (mapping_type 의 difference_from_level 은 같은 항목의 '시점 간' 차이다).
#
# 실측 근거:
#   '518억달러 무역 흑자' → 관세청 수출입 통계(DT_1R11001_FRM101)에는 수출액·수입액만
#   있고 무역수지 항목이 없다(메타 조회로 확인). 그런데 표 이름에 '무역수지'가 들어간
#   표는 대부분 **기술무역수지**라, 문자열이 겹쳐 엉뚱한 표가 상위에 올라온다.
#   실제로 '기관유형별 산업별 기술무역수지 / objL1=건설' 로 오매핑됐다.
#   실버가 좌표 10~12개를 조회했지만 값을 재현한 것은 하나도 없었다.
#
# 주의: 목록은 관측된 사례에서만 뽑았다. 경상수지·재정수지처럼 KOSIS 에 항목으로
#       존재하는 수지는 넣지 않는다(국제수지 표에 실재한다).
DERIVED_INDICATOR = ("무역수지", "무역 수지", "무역흑자", "무역 흑자",
                     "무역적자", "무역 적자", "수출입 격차", "수출입 차이")

# 파생 차액을 나타내는 표현 (어간으로 잡는다 — 올랐다/올렸다/올린 등 활용형이 많다)
DIFFERENCE_HINT = ("올랐", "올렸", "올린", "내렸", "내린", "인상", "인하",
                   "늘었", "늘렸", "줄었", "줄였", "높였", "낮췄", "낮아",
                   "개선", "차이", "포인트", "급감", "급증")

# 장중·특정 시각 시세: KOSIS 는 월평균·연평균만 수록한다.
# 실측: '오후 3시 30분 기준 1466.6원', '지난달 말(30일) 오후 3시 30분 기준 1472.5원'
TIME_OF_DAY = re.compile(r"(?:오전|오후)?\s*\d{1,2}\s*시\s*(?:\d{1,2}\s*분)?")
MARKET_SUBJECT = ("환율", "주가", "종가", "시세", "코스피", "코스닥", "지수")
MARKET_DAILY_HINT = ("전 거래일", "전거래일", "장 마감", "장중", "마감", "기준")

# 개별 기업 단위 실적: KOSIS 는 통계법상 개별 기업 자료를 수록하지 않는다(산업 집계만).
# 목록은 관측된 사례에서만 뽑았으므로 **불완전하며 확장 전제**다.
SINGLE_COMPANY = ("현대차", "기아", "gm 한국사업장", "kg모빌리티", "르노코리아",
                  "제주항공", "진에어", "대한항공", "아시아나항공", "티웨이",
                  "동아오츠카", "오리온", "롤렉스", "에르메스", "삼성전자", "sk하이닉스",
                  "포스코", "현대제철", "lg전자")
COMPANY_METRIC = ("판매", "수출", "생산", "실적", "정비사", "인력", "매출", "영업이익")

# 기업명 바로 뒤에 주격·화제 조사가 붙으면 그 기업이 주장의 **주체**다.
# "현대차는 414만1791대", "기아는 308만9457대를 팔아" — 산업 집계가 아니다.
# 반대로 "국내 완성차 업체들의 판매량"처럼 기업명이 예시로만 스치는 문장과 구분된다.
SUBJECT_PARTICLE = ("는", "은", "이", "가", "도", "의")

# 국회의원·언론이 기관에서 받아온 자료. 공표 통계가 아니라 개별 요청 산출물이다.
INTERNAL_DOCUMENT = ("제출받은 자료", "제출한 자료", "제출받은", "의원실",
                     "입수한 자료", "확보한 자료", "단독 입수", "내부 자료",
                     "본지가", "본지 분석")

# KOSIS 에 수록되지 않는 것이 확실한 국제기구 통계.
# OECD·IMF 등은 KOSIS 국제통계에 일부 수록되므로 여기 넣지 않는다.
FOREIGN_ORG_ONLY = ("국제로봇연맹", "ifr", "international federation of robotics")

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 따옴표로 감싼 제품·모델명: '데이트저스트 오이스터스틸…', ‘에버 헤라클레스 웨딩 밴드’
QUOTED_PRODUCT = re.compile(r"[‘'\"“]([^’'\"”]{4,40})[’'\"”]")
PRICE_WORD = ("판매가", "가격을", "값을", "출고가", "정가")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _has(text: str, words) -> str:
    """매칭된 첫 키워드를 돌려준다(근거로 남기기 위해)."""
    low = text.lower()
    for word in words:
        if word in low:
            return word
    return ""


def _first(row: Mapping[str, Any], *names: str) -> str:
    """여러 후보 컬럼 중 값이 있는 첫 번째를 돌려준다."""
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return ""


def _numbers(text: str) -> list[float]:
    out = []
    for token in NUMBER.findall(text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------
# 개별 판정기 — 각각 (code, reason, severity) 또는 None
# --------------------------------------------------------------------------

def foreign_market(claim_text: str, row: Mapping[str, Any]):
    hit = _has(claim_text, FOREIGN_MARKET)
    if hit:
        return ("FOREIGN_MARKET_VALUE", f"해외 자산·지수({hit})는 KOSIS 수록 대상이 아님", REJECT)
    return None


def global_scope(claim_text: str, row: Mapping[str, Any]):
    """'세계 평균' 같은 집계값은 버리고, '전 세계 수출순위' 같은 비교 문맥은 남긴다."""
    aggregate = _has(claim_text, GLOBAL_AGGREGATE)
    if aggregate:
        return ("GLOBAL_SCOPE_VALUE", f"세계 집계값({aggregate})은 국내 공식통계에 없음", REJECT)
    context = _has(claim_text, GLOBAL_CONTEXT)
    if context:
        return ("GLOBAL_COMPARISON", f"세계 비교 문맥({context}) — 대상이 국내 통계인지 확인 필요", REVIEW)
    return None


def forecast_or_plan(claim_text: str, row: Mapping[str, Any]):
    """전망·계획은 실적통계와 대조 불가. 다만 과거 전망의 '실적 비교'는 살린다."""
    forecast_hit = _has(claim_text, FORECAST)
    plan_hit = _has(claim_text, PLAN)
    if not (forecast_hit or plan_hit):
        return None
    hit = forecast_hit or plan_hit
    label = "전망" if forecast_hit else "계획"
    return (f"{'FORECAST' if forecast_hit else 'PLAN'}_VALUE",
            f"{label} 표현({hit}) — 아직 실현되지 않은 값은 실적통계와 대조할 수 없음", REJECT)


def policy_parameter(claim_text: str, row: Mapping[str, Any]):
    hit = _has(claim_text, POLICY_PARAM)
    if hit:
        return ("POLICY_PARAMETER", f"제도 규정값({hit})은 통계 수치가 아님", REJECT)
    return None


def branded_product_price(claim_text: str, row: Mapping[str, Any]):
    """특정 브랜드·모델 가격. KOSIS 물가통계는 품목 평균가만 있고 개별 상품가는 없다."""
    unit = _text(row.get("unit"))
    if unit not in {"원", "만원", "달러"}:
        return None
    quoted = QUOTED_PRODUCT.search(claim_text)
    has_price_word = any(word in claim_text for word in PRICE_WORD)
    if quoted and has_price_word:
        return ("BRANDED_PRODUCT_PRICE",
                f"개별 상품 가격(‘{quoted.group(1)[:20]}’) — KOSIS 는 품목 평균가만 수록", REJECT)
    if quoted:
        return ("POSSIBLE_PRODUCT_PRICE",
                f"제품명으로 보이는 표현(‘{quoted.group(1)[:20]}’) — 품목 통계인지 확인 필요", REVIEW)
    return None


def derived_difference(claim_text: str, row: Mapping[str, Any]):
    """문장 안 두 값의 '차이'를 독립 measurement 로 뽑은 경우.

    예: '1292만원에서 1373만원으로 81만원(6.3%) 올렸다' 의 81만원.
    KOSIS 에 그런 항목은 없다 — 수준값 두 개로 계산해야 한다.
    """
    value = row.get("value")
    try:
        target = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if target <= 0:
        return None
    if not _has(claim_text, DIFFERENCE_HINT):
        return None
    numbers = _numbers(claim_text)
    for i, first in enumerate(numbers):
        for second in numbers[i + 1:]:
            gap = abs(second - first)
            if gap <= 0:
                continue
            # 자릿수 표기가 달라도(만원/원) 비율이 맞으면 차액으로 본다.
            for scale in (1, 10, 100, 1000, 10000):
                if abs(gap * scale - target) <= max(target * 0.001, 1e-9):
                    return ("DERIVED_DIFFERENCE",
                            f"문장 내 {first:g}과 {second:g}의 차이({gap:g})와 일치 — 파생 차액",
                            REJECT)
    return None


def derived_indicator(claim_text: str, row: Mapping[str, Any]):
    """두 항목의 연산이 필요한 지표 (예: 무역수지 = 수출액 − 수입액).

    **claim_text 가 아니라 measurement 의 지표 필드만 본다.** 문장으로 판정하면
    '수입액은 …6320억달러로, 518억달러의 무역 흑자를 기록했다' 한 문장에서 나온
    수입액·수입 증감률까지 같이 버리게 된다(실측에서 그 둘은 정상 매핑이었다).
    """
    indicator = _lower(_first(row, "measurement_indicator", "indicator"))
    if not indicator:
        return None
    hit = _has(indicator, DERIVED_INDICATOR)
    if hit:
        return ("DERIVED_INDICATOR",
                f"'{hit}' 는 두 항목의 차이로만 얻어지는 값 — 단일 좌표로 조회할 수 없음",
                REJECT)
    return None


def intraday_market_rate(claim_text: str, row: Mapping[str, Any]):
    """특정 시각·거래일 기준 시세.

    실측: '오후 3시 30분 기준 1466.6원' 을 월평균 환율 표에 대면 값이 맞을 리 없다.
    다만 환율 실측값 자체는 일별/일중 공식 표가 있을 수 있으므로 hard reject 하지
    않고 REVIEW 로 남긴다. 전망·우려 문장은 forecast gate 에서 별도로 제외된다.
    """
    subject = _has(claim_text, MARKET_SUBJECT) or _has(
        _first(row, "measurement_indicator", "indicator"), MARKET_SUBJECT)
    if not subject:
        return None
    if TIME_OF_DAY.search(claim_text):
        return ("INTRADAY_MARKET_RATE",
                f"특정 시각 기준 {subject} — 일별/일중 공식 표 확인 전까지 REVIEW", REVIEW)
    hint = _has(claim_text, MARKET_DAILY_HINT)
    if hint and _has(claim_text, ("환율", "종가", "주가")):
        return ("DAILY_MARKET_RATE",
                f"일별 {subject} 기준({hint}) — 일별 공식 표 확인 전까지 REVIEW", REVIEW)
    return None


def single_company_metric(claim_text: str, row: Mapping[str, Any]):
    """개별 기업 하나의 실적. KOSIS 는 통계법상 개별 기업 자료를 수록하지 않는다.

    지표·품목 필드를 먼저 보고, 없으면 문장에서 찾는다. 목록이 불완전하므로
    문장에서만 걸린 경우는 REVIEW 로 남긴다(오탐 방지).
    """
    scope = _lower(_first(row, "measurement_indicator", "indicator",
                          "measurement_item", "industry_or_item"))
    company = _has(scope, SINGLE_COMPANY)
    if company:
        return ("SINGLE_COMPANY_METRIC",
                f"개별 기업({company}) 실적 — KOSIS 는 산업 집계만 수록", REJECT)
    company = _has(claim_text, SINGLE_COMPANY)
    if not company:
        return None
    subject = company_is_subject(claim_text)
    if subject and _has(claim_text, COMPANY_METRIC):
        return ("SINGLE_COMPANY_METRIC",
                f"'{subject}'가 주장의 주체 — 개별 기업 실적이지 산업 집계가 아님", REJECT)
    if _has(claim_text, COMPANY_METRIC):
        return ("POSSIBLE_COMPANY_METRIC",
                f"문장에 개별 기업({company})이 있음 — 대상이 산업 집계인지 확인 필요", REVIEW)
    return None


def company_is_subject(claim_text: str) -> str:
    """기업명 바로 뒤에 주격·화제 조사가 붙는가.

    2026-08-02 실측: 게이트가 개별 기업 실적 13문장을 통과시켰다.
    문장에 기업명이 있으면 REVIEW 로만 두고 REJECT 하지 않았기 때문이다.
    '현대차는 414만대'(주체)와 '완성차 업체들의 판매량'(집계)을 조사로 가른다.
    """
    lowered = _lower(claim_text)
    for company in SINGLE_COMPANY:
        start = 0
        while (index := lowered.find(company, start)) != -1:
            tail = lowered[index + len(company):index + len(company) + 1]
            if tail in SUBJECT_PARTICLE:
                return company
            start = index + 1
    return ""


def enumerated_companies(claim_text: str, row: Mapping[str, Any]):
    """기업을 둘 이상 열거하면 개별 기업 자료의 합이다.

    예: '완성차 5사(현대차, 기아, GM 한국사업장, KG모빌리티, 르노코리아)는 794만대를 판매'
    KOSIS 의 산업 집계와 표본·정의가 다르므로 대조할 수 없다.
    """
    lowered = _lower(claim_text)
    found = {company for company in SINGLE_COMPANY if company in lowered}
    if len(found) >= 2 and _has(claim_text, COMPANY_METRIC):
        names = ", ".join(sorted(found)[:3])
        return ("ENUMERATED_COMPANIES",
                f"개별 기업 {len(found)}곳({names}) 합계 — 산업 집계와 정의가 다름", REJECT)
    return None


def internal_document_source(claim_text: str, row: Mapping[str, Any]):
    """국회의원·언론이 기관에서 받아온 자료. 공표 통계가 아니다.

    2026-08-02 실측: 정부의 한은 일시차입 관련 7문장이 전부 이 유형이었다.
    '한은에서 제출받은 자료'는 KOSIS 어디에도 없다.
    """
    hit = _has(claim_text, INTERNAL_DOCUMENT)
    if hit:
        return ("INTERNAL_DOCUMENT_SOURCE",
                f"'{hit}' — 공표 통계가 아니라 개별 요청으로 받은 자료", REJECT)
    return None


def foreign_organization_source(claim_text: str, row: Mapping[str, Any]):
    """KOSIS 에 수록되지 않는 국제기구 자료.

    OECD·IMF 등은 KOSIS 국제통계에 일부 수록되므로 대상에서 뺐다.
    확실히 미수록인 것만 REJECT 한다.
    """
    hit = _has(claim_text, FOREIGN_ORG_ONLY)
    if hit:
        return ("FOREIGN_ORG_SOURCE",
                f"'{hit}' 발표 수치 — KOSIS 미수록 국제기구 통계", REJECT)
    return None


DETECTORS = (foreign_market, global_scope, forecast_or_plan,
             policy_parameter, branded_product_price, derived_difference,
             derived_indicator, intraday_market_rate, single_company_metric,
             enumerated_companies, internal_document_source,
             foreign_organization_source)


def scope_violation(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """KOSIS 범위 밖으로 볼 근거가 있으면 (code, reason, severity) 를 돌려준다.

    근거가 없으면 ('', '', '') — '검증 가능하다'는 보증이 아니라 '반증이 없다'는 뜻이다.
    """
    claim_text = _text(row.get("claim_text"))
    if not claim_text:
        return "", "", ""
    findings = [result for detector in DETECTORS
                if (result := detector(claim_text, row)) is not None]
    if not findings:
        return "", "", ""
    # REJECT 가 하나라도 있으면 REJECT 가 이긴다.
    for code, reason, severity in findings:
        if severity == REJECT:
            return code, reason, severity
    return findings[0]


def gate_decision(row: Mapping[str, Any]) -> dict[str, str]:
    """기존 게이트 출력에 얹을 보조 판정. 기존 코드를 덮어쓰지 않고 컬럼만 추가한다."""
    code, reason, severity = scope_violation(row)
    return {
        "scope_gate_code": code,
        "scope_gate_reason": reason,
        "scope_gate_severity": severity,
        "scope_gate_blocked": "Y" if severity == REJECT else "N",
    }


# 기사 단위로 번지는 판정. **출처 귀속만** 해당한다.
# 기사는 출처를 한 번만 밝히고 수치는 여러 문장에 흩어놓는다(실측: 한은 차입 7문장 중
# '제출받은 자료' 표현이 있는 건 1문장뿐이었다).
#
# 반대로 SINGLE_COMPANY_METRIC 은 전파하면 안 된다 — 같은 기사에 개별 기업 문장과
# 산업 집계 문장이 함께 있을 수 있고(완성차 기사가 그렇다), 전파하면 정상 주장을 잃는다.
ARTICLE_SCOPED_CODES = frozenset({"INTERNAL_DOCUMENT_SOURCE", "FOREIGN_ORG_SOURCE"})

# 문장이 스스로 출처를 밝히면 기사 단위 전파를 적용하지 않는다.
# 1차 전파가 '한국로봇산업진흥원에 따르면 로봇화 기업 2524곳'을 부당하게 막았다 —
# 같은 기사에 IFR 문장이 있었기 때문이다. 자체 출처가 있으면 그 문장의 출처다.
OWN_SOURCE_MARKERS = ("에 따르면", "가 발표한", "이 발표한", "가 밝힌", "이 밝힌",
                      "조사에 따르면", "통계에 따르면", "집계에 따르면")


def has_own_source(claim_text: str) -> bool:
    return bool(_has(claim_text, OWN_SOURCE_MARKERS))


def propagate_by_article(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """문장별 판정을 낸 뒤, 출처 귀속 판정을 같은 기사의 나머지 문장에 **표시만** 한다.

    2026-08-02 1차 시도는 전파를 REJECT 로 했다가 되돌렸다. 실측에서 두 건이
    부당하게 막혔다.
      · '한국로봇산업진흥원에 따르면 로봇화 기업 2524곳' — 출처가 IFR 이 아니다.
        로봇산업실태조사는 KOSIS 수록 국가승인통계다.
      · '2023년 국적기 국제선 여객 4720만명' — 국토부 항공통계로 확인 가능한 건인데
        같은 기사의 '본지가 분석한' 문장 때문에 번졌다.
    **한 기사가 여러 출처를 인용하는데 문장에 출처가 없으면 소속을 알 수 없다.**

    그래서 REVIEW 로만 남긴다. 어느 오류가 더 나쁜지가 기준이다 —
    범위 밖이 남으면 NEEDS_CONFIRMATION 으로 앉아 있을 뿐이지만,
    정상 주장을 빼면 분모가 줄어 커버리지가 공짜로 오른다. 후자가 더 나쁘다.

    자동 오탐 검사(실버·골드 대조)로는 이걸 못 잡는다는 것도 배웠다.
    골드가 없는 건은 검사 대상이 아니기 때문이다. 눈으로 봐야 했다.
    """
    decisions = [dict(gate_decision(row)) for row in rows]
    source_of: dict[str, tuple[str, str]] = {}
    for row, decision in zip(rows, decisions):
        article = _text(row.get("article_id"))
        if article and decision["scope_gate_code"] in ARTICLE_SCOPED_CODES:
            source_of.setdefault(article, (decision["scope_gate_code"],
                                           decision["scope_gate_reason"]))
    for row, decision in zip(rows, decisions):
        decision.setdefault("scope_gate_propagated", "N")
        decision.setdefault("article_source_hint", "")
        if decision["scope_gate_blocked"] == "Y":
            continue
        found = source_of.get(_text(row.get("article_id")))
        if not found:
            continue
        code, reason = found
        decision["article_source_hint"] = code
        decision["scope_gate_propagated"] = "Y"
        if has_own_source(_text(row.get("claim_text"))):
            # 문장이 스스로 출처를 밝히면 그 문장의 출처다. 표시만 남긴다.
            decision["scope_gate_severity"] = decision["scope_gate_severity"] or REVIEW
            decision["scope_gate_reason"] = (
                decision["scope_gate_reason"]
                or f"{reason} (같은 기사의 다른 문장 출처 — 이 문장은 자체 출처가 있다)")
            continue
        decision.update({
            "scope_gate_code": code,
            "scope_gate_reason": f"{reason} (같은 기사에서 확인된 출처, 이 문장은 자체 출처 없음)",
            "scope_gate_severity": REJECT,
            "scope_gate_blocked": "Y",
        })
    return decisions
