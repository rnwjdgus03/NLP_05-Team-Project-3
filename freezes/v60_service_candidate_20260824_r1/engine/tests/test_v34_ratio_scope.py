from prepare_kosis_mapping_input import (
    indicator_unit_conflict,
    indicator_unit_dimensions,
)


def test_ratio_by_is_scope_modifier_when_outer_measurement_is_currency() -> None:
    row = {"measurement_indicator": "수출비율별 설비투자액"}
    assert indicator_unit_conflict(row, "currency") == ""
    assert indicator_unit_dimensions(row) == ("currency",)


def test_plain_ratio_indicator_remains_rate() -> None:
    row = {"measurement_indicator": "청년 취업자 비율"}
    assert indicator_unit_conflict(row, "currency")
    assert indicator_unit_dimensions(row) == ("rate",)
