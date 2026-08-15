from kosis_topk_fallback import merge_fallback, prepare_fallback


def test_prepare_only_sends_technical_top5_failures_to_top10():
    primary = [
        {"claim_measurement_id": "M1", "mapping_status": "READY"},
        {"claim_measurement_id": "M2", "mapping_status": "MAPPING_FAILED",
         "mapping_reason": "EMPTY_RESPONSE", "tbl_id": "T5"},
        {"claim_measurement_id": "M3", "mapping_status": "NEEDS_CONFIRMATION"},
    ]
    fallback = [
        {"claim_measurement_id": "M1", "tbl_id": "T10A"},
        {"claim_measurement_id": "M2", "tbl_id": "T10B"},
        {"claim_measurement_id": "M3", "tbl_id": "T10C"},
    ]
    rows = prepare_fallback(primary, fallback)
    assert [row["claim_measurement_id"] for row in rows] == ["M2"]
    assert rows[0]["topk_primary_reason"] == "EMPTY_RESPONSE"


def test_merge_uses_top10_only_when_it_recovers_a_failure():
    primary = [
        {"claim_measurement_id": "M1", "mapping_status": "READY", "tbl_id": "P1"},
        {"claim_measurement_id": "M2", "mapping_status": "MAPPING_FAILED",
         "mapping_reason": "EMPTY_RESPONSE", "tbl_id": "P2"},
        {"claim_measurement_id": "M3", "mapping_status": "MAPPING_FAILED",
         "mapping_reason": "EMPTY_RESPONSE", "tbl_id": "P3"},
    ]
    fallback = [
        {"claim_measurement_id": "M2", "mapping_status": "NEEDS_CONFIRMATION",
         "mapping_reason": "OBJ_RELAXED_AFTER_EMPTY_RESPONSE", "tbl_id": "F2"},
        {"claim_measurement_id": "M3", "mapping_status": "MAPPING_FAILED",
         "mapping_reason": "EMPTY_RESPONSE", "tbl_id": "F3"},
    ]
    rows = {row["claim_measurement_id"]: row for row in merge_fallback(primary, fallback)}
    assert rows["M1"]["tbl_id"] == "P1" and rows["M1"]["topk_fallback_attempted"] == "N"
    assert rows["M2"]["tbl_id"] == "F2" and rows["M2"]["topk_source"] == "TOP10_FALLBACK"
    assert rows["M3"]["tbl_id"] == "P3" and rows["M3"]["topk_fallback_recovered"] == "N"


def test_top10_recovery_can_never_become_automatic_ready():
    primary = [{
        "claim_measurement_id": "M1", "mapping_status": "MAPPING_FAILED",
        "mapping_reason": "EMPTY_RESPONSE", "tbl_id": "P1",
    }]
    fallback = [{
        "claim_measurement_id": "M1", "mapping_status": "READY",
        "mapping_reason": "validated candidate", "tbl_id": "F1",
    }]

    row = merge_fallback(primary, fallback)[0]

    assert row["tbl_id"] == "F1"
    assert row["mapping_status"] == "NEEDS_CONFIRMATION"
    assert row["mapping_reason"] == "TOP10_FALLBACK_REQUIRES_CONFIRMATION"
    assert row["topk_fallback_status"] == "READY"
    assert row["topk_fallback_auto_ready_blocked"] == "Y"
