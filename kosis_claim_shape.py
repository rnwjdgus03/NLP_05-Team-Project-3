"""주장의 '모양'이 우리 좌표 모델로 표현 가능한가 (2026-08-04).

홀드아웃 50건에서 확정 4건이 전부 불일치로 나왔고 **넷 다 오판이었다.**
기사는 맞았고 파이프라인이 다른 것을 물어봤다.

  1. 소매판매액지수 '2022년 **2분기** -0.2%'  → 2022년 **연간** +5.88% 와 대조
  2. 반도체 수출 '**1~11월** 1274억달러'      → 2024년 **12개월** 1420억과 대조
  3. 중국+홍콩 '**비율** 51.7%'               → 반도체 수출액 총계에서 증감률 계산
  4. 미국+대만 비율 변화 '8%p'                → 위와 같은 좌표

`extreme_error` 가드는 이걸 못 잡는다. 그 가드는 좌표를 통째로 잘못 잡은 경우
(무역흑자 518억 ↔ 수입액 6320억, 차이율 1,120%)를 잡으라고 만든 것이고,
위 네 건의 차이는 6.1%p · 11.5% · 9.2%p · 34.5%p 로 **그럴듯해 보인다.**

값을 비교하기 **전에** 주장의 모양을 보고 빼는 편이 맞다.
셋 다 커버리지를 늘리는 것이 아니라 **잘못된 확정을 빼는** 방향이다.

넓히면 정당한 주장이 죽는다. 전례가 둘 있다 —
추출 프롬프트 품목 규칙(50%→22%), 1차 출처 전파(로봇산업진흥원).
**바꾸기 전에 두 평가 집합 모두에서 재고, 기존 '일치' 가 하나도 안 빠지는지 확인할 것.**
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# 1. 누적 기간 — '1~11월', '1∼9월 누적'
# --------------------------------------------------------------------------
# KOSIS 는 월 단위 합산으로 답할 수 있지만 **우리 좌표 모델에 그 개념이 없다.**
# 연간값과 대면 빠진 개월 수만큼 어긋난다(실측: 11.5% = 12월 한 달).
_CUMULATIVE = re.compile(
    r"(?<!\d)\d{1,2}\s*[~∼〜–—-]\s*\d{1,2}\s*월"      # 1~11월
    r"|\d{1,2}\s*월\s*(?:까지|누적)"                    # 11월까지 / 11월 누적
    r"|\d{1,2}\s*월\s*부터\s*\d{1,2}\s*월"              # 1월부터 11월
    r"|누적\s*(?:기준|치|액|량)"
)

# --------------------------------------------------------------------------
# 2. 구성비 — '중국 비율 33.3%', '둘을 합해 51.7%'
# --------------------------------------------------------------------------
# 분자(국가별)와 분모(총계)가 **둘 다** 필요하다. 지금 좌표는 하나만 가리킨다.
# '증감률'·'증가율'·'실업률' 은 구성비가 아니다. 반드시 제외해야 한다.
_SHARE_WORDS = ("비율", "비중", "점유율", "구성비", "차지하는", "차지했")
_NOT_SHARE = ("증감률", "증가율", "감소율", "상승률", "하락률", "성장률",
              "실업률", "고용률", "출산율", "이자율", "환율", "가동률", "공실률")
_SHARE_CONTEXT = re.compile(r"(가운데|중)\s*[^.]{0,40}?\d+(?:\.\d+)?\s*%")

# --------------------------------------------------------------------------
# 3. 기간 단위 — 문장은 분기인데 prd_se 가 연간
# --------------------------------------------------------------------------
# 문장에 '분기' 라는 말이 있다는 것만으로는 부족하다. 1차 시도가 이걸로 과잉 발동했다 —
#   '자동차 수출은 **하반기** 파업 영향으로 전년도와 보합세인 708억 달러(-0.1%)'
# 이건 **연간** 주장이고 '하반기' 는 원인 설명이다. 석유화학 문장도 같다.
# 그래서 **연도가 붙은** 분기·반기 표현이 추출된 기간과 **같은 해** 일 때만 잡는다.
#   '2022년 2분기(-0.2%)' + period=2022 + prd_se=Y  → 잡는다
#   '하반기 유가 하락'      + period=2024            → 안 잡는다
_YEAR_QUARTER = re.compile(r"(\d{4})\s*년\s*(?:\d\s*/?\s*4?\s*분기|상반기|하반기)")


def _t(value) -> str:
    return "" if value is None else str(value).strip()


def cumulative_period(claim_text, prd_se) -> bool:
    """부분 누적 기간을 연간 좌표로 물어보려 하는가."""
    if _t(prd_se).upper() != "Y":
        return False
    return bool(_CUMULATIVE.search(_t(claim_text)))


def share_claim(indicator, claim_text) -> bool:
    """분자와 분모가 둘 다 필요한 구성비 주장인가."""
    ind = _t(indicator)
    if any(word in ind for word in _NOT_SHARE):
        return False
    if any(word in ind for word in _SHARE_WORDS):
        return True
    text = _t(claim_text)
    if any(word in text for word in _NOT_SHARE):
        return False
    return bool(any(w in text for w in ("비율", "비중", "점유율"))
                and _SHARE_CONTEXT.search(text))


def period_granularity_mismatch(claim_text, prd_se, period=None) -> bool:
    """추출된 그 해가 문장에서는 분기·반기로 한정돼 있는가."""
    if _t(prd_se).upper() != "Y":
        return False
    year = re.sub(r"\D", "", _t(period))[:4]
    if len(year) != 4:
        return False
    return any(match.group(1) == year
               for match in _YEAR_QUARTER.finditer(_t(claim_text)))


CODES = {
    "CUMULATIVE_PERIOD_UNSUPPORTED":
        "부분 누적 기간(1~11월 등)은 연간 좌표로 확인할 수 없다",
    "SHARE_CLAIM_UNSUPPORTED":
        "구성비 주장은 분자·분모 축이 둘 다 필요해 현재 좌표 모델로 표현할 수 없다",
    "PERIOD_GRANULARITY_MISMATCH":
        "문장은 분기·반기인데 연간으로 추출됐다",
}


def claim_shape_exclusion(row) -> tuple[str, str]:
    """빼야 할 모양이면 (코드, 사유). 아니면 ('', '')."""
    text = row.get("claim_text")
    prd_se = row.get("measurement_prd_se") or row.get("prd_se")
    indicator = row.get("measurement_indicator") or row.get("indicator")

    if cumulative_period(text, prd_se):
        return "CUMULATIVE_PERIOD_UNSUPPORTED", CODES["CUMULATIVE_PERIOD_UNSUPPORTED"]
    if share_claim(indicator, text):
        return "SHARE_CLAIM_UNSUPPORTED", CODES["SHARE_CLAIM_UNSUPPORTED"]
    period = row.get("measurement_period") or row.get("period")
    if period_granularity_mismatch(text, prd_se, period):
        return "PERIOD_GRANULARITY_MISMATCH", CODES["PERIOD_GRANULARITY_MISMATCH"]
    return "", ""
