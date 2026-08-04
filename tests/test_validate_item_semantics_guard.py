from kosis_validate_mapping_candidates import (
    claim_item_matches_selection,
    downstream_validated_rank1,
)


def _valid_result(**kw):
    base = {
        "item_meta_valid": "True",
        "obj_meta_valid": "True",
        "response_code_valid": "True",
        "unit_valid": "True",
        "period_valid": "True",
        "selected_obj_l1_name": "반도체",
    }
    base.update(kw)
    return base


def _rank1_row(**kw):
    base = {
        "candidate_rank": "1",
        "candidate_status": "REVIEW",
        "candidate_score": "650",
        "candidate_runner_up_score": "600",
        "industry_or_item": "",
    }
    base.update(kw)
    return base


def test_no_item_constraint_passes():
    assert claim_item_matches_selection({"industry_or_item": "-"},
                                        {"selected_obj_l1_name": "총액"})


def test_matching_item_passes():
    assert claim_item_matches_selection({"industry_or_item": "반도체"},
                                        {"selected_obj_l1_name": "반도체"})


def test_partial_token_match_passes():
    assert claim_item_matches_selection({"industry_or_item": "석유화학"},
                                        {"selected_obj_l1_name": "석유화학제품"})


def test_real_mismatch_semiconductor_blocked():
    assert not claim_item_matches_selection(
        {"industry_or_item": "반도체"},
        {"selected_obj_l1_name": "인산에스테르 및 그 염(락토포스페이트 포함)"})


def test_real_mismatch_agriculture_blocked():
    assert not claim_item_matches_selection(
        {"industry_or_item": "농수산식품"},
        {"selected_obj_l1_name": "건조기(농산물용의 것)"})


def test_generic_total_obj_blocked_for_specific_item():
    assert not claim_item_matches_selection({"industry_or_item": "반도체"},
                                            {"selected_obj_l1_name": "전체"})


def test_downstream_trust_requires_item_semantics():
    row = _rank1_row(industry_or_item="반도체")
    mismatched = _valid_result(selected_obj_l1_name="인산에스테르 및 그 염")
    assert not downstream_validated_rank1(row, mismatched)
    assert downstream_validated_rank1(row, _valid_result())


def test_downstream_trust_still_blocks_upstream_reject():
    row = _rank1_row(candidate_status="REJECT", industry_or_item="반도체")
    assert not downstream_validated_rank1(row, _valid_result())


def test_downstream_trust_requires_rank1():
    row = _rank1_row(candidate_rank="2", industry_or_item="반도체")
    assert not downstream_validated_rank1(row, _valid_result())


def test_downstream_trust_requires_all_measurements():
    row = _rank1_row(industry_or_item="반도체")
    assert not downstream_validated_rank1(row, _valid_result(unit_valid="False"))
    assert not downstream_validated_rank1(row, _valid_result(period_valid="False"))
