import csv

from prepare_kosis_mapping_input import (
    canonicalize_unit,
    normalize_row,
    prepare,
    unit_dimension,
)


def measurement_row(**overrides):
    row = {
        "claim_id": "A1-C1",
        "claim_measurement_id": "A1-C1-m1",
        "claim_text": "2024년 반도체 수출액은 100억 달러였다.",
        "claim_domain_scope": "국내공식통계",
        "indicator": "수출 통계",
        "industry_or_item": "반도체",
        "period": "2024",
        "prd_se": "Y",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_indicator": "반도체 수출액",
        "measurement_item": "반도체",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
        "measurement_binding_source": "hcx",
        "measurement_role": "현재값",
        "value": "10000000000",
        "unit": "달러",
        "value_type": "수준값",
    }
    row.update(overrides)
    return row


def test_unit_normalization_preserves_meaning():
    assert canonicalize_unit("불") == "달러"
    assert canonicalize_unit("개사") == "개"
    assert unit_dimension("세") == "age"
    assert unit_dimension("배") == "multiple"
    assert unit_dimension("백만달러") == "currency"


def test_normalize_row_uses_measurement_level_aliases():
    out = normalize_row(measurement_row())
    assert out["indicator"] == "반도체 수출액"
    assert out["industry_or_item"] == "반도체"
    assert out["period"] == "2024"
    assert out["unit_dimension"] == "currency"
    assert out["semantic_type"] == "amount"
    assert out["mapping_eligible"] == "Y"


def test_condition_and_missing_period_are_rejected_with_codes():
    condition = normalize_row(
        measurement_row(
            measurement_usage="CONDITION",
            measurement_indicator="검진 대상 연령",
            value="54",
            unit="세",
        )
    )
    assert condition["mapping_exclusion_code"] == "NOT_KOSIS_VALUE"

    missing_period = normalize_row(
        measurement_row(
            claim_text="수출액은 높은 수준이었다.",
            measurement_period="-",
            measurement_prd_se="-",
        )
    )
    assert missing_period["mapping_exclusion_code"] == "PERIOD_MISSING"


def test_previous_value_with_period_is_ready():
    out = normalize_row(measurement_row(measurement_role="이전값", measurement_period="2023"))
    assert out["mapping_eligible"] == "Y"


def test_target_value_is_rejected_as_not_observed():
    out = normalize_row(measurement_row(measurement_role="목표값"))
    assert out["mapping_exclusion_code"] == "ROLE_NOT_OBSERVED_VALUE"


def test_unclear_reference_value_is_rejected():
    out = normalize_row(
        measurement_row(
            measurement_role="참고값",
            claim_text="수출 흐름은 안정적이었다.",
            measurement_text="100억 달러",
        )
    )
    assert out["mapping_exclusion_code"] == "REFERENCE_RELATION_UNCLEAR"


def test_missing_period_infers_last_year_only_with_context():
    out = normalize_row(
        measurement_row(
            date="2025-01-01",
            claim_text="지난해 수출액은 100억 달러였다.",
            measurement_period="-",
            measurement_prd_se="-",
        )
    )
    assert out["period"] == "2024"
    assert out["prd_se"] == "Y"
    assert out["default_applied"] == "Y"


def test_missing_period_without_context_stays_rejected():
    out = normalize_row(
        measurement_row(
            date="2025-01-01",
            claim_text="수출액은 높은 수준이었다.",
            measurement_period="-",
            measurement_prd_se="-",
        )
    )
    assert out["mapping_exclusion_code"] == "PERIOD_MISSING"
    assert out["default_applied"] == "N"


def test_person_entity_wins_over_airline_context():
    out = normalize_row(
        measurement_row(
            measurement_indicator="LCC 이용객 수",
            measurement_item="LCC",
            claim_text="10개 항공사의 LCC 이용객은 100만 명이었다.",
            value="1000000",
            unit="명",
        )
    )
    assert out["entity_type"] == "person"


def test_explicit_comparison_year_beats_incorrect_change_base():
    out = normalize_row(
        measurement_row(
            claim_text="2023년까지 사업체는 지난 2019년보다 13% 증가했다.",
            measurement_indicator="로봇 사업체 수 증가율",
            measurement_period="2023",
            value="13",
            unit="%",
            value_type="증감률",
            measurement_role="증감률",
            change_base="전년",
        )
    )
    assert out["comparison_period"] == "2019"


def test_prepare_writes_ready_and_rejected_files(tmp_path):
    source = tmp_path / "source.csv"
    ready = measurement_row()
    rejected = measurement_row(
        claim_measurement_id="A1-C2-m1",
        measurement_usage="POLICY_VALUE",
        measurement_indicator="최저임금",
        measurement_item="-",
        claim_text="최저임금은 시간당 1만30원이다.",
        value="10030",
        unit="원",
    )
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ready))
        writer.writeheader()
        writer.writerows([ready, rejected])

    output = tmp_path / "ready.csv"
    rejected_output = tmp_path / "rejected.csv"
    accepted, excluded = prepare(source, output, rejected_output)

    assert len(accepted) == 1
    assert len(excluded) == 1
    assert list(csv.DictReader(output.open(encoding="utf-8-sig")))[0]["mapping_eligible"] == "Y"
    assert list(csv.DictReader(rejected_output.open(encoding="utf-8-sig")))[0]["mapping_exclusion_code"] == "NOT_KOSIS_VALUE"
