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

    missing_period = normalize_row(measurement_row(measurement_period="-", measurement_prd_se="-"))
    assert missing_period["mapping_exclusion_code"] == "PERIOD_MISSING"


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
