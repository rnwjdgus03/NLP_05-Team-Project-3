from __future__ import annotations

from apply_kosis_structural_table_policy import table_structure_score


class FakeStore:
    def __init__(self, table_name: str, axis_values=(), periods=()):
        self.table_name = table_name
        self.axis_values = axis_values
        self.periods = set(periods)

    def table(self, org_id: str, tbl_id: str):
        return {"tbl_name": self.table_name, "category_path": "경제활동인구조사"}

    def axes(self, org_id: str, tbl_id: str):
        return [{"axis_name": "연령별", "values": [
            {"obj_name": value} for value in self.axis_values
        ]}]

    def periodicities(self, org_id: str, tbl_id: str):
        return self.periods


ROW = {"org_id": "101", "tbl_id": "T", "tbl_name": ""}


def test_unrequested_seasonal_adjustment_is_penalized() -> None:
    claim = {"claim_text": "취업자는 20만명 증가했다", "measurement_prd_se": "M"}
    score, reasons = table_structure_score(
        claim, ROW, FakeStore("계절조정 경제활동인구 총괄", periods=("M",))  # type: ignore[arg-type]
    )
    assert score < 0
    assert "UNREQUESTED_SCOPE:계절조정" in reasons


def test_explicit_age_target_requires_supported_axis_value() -> None:
    claim = {"claim_text": "청년 고용률", "age_group": "15 - 29세", "obj_target_terms": "15 - 29세"}
    supported, supported_reasons = table_structure_score(
        claim, ROW, FakeStore("연령별 경제활동인구 총괄", ("15 - 29세",))  # type: ignore[arg-type]
    )
    unsupported, unsupported_reasons = table_structure_score(
        claim, ROW, FakeStore("경제활동인구 총괄(이민자)", ("이민자",))  # type: ignore[arg-type]
    )
    assert supported > unsupported
    assert "ALL_OBJ_TARGETS_SUPPORTED" in supported_reasons
    assert "OBJ_TARGETS_UNSUPPORTED" in unsupported_reasons


def test_periodicity_and_table_name_are_checked_together() -> None:
    claim = {"claim_text": "지난달 소비자물가지수", "measurement_prd_se": "M"}
    score, reasons = table_structure_score(
        claim, ROW, FakeStore("연도별 소비자물가지수", periods=("Y",))  # type: ignore[arg-type]
    )
    assert score <= -2.0
    assert "PERIOD_UNSUPPORTED" in reasons
    assert "ANNUAL_TABLE_MISMATCH" in reasons


def test_unrequested_regional_table_loses_to_national_indicator_table() -> None:
    claim = {
        "claim_text": "전국 소비자물가지수 상승률은 2.3%였다",
        "measurement_indicator": "소비자물가지수",
        "measurement_prd_se": "Y",
    }
    national_score, national_reasons = table_structure_score(
        claim, ROW, FakeStore("소비자물가지수(2020=100)", periods=("Y",))  # type: ignore[arg-type]
    )
    regional_score, regional_reasons = table_structure_score(
        claim, ROW, FakeStore("연도별 품목성질별 소비자물가지수(9개도, 39개시: 2020=100)", periods=("Y",))  # type: ignore[arg-type]
    )
    assert national_score > regional_score
    assert "INDICATOR_LEADING_TABLE" in national_reasons
    assert "UNREQUESTED_GEOGRAPHIC_GRANULARITY" in regional_reasons


def test_geographic_table_with_national_total_is_valid_for_aggregate_claim() -> None:
    claim = {
        "claim_text": "국내 농가 수는 97만 가구였다",
        "measurement_indicator": "농가 수",
        "measurement_prd_se": "Y",
    }
    score, reasons = table_structure_score(
        claim, ROW,
        FakeStore("행정구역별 농가, 농가인구", ("전국", "서울특별시"), ("Y",)),  # type: ignore[arg-type]
    )
    assert score > 0
    assert "GEOGRAPHIC_TABLE_HAS_AGGREGATE" in reasons
    assert "UNREQUESTED_GEOGRAPHIC_GRANULARITY" not in reasons
