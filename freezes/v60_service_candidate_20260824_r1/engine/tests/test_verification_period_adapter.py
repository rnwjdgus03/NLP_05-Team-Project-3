import run_kosis_top5_verification as verifier


def test_previous_period_is_bridged_to_comparison_period(monkeypatch):
    monkeypatch.setattr(
        verifier,
        "postgres_preflight",
        lambda coordinate, claim, catalog: {
            "requested_prd_se": "Y",
            "api_prd_se": "Y",
            "period_alignment_state": "exact",
            "normalized_target_period": "2025",
            "normalized_previous_period": "2024",
            "repaired_axis_values": [],
            "repair_history": [],
            "postgres_coordinate_valid": True,
            "official_table_name": "테스트표",
            "official_item_name": "테스트항목",
            "official_item_unit": "지수",
        },
    )
    candidate = {
        "coordinate_id": "source-coordinate",
        "coordinate": {
            "org_id": "101",
            "tbl_id": "T1",
            "item_id": "I1",
            "prd_se": "Y",
            "target_period": "2025",
            "previous_period": "2024",
            "aggregation": None,
            "axis_values": [],
        },
        "source_support": [],
    }
    row = verifier.verification_input(
        {"claim_measurement_id": "c1", "mapping_type": "rate_from_level"},
        {"raw_suggestions": []},
        candidate,
        {},
    )
    assert row["period"] == "2025"
    assert row["previous_period"] == "2024"
    assert row["comparison_period"] == "2024"
