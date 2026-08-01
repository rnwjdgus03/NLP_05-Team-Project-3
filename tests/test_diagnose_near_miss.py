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


def test_fixable_covers_only_our_side_problems():
    """'고치면 비교 가능' 은 우리 쪽 결함만 세야 한다.

    반올림·개정·좌표오류는 우리가 고칠 수 있는 게 아니므로 넣지 않는다.
    """
    assert FIXABLE == {"SIGN_MISMATCH", "SCALE_MISMATCH", "UNIT_UNCONVERTIBLE"}
    for not_ours in ("DISPLAY_ROUNDING", "SMALL_GAP", "LARGE_GAP", "NO_DATA_IN_PERIOD"):
        assert not_ours not in FIXABLE


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


# --------------------------------------------------------------------------
# 부호 적용 결과를 읽는다 (2026-08-01 수정)
#
# review CSV 의 claim_value 는 **부호 적용 전** 원본이다. 그대로 비교하면
# 정상 판정을 SIGN_MISMATCH 로 오분류한다 — 실측에서 2건이 그렇게 잘못 잡혔다.
# 검증기가 실제로 쓴 값은 verdict_reason 에 '(방향부호 적용: claim=-1.6)' 로 남는다.
# --------------------------------------------------------------------------

from diagnose_near_miss import effective_claim_value, no_value_cause


def test_signed_claim_is_read_from_verdict_reason():
    value, raw = effective_claim_value(
        {"claim_value": "1.6",
         "verdict_reason": "차이=0.0815 (방향부호 적용: claim=-1.6) (KOSIS 개정일…)"})
    assert value == -1.6 and raw == "-1.6"


def test_raw_value_is_used_when_no_sign_applied():
    value, raw = effective_claim_value({"claim_value": "6838", "verdict_reason": "차이=1.9"})
    assert value == 6838.0 and raw == "6838"


def test_real_case_is_rounding_not_sign_mismatch():
    """실측 오분류 재현: 기사 1.6(원본) / KOSIS -1.68 → 부호 적용하면 반올림 수준."""
    row = {"claim_value": "1.6", "kosis_actual_value": "-1.68151038036",
           "verdict_reason": "차이=0.0815104 (방향부호 적용: claim=-1.6)"}
    value, raw = effective_claim_value(row)
    code, _ = classify_gap(value, float(row["kosis_actual_value"]), raw)
    assert code == "DISPLAY_ROUNDING"


# --------------------------------------------------------------------------
# 값이 없는 경우의 원인을 가른다 — 좌표 문제와 섞지 않는다
# --------------------------------------------------------------------------

def test_unit_failure_is_separated_from_coordinate_problem():
    code, why = no_value_cause(
        {"verdict_code": "UNIT_UNCERTAIN", "verdict_reason": "단위 비호환 → 후보 유지"})
    assert code == "UNIT_UNCONVERTIBLE" and "좌표 문제가 아니다" in why


def test_missing_period_data_is_its_own_cause():
    code, _ = no_value_cause(
        {"verdict_code": "ACTUAL_DERIVATION_FAILED", "verdict_reason": "조회 데이터 없음"})
    assert code == "NO_DATA_IN_PERIOD"


def test_unknown_cause_keeps_the_code_for_tracing():
    code, why = no_value_cause({"verdict_code": "SOMETHING_NEW", "verdict_reason": ""})
    assert code == "NO_VALUE_OTHER" and "SOMETHING_NEW" in why


def test_unit_failure_counts_as_fixable():
    """단위 변환은 우리 쪽 문제다 — 사람이 라벨할 대상이 아니다."""
    assert "UNIT_UNCONVERTIBLE" in FIXABLE


def test_comparable_candidate_wins_over_unit_failed_one():
    rows = [_row("M1", 100, "", verdict_reason="단위 비호환", tbl_id="T_UNIT"),
            _row("M1", 100, 101, tbl_id="T_OK")]
    assert best_row(rows)["tbl_id"] == "T_OK"
