"""REVISION_VINTAGE_RISK 정책 조임 (2026-07-31).

문제: READY 9건 중 5건(56%)이 이 사유로 보류됐다. 보류가 과반이면 판정 회피에 가깝다.

원인 진단: `LST_CHN_DE` 는 **표 전체의 최종 수정일**이라 월간 표는 새 달 데이터가
붙을 때마다 갱신된다. 그래서 '개정일 > 기사일' 조건은 최근 기사에 대해 거의 항상 참이다.

조임 두 가지 (둘 다 개정을 '핑계'로 쓰지 못하게 한다):
  ① 관측 시점이 아직 잠정치 구간에 있어야 한다
  ② 차이 크기가 개정으로 설명될 만해야 한다
"""
from kosis_verify_claim_values import (
    REVISION_MAX_LEVEL_PCT,
    REVISION_MAX_RATE_POINT,
    months_between,
    revision_explains_gap,
    revision_vintage_risk,
    within_revision_window,
)

DATA = [{"PRD_DE": "2024", "LST_CHN_DE": "2025-05-16", "DT": "100"}]


def _row(**kw):
    base = {"date": "2025-01-01", "value_type": "증감률"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 기간 계산
# --------------------------------------------------------------------------

def test_months_between_handles_monthly_period():
    assert months_between("20250101", "202412") == 1
    assert months_between("20250102", "202409") == 4


def test_annual_period_ends_in_december():
    assert months_between("20250101", "2024") == 1


def test_unparseable_period_returns_none():
    assert months_between("20250101", "") is None


# --------------------------------------------------------------------------
# ① 잠정치 구간
# --------------------------------------------------------------------------

def test_recent_observation_is_inside_the_window():
    """신년 기사가 직전 월 통계를 다루는 것 — 실제 잠정치 구간이다."""
    assert within_revision_window("20250101", "202412") is True


def test_old_observation_is_outside_the_window():
    """2025년 기사가 2020년 통계를 인용하면 이미 확정치다 — 개정 핑계 금지."""
    assert within_revision_window("20250101", "202001") is False


def test_window_boundary():
    assert within_revision_window("20250101", "202301", months=24) is True
    assert within_revision_window("20250101", "202212", months=24) is False


def test_unknown_period_stays_permissive():
    """판단 불가하면 기존 동작을 유지한다(조임이 새 오탐을 만들면 안 된다)."""
    assert within_revision_window("20250101", "") is True


# --------------------------------------------------------------------------
# ② 개정으로 설명 가능한 크기
# --------------------------------------------------------------------------

def test_small_rate_gap_is_explainable():
    """수입 -1.6% vs -1.68% (0.08%p) — 잠정→확정 개정으로 설명 가능."""
    assert revision_explains_gap(-1.6, -1.68, rate_like=True) is True


def test_large_rate_gap_is_not_explainable():
    """증감률이 10%p 어긋난 것을 개정 탓으로 돌리면 판정 회피다."""
    assert revision_explains_gap(2.0, 12.0, rate_like=True) is False


def test_rate_boundary():
    assert revision_explains_gap(0.0, REVISION_MAX_RATE_POINT, rate_like=True) is True
    assert revision_explains_gap(0.0, REVISION_MAX_RATE_POINT + 0.1, rate_like=True) is False


def test_level_gap_uses_relative_scale():
    assert revision_explains_gap(1000.0, 1050.0, rate_like=False) is True    # 5%
    assert revision_explains_gap(1000.0, 1500.0, rate_like=False) is False   # 50%


def test_level_boundary():
    assert revision_explains_gap(100.0, 100 + REVISION_MAX_LEVEL_PCT, rate_like=False) is True


def test_unknown_values_stay_permissive():
    assert revision_explains_gap(None, 1.0, rate_like=True) is True


# --------------------------------------------------------------------------
# 통합 — 실측 사례가 그대로 유지되는지 / 남용이 막히는지
# --------------------------------------------------------------------------

def test_measured_case_still_defers():
    """실측: 수입 -1.6% vs -1.68%, 기사 2025-01-01, 관측 2024 → 보류 유지."""
    revised, article = revision_vintage_risk(
        _row(), DATA, "rate_from_level", "2024", "2023",
        claim_value=-1.6, actual_value=-1.68)
    assert revised and article == "20250101"


def test_stale_observation_no_longer_defers():
    """관측이 확정 구간이면 개정을 핑계로 보류하지 않는다."""
    data = [{"PRD_DE": "202001", "LST_CHN_DE": "2025-05-16"}]
    revised, _ = revision_vintage_risk(
        _row(), data, "rate_from_level", "202001", "201912",
        claim_value=1.0, actual_value=2.0)
    assert revised == ""


def test_unexplainable_gap_no_longer_defers():
    """개정으로 설명 못 할 차이는 불일치로 남긴다."""
    revised, _ = revision_vintage_risk(
        _row(), DATA, "rate_from_level", "2024", "2023",
        claim_value=2.0, actual_value=30.0)
    assert revised == ""


def test_non_rate_claim_is_untouched():
    revised, _ = revision_vintage_risk(
        _row(value_type="수준값"), DATA, "direct", "2024", "2023",
        claim_value=1.0, actual_value=1.1)
    assert revised == ""


def test_backward_compatible_without_values():
    """값을 안 넘기면 기존 5인자 호출과 동일하게 동작해야 한다."""
    revised, _ = revision_vintage_risk(_row(), DATA, "rate_from_level", "2024", "2023")
    assert revised
