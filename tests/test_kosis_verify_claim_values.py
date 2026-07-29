from kosis_verify_claim_values import (
    derive_actual,
    infer_comparison_period,
    item_compatible,
    parse_number,
    unit_factor,
    verify_row,
)


def test_scientific_notation_claim_value_is_not_truncated():
    assert parse_number("1.42E+11") == 142_000_000_000


def test_base_unit_conversion_uses_multiplication_for_canonical_claim_values():
    assert unit_factor("백만달러", "달러")[0] == 1_000_000
    assert unit_factor("백만원", "원")[0] == 1_000_000
    assert unit_factor("천명", "명")[0] == 1_000
    assert unit_factor("백만달러", "원")[0] is None


def test_explicit_year_over_year_text_infers_comparison_period():
    monthly, monthly_reason = infer_comparison_period({
        "period": "202412",
        "claim_text": "12월 수출액은 전년 동월 대비 6.6% 증가했다.",
    })
    yearly, yearly_reason = infer_comparison_period({
        "period": "2024",
        "claim_text": "전체 수입이 전년 대비 1.6% 감소했다.",
    })

    assert monthly == "202312"
    assert "비교 월" in monthly_reason
    assert yearly == "2023"
    assert "비교 연도" in yearly_reason


def test_comparison_period_is_not_guessed_without_explicit_yoy_text():
    period, reason = infer_comparison_period({
        "period": "202412",
        "claim_text": "수출 증가율이 6.6%를 기록했다.",
    })
    assert period == ""
    assert reason == ""


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


def test_rate_change_accepts_kosis_index_level_item():
    row = {
        "indicator": "서비스업 생산지수",
        "semantic_type": "rate_change",
        "mapping_type": "rate_from_level",
        "unit": "%",
        "unit_dimension": "rate",
    }
    assert item_compatible("불변지수", "2020＝100", row)[0] is True


def test_rate_change_rejects_unknown_non_index_level_item():
    row = {
        "indicator": "서비스업 생산지수",
        "semantic_type": "rate_change",
        "mapping_type": "rate_from_level",
        "unit": "%",
        "unit_dimension": "rate",
    }
    assert item_compatible("기타 항목", "-", row)[0] is False


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
