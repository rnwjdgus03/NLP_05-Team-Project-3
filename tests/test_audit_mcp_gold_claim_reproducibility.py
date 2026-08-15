from audit_mcp_gold_claim_reproducibility import audit_row


def base_row(**overrides: str) -> dict[str, str]:
    row = {
        "claim_type": "CHANGE_RATE",
        "claim_value": "6.6",
        "gold_derivation_method": "(MCP current − MCP previous) / |MCP previous| × 100",
        "mcp_actual_value": "61359250",
        "mcp_previous_actual_value": "57573193",
        "mcp_coordinate_confirmed": "Y",
        "mcp_value_confirmed": "Y",
    }
    row.update(overrides)
    return row


def test_change_rate_reproduced_with_rounding_tolerance() -> None:
    result = audit_row(base_row())
    assert result["reproducibility_status"] == "PASS"


def test_unrelated_change_rate_is_rejected() -> None:
    result = audit_row(base_row(claim_value="2.9", mcp_actual_value="631767209", mcp_previous_actual_value="642572126"))
    assert result["reproducibility_status"] == "REVIEW"
    assert result["reproducibility_reason"] == "CLAIM_VALUE_NOT_REPRODUCED"


def test_scaled_level_is_reproduced() -> None:
    result = audit_row(
        base_row(
            claim_type="LEVEL",
            claim_value="6838",
            gold_derivation_method="MCP current value × source unit scale (1e-05)",
            mcp_actual_value="683609488",
            mcp_previous_actual_value="N/A",
        )
    )
    assert result["reproducibility_status"] == "PASS"


def test_wrong_scaled_level_is_rejected() -> None:
    result = audit_row(
        base_row(
            claim_type="LEVEL",
            claim_value="633",
            gold_derivation_method="MCP current value × source unit scale (1e-05)",
            mcp_actual_value="61359250",
            mcp_previous_actual_value="N/A",
        )
    )
    assert result["reproducibility_status"] == "REVIEW"


def test_percentage_level_uses_percentage_point_tolerance() -> None:
    result = audit_row(
        base_row(
            claim_type="LEVEL",
            claim_value="4.1",
            gold_derivation_method="MCP current value × source unit scale (1)",
            mcp_actual_value="3.7",
            mcp_previous_actual_value="N/A",
            mcp_actual_unit="%",
        )
    )
    assert result["reproducibility_status"] == "REVIEW"
