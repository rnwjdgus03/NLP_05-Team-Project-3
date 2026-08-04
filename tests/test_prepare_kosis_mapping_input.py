import csv

from prepare_kosis_mapping_input import (
    align_change_period,
    canonicalize_period,
    canonicalize_unit,
    expected_base_period,
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
    assert unit_dimension("백만US$") == "currency"


def test_period_labels_are_canonicalized_for_kosis():
    assert canonicalize_period("2023년말", "Y") == "2023"
    assert canonicalize_period("2024년 12월", "M") == "202412"


def test_normalize_row_uses_measurement_level_aliases():
    out = normalize_row(measurement_row())
    assert out["indicator"] == "반도체 수출액"
    assert out["industry_or_item"] == "반도체"
    assert out["period"] == "2024"
    assert out["unit_dimension"] == "currency"
    assert out["semantic_type"] == "amount"
    assert out["mapping_eligible"] == "Y"
    assert out["in_ready"] == "Y"
    assert out["mapping_gate"] == "READY"


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
    assert condition["mapping_gate"] == "REJECT"

    missing_period = normalize_row(measurement_row(measurement_period="-", measurement_prd_se="-"))
    assert missing_period["mapping_exclusion_code"] == "PERIOD_MISSING"
    assert missing_period["mapping_gate"] == "ENRICH"
    assert missing_period["enrichment_actions"] == "RESOLVE_PERIOD_FROM_CONTEXT"


def test_fallback_and_unknown_scope_are_sent_to_enrichment():
    fallback = normalize_row(measurement_row(measurement_binding_source="rule_fallback"))
    assert fallback["mapping_gate"] == "ENRICH"
    assert fallback["enrichment_actions"] == "CONFIRM_MEASUREMENT_BINDING"

    unknown_scope = normalize_row(measurement_row(claim_domain_scope="기타"))
    assert unknown_scope["mapping_gate"] == "REJECT"
    assert unknown_scope["mapping_exclusion_code"] == "SOURCE_SCOPE_UNCONFIRMED"
    assert unknown_scope["source_scope"] == "UNCONFIRMED"


def test_only_target_role_is_hard_rejected():
    target = normalize_row(measurement_row(measurement_role="목표값"))
    assert target["mapping_exclusion_code"] == "TARGET_NOT_OBSERVED"
    assert target["mapping_gate"] == "REJECT"
    assert target["in_ready"] == "N"

    for role in ("이전값", "참고값"):
        reviewable = normalize_row(measurement_row(measurement_role=role))
        assert reviewable["mapping_exclusion_code"] == "ROLE_NOT_DIRECT_TARGET"
        assert reviewable["mapping_gate"] == "ENRICH"
        assert reviewable["in_ready"] == "N"


def test_front_gate_blocks_forecast_company_and_foreign_market_values():
    forecast = normalize_row(measurement_row(
        claim_text="정부는 물가 상승률이 1.8%로 둔화될 것으로 봤다.",
        measurement_indicator="물가 상승률 전망",
        value="1.8",
        unit="%",
    ))
    assert forecast["measurement_observation_type"] == "FORECAST"
    assert forecast["source_scope"] == "POLICY_FORECAST"
    assert forecast["mapping_gate"] == "REJECT"
    assert forecast["mapping_exclusion_code"] == "FORECAST_NOT_OBSERVED"

    company = normalize_row(measurement_row(
        claim_text="회사 측은 정비사가 총 5849명이라고 밝혔다.",
        measurement_indicator="정비사 수",
        value="5849",
        unit="명",
    ))
    assert company["measurement_observation_type"] == "COMPANY_REPORTED"
    assert company["source_scope"] == "COMPANY"
    assert company["mapping_gate"] == "REJECT"

    wsts = normalize_row(measurement_row(
        claim_text="WSTS는 메모리반도체 시장이 20.6% 성장할 것으로 전망했다.",
        measurement_indicator="메모리반도체 시장 성장률 전망",
        value="20.6",
        unit="%",
    ))
    assert wsts["source_scope"] == "FOREIGN_OR_MARKET"
    assert wsts["mapping_gate"] == "REJECT"

    export_forecast = normalize_row(measurement_row(
        claim_text="수출 증가율은 작년 8.2%에서 올해 1.5%로 쪼그라들 것으로 봤다.",
        measurement_indicator="수출 증가율",
        measurement_period="2025",
        value="1.5",
        unit="%",
    ))
    assert export_forecast["measurement_observation_type"] == "FORECAST"
    assert export_forecast["mapping_gate"] == "REJECT"


def test_front_gate_keeps_derived_ratio_and_relative_date_as_diagnostics():
    ratio = normalize_row(measurement_row(
        claim_text="항공기 대당 정비사는 12.7명이다.",
        measurement_indicator="정비사 수",
        value="12.7",
        unit="명",
        value_type="수준값",
    ))
    assert ratio["unit"] == "명/대"
    assert ratio["unit_dimension"] == "ratio"
    assert ratio["measurement_observation_type"] == "DERIVED_RATIO"
    assert ratio["mapping_gate"] == "REJECT"

    relative = normalize_row(measurement_row(
        date="2025-01-02",
        claim_text="지난달 말(30일) 오후 3시 30분 기준 원달러 환율은 1472.5원이었다.",
        measurement_indicator="원달러 환율",
        measurement_period="지난달 말(30일)",
        measurement_prd_se="D",
        value="1472.5",
        unit="원",
    ))
    assert relative["measurement_period_normalized"] == "20241230"
    assert relative["relative_date_status"] == "ARTICLE_DATE_RELATIVE_EXPLICIT_DAY"
    assert relative["mapping_gate"] == "ENRICH"
    assert relative["mapping_exclusion_code"] == "INTRADAY_MARKET_RATE"
    assert relative["enrichment_actions"] == "CONFIRM_DAILY_OR_INTRADAY_OFFICIAL_TABLE"


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


def test_change_rate_bound_to_base_period_is_aligned_to_claim_target():
    row = measurement_row(
        claim_text=(
            "숙박·음식점업은 지난해 12월보다 1.4% 늘었지만, "
            "지난해 1월에 비하면 3.3% 줄었다."
        ),
        indicator="서비스업 생산지수",
        measurement_indicator="서비스업 생산지수",
        industry_or_item="숙박·음식점업",
        measurement_item="숙박·음식점업",
        period="202501",
        prd_se="M",
        measurement_period="202401",
        measurement_prd_se="M",
        measurement_role="증감률",
        value="3.3",
        unit="%",
        value_type="증감률",
        change_base="전년동월",
    )

    assert expected_base_period("202501", "전년동월") == "202401"
    assert align_change_period(row) == ("202501", "COMPARISON_PERIOD_TO_TARGET")
    out = normalize_row(row)
    assert out["raw_measurement_period"] == "202401"
    assert out["period"] == "202501"
    assert out["comparison_period"] == "202401"
    assert out["mapping_gate"] == "READY"


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


def test_prepare_writes_three_way_gate_files(tmp_path):
    source = tmp_path / "source.csv"
    rows = [
        measurement_row(),
        measurement_row(
            claim_measurement_id="A1-C2-m1",
            measurement_period="-",
            measurement_prd_se="-",
        ),
        measurement_row(
            claim_measurement_id="A1-C3-m1",
            measurement_usage="POLICY_VALUE",
        ),
    ]
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    ready_path = tmp_path / "ready.csv"
    enrich_path = tmp_path / "enrich.csv"
    reject_path = tmp_path / "reject.csv"
    all_path = tmp_path / "all.csv"
    prepare(source, ready_path, reject_path, enrich_path, all_path)

    ready = list(csv.DictReader(ready_path.open(encoding="utf-8-sig")))
    enrich = list(csv.DictReader(enrich_path.open(encoding="utf-8-sig")))
    reject = list(csv.DictReader(reject_path.open(encoding="utf-8-sig")))
    all_rows = list(csv.DictReader(all_path.open(encoding="utf-8-sig")))
    assert [row["mapping_gate"] for row in ready] == ["READY"]
    assert [row["mapping_gate"] for row in enrich] == ["ENRICH"]
    assert [row["mapping_gate"] for row in reject] == ["REJECT"]
    assert [row["in_ready"] for row in all_rows] == ["Y", "N", "N"]
