"""주장의 모양이 우리 좌표 모델로 표현 가능한가 (2026-08-04).

홀드아웃 50건에서 확정 4건이 전부 '불일치'로 나왔고 **넷 다 오판이었다.**
기사는 맞았고 파이프라인이 다른 것을 물어봤다.

`extreme_error` 가드는 이걸 못 잡는다. 그 가드의 문턱은 증감률 100%p / 수준값 300%
인데 네 건의 차이는 6.1%p · 11.5% · 9.2%p · 34.5%p 로 **그럴듯해 보이기** 때문이다.
값을 비교하기 전에 주장의 모양을 보고 빼야 한다.

## 전수 측정 (첫 50건 88건 기준)

10건이 걸리고, 그중 **'일치'였던 것은 0건**이다. 확정 1건은 판정보류였다.
기존 성과를 깎지 않는다는 뜻이다.
"""
import pandas as pd
import pytest

from kosis_claim_shape import (claim_shape_exclusion, cumulative_period,
                               period_granularity_mismatch, share_claim)


# --------------------------------------------------------------------------
# 누적 기간 — 홀드아웃 [2]
# --------------------------------------------------------------------------

def test_cumulative_months_are_caught():
    text = "작년 1~11월 반도체 수출(1274억달러) 가운데 중국 비율은 33.3%로 나타났다."
    assert cumulative_period(text, "Y")


@pytest.mark.parametrize("text", [
    "2024년 1~9월 기준(WTO)으로 전 세계 수출순위도 6위를 달성했다.",
    "1월부터 11월까지 수출은 6000억달러였다.",
    "11월 누적 기준 수출은 6000억달러였다.",
])
def test_other_cumulative_forms(text):
    assert cumulative_period(text, "Y")


def test_monthly_claims_are_untouched():
    """월 단위로 물어보면 누적이 아니다. prd_se 가 M 이면 그대로 둔다."""
    assert not cumulative_period("작년 1~11월 수출은 1274억달러였다.", "M")


def test_plain_annual_claim_is_untouched():
    assert not cumulative_period("작년 한 해 수출액이 6838억달러였다.", "Y")


# --------------------------------------------------------------------------
# 구성비 — 홀드아웃 [3][4]
# --------------------------------------------------------------------------

def test_share_of_exports_is_caught():
    assert share_claim("중국과 홍콩으로의 반도체 수출 비율 합계", "")


@pytest.mark.parametrize("indicator", [
    "전시 분야 비중", "조선 산업기술인력 중 외국인의 비율",
    "중소제조업체 자금 조달 어려움 비율", "상승 품목 비율",
])
def test_share_indicators_from_the_first_50(indicator):
    assert share_claim(indicator, "")


@pytest.mark.parametrize("indicator", [
    "수출액 증감률", "총수출액 증감률", "국내 판매 감소율", "수출 증가율",
    "성장률과 물가 상승률", "실업률", "고용률", "공실률",
])
def test_rate_indicators_are_not_shares(indicator):
    """'증감률'·'실업률' 은 구성비가 아니다. 이걸 빼면 첫 50건의 '일치' 가 죽는다."""
    assert not share_claim(indicator, "")


def test_level_indicators_are_not_shares():
    for indicator in ("수출액", "수입액", "반도체 수출액", "국제선 이용객 총수"):
        assert not share_claim(indicator, "")


# --------------------------------------------------------------------------
# 기간 단위 — 홀드아웃 [1]
# --------------------------------------------------------------------------

def test_year_qualified_quarter_is_caught():
    text = ("소매판매액지수는 2024년 3분기 100.6으로 1년 전보다 1.9% 감소했는데, "
            "2022년 2분기(-0.2%) 이래 10개 분기 연속으로 감소세가 이어지고 있다.")
    assert period_granularity_mismatch(text, "Y", "2022")


def test_a_bare_half_year_mention_is_not_enough():
    """1차 시도가 이걸로 과잉 발동했다. 이건 **연간** 주장이고 '하반기' 는 원인 설명이다."""
    text = ("자동차 수출은 하반기 주요 완성차·부품업계 파업 등에 따른 일부 생산 차질 영향으로 "
            "전년도와 보합세인 708억 달러(-0.1%)를 기록하였다.")
    assert not period_granularity_mismatch(text, "Y", "2024")


def test_another_bare_mention():
    text = "석유화학 수출은 480억 달러로, 하반기 유가 하락에도 수출물량이 확대되면서 5% 증가했다."
    assert not period_granularity_mismatch(text, "Y", "2024")


def test_a_different_year_does_not_fire():
    """문장의 분기가 다른 해면 이 측정과 무관하다."""
    assert not period_granularity_mismatch("2022년 2분기(-0.2%) 이래", "Y", "2024")


def test_quarterly_prd_se_is_untouched():
    assert not period_granularity_mismatch("2022년 2분기(-0.2%) 이래", "Q", "2022")


# --------------------------------------------------------------------------
# 통합
# --------------------------------------------------------------------------

def test_exclusion_returns_a_code_and_a_reason():
    row = {"claim_text": "작년 1~11월 반도체 수출은 1274억달러였다.",
           "measurement_prd_se": "Y", "measurement_indicator": "반도체 수출 총액",
           "measurement_period": "2024"}
    code, reason = claim_shape_exclusion(row)
    assert code == "CUMULATIVE_PERIOD_UNSUPPORTED"
    assert reason


def test_clean_claim_passes():
    row = {"claim_text": "작년 한 해 전체 수출액이 6838억달러로 8.2% 증가했다.",
           "measurement_prd_se": "Y", "measurement_indicator": "총수출액 증감률",
           "measurement_period": "2024"}
    assert claim_shape_exclusion(row) == ("", "")


# --------------------------------------------------------------------------
# 회귀 — 첫 50건의 '일치' 7건은 하나도 빠지면 안 된다
# --------------------------------------------------------------------------

MATCHED_FROM_THE_FIRST_50 = [
    ("총수출액", "작년 한 해 전체 수출액이 6838억달러(약 1006조원)로 2023년에 비해 8.2% 증가했다"),
    ("총수출액 증감률", "작년 한 해 전체 수출액이 6838억달러(약 1006조원)로 8.2% 증가했다"),
    ("수입액", "작년 한국의 수입액은 전년보다 1.6% 감소한 6320억달러로 무역 흑자를 기록했다."),
    ("수입액 증감률", "작년 한국의 수입액은 전년보다 1.6% 감소한 6320억달러였다."),
    ("수출액", "주력 수출 품목인 반도체 수출액이 1419억달러로 역대 최대치를 고쳐 썼다."),
    ("전체 수입 증감률", "2024년에는 에너지 수입이 감소하면서 전체 수입이 전년 대비 1.6% 감소했다."),
    ("국내 판매 감소율", "해외 판매가 1% 늘었지만, 국내 판매량은 4.2% 줄었다."),
]


@pytest.mark.parametrize("indicator,text", MATCHED_FROM_THE_FIRST_50)
def test_previously_matched_claims_still_pass(indicator, text):
    row = {"claim_text": text, "measurement_prd_se": "Y",
           "measurement_indicator": indicator, "measurement_period": "2024"}
    assert claim_shape_exclusion(row) == ("", "")
