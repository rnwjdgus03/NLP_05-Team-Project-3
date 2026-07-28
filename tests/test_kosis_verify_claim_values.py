from kosis_verify_claim_values import (
    annual_context_month_period_mismatch,
    derive_actual,
    judge,
    unit_factor,
    verify_row,
)


def test_base_unit_conversion_uses_multiplication_for_canonical_claim_values():
    assert unit_factor("백만달러", "달러")[0] == 1_000_000
    assert unit_factor("백만원", "원")[0] == 1_000_000
    assert unit_factor("천명", "명")[0] == 1_000
    assert unit_factor("백만달러", "원")[0] is None


def test_rate_from_monthly_flow_uses_previous_year_sum():
    rows = [
        {"PRD_DE": "202301", "DT": "40"},
        {"PRD_DE": "202302", "DT": "60"},
        {"PRD_DE": "202401", "DT": "50"},
        {"PRD_DE": "202402", "DT": "70"},
    ]
    row = {
        "indicator": "반도체 수출액",
        "mapping_type": "rate_from_level",
        "comparison_period": "2023",
    }
    actual, current, previous, reason = derive_actual(rows, "M", "2024", row)
    assert actual == 20
    assert current == "202401+202402"
    assert previous == "202301+202302"
    assert "증감률" in reason


def test_stock_measurement_uses_latest_not_sum():
    rows = [
        {"PRD_DE": "202401", "DT": "100"},
        {"PRD_DE": "202402", "DT": "110"},
    ]
    row = {"indicator": "정비사 수", "mapping_type": "direct"}
    actual, period, _, reason = derive_actual(rows, "M", "2024", row)
    assert actual == 110
    assert period == "202402"
    assert "latest" in reason


def test_non_ready_candidate_stops_before_api_call():
    row = {
        "candidate_rank": "1",
        "candidate_status": "REVIEW",
        "candidate_status_code": "AMBIGUOUS_TABLE",
        "candidate_status_reason": "1·2위 점수 차이 부족",
        "value": "10",
    }
    out = verify_row(row, {}, 0)
    assert out["verdict"] == "판단불가"
    assert out["verdict_code"] == "AMBIGUOUS_TABLE"
    assert out["verdict_stage"] == "candidate"


def test_near_miss_rate_goes_to_tolerance_review():
    verdict, reason = judge(20.6, 19.58, tolerance_abs=0.5, tolerance_pct=1.0,
                            pending_abs=1.5, pending_pct=10.0)
    assert verdict == "판정보류"
    assert "오차범위" in reason


def test_annual_context_month_period_is_reviewed():
    mismatch, reason = annual_context_month_period_mismatch({
        "period": "202301",
        "claim_text": "2023년 국제선을 이용한 여객 4720만여 명 가운데 저비용항공사 이용객이 늘었다.",
    })
    assert mismatch is True
    assert "월 단위" in reason


def test_explicit_month_context_is_not_reviewed():
    mismatch, _ = annual_context_month_period_mismatch({
        "period": "202301",
        "claim_text": "2023년 1월 국제선을 이용한 여객이 늘었다.",
    })
    assert mismatch is False
