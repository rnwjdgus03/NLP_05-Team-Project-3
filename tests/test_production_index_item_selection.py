from select_mcp_gold_200_two_stage_coordinates import item_match_score


def test_year_over_year_production_drop_prefers_constant_index():
    claim = {
        "claim_text": "1월 주점업 생산의 낙폭도 6.7%에 달했다.",
        "measurement_indicator": "주점업 생산",
        "unit": "%",
        "change_base": "전년동월",
    }
    current, _ = item_match_score(claim, {
        "selected_itm_name": "경상지수", "candidate_rank": "1", "table_rank": "1",
    })
    constant, _ = item_match_score(claim, {
        "selected_itm_name": "불변지수", "candidate_rank": "2", "table_rank": "1",
    })
    seasonal, _ = item_match_score(claim, {
        "selected_itm_name": "계절조정지수", "candidate_rank": "3", "table_rank": "1",
    })
    assert constant > current
    assert constant > seasonal
