from recover_downstream_validated import TRIGGER_REASON, can_recover, item_semantics_ok


def _row(**kw):
    base = {
        "mapping_status": "NEEDS_CONFIRMATION",
        "mapping_reason": TRIGGER_REASON,
        "candidate_rank": "1",
        "candidate_status": "REVIEW",
        "item_meta_valid": "True",
        "obj_meta_valid": "True",
        "response_code_valid": "True",
        "unit_valid": "True",
        "period_valid": "True",
        "candidate_score": "650",
        "candidate_runner_up_score": "600",
        "industry_or_item": "",
        "selected_obj_l1_name": "총액",
    }
    base.update(kw)
    return base


def test_no_item_constraint_allows_total():
    assert item_semantics_ok(_row(industry_or_item="", selected_obj_l1_name="총액"))
    assert item_semantics_ok(_row(industry_or_item="-", selected_obj_l1_name="총액"))


def test_exact_item_match_allowed():
    assert item_semantics_ok(_row(industry_or_item="반도체",
                                  selected_obj_l1_name="반도체"))


def test_partial_item_match_allowed():
    assert item_semantics_ok(_row(industry_or_item="석유화학",
                                  selected_obj_l1_name="석유화학제품"))


def test_unrelated_obj_blocked_real_case_agriculture():
    """실측 오매핑: 농수산식품 수출 → '건조기(농산물용의 것)'"""
    assert not item_semantics_ok(_row(industry_or_item="농수산식품",
                                      selected_obj_l1_name="건조기(농산물용의 것)"))


def test_unrelated_obj_blocked_real_case_semiconductor():
    """실측 오매핑: 반도체 수출 → '인산에스테르 및 그 염...'"""
    assert not item_semantics_ok(_row(
        industry_or_item="반도체",
        selected_obj_l1_name="인산에스테르 및 그 염(락토포스페이트 포함)과 그 할로겐화유도체"))


def test_can_recover_blocks_mismatched_item():
    assert not can_recover(_row(industry_or_item="반도체",
                                selected_obj_l1_name="전체"))


def test_can_recover_allows_matching_item():
    assert can_recover(_row(industry_or_item="반도체",
                            selected_obj_l1_name="반도체"))


def test_item_match_can_come_from_item_name():
    assert item_semantics_ok(_row(industry_or_item="반도체",
                                  selected_obj_l1_name="총계",
                                  selected_itm_name="반도체 수출액"))
