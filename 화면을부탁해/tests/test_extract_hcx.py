import json

from extract_hcx import (
    add_fallback_measurements,
    apply_local_explicit_years,
    apply_relative_month_periods,
    build_hcx_user_content,
    ensure_measurement_bindings,
    extract_claim,
    extract_numeric_candidates,
    infer_relative_month_period,
    measurement_issues,
    normalize_number,
    normalize_hcx_measurements,
    period_is_grounded,
    remove_ungrounded_claim_period,
    remove_ungrounded_measurement_periods,
    to_rows,
)


def candidate_pairs(text):
    return {(item["value"], item["unit"]) for item in extract_numeric_candidates(text)}


def test_retrieval_context_is_marked_as_hint_not_article_evidence():
    content = build_hcx_user_content(
        title="Title",
        date="2025-01-01",
        text="The measured value is 10 percent.",
        prev="-",
        nxt="-",
        candidates=[],
        retrieval_context='[{"tbl_id":"T1","table_name":"Rate table"}]',
        article_context="[title] Employment\nLead paragraph.",
        local_context="[C1] The measured value is 10 percent.",
        antecedent_context="[C0] In 2024 the baseline was measured.",
    )

    assert "KOSIS retrieval hints - not article evidence" in content
    assert '"tbl_id":"T1"' in content
    assert "Never copy a value, period, unit" in content
    assert "[Additional article evidence]" in content
    assert "[Shared article context]" in content
    assert "publication date is metadata" in content


def test_normalize_korean_magnitude_numbers():
    assert normalize_number("1만30") == "10030"
    assert normalize_number("209만6270") == "2096270"
    assert normalize_number("31.2만") == "312000"
    assert normalize_number("1,800만") == "18000000"


def test_extracts_and_deduplicates_multi_measurement_claim():
    text = (
        "국가 검진에 C형 간염도 포함 ▲ 최저임금 시간당 1만30원 "
        "=최저임금이 시간당 9860원에서 1만30원으로 1.7% 인상된다."
    )
    candidates = extract_numeric_candidates(text)

    assert {(item["value"], item["unit"]) for item in candidates} == {
        ("10030", "원"),
        ("9860", "원"),
        ("1.7", "%"),
    }
    assert len(candidates) == 3
    assert next(item for item in candidates if item["value"] == "9860")["measurement_role"] == "이전값"
    assert next(item for item in candidates if item["value"] == "1.7")["value_type"] == "증감률"


def test_extracts_context_policy_and_age_values():
    assert candidate_pairs("주 근로시간 40시간을 기준으로 환산한 월급은 209만6270원이다.") == {
        ("40", "시간"),
        ("2096270", "원"),
    }
    assert candidate_pairs("1년간 받을 수 있는 급여는 최대 1800만원에서 2310만원으로 오른다.") == {
        ("1", "년"),
        ("18000000", "원"),
        ("23100000", "원"),
    }
    assert candidate_pairs("기존엔 54, 66세 여성만 검사했는데 60세 여성도 포함됐다.") == {
        ("54", "세"),
        ("66", "세"),
        ("60", "세"),
    }


def test_extracts_scaled_currency_approximate_counts_and_ranges():
    currency = extract_numeric_candidates("수출은 6838억 달러를 기록했다.")
    assert {(item["value"], item["unit"]) for item in currency} == {
        ("683800000000", "달러"),
    }

    approximate = extract_numeric_candidates("여객 4720만여 명과 기업 455여개가 참가했다.")
    assert {(item["value"], item["unit"]) for item in approximate} == {
        ("47200000", "명"),
        ("455", "개"),
    }
    assert {item["value_approximate"] for item in approximate} == {"Y"}

    prefixed = extract_numeric_candidates("약 900개사가 참가한다.")
    assert prefixed[0]["value_approximate"] == "Y"

    assert candidate_pairs("정비사는 대당 16~18명 수준이다.") == {
        ("16", "명/대"),
        ("18", "명/대"),
    }


def test_extracts_percent_band_as_range_not_exact_point():
    candidates = extract_numeric_candidates("물가 상승률은 1%대에 머물 것으로 전망했다.")
    band = next(item for item in candidates if item["measurement_text"] == "1%대")

    assert band["value"] == "1"
    assert band["value_min"] == "1"
    assert band["value_max"] == "1.9"
    assert band["value_approximate"] == "Y"
    assert band["measurement_observation_type"] == "FORECAST"
    assert band["measurement_usage"] == "CONTEXT"


def test_extracts_percent_point_and_company_ratio_scope():
    pp = extract_numeric_candidates("전망치는 기존보다 0.3%포인트 낮아졌다.")
    assert pp[0]["unit"] == "%p"
    assert pp[0]["value_type"] == "증감량"

    ratio = extract_numeric_candidates("회사 측은 항공기 대당 12.7명이라고 밝혔다.")
    assert ratio[0]["unit"] == "명/대"
    assert ratio[0]["measurement_observation_type"] == "COMPANY_REPORTED"
    assert ratio[0]["source_scope"] == "COMPANY"


def test_policy_threshold_is_condition_but_support_amount_is_policy_value():
    candidates = extract_numeric_candidates(
        "지원 대상은 중위소득 150% 이하이며 월 20만원을 지원받는다."
    )
    usages = {item["value"]: item["measurement_usage"] for item in candidates}

    assert usages == {"150": "CONDITION", "200000": "POLICY_VALUE"}


def test_breakthrough_threshold_is_context_not_observed_kosis_value():
    candidates = extract_numeric_candidates(
        "화장품 수출은 102억 달러로 처음으로 100억 달러를 돌파했다."
    )
    usages = {item["value"]: item["measurement_usage"] for item in candidates}

    assert usages["10200000000"] == "KOSIS_VALUE"
    assert usages["10000000000"] == "CONTEXT"


def test_denominator_and_group_counts_are_context_not_kosis_values():
    density = extract_numeric_candidates("직원 1만명당 로봇 1012대를 사용한다.")
    usages = {item["value"]: item["measurement_usage"] for item in density}
    assert usages == {"10000": "CONDITION", "1012": "KOSIS_VALUE"}

    airlines = extract_numeric_candidates("LCC 10사와 국내 12개 항공사의 정비사를 조사했다.")
    assert {item["measurement_usage"] for item in airlines} == {"CONTEXT"}


def test_as_of_date_context_does_not_turn_observed_count_into_condition():
    candidates = extract_numeric_candidates("정비사 총 5849명(2023년말 기준)이다.")

    assert candidates[0]["measurement_usage"] == "KOSIS_VALUE"


def test_measurement_validation_and_rule_fallback_cover_missing_values():
    candidates = extract_numeric_candidates("급여가 1800만원에서 2310만원으로 올랐다.")
    result = {"measurements": []}

    assert measurement_issues(result, candidates)
    assert add_fallback_measurements(result, candidates) == 2
    assert measurement_issues(result, candidates) == []
    assert {item["_source"] for item in result["measurements"]} == {"rule_fallback"}


def test_kosis_measurement_requires_indicator_but_allows_unresolved_period():
    candidates = extract_numeric_candidates("반도체 수출은 1419억 달러를 기록했다.")
    result = {
        "measurements": [{
            "measurement_text": "1419억 달러",
            "measurement_usage": "KOSIS_VALUE",
            "measurement_role": "현재값",
            "value": "141900000000",
            "unit": "달러",
            "measurement_indicator": "-",
            "measurement_period": "-",
            "measurement_prd_se": "-",
        }]
    }

    issues = measurement_issues(result, candidates)

    assert any("measurement_indicator" in issue for issue in issues)
    assert not any("measurement_period" in issue for issue in issues)
    assert not any("measurement_prd_se" in issue for issue in issues)


def test_missing_binding_uses_claim_fields_and_is_marked_for_review():
    result = {
        "indicator": "수출액",
        "industry_or_item": "반도체",
        "period": "2024",
        "prd_se": "Y",
        "measurements": [{
            "measurement_usage": "KOSIS_VALUE",
            "_source": "hcx",
        }],
    }

    assert ensure_measurement_bindings(result) == 1
    measurement = result["measurements"][0]
    assert measurement["measurement_indicator"] == "수출액"
    assert measurement["measurement_item"] == "반도체"
    assert measurement["measurement_period"] == "2024"
    assert measurement["measurement_prd_se"] == "Y"
    assert measurement["_binding_source"] == "claim_fallback"


def test_missing_measurement_period_stays_unresolved_when_claim_period_is_missing():
    result = {
        "indicator": "-",
        "industry_or_item": "-",
        "period": "-",
        "prd_se": "-",
        "measurements": [{
            "measurement_usage": "KOSIS_VALUE",
            "measurement_period": "-",
            "measurement_prd_se": "-",
            "_source": "hcx",
        }],
    }

    assert ensure_measurement_bindings(result) == 0
    measurement = result["measurements"][0]
    assert measurement["measurement_period"] == "-"
    assert measurement["measurement_prd_se"] == "-"
    assert measurement["_binding_source"] == "hcx"


def test_optional_item_fallback_keeps_hcx_binding_source():
    result = {
        "indicator": "정비사 수",
        "industry_or_item": "항공",
        "period": "2023",
        "prd_se": "Y",
        "measurements": [{
            "measurement_usage": "KOSIS_VALUE",
            "measurement_indicator": "정비사 수",
            "measurement_item": "-",
            "measurement_period": "2023",
            "measurement_prd_se": "Y",
            "_source": "hcx",
        }],
    }

    assert ensure_measurement_bindings(result) == 0
    assert result["measurements"][0]["measurement_item"] == "항공"
    assert result["measurements"][0]["_binding_source"] == "hcx"


def test_measurement_period_must_be_grounded_in_article_context():
    claim = {
        "title": "수출 역대 최대",
        "date": "2025-01-01",
        "claim_text": "2022년 기록을 넘어 수출액이 증가했다.",
        "prev_sentence": "지난해 수출이 호조였다.",
        "prev_prev_sentence": "2024년 수출 실적이 발표됐다.",
    }

    assert period_is_grounded("2024", claim)
    assert period_is_grounded("2022", claim)
    assert not period_is_grounded("202501", claim)


def test_last_august_before_february_article_resolves_to_previous_year():
    claim = {
        "title": "제주 주소 갖기 캠페인",
        "date": "2026-02-25",
        "claim_text": (
            "통계청에 따르면 지난 8월 기준 제주도는 청년인구 중심으로 "
            "주민등록인구가 28개월째 감소하고 있다."
        ),
        "prev_sentence": "-",
        "prev_prev_sentence": "-",
    }

    assert infer_relative_month_period(claim) == "202508"
    assert period_is_grounded("202508", claim)
    assert not period_is_grounded("202608", claim)


def test_relative_month_in_same_year_and_last_month_year_boundary():
    same_year = {
        "date": "2026-10-03",
        "claim_text": "지난 8월 소비자물가는 2.1% 상승했다.",
    }
    year_boundary = {
        "date": "2026-01-05",
        "claim_text": "지난달 소비자물가는 2.1% 상승했다.",
    }

    assert infer_relative_month_period(same_year) == "202608"
    assert infer_relative_month_period(year_boundary) == "202512"


def test_relative_month_postprocessing_corrects_hcx_future_period():
    claim = {
        "date": "2026-02-25",
        "claim_text": "지난 8월 기준 주민등록인구가 28개월째 감소하고 있다.",
    }
    result = {
        "period": "202608",
        "prd_se": "M",
        "time_resolution_status": "확정",
        "measurements": [{
            "measurement_period": "202608",
            "measurement_prd_se": "M",
        }],
    }

    assert apply_relative_month_periods(result, claim) == 2
    assert result["period"] == "202508"
    assert result["measurements"][0]["measurement_period"] == "202508"
    assert remove_ungrounded_claim_period(result, claim) == 0
    assert remove_ungrounded_measurement_periods(result, claim) == 0


def test_extract_claim_corrects_wrong_hcx_period_for_jeju_article(monkeypatch):
    claim_text = (
        "통계청에 따르면 지난 8월 기준 제주도는 청년인구 중심으로 "
        "주민등록인구가 28개월째 감소하고 있으며, 전입보다 전출이 많은 "
        "순유출 현상이 25개월째 지속되고 있다."
    )
    candidates = extract_numeric_candidates(claim_text)
    measurements = [
        {
            "measurement_text": candidate["measurement_text"],
            "measurement_usage": candidate["measurement_usage"],
            "measurement_indicator": "주민등록인구 감소 지속기간",
            "measurement_item": "제주도",
            "measurement_period": "202608",
            "measurement_prd_se": "M",
            "measurement_role": candidate["measurement_role"],
            "value": candidate["value"],
            "unit": candidate["unit"],
            "value_type": candidate["value_type"],
            "direction": candidate["direction"],
            "change_base": candidate["change_base"],
        }
        for candidate in candidates
    ]
    wrong_hcx_result = {
        "indicator": "주민등록인구",
        "industry_or_item": "제주도",
        "period": "202608",
        "prd_se": "M",
        "time_resolution_status": "확정",
        "measurements": measurements,
    }
    monkeypatch.setattr(
        "extract_hcx.call_hcx",
        lambda **kwargs: json.dumps(wrong_hcx_result, ensure_ascii=False),
    )

    result = extract_claim(
        "test-key",
        "HCX-007",
        {
            "title": "제주 주소 갖기 캠페인",
            "date": "2026-02-25",
            "claim_text": claim_text,
            "prev_sentence": "-",
            "prev_prev_sentence": "-",
        },
    )

    assert result["period"] == "202508"
    assert {row["measurement_period"] for row in result["measurements"]} == {"202508"}
    assert result["_relative_period_corrected_count"] == "3"


def test_ungrounded_claim_period_is_not_reintroduced_by_binding_fallback():
    claim = {
        "title": "정비 인력 부족",
        "date": "2026-02-25",
        "claim_text": "정비사 비율은 27.4%였다.",
    }
    result = {
        "period": "202602",
        "prd_se": "M",
        "indicator": "정비사 비율",
        "industry_or_item": "항공",
        "measurements": [{
            "measurement_period": "202602",
            "measurement_prd_se": "M",
            "measurement_indicator": "정비사 비율",
            "measurement_item": "항공",
        }],
    }

    assert remove_ungrounded_claim_period(result, claim) == 1
    assert remove_ungrounded_measurement_periods(result, claim) == 1
    assert ensure_measurement_bindings(result) == 0
    assert result["period"] == "-"
    assert result["measurements"][0]["measurement_period"] == "-"


def test_ungrounded_period_is_removed_instead_of_using_article_date():
    claim = {
        "title": "LCC 정비 인력 부족",
        "date": "2025-01-01",
        "claim_text": "LCC 정비사 비율은 27.4%였다.",
        "prev_sentence": "-",
        "prev_prev_sentence": "-",
    }
    result = {"measurements": [{
        "measurement_period": "202501",
        "measurement_prd_se": "M",
    }]}

    assert remove_ungrounded_measurement_periods(result, claim) == 1
    assert result["measurements"][0]["measurement_period"] == "-"
    assert result["measurements"][0]["measurement_prd_se"] == "-"


def test_publication_date_in_shared_context_does_not_ground_period():
    claim = {
        "title": "LCC staffing",
        "date": "2025-01-01",
        "claim_text": "The staffing ratio was 27.4 percent.",
        "prev_sentence": "-",
        "next_sentence": "-",
        "article_context": (
            "[title] LCC staffing\n"
            "[publication_date] 2025-01-01\n"
            "[A1-C001] Staffing was discussed."
        ),
    }

    assert not period_is_grounded("2025", claim)


def test_local_explicit_year_overrides_title_year_for_that_value():
    claim = {
        "title": "2024년 수출 역대 최대",
        "claim_text": "이에 2018년(697억 달러 흑자) 이후 최대 흑자를 기록했다.",
    }
    result = {"measurements": [{
        "measurement_text": "697억 달러",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
    }]}

    assert apply_local_explicit_years(result, claim) == 1
    assert result["measurements"][0]["measurement_period"] == "2018"


def test_distant_background_year_does_not_override_observation_period():
    claim = {
        "claim_text": (
            "선박 수출은 2021년 높은 선가로 수주한 LNG 운반선이 본격 수출되면서 "
            "18% 증가한 256억 달러를 기록했다."
        ),
    }
    result = {"measurements": [{
        "measurement_text": "256억 달러",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
    }]}

    assert apply_local_explicit_years(result, claim) == 0
    assert result["measurements"][0]["measurement_period"] == "2024"


def test_normalization_drops_values_copied_from_neighboring_sentences():
    result = {
        "measurements": [
            {
                "measurement_text": "시간당 1만30원",
                "measurement_usage": "KOSIS_VALUE",
                "measurement_role": "현재값",
                "value": "10300",
                "unit": "원",
            }
        ]
    }

    normalized = normalize_hcx_measurements(
        result,
        candidates=[],
        text="1 노동·복지·가정 못 받은 양육비, 정부가 선지급…",
    )

    assert normalized["measurements"] == []


def test_normalization_corrects_value_using_grounded_measurement_text():
    text = "최저임금 시간당 1만30원으로 인상된다."
    candidates = extract_numeric_candidates(text)
    result = {
        "measurements": [
            {
                "measurement_text": "최저임금 시간당 1만30원",
                "measurement_usage": "POLICY_VALUE",
                "measurement_role": "현재값",
                "value": "10300",
                "unit": "원",
            }
        ]
    }

    normalized = normalize_hcx_measurements(result, candidates, text=text)

    assert normalized["measurements"][0]["value"] == "10030"


def test_to_rows_keeps_measurements_without_precomputed_kosis_gate():
    claim = {
        "claim_id": "A0003-C009",
        "article_id": "A0003",
        "title": "육아휴직 급여",
        "date": "2025-01-01",
        "url": "https://example.com",
        "claim_text": "급여가 1800만원에서 2310만원으로 오른다.",
        "prev_sentence": "-",
        "prev_prev_sentence": "육아휴직 제도가 개편됐다.",
    }
    result = {
        "claim_domain_scope": "기타",
        "is_recurring_series": "N",
        "measurements": [
            {
                "measurement_text": "1800만원",
                "measurement_usage": "POLICY_VALUE",
                "measurement_indicator": "육아휴직 급여",
                "measurement_item": "-",
                "measurement_period": "2024",
                "measurement_prd_se": "Y",
                "measurement_role": "이전값",
                "value": "18000000",
                "value_min": "-",
                "value_max": "-",
                "value_approximate": "N",
                "unit": "원",
                "value_type": "수준값",
                "direction": "증가",
                "change_base": "특정시점",
                "_source": "hcx",
            },
            {
                "measurement_text": "2310만원",
                "measurement_usage": "POLICY_VALUE",
                "measurement_indicator": "육아휴직 급여",
                "measurement_item": "-",
                "measurement_period": "2025",
                "measurement_prd_se": "Y",
                "measurement_role": "현재값",
                "value": "23100000",
                "value_min": "-",
                "value_max": "-",
                "value_approximate": "N",
                "unit": "원",
                "value_type": "수준값",
                "direction": "증가",
                "change_base": "특정시점",
                "_source": "hcx",
            },
        ],
    }

    rows = to_rows(claim, result, "HCX-007")

    assert len(rows) == 2
    assert [row["claim_measurement_id"] for row in rows] == [
        "A0003-C009-m1",
        "A0003-C009-m2",
    ]
    assert {row["value"] for row in rows} == {"18000000", "23100000"}
    assert {row["measurement_period"] for row in rows} == {"2024", "2025"}
    assert {row["measurement_indicator"] for row in rows} == {"육아휴직 급여"}
    assert {row["prev_prev_sentence"] for row in rows} == {"육아휴직 제도가 개편됐다."}
    assert all("verifiable_kosis" not in row for row in rows)
    assert all("unverifiable_reason" not in row for row in rows)
