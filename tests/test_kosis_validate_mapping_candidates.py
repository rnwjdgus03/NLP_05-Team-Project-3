import ast
from pathlib import Path

import pytest

from kosis_validate_mapping_candidates import (
    API_ERROR,
    EMPTY_RESPONSE,
    ITEM_UNRESOLVED,
    MAPPING_FAILED,
    META_NOT_AVAILABLE,
    NEEDS_CONFIRMATION,
    OBJ_UNRESOLVED,
    PERIOD_MISSING,
    READY,
    build_candidate_combinations,
    build_kosis_request,
    choose_or_abstain,
    group_official_meta,
    rank_valid_combinations,
    response_matches_request,
    validate_candidate_codes_against_meta,
    validate_mapping_candidates,
    validate_unit_and_period,
)


def eight_axis_meta():
    rows = [{"OBJ_ID": "ITEM", "ITM_ID": "I1", "ITM_NM": "지표"}]
    for level in range(1, 9):
        rows.append({
            "OBJ_ID": f"AXIS_{9 - level}",
            "OBJ_ID_SN": str(level),
            "OBJ_NM": f"축{level}",
            "ITM_ID": f"O{level}",
            "ITM_NM": f"값{level}",
        })
    return rows


def eight_axis_combination():
    grouped = group_official_meta(eight_axis_meta())
    candidate = {"itm_id": "I1", "itm_name": "지표", "semantic_score": 1.0}
    for level in range(1, 9):
        candidate[f"objL{level}"] = f"O{level}"
        candidate[f"objL{level}_name"] = f"값{level}"
    candidate.update(validate_candidate_codes_against_meta(candidate, grouped))
    return candidate


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
    assert empty["mapping_status"] == EMPTY_RESPONSE
    assert empty["mapping_reason"] == EMPTY_RESPONSE


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


def test_period_range_removes_new_est_period_count():
    request = build_kosis_request(
        "ORG", "TBL", one_combination(), periods=["2022", "2024"], new_est_prd_cnt=8
    )
    assert request["startPrdDe"] == "2022"
    assert request["endPrdDe"] == "2024"
    assert "newEstPrdCnt" not in request


def test_latest_n_omits_start_and_end_periods():
    request = build_kosis_request("ORG", "TBL", one_combination(), new_est_prd_cnt=5)
    assert request["newEstPrdCnt"] == 5
    assert "startPrdDe" not in request
    assert "endPrdDe" not in request


def test_request_omits_none_and_empty_parameters():
    combo = {**one_combination(), "objL3": "", "objL4": None}
    request = build_kosis_request("ORG", "TBL", combo, periods=[None, "", "2024"])
    assert all(value not in (None, "") for value in request.values())
    assert "objL3" not in request
    assert "objL4" not in request


def test_request_forwards_all_obj_l1_to_l8():
    request = build_kosis_request("ORG", "TBL", eight_axis_combination(), periods=["2024"])
    assert {request[f"objL{level}"] for level in range(1, 9)} == {f"O{level}" for level in range(1, 9)}


def test_selected_output_includes_obj_l1_to_l8():
    combo = eight_axis_combination()

    def fetcher(request):
        return [{
            "ITM_ID": request["itmId"],
            **{f"C{level}": request[f"objL{level}"] for level in range(1, 9)},
            "PRD_DE": "2024",
            "UNIT_NM": "명",
        }]

    result = validate_mapping_candidates(
        org_id="ORG",
        tbl_id="TBL",
        meta_rows=eight_axis_meta(),
        item_candidates=[{"code": "I1", "name": "지표", "semantic_score": 1.0}],
        obj_candidates={level: [{"code": f"O{level}", "name": f"값{level}", "semantic_score": 0.8}]
                        for level in range(1, 9)},
        data_fetcher=fetcher,
        expected_unit="명",
        required_periods=["2024"],
    )
    assert [result[f"selected_obj_l{level}"] for level in range(1, 9)] == [f"O{level}" for level in range(1, 9)]
    assert [result[f"selected_obj_l{level}_name"] for level in range(1, 9)] == [f"값{level}" for level in range(1, 9)]


@pytest.mark.parametrize("level", range(4, 9))
def test_response_c4_to_c8_mismatch_is_rejected(level):
    combo = eight_axis_combination()
    request = build_kosis_request("ORG", "TBL", combo)
    row = {"ITM_ID": "I1", **{f"C{i}": f"O{i}" for i in range(1, 9)}}
    row[f"C{level}"] = "WRONG"
    assert response_matches_request(request, [row])["response_code_valid"] is False


def test_verifier_forwards_selected_obj_l6_to_l8_without_importing_api_module():
    # Importing the verifier imports kosis_api_test, whose legacy module-level
    # dotenv loader would violate this unit test's no-.env boundary. AST-check the
    # wiring instead; all candidate-validator behavior tests above remain runtime tests.
    source = (Path(__file__).parents[1] / "kosis_verify_claim_values.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    verify = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "verify_row")
    text = ast.unparse(verify)
    assert "range(2, 9)" in text
    assert "selected_obj_l{level}" in text
    assert "obj_l{level}" in text
    assert "get_stat_data" in text and "**extra_obj" in text


def test_max_twenty_gives_each_top_k_item_an_attempt():
    meta = official_meta()[:2]
    obj_candidates = {}
    # No OBJ axes makes a compact way to isolate ITEM fairness.
    combinations = build_candidate_combinations(
        [
            {"code": "I_TOTAL", "semantic_score": 1.0},
            {"code": "I_RATE", "semantic_score": 0.9},
        ],
        obj_candidates,
        meta,
        item_top_k=2,
        max_combinations=20,
    )
    assert {row["itm_id"] for row in combinations} == {"I_TOTAL", "I_RATE"}


def test_combinations_are_ordered_by_joint_score():
    combinations = build_candidate_combinations(
        [
            {"code": "I_TOTAL", "semantic_score": 0.5},
            {"code": "I_RATE", "semantic_score": 0.9},
        ],
        explicit_obj_candidates(score=0.2),
        official_meta(),
        item_top_k=2,
    )
    assert combinations[0]["itm_id"] == "I_RATE"
    assert [row["semantic_score"] for row in combinations] == sorted(
        (row["semantic_score"] for row in combinations), reverse=True
    )


def test_api_success_does_not_change_semantic_score():
    candidate = {**one_combination(item_score=0.73), "response_code_valid": True,
                 "unit_valid": True, "period_valid": True}
    before = candidate["semantic_score"]
    ranked = rank_valid_combinations([candidate])
    assert ranked[0]["api_valid"] is True
    assert ranked[0]["semantic_score"] == before


def test_legacy_rank_one_candidate_shape_remains_compatible():
    legacy = {
        "selected_itm_id": "I_TOTAL",
        "selected_obj_l1": "R_SEOUL",
        "selected_obj_l2": "S_F",
        "selected_obj_l3": "A_20",
        "candidate_rank": "1",
    }
    validation = validate_candidate_codes_against_meta(legacy, official_meta())
    assert validation["metadata_valid"] is True


def validation_kwargs(**overrides):
    kwargs = {
        "org_id": "ORG",
        "tbl_id": "TBL",
        "meta_rows": official_meta(),
        "item_candidates": [{"code": "I_TOTAL", "name": "취업자 수", "semantic_score": 0.9}],
        "obj_candidates": explicit_obj_candidates(),
        "data_fetcher": lambda _request: response_rows(),
        "expected_unit": "명",
        "required_periods": ["2023", "2024"],
        "claim": {"indicator": "취업자 수", "period": "2024"},
    }
    kwargs.update(overrides)
    return kwargs


def test_missing_indicator_needs_confirmation():
    result = validate_mapping_candidates(**validation_kwargs(claim={"period": "2024"}))
    assert result["mapping_status"] == NEEDS_CONFIRMATION
    assert "indicator" in result["high_risk_missing"]


def test_missing_required_period_needs_confirmation_with_period_reason():
    result = validate_mapping_candidates(**validation_kwargs(
        data_fetcher=lambda _request: response_rows(periods=("2024",)),
    ))
    assert result["mapping_status"] == NEEDS_CONFIRMATION
    assert result["mapping_reason"] == PERIOD_MISSING
    assert result["period_valid"] is False


def test_change_claim_missing_comparison_period_needs_confirmation():
    result = validate_mapping_candidates(**validation_kwargs(
        claim={"indicator": "취업자 수 증감", "period": "2024", "mapping_type": "rate_from_level",
               "comparison_basis": "전년 대비"},
        required_periods=["2024"],
    ))
    assert result["mapping_status"] == NEEDS_CONFIRMATION
    assert "comparison_period" in result["high_risk_missing"]


def test_missing_official_meta_has_specific_status():
    result = validate_mapping_candidates(**validation_kwargs(meta_rows=[]))
    assert result["mapping_status"] == META_NOT_AVAILABLE
    assert result["mapping_reason"] == META_NOT_AVAILABLE
    assert result["attempted_combination_count"] == 0


def test_no_official_item_candidate_has_specific_status():
    result = validate_mapping_candidates(**validation_kwargs(
        item_candidates=[{"code": "I_UNKNOWN", "semantic_score": 1.0}],
    ))
    assert result["mapping_status"] == ITEM_UNRESOLVED
    assert result["mapping_reason"] == ITEM_UNRESOLVED
    assert result["attempted_combination_count"] == 0


def test_required_obj_unresolved_has_specific_status():
    ambiguous_meta = official_meta() + [
        {"OBJ_ID": "AGE", "OBJ_ID_SN": "3", "OBJ_NM": "연령", "ITM_ID": "A_TOTAL2", "ITM_NM": "총계"},
    ]
    result = validate_mapping_candidates(**validation_kwargs(
        meta_rows=ambiguous_meta,
        obj_candidates={},
    ))
    assert result["mapping_status"] == OBJ_UNRESOLVED
    assert result["mapping_reason"] == OBJ_UNRESOLVED
    assert result["attempted_combination_count"] == 0
