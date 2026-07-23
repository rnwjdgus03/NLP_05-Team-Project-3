import pytest

from kosis_validate_mapping_candidates import (
    API_ERROR,
    MAPPING_FAILED,
    NEEDS_CONFIRMATION,
    NOT_EVALUATED,
    READY,
    build_candidate_combinations,
    build_claim_context,
    build_kosis_request,
    choose_or_abstain,
    group_official_meta,
    low_priority_reason,
    rank_valid_combinations,
    resolve_table_ambiguity,
    response_matches_request,
    validate_candidate_codes_against_meta,
    validate_mapping_candidates,
    validate_unit_and_period,
)


def official_meta():
    return [
        {"OBJ_ID": "ITEM", "ITM_ID": "I_TOTAL", "ITM_NM": "취업자 수"},
        {"OBJ_ID": "ITEM", "ITM_ID": "I_RATE", "ITM_NM": "고용률"},
        {"OBJ_ID": "REGION", "OBJ_ID_SN": "1", "OBJ_NM": "지역", "ITM_ID": "R_ALL", "ITM_NM": "전국"},
        {"OBJ_ID": "REGION", "OBJ_ID_SN": "1", "OBJ_NM": "지역", "ITM_ID": "R_SEOUL", "ITM_NM": "서울"},
        {"OBJ_ID": "SEX", "OBJ_ID_SN": "2", "OBJ_NM": "성별", "ITM_ID": "S_ALL", "ITM_NM": "계"},
        {"OBJ_ID": "SEX", "OBJ_ID_SN": "2", "OBJ_NM": "성별", "ITM_ID": "S_F", "ITM_NM": "여자"},
        {"OBJ_ID": "AGE", "OBJ_ID_SN": "3", "OBJ_NM": "연령", "ITM_ID": "A_ALL", "ITM_NM": "전체"},
        {"OBJ_ID": "AGE", "OBJ_ID_SN": "3", "OBJ_NM": "연령", "ITM_ID": "A_20", "ITM_NM": "20대"},
    ]


def explicit_obj_candidates(score=0.8):
    return {
        1: [{"code": "R_SEOUL", "name": "서울", "semantic_score": score}],
        2: [{"code": "S_F", "name": "여자", "semantic_score": score}],
        3: [{"code": "A_20", "name": "20대", "semantic_score": score}],
    }


def one_combination(item_score=0.9):
    return build_candidate_combinations(
        [{"code": "I_TOTAL", "name": "취업자 수", "semantic_score": item_score}],
        explicit_obj_candidates(),
        official_meta(),
    )[0]


def response_rows(itm="I_TOTAL", c1="R_SEOUL", c2="S_F", c3="A_20", periods=("2023", "2024"), unit="명"):
    return [
        {"ITM_ID": itm, "C1": c1, "C2": c2, "C3": c3, "PRD_DE": period, "UNIT_NM": unit, "DT": "100"}
        for period in periods
    ]


def test_rejects_item_code_absent_from_official_meta():
    grouped = group_official_meta(official_meta())
    result = validate_candidate_codes_against_meta(
        {"itm_id": "I_UNKNOWN", "objL1": "R_SEOUL", "objL2": "S_F", "objL3": "A_20"}, grouped
    )
    assert result["item_meta_valid"] is False
    assert result["metadata_valid"] is False

    combinations = build_candidate_combinations(
        [{"code": "I_UNKNOWN", "semantic_score": 1.0}], explicit_obj_candidates(), grouped
    )
    assert combinations == []


def test_rejects_obj_code_absent_from_official_meta():
    grouped = group_official_meta(official_meta())
    result = validate_candidate_codes_against_meta(
        {"itm_id": "I_TOTAL", "objL1": "R_UNKNOWN", "objL2": "S_F", "objL3": "A_20"}, grouped
    )
    assert result["obj_meta_valid"] is False
    assert result["invalid_obj_codes"] == [{"axis_order": 1, "code": "R_UNKNOWN"}]

    obj_candidates = explicit_obj_candidates()
    obj_candidates[1] = [{"code": "R_UNKNOWN", "semantic_score": 1.0}]
    combinations = build_candidate_combinations(["I_TOTAL"], obj_candidates, grouped)
    assert combinations[0]["objL1"] == "R_ALL"
    assert combinations[0]["objL1"] != "R_UNKNOWN"


def test_axis_order_builds_obj_l1_l2_l3_without_inferring_from_obj_id():
    shuffled = list(reversed(official_meta()))
    grouped = group_official_meta(shuffled)
    assert list(grouped["axes"]) == [1, 2, 3]

    combo = build_candidate_combinations(["I_TOTAL"], explicit_obj_candidates(), grouped)[0]
    assert (combo["objL1"], combo["objL2"], combo["objL3"]) == ("R_SEOUL", "S_F", "A_20")
    request = build_kosis_request("ORG", "TBL", combo, periods=["2023", "2024"])
    assert (request["objL1"], request["objL2"], request["objL3"]) == ("R_SEOUL", "S_F", "A_20")


def test_group_meta_accepts_pipeline_meta_index_schema():
    rows = [
        {"axis_id": "ITEM", "axis_order": "", "code_id": "I1", "code_name": "지표"},
        {"axis_id": "Z", "axis_order": "1", "axis_name": "지역", "code_id": "R1", "code_name": "전국"},
    ]
    grouped = group_official_meta(rows)
    assert grouped["item_codes"] == {"I1"}
    assert grouped["axis_codes"][1] == {"R1"}


def test_response_item_id_mismatch_is_rejected():
    combo = one_combination()
    request = build_kosis_request("ORG", "TBL", combo)
    result = response_matches_request(request, response_rows(itm="I_RATE"))
    assert result["response_code_valid"] is False
    assert result["matching_rows"] == []


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [("C1", "R_ALL"), ("C2", "S_ALL"), ("C3", "A_ALL")],
)
def test_response_obj_l1_to_l3_mismatch_is_rejected(field, wrong_value):
    combo = one_combination()
    request = build_kosis_request("ORG", "TBL", combo)
    rows = response_rows()
    for row in rows:
        row[field] = wrong_value
    assert response_matches_request(request, rows)["response_code_valid"] is False


def test_missing_one_of_two_required_periods_is_period_missing():
    result = validate_unit_and_period(
        response_rows(periods=("2024",)), expected_unit="명", required_periods=["2023", "2024"]
    )
    assert result["period_valid"] is False
    assert result["missing_periods"] == ["2023"]
    assert result["validation_reason"] == "PERIOD_MISSING"


def test_unit_mismatch_is_retained_with_ranking_penalty():
    validation = validate_unit_and_period(response_rows(unit="%"), expected_unit="명", required_periods=["2023", "2024"])
    assert validation["unit_valid"] is False
    assert validation["validation_reason"] == "UNIT_MISMATCH"

    candidate = {**one_combination(), **validation, "response_code_valid": True}
    ranked = rank_valid_combinations([candidate], unit_penalty=0.25)
    assert len(ranked) == 1
    assert ranked[0]["ranking_score"] == pytest.approx(ranked[0]["semantic_score"] - 0.25)


@pytest.mark.parametrize(
    ("claim_unit", "kosis_unit"),
    [("달러", "백만달러"), ("억달러", "천달러"), ("개", "개사")],
)
def test_scaled_and_organization_units_are_compatible(claim_unit, kosis_unit):
    result = validate_unit_and_period(
        response_rows(unit=kosis_unit),
        expected_unit=claim_unit,
        required_periods=["2023", "2024"],
    )
    assert result["unit_valid"] is True


def test_claim_context_includes_measurement_scope_fields():
    context = build_claim_context({
        "measurement_indicator": "수출액",
        "industry_or_item": "반도체",
        "region": "전국",
        "age_group": "20~29세",
        "gender": "전체",
    })
    assert all(token in context for token in ("수출액", "반도체", "전국", "20~29세", "전체"))


def test_one_valid_combination_is_ready():
    candidate = {
        **one_combination(),
        "response_code_valid": True,
        "unit_valid": True,
        "period_valid": True,
    }
    decision = choose_or_abstain(rank_valid_combinations([candidate]), ready_threshold=0.1)
    assert decision["mapping_status"] == READY
    assert decision["selected_combination"]["itm_id"] == "I_TOTAL"


def test_two_close_valid_combinations_need_confirmation():
    base = {**one_combination(), "response_code_valid": True, "unit_valid": True, "period_valid": True}
    second = {**base, "itm_id": "I_RATE", "itm_name": "고용률", "semantic_score": base["semantic_score"] - 0.02}
    ranked = rank_valid_combinations([base, second])
    decision = choose_or_abstain(ranked, margin_threshold=0.1)
    assert decision["mapping_status"] == NEEDS_CONFIRMATION
    assert "small margin" in decision["mapping_reason"]


def test_api_error_and_empty_response_have_distinct_outcomes():
    kwargs = dict(
        org_id="ORG",
        tbl_id="TBL",
        meta_rows=official_meta(),
        item_candidates=[{"code": "I_TOTAL", "semantic_score": 0.9}],
        obj_candidates=explicit_obj_candidates(),
        expected_unit="명",
        required_periods=["2023", "2024"],
    )

    def failing_fetcher(_request):
        raise TimeoutError("mock timeout")

    api_error = validate_mapping_candidates(**kwargs, data_fetcher=failing_fetcher)
    empty = validate_mapping_candidates(**kwargs, data_fetcher=lambda _request: [])
    assert api_error["mapping_status"] == API_ERROR
    assert empty["mapping_status"] == MAPPING_FAILED
    assert empty["mapping_reason"] == "EMPTY_RESPONSE"


def test_unique_national_and_total_defaults_include_reason_and_low_risk():
    combos = build_candidate_combinations(
        [{"code": "I_TOTAL", "semantic_score": 0.9}],
        {},
        official_meta(),
    )
    assert len(combos) == 1
    combo = combos[0]
    assert (combo["objL1"], combo["objL2"], combo["objL3"]) == ("R_ALL", "S_ALL", "A_ALL")
    assert combo["default_risk"] == "LOW"
    assert "공식 메타의 유일한 집계값 적용" in combo["default_reason"]
    assert {entry["default_field"] for entry in combo["default_fields"]} == {"objL1", "objL2", "objL3"}


def test_max_combinations_bounds_api_calls_and_invalid_codes_never_reach_fetcher():
    calls = []

    def fetcher(request):
        calls.append(dict(request))
        return response_rows(itm=request["itmId"], c1=request["objL1"], c2=request["objL2"], c3=request["objL3"])

    result = validate_mapping_candidates(
        org_id="ORG",
        tbl_id="TBL",
        meta_rows=official_meta(),
        item_candidates=[
            {"code": "I_UNKNOWN", "semantic_score": 1.0},
            {"code": "I_TOTAL", "semantic_score": 0.9},
            {"code": "I_RATE", "semantic_score": 0.8},
        ],
        obj_candidates=explicit_obj_candidates(),
        data_fetcher=fetcher,
        expected_unit="명",
        required_periods=["2023", "2024"],
        max_combinations=1,
    )
    assert result["attempted_combination_count"] == 1
    assert len(calls) == 1
    assert calls[0]["itmId"] != "I_UNKNOWN"


def test_table_ambiguity_is_recomputed_for_each_top_k_slice():
    rows = [
        {"claim_measurement_id": "m1", "candidate_rank": "1", "mapping_status": READY},
        {"claim_measurement_id": "m1", "candidate_rank": "2", "mapping_status": READY},
    ]

    top1 = resolve_table_ambiguity(rows[:1])
    top2 = resolve_table_ambiguity(rows)

    assert top1[0]["mapping_status"] == READY
    assert {row["mapping_status"] for row in top2} == {NEEDS_CONFIRMATION}


def test_rank_three_alternate_is_not_evaluated():
    assert low_priority_reason({
        "candidate_rank": "3",
        "candidate_status": "ALTERNATE",
    }) == "LOW_PRIORITY_CANDIDATE"
    assert low_priority_reason({
        "candidate_rank": "2",
        "candidate_status": "ALTERNATE",
    }) == ""
    assert NOT_EVALUATED == "NOT_EVALUATED"
