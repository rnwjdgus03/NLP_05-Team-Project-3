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
from typing import Any, Mapping

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
PLAN = ("하겠다", "겠다고", "계획", "목표로", "추진", "집행하겠", "확대했다", "적용하고")

# 제도·정책 파라미터: 통계가 아니라 규정값.
POLICY_PARAM = ("세율", "개별소비세", "관세율", "부가세율", "법인세율", "소득세율",
                "정원", "허용 비율", "한도", "요율", "공제율", "지원 비율")

# 파생 차액을 나타내는 표현 (어간으로 잡는다 — 올랐다/올렸다/올린 등 활용형이 많다)
DIFFERENCE_HINT = ("올랐", "올렸", "올린", "내렸", "내린", "인상", "인하",
                   "늘었", "늘렸", "줄었", "줄였", "높였", "낮췄", "낮아",
                   "개선", "차이", "포인트", "급감", "급증")

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


DETECTORS = (foreign_market, global_scope, forecast_or_plan,
             policy_parameter, branded_product_price, derived_difference)


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
