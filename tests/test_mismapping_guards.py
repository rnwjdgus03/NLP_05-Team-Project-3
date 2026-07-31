"""이중 게이트 해제 직후 실측된 오매핑 4건을 막는 보완 장치.

READY 12건을 검수했더니 4건이 오매핑이었고, 그중 2건이 자동 '불일치'까지 갔다.
팩트체크에서 맞는 기사를 틀렸다고 하는 것이 최악이므로 두 겹으로 막는다.
  ① 주장이 세부 대상을 말하지 않으면 좌표도 집계값이어야 한다  (확정 단계)
  ② 차이율이 비상식적으로 크면 매핑 오류를 먼저 의심한다        (판정 단계)
"""
from kosis_validate_mapping_candidates import (
    claim_item_matches_selection,
    selection_is_aggregate,
)
from kosis_verify_claim_values import MISMAPPING_PCT, extreme_error


# --------------------------------------------------------------------------
# ① 집계 규칙 — 실측 오매핑 재현
# --------------------------------------------------------------------------

def test_trade_balance_claim_must_not_map_to_construction_subcategory():
    """'무역수지 518억달러 흑자' → 기술무역수지 / objL1=건설 (실측 오매핑)."""
    row = {"indicator": "무역수지", "measurement_item": ""}
    result = {"selected_itm_name": "기관유형별 산업별 기술무역수지 추이",
              "selected_obj_l1_name": "건설"}
    assert claim_item_matches_selection(row, result) is False


def test_overall_price_claim_must_not_map_to_housing_subcategory():
    """'성장률과 물가 상승률' → 소비자물가지수 / objL1=자가주거비 (실측 오매핑)."""
    row = {"indicator": "물가 상승률", "measurement_item": ""}
    result = {"selected_itm_name": "소비자물가지수", "selected_obj_l1_name": "자가주거비"}
    assert claim_item_matches_selection(row, result) is False


def test_unqualified_claim_passes_when_coordinate_is_aggregate():
    row = {"indicator": "무역수지", "measurement_item": ""}
    result = {"selected_itm_name": "수입액", "selected_obj_l1_name": "총액"}
    assert claim_item_matches_selection(row, result) is True


def test_aggregate_names_are_recognized():
    for name in ("계", "전체", "총계", "총액", "전국", "소계"):
        assert selection_is_aggregate({"selected_obj_l1_name": name}) is True
    assert selection_is_aggregate({"selected_obj_l1_name": "건설"}) is False


def test_missing_obj_axis_counts_as_aggregate():
    """분류축이 없는 표는 집계로 본다 — 없는 축을 이유로 막으면 안 된다."""
    assert selection_is_aggregate({}) is True


def test_every_level_must_be_aggregate():
    result = {"selected_obj_l1_name": "전국", "selected_obj_l2_name": "제조업"}
    assert selection_is_aggregate(result) is False


def test_itemized_claim_still_uses_the_old_path():
    """품목을 특정한 주장은 기존 토큰 매칭으로 판단한다(집계 규칙을 적용하지 않는다)."""
    row = {"indicator": "반도체 수출", "measurement_item": "반도체"}
    ok = {"selected_itm_name": "수출액", "selected_obj_l1_name": "반도체"}
    bad = {"selected_itm_name": "인산에스테르 및 그 염", "selected_obj_l1_name": "화학"}
    assert claim_item_matches_selection(row, ok) is True
    assert claim_item_matches_selection(row, bad) is False


# --------------------------------------------------------------------------
# ② 극단 오차 — 기사 오류로 단정하지 않는다
# --------------------------------------------------------------------------

def test_absurd_difference_is_flagged_as_probable_mismapping():
    """무역흑자 518억달러를 수입액 6320억달러에 대면 1,120%."""
    assert extreme_error(51_800_000_000, 632_000_000_000) is True


def test_rate_claims_use_percentage_points_not_ratio():
    """증감률 8.2% 와 42.5% 는 상대오차 418% 지만 둘 다 실재할 수 있는 값이다.

    비율 기준을 그대로 쓰면 평범한 불일치를 '매핑 오류'로 덮어버린다.
    """
    assert extreme_error(8.2, 42.5, rate_like=True) is False
    assert extreme_error(8.2, 42.5, rate_like=False) is True    # 수준값이었다면 이상


def test_absurd_rate_gap_is_still_flagged():
    assert extreme_error(2.0, 150.0, rate_like=True) is True


def test_small_discrepancy_is_not_flagged():
    assert extreme_error(100.0, 103.0) is False


def test_threshold_boundary():
    assert extreme_error(100.0, 400.0) is True       # 정확히 300%
    assert extreme_error(100.0, 399.0) is False


def test_none_values_do_not_raise():
    assert extreme_error(None, 100.0) is False
    assert extreme_error(100.0, None) is False


def test_zero_claim_value_does_not_divide_by_zero():
    assert extreme_error(0.0, 5.0) is True


def test_threshold_is_configurable():
    assert extreme_error(100.0, 250.0, threshold=100.0) is True
    assert extreme_error(100.0, 250.0, threshold=MISMAPPING_PCT) is False
