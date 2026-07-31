from recover_downstream_validated import TRIGGER_REASON, can_recover, recover


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
    }
    base.update(kw)
    return base


def test_recovers_fully_validated_rank1():
    assert can_recover(_row())


def test_recover_marks_status_and_audit_field():
    rows, n = recover([_row()])
    assert n == 1
    assert rows[0]["mapping_status"] == "READY"
    assert rows[0]["recovered_by"] == "downstream_validation"


def test_upstream_reject_is_respected():
    assert not can_recover(_row(candidate_status="REJECT"))


def test_lower_rank_not_recovered():
    assert not can_recover(_row(candidate_rank="2"))


def test_failed_api_response_not_recovered():
    assert not can_recover(_row(response_code_valid="False"))


def test_unit_or_period_failure_not_recovered():
    assert not can_recover(_row(unit_valid="False"))
    assert not can_recover(_row(period_valid="False"))


def test_tied_scores_not_recovered():
    assert not can_recover(_row(candidate_score="650", candidate_runner_up_score="649"))


def test_other_reasons_untouched():
    assert not can_recover(_row(mapping_reason="UNIT_MISMATCH"))
    assert not can_recover(_row(mapping_status="MAPPING_FAILED",
                                mapping_reason="EMPTY_RESPONSE"))


def test_metadata_valid_column_fallback():
    row = _row()
    del row["item_meta_valid"]
    del row["obj_meta_valid"]
    row["metadata_valid"] = "True"
    assert can_recover(row)


def test_missing_scores_allowed_when_measurements_pass():
    row = _row()
    row["candidate_score"] = ""
    row["candidate_runner_up_score"] = ""
    assert can_recover(row)
