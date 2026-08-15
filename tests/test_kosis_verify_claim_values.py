from kosis_verify_claim_values import (
    derive_actual,
    infer_comparison_period,
    item_compatible,
    parse_number,
    unit_factor,
    validated_matching_rows,
    verify_row,
)


def test_scientific_notation_claim_value_is_not_truncated():
    assert parse_number("1.42E+11") == 142_000_000_000


def test_base_unit_conversion_uses_multiplication_for_canonical_claim_values():
    assert unit_factor("백만달러", "달러")[0] == 1_000_000
    assert unit_factor("백만원", "원")[0] == 1_000_000
    assert unit_factor("천명", "명")[0] == 1_000
    assert unit_factor("백만달러", "원")[0] is None


def test_ten_thousand_won_conversion_is_not_silently_treated_as_one_won():
    assert unit_factor("만원", "원")[0] == 10_000


def test_compound_person_density_is_not_a_person_count():
    assert unit_factor("명/㎢", "명")[0] is None


def test_validated_api_rows_are_reused_only_for_the_selected_coordinate():
    row = {
        "mapping_status": "READY",
        "item_meta_valid": "True",
        "obj_meta_valid": "True",
        "response_code_valid": "True",
        "selected_itm_id": "I1",
        "selected_obj_l1": "A1",
        "selected_combination": '{"matching_rows": ['
        '{"ITM_ID":"I1","C1":"A1","PRD_DE":"2024","PRD_SE":"A","DT":"10"},'
        '{"ITM_ID":"I2","C1":"A1","PRD_DE":"2024","PRD_SE":"A","DT":"99"}]}'
    }
    rows = validated_matching_rows(row)
    assert len(rows) == 1
    assert rows[0]["DT"] == "10"


def test_empty_mapping_type_recovers_direct_for_ready_level_value(monkeypatch):
    row = {
        "mapping_status": "READY", "value": "10", "period": "2024",
        "semantic_type": "count", "value_type": "수준값", "unit": "명",
        "org_id": "101", "tbl_id": "T1", "selected_itm_id": "I1",
        "selected_itm_name": "인구", "selected_itm_unit": "명",
        "selected_obj_l1": "A1", "selected_obj_l1_name": "전국",
        "selected_obj_l1_axis_id": "A", "prd_se": "Y",
        "item_meta_valid": "True", "obj_meta_valid": "True",
        "response_code_valid": "True",
        "selected_combination": '{"matching_rows": ['
        '{"ITM_ID":"I1","ITM_NM":"인구","UNIT_NM":"명",'
        '"C1":"A1","PRD_DE":"2024","PRD_SE":"A","DT":"10"}]}'
    }
    meta = [{"OBJ_ID": "ITEM", "ITM_ID": "I1", "ITM_NM": "인구", "UNIT_NM": "명"},
            {"OBJ_ID": "A", "ITM_ID": "A1", "ITM_NM": "전국"}]
    out = verify_row(row, {("101", "T1"): meta}, 0, use_pinned_item=True)
    assert out["mapping_type"] == "direct"
    assert out["value_data_source"] == "validated_api_response"
    assert out["verdict"] == "일치"


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
