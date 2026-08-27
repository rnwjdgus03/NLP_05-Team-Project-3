import run_kosis_top5_verification as verifier


def catalog():
    return {
        "table": {"tbl_name": "테스트표"},
        "items": {"I1": {"itm_name": "인구", "unit": "명"}},
        "axes": {
            "A": {
                "axis_order": 1,
                "values": {"ALL": {"obj_code": "ALL", "obj_name": "전체", "is_aggregate": True}},
            },
            "B": {
                "axis_order": 2,
                "values": {"M": {"obj_code": "M", "obj_name": "남자", "is_aggregate": False}},
            },
        },
        "periodicities": {"M"},
        "periodicity_rows": [],
    }


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


def test_postgres_preflight_rejects_axis_order_mismatch():
    coordinate = {
        "item_id": "I1", "prd_se": "M", "target_period": "202401",
        "axis_values": [
            {"axis_order": 2, "axis_id": "A", "value_id": "ALL"},
            {"axis_order": 1, "axis_id": "B", "value_id": "M"},
        ],
    }
    result = verifier.postgres_preflight(coordinate, {"unit": "명"}, catalog())
    assert result["postgres_coordinate_valid"] is False
    assert "axis_order_mismatches=A,B" in result["preflight_reason"]


def test_postgres_preflight_rejects_duplicate_axis_id_and_order():
    coordinate = {
        "item_id": "I1", "prd_se": "M", "target_period": "202401",
        "axis_values": [
            {"axis_order": 1, "axis_id": "A", "value_id": "ALL"},
            {"axis_order": 1, "axis_id": "A", "value_id": "ALL"},
            {"axis_order": 2, "axis_id": "B", "value_id": "M"},
        ],
    }
    result = verifier.postgres_preflight(coordinate, {"unit": "명"}, catalog())
    assert result["postgres_coordinate_valid"] is False
    assert "duplicate_axis_ids=A" in result["preflight_reason"]
    assert "duplicate_axis_orders=1" in result["preflight_reason"]


def test_six_digit_month_is_not_inferred_as_quarter_without_quarter_cue():
    result = verifier.align_period(
        {"target_period": "202401"}, {}, {"Q", "Y"},
    )
    assert result["api_prd_se"] == ""
    assert result["period_alignment_state"] == "mismatch"
