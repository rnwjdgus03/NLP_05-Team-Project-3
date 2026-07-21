from map_verify_kosis import (
    effective_indicator,
    effective_period,
    effective_prd_se,
    mapping_exclusion_reason,
)


def test_new_measurement_usage_gates_non_kosis_values():
    assert "POLICY_VALUE" in mapping_exclusion_reason(
        {"measurement_usage": "POLICY_VALUE", "value": "10030", "unit": "원", "measurement_role": "현재값"}
    )
    assert "CONDITION" in mapping_exclusion_reason(
        {"measurement_usage": "CONDITION", "value": "40", "unit": "시간", "measurement_role": "참고값"}
    )


def test_kosis_value_can_continue_to_mapping():
    row = {
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "value": "2.3",
        "unit": "%",
        "measurement_role": "현재값",
    }

    assert mapping_exclusion_reason(row) == ""


def test_new_schema_gates_non_domestic_scope_and_rankings():
    overseas = {
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "해외통계·정책",
        "value": "683800000000",
        "unit": "달러",
        "value_type": "수준값",
        "measurement_role": "현재값",
    }
    ranking = {
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "value": "1",
        "unit": "위",
        "value_type": "순위",
        "measurement_role": "현재값",
    }

    assert "해외통계·정책" in mapping_exclusion_reason(overseas)
    assert "순위값" in mapping_exclusion_reason(ranking)


def test_legacy_rows_without_usage_keep_previous_behavior():
    row = {"value": "2.3", "unit": "%", "measurement_role": "현재값"}

    assert mapping_exclusion_reason(row) == ""


def test_missing_value_or_unit_is_excluded():
    assert "value/unit" in mapping_exclusion_reason(
        {"measurement_usage": "KOSIS_VALUE", "value": "-", "unit": "%", "measurement_role": "현재값"}
    )


def test_v15_uses_measurement_level_mapping_fields():
    row = {
        "indicator": "결합 지표",
        "period": "2025",
        "prd_se": "M",
        "measurement_indicator": "수출액",
        "measurement_item": "반도체",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
    }

    assert effective_indicator(row) == "수출액"
    assert effective_period(row) == "2024"
    assert effective_prd_se(row) == "Y"


def test_v15_excludes_incomplete_or_fallback_binding():
    base = {
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "measurement_indicator": "수출액",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
        "value": "15100000000",
        "unit": "달러",
        "value_type": "수준값",
        "measurement_role": "현재값",
    }

    assert "claim_fallback" in mapping_exclusion_reason(
        {**base, "measurement_binding_source": "claim_fallback"}
    )
    assert "measurement_period" in mapping_exclusion_reason(
        {**base, "measurement_binding_source": "hcx", "measurement_period": "-"}
    )
    assert mapping_exclusion_reason(
        {**base, "measurement_binding_source": "hcx"}
    ) == ""
