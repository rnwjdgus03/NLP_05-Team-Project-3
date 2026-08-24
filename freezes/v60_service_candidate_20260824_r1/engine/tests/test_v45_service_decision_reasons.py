from run_kosis_top5_verification import (
    decision_failure_counts,
    prepared_claim_id,
)


def test_placeholder_measurement_id_is_not_a_public_claim():
    assert prepared_claim_id({"claim_measurement_id": "-", "claim_id": "claim-1"}) == ""


def test_prepare_gate_reason_survives_zero_candidate_decision():
    verdicts, stages = decision_failure_counts(
        {"mapping_exclusion_code": "MEASUREMENT_REVIEW_REQUIRED"}, []
    )
    assert verdicts == {"MEASUREMENT_REVIEW_REQUIRED": 1}
    assert stages == {"gate": 1}


def test_ready_claim_without_coordinate_gets_retrieval_reason():
    verdicts, stages = decision_failure_counts(
        {"mapping_exclusion_code": "", "mapping_gate": "READY"}, []
    )
    assert verdicts == {"RETRIEVAL_NO_CANDIDATE": 1}
    assert stages == {"retrieval": 1}


def test_verified_candidate_reasons_remain_authoritative():
    verdicts, stages = decision_failure_counts(
        {"mapping_exclusion_code": "MEASUREMENT_REVIEW_REQUIRED"},
        [{"verdict_code": "SEMANTIC_SCOPE_REVIEW_REQUIRED", "verdict_stage": "semantic"}],
    )
    assert verdicts == {"SEMANTIC_SCOPE_REVIEW_REQUIRED": 1}
    assert stages == {"semantic": 1}
