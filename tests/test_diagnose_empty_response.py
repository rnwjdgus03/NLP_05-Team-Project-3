"""EMPTY_RESPONSE 를 '아직 안 나왔다' 와 '좌표가 틀렸다' 로 가른다 (2026-08-02).

이 구분이 처방을 정한다. 전자는 버그가 아니라 판정 카테고리가 필요한 것이고,
후자만 고칠 대상이다. 둘을 뭉뚱그리면 커버리지를 과소평가하고 원인도 오해한다.
"""
from datetime import date

import pytest

from diagnose_empty_response import (
    FUTURE,
    SHOULD_EXIST,
    UNKNOWN,
    UNPUBLISHED,
    _month_end,
    classify,
    months_between,
    parse_article_date,
    period_end,
)


# --------------------------------------------------------------------------
# 기사일
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["2025-01-01", "2025/01/01", "20250101",
                                 "2025-01-01T09:30:00"])
def test_article_date_formats(raw):
    assert parse_article_date(raw) == date(2025, 1, 1)


def test_unparseable_article_date_is_none():
    assert parse_article_date("") is None
    assert parse_article_date("작년") is None


def test_impossible_date_is_none():
    assert parse_article_date("2025-02-31") is None


# --------------------------------------------------------------------------
# 기간의 '마지막 날' — 통계는 구간이 끝나야 집계된다
# --------------------------------------------------------------------------

def test_annual_period_ends_in_december():
    assert period_end("2023", "Y") == date(2023, 12, 31)


def test_monthly_period_ends_on_the_last_day():
    assert period_end("202501", "M") == date(2025, 1, 31)
    assert period_end("202502", "M") == date(2025, 2, 28)


def test_leap_february():
    assert period_end("202402", "M") == date(2024, 2, 29)


def test_month_end_handles_december_without_rolling_the_year():
    assert _month_end(2024, 12) == date(2024, 12, 31)


def test_quarterly_period_ends_at_the_quarter():
    assert period_end("20241", "Q") == date(2024, 3, 31)
    assert period_end("20244", "Q") == date(2024, 12, 31)
    assert period_end("2024Q2", "Q") == date(2024, 6, 30)


def test_half_year_period():
    assert period_end("202401", "H") == date(2024, 6, 30)


def test_daily_period():
    assert period_end("20240115", "D") == date(2024, 1, 15)


def test_garbage_period_is_none():
    assert period_end("", "Y") is None
    assert period_end("작년", "Y") is None
    assert period_end("202499", "M") is None


# --------------------------------------------------------------------------
# 분류
# --------------------------------------------------------------------------

ARTICLE = date(2025, 1, 1)


def test_future_period_cannot_have_data():
    """기사일 2025-01-01 에 2025 연간을 요청한 실측 사례가 있었다."""
    cause, _ = classify(ARTICLE, period_end("2025", "Y"), "Y")
    assert cause == FUTURE


def test_annual_just_ended_is_probably_unpublished():
    """2024 연간을 2025-01-01 기사가 인용 — 하루 지났을 뿐이다."""
    cause, _ = classify(ARTICLE, period_end("2024", "Y"), "Y")
    assert cause == UNPUBLISHED


def test_old_annual_should_exist():
    cause, _ = classify(ARTICLE, period_end("2022", "Y"), "Y")
    assert cause == SHOULD_EXIST


def test_monthly_uses_a_shorter_lag_than_annual():
    """같은 시차라도 월간은 나왔고 연간은 아직일 수 있다.

    구간 종료 후 4개월 — 월간(임계 2)은 나왔고, 연간(임계 12)은 아직이다.
    """
    ends = period_end("202408", "M")
    assert classify(ARTICLE, ends, "M")[0] == SHOULD_EXIST
    assert classify(ARTICLE, ends, "Y")[0] == UNPUBLISHED


def test_month_old_monthly_data_is_still_treated_as_unpublished():
    """2024-11 데이터를 2025-01-01 기사가 인용 — 한 달 남짓이라 아직으로 본다.

    임계 2개월은 보수적 가정이다. 실제 공표 일정은 통계마다 다르다.
    """
    assert classify(ARTICLE, period_end("202411", "M"), "M")[0] == UNPUBLISHED


def test_missing_inputs_are_their_own_bucket():
    assert classify(None, period_end("2023", "Y"), "Y")[0] == UNKNOWN
    assert classify(ARTICLE, None, "Y")[0] == UNKNOWN


def test_reason_is_always_given():
    for ends in (period_end("2025", "Y"), period_end("2024", "Y"), period_end("2020", "Y")):
        _, why = classify(ARTICLE, ends, "Y")
        assert why


def test_unknown_prd_se_falls_back_to_a_default_lag():
    cause, _ = classify(ARTICLE, period_end("2024", "Y"), "")
    assert cause in {UNPUBLISHED, SHOULD_EXIST}


# --------------------------------------------------------------------------
# 개월 계산
# --------------------------------------------------------------------------

def test_months_between_counts_forward():
    assert months_between(date(2025, 1, 1), date(2024, 1, 1)) == pytest.approx(12, abs=0.1)


def test_same_day_is_zero():
    assert months_between(ARTICLE, ARTICLE) == 0
