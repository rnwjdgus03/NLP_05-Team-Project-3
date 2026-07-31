from kosis_validate_mapping_candidates import (
    NEEDS_CONFIRMATION,
    PROVISIONAL,
    READY,
    _rank_of,
    measurement_key,
    needs_fallback,
)


def test_rank_parsing_is_guarded():
    assert _rank_of({"candidate_rank": "2"}) == 2
    assert _rank_of({"candidate_rank": "3.0"}) == 3
    assert _rank_of({"candidate_rank": "abc"}) == 999
    assert _rank_of({}) == 999


def test_measurement_key_prefers_measurement_id():
    assert measurement_key({"claim_measurement_id": "M1", "claim_id": "C1"}) == "M1"
    assert measurement_key({"claim_id": "C1"}) == "C1"
    assert measurement_key({}) == ""


def test_empty_response_triggers_fallback():
    assert needs_fallback({"mapping_status": "MAPPING_FAILED",
                           "mapping_reason": "EMPTY_RESPONSE"})


def test_invalid_combination_triggers_fallback():
    assert needs_fallback({"mapping_status": "MAPPING_FAILED",
                           "mapping_reason": "INVALID_COMBINATION"})


def test_ready_does_not_trigger_fallback():
    assert not needs_fallback({"mapping_status": READY, "mapping_reason": "validated candidate"})


def test_provisional_does_not_trigger_fallback():
    assert not needs_fallback({
        "mapping_status": PROVISIONAL,
        "mapping_reason": "top candidates have small margin (0.0200)",
    })


def test_needs_confirmation_does_not_trigger_fallback():
    """사람 확인 대기는 이미 쓸 수 있는 좌표를 찾은 것이므로 다음 순위로 넘어가지 않는다."""
    assert not needs_fallback({
        "mapping_status": NEEDS_CONFIRMATION,
        "mapping_reason": "upstream table candidate is not decisive rank-1 READY",
    })


def test_status_reason_is_also_inspected():
    assert needs_fallback({"mapping_status": "MAPPING_FAILED",
                           "mapping_reason": "",
                           "status_reason": "RESPONSE_CODE_MISMATCH"})
