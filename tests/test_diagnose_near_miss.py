"""NEAR_MISS 원인 분류 테스트 (2026-08-01).

목적: 사람이 라벨하기 전에 **버그로 설명되는 것**을 먼저 걸러낸다.
분류는 추정이 아니라 산술이어야 한다 — 그래야 오늘처럼 추측으로 틀리지 않는다.
"""
from diagnose_near_miss import (
    FIXABLE,
    best_row,
    classify_gap,
    diagnose,
    display_ulp,
)


# --------------------------------------------------------------------------
# 표시 자릿수
# --------------------------------------------------------------------------

def test_display_ulp_from_decimals():
    assert display_ulp("1.6") == 0.1
    assert display_ulp("-0.45") == 0.01
    assert display_ulp("2") == 1.0
    assert display_ulp("6,838") == 1.0


# --------------------------------------------------------------------------
# 부호 문제 — 고치면 승격 가능
# --------------------------------------------------------------------------

def test_sign_flip_with_similar_magnitude():
    code, why = classify_gap(0.4, -0.41, "0.4")
    assert code == "SIGN_MISMATCH" and "부호" in why


def test_sign_flip_with_very_different_magnitude_is_not_sign_issue():
    """부호가 달라도 크기가 3배 차이면 부호 문제로 단정할 수 없다."""
    code, _ = classify_gap(0.4, -12.0, "0.4")
    assert code != "SIGN_MISMATCH"


def test_same_sign_is_never_sign_mismatch():
    code, _ = classify_gap(-1.6, -1.68, "-1.6")
    assert code != "SIGN_MISMATCH"


# --------------------------------------------------------------------------
# 배율 문제 — 고치면 승격 가능
# --------------------------------------------------------------------------

def test_thousand_scale_is_detected():
    code, why = classify_gap(145.0, 145000.0, "145")
    assert code == "SCALE_MISMATCH" and "10^3" in why


def test_ten_thousand_scale_is_detected():
    code, _ = classify_gap(6838.0, 68380000.0, "6838")
    assert code == "SCALE_MISMATCH"


def test_near_but_not_exact_power_of_ten_is_not_scale():
    """1.5배는 배율 문제가 아니다 — 단위가 아니라 값이 다른 것."""
    code, _ = classify_gap(100.0, 150.0, "100")
    assert code != "SCALE_MISMATCH"


# --------------------------------------------------------------------------
# 반올림 / 작은 차이
# --------------------------------------------------------------------------

def test_gap_within_display_unit_is_rounding():
    """기사 '-1.6' 은 소수 1자리 표기 → 0.1 이내 차이는 반올림 수준."""
    code, why = classify_gap(-1.6, -1.68, "-1.6")
    assert code == "DISPLAY_ROUNDING" and "표시 단위" in why


def test_small_relative_gap_is_explainable():
    code, why = classify_gap(100.0, 105.0, "100")
    assert code == "SMALL_GAP" and "5.00%" in why


def test_large_gap_points_at_wrong_coordinate():
    code, why = classify_gap(100.0, 400.0, "100")
    assert code == "LARGE_GAP" and "좌표" in why


# --------------------------------------------------------------------------
# 방어
# --------------------------------------------------------------------------

def test_missing_value_is_not_classified():
    assert classify_gap(None, 1.0, "")[0] == "NO_VALUE"
    assert classify_gap(1.0, None, "1")[0] == "NO_VALUE"


def test_zero_claim_does_not_divide_by_zero():
    code, _ = classify_gap(0.0, 5.0, "0")
    assert code == "LARGE_GAP"


def test_fixable_set_covers_only_bug_causes():
    """반올림·개정은 버그가 아니므로 '고치면 승격' 으로 세면 안 된다."""
    assert FIXABLE == {"SIGN_MISMATCH", "SCALE_MISMATCH"}


# --------------------------------------------------------------------------
# measurement 당 최선 후보 선택
# --------------------------------------------------------------------------

def _row(mid, claim, actual, **kw):
    base = {"claim_measurement_id": mid, "claim_value": str(claim),
            "kosis_actual_value": str(actual), "verdict": "판정보류",
            "tbl_id": "T1", "tbl_name": "표", "selected_itm_name": "항목",
            "selected_obj_l1": "1", "mapping_type": "direct", "claim_text": "문장"}
    base.update(kw)
    return base


def test_closest_coordinate_is_chosen():
    rows = [_row("M1", 100, 400, tbl_id="T_FAR"), _row("M1", 100, 101, tbl_id="T_NEAR")]
    assert best_row(rows)["tbl_id"] == "T_NEAR"


def test_rows_without_numbers_do_not_crash():
    assert best_row([_row("M1", "", "")]) is not None


# --------------------------------------------------------------------------
# 통합 — NEAR_MISS 만 대상으로 한다
# --------------------------------------------------------------------------

SILVER = [{"claim_measurement_id": "M1", "tier": "NEAR_MISS"},
          {"claim_measurement_id": "M2", "tier": "NO_MATCH"},
          {"claim_measurement_id": "M3", "tier": "SILVER_UNIQUE"}]


def test_only_near_miss_measurements_are_diagnosed():
    review = [_row("M1", 100, 101), _row("M2", 100, 999), _row("M3", 100, 100)]
    result = diagnose(SILVER, review)
    assert [r["claim_measurement_id"] for r in result] == ["M1"]


def test_non_deferred_verdicts_are_ignored():
    review = [_row("M1", 100, 101, verdict="불일치")]
    assert diagnose(SILVER, review) == []


def test_fixable_flag_is_set():
    review = [_row("M1", 0.4, -0.41)]
    result = diagnose(SILVER, review)
    assert result[0]["cause"] == "SIGN_MISMATCH"
    assert result[0]["fixable"] == "Y"


def test_rounding_is_not_marked_fixable():
    review = [_row("M1", -1.6, -1.68)]
    result = diagnose(SILVER, review)
    assert result[0]["cause"] == "DISPLAY_ROUNDING"
    assert result[0]["fixable"] == "N"
