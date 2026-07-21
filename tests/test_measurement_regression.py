import csv

from measurement_regression import CLAIM_COLS, audit_claim, problem_claims


def test_problem_claims_selects_missing_values_once():
    rows = [
        {"claim_id": "C1", "claim_text": "10명", "value": "-"},
        {"claim_id": "C1", "claim_text": "10명", "value": "-"},
        {"claim_id": "C2", "claim_text": "20명", "value": "20"},
    ]

    selected = problem_claims(rows)

    assert len(selected) == 1
    assert selected[0]["claim_id"] == "C1"
    assert set(selected[0]) == set(CLAIM_COLS)


def test_audit_passes_complete_split_measurements():
    claim = {"claim_id": "C1", "claim_text": "10명에서 20명으로 늘었다."}
    actual = [
        {
            "value": "10", "unit": "명", "value_type": "수준값",
            "measurement_role": "이전값", "measurement_text": "10명",
            "measurement_source": "hcx", "measurement_repaired": "N",
        },
        {
            "value": "20", "unit": "명", "value_type": "수준값",
            "measurement_role": "현재값", "measurement_text": "20명",
            "measurement_source": "hcx", "measurement_repaired": "N",
        },
    ]

    report = audit_claim(claim, actual)

    assert report["status"] == "PASS"
    assert report["expected_measurement_count"] == 2
    assert report["actual_measurement_count"] == 2
    assert report["missing_required_fields"] == "-"


def test_audit_fails_missing_expected_measurement():
    claim = {"claim_id": "C1", "claim_text": "10명에서 20명으로 늘었다."}
    actual = [{
        "value": "20", "unit": "명", "value_type": "수준값",
        "measurement_role": "현재값", "measurement_text": "20명",
        "measurement_source": "hcx", "measurement_repaired": "Y",
    }]

    report = audit_claim(claim, actual)

    assert report["status"] == "FAIL"
    assert report["missing_expected"] == "10명"
