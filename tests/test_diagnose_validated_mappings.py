from diagnose_validated_mappings import (
    diagnose,
    next_action,
    recovery_class,
    technically_sound,
)


def _cand(**kw):
    base = {
        "claim_measurement_id": "M1", "claim_id": "C1", "claim_text": "t",
        "candidate_rank": "1", "mapping_status": "NEEDS_CONFIRMATION",
        "mapping_reason": "", "status_reason": "",
        "metadata_valid": "True", "response_code_valid": "True",
        "unit_valid": "True", "period_valid": "True",
        "tbl_id": "T", "tbl_name": "표",
    }
    base.update(kw)
    return base


def test_best_status_priority_and_rank_guard():
    rows = [
        _cand(candidate_rank="abc", mapping_status="NOT_EVALUATED",
              status_reason="LOW_PRIORITY_CANDIDATE"),
        _cand(candidate_rank="2", mapping_status="NEEDS_CONFIRMATION",
              mapping_reason="top candidates have small margin (0.01)"),
        _cand(candidate_rank="1", mapping_status="READY"),
    ]
    out = diagnose(rows)
    assert len(out) == 1
    assert out[0]["measurement_mapping_status"] == "READY"
    assert out[0]["next_action"] == "VERIFY_ACTUAL_VALUE"


def test_reason_falls_back_to_status_reason():
    rows = [_cand(mapping_status="MAPPING_FAILED", mapping_reason="",
                  status_reason="EMPTY_RESPONSE")]
    out = diagnose(rows)
    assert out[0]["next_action"] == "REVIEW_ITEM_OBJ_PERIOD"


def test_next_action_mapping():
    assert next_action("READY", "") == "VERIFY_ACTUAL_VALUE"
    assert next_action("NEEDS_CONFIRMATION",
                       "upstream table candidate is not decisive rank-1 READY") == "REVIEW_TABLE_RANKING"
    assert next_action("NEEDS_CONFIRMATION", "UNIT_MISMATCH") == "REVIEW_UNIT_OR_TABLE"
    assert next_action("MAPPING_FAILED", "EMPTY_RESPONSE") == "REVIEW_ITEM_OBJ_PERIOD"
    assert next_action("NEEDS_CONFIRMATION", "PERIOD_MISSING") == "ENRICH_PERIOD"
    assert next_action("MAPPING_FAILED", "???") == "MANUAL_REVIEW"


def test_recovery_top1_gate_only():
    cands = [_cand(candidate_rank="1",
                   mapping_reason="upstream table candidate is not decisive rank-1 READY")]
    assert recovery_class(cands) == "TOP1_GATE_ONLY"


def test_recovery_rank_only_for_lower_rank():
    cands = [_cand(candidate_rank="2",
                   mapping_reason="top candidates have small margin (0.02)")]
    assert recovery_class(cands) == "RANK_ONLY"


def test_recovery_item_obj_fixable():
    cands = [_cand(mapping_status="MAPPING_FAILED", status_reason="EMPTY_RESPONSE",
                   response_code_valid="False")]
    assert recovery_class(cands) == "ITEM_OBJ_FIXABLE"


def test_recovery_unit_fix_only():
    cands = [_cand(mapping_status="NEEDS_CONFIRMATION", mapping_reason="UNIT_MISMATCH",
                   unit_valid="False")]
    assert recovery_class(cands) == "UNIT_FIX_ONLY"


def test_no_recovery_when_nothing_sound():
    cands = [_cand(mapping_status="MAPPING_FAILED", status_reason="API_ERROR",
                   metadata_valid="False", response_code_valid="False",
                   unit_valid="False", period_valid="False")]
    assert recovery_class(cands) == ""
    assert not technically_sound(cands[0])
