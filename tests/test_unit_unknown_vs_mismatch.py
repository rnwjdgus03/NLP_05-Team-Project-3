from diagnose_validated_mappings import recovery_class
from kosis_validate_mapping_candidates import validate_unit_and_period


def _row(unit="", period="2024"):
    return {"PRD_DE": period, "UNIT_NM": unit}


def test_missing_kosis_unit_is_unknown_not_mismatch():
    result = validate_unit_and_period([_row("")], expected_unit="달러",
                                      required_periods=["2024"])
    assert result["validation_reason"] == "UNIT_UNKNOWN"
    assert result["unit_unknown"] is True
    # 자동 확정은 여전히 막는다
    assert result["unit_valid"] is False


def test_conflicting_units_stay_mismatch():
    result = validate_unit_and_period([_row("억원")], expected_unit="달러",
                                      required_periods=["2024"])
    assert result["validation_reason"] == "UNIT_MISMATCH"
    assert result["unit_unknown"] is False


def test_matching_unit_has_no_reason():
    result = validate_unit_and_period([_row("달러")], expected_unit="달러",
                                      required_periods=["2024"])
    assert result["validation_reason"] == ""
    assert result["unit_valid"] is True


def test_period_missing_takes_priority_over_unit():
    result = validate_unit_and_period([_row("", period="2023")], expected_unit="달러",
                                      required_periods=["2024"])
    assert result["validation_reason"] == "PERIOD_MISSING"


def test_no_expected_unit_is_not_unknown():
    result = validate_unit_and_period([_row("")], expected_unit=None,
                                      required_periods=["2024"])
    assert result["unit_valid"] is True
    assert result["unit_unknown"] is False


def _candidate(**kw):
    base = {
        "mapping_status": "NEEDS_CONFIRMATION",
        "item_meta_valid": "True", "obj_meta_valid": "True",
        "response_code_valid": "True", "period_valid": "True",
        "unit_valid": "False", "candidate_rank": "1",
        "mapping_reason": "UNIT_MISMATCH", "unit_unknown": "False",
    }
    base.update(kw)
    return base


def test_recovery_class_separates_unknown_meta_from_fixable_unit():
    assert recovery_class([_candidate()]) == "UNIT_FIX_ONLY"
    assert recovery_class([_candidate(unit_unknown="True",
                                      mapping_reason="UNIT_UNKNOWN")]) == "UNIT_UNKNOWN_META"


def test_recovery_class_reads_reason_when_flag_column_absent():
    candidate = _candidate(mapping_reason="UNIT_UNKNOWN")
    candidate.pop("unit_unknown")
    assert recovery_class([candidate]) == "UNIT_UNKNOWN_META"
