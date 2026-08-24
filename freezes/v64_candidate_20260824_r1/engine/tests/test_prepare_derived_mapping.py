from prepare_kosis_mapping_input import normalize_row


def test_rate_change_of_level_indicator_uses_derived_mapping():
    row = normalize_row({
        "claim_id": "c1",
        "claim_measurement_id": "c1-m1",
        "article_id": "DEV-1",
        "title": "소매판매 지수",
        "date": "2026-02-01",
        "url": "https://example.test/dev-1",
        "claim_text": "지난해 소매판매액 지수는 0.5% 증가했다.",
        "prev_sentence": "",
        "next_sentence": "",
        "claim_domain_scope": "국내공식통계",
        "is_recurring_series": "Y",
        "metric_domain": "소매·소비",
        "indicator": "소매판매액 지수",
        "measurement_text": "0.5%",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_indicator": "소매판매액 지수",
        "measurement_item": "",
        "measurement_period": "2025",
        "measurement_prd_se": "Y",
        "measurement_role": "증감률",
        "value": "0.5",
        "unit": "%",
        "value_type": "증감률",
        "direction": "증가",
        "change_base": "전년",
        "needs_review": "N",
    })
    assert row["mapping_gate"] == "READY"
    assert row["semantic_type"] == "rate_change"
    assert row["comparison_period"] == "2024"
    assert row["derived_computation_required"] == "Y"
    assert row["mapping_type"] == ""
    assert row["allowed_mapping_types"] == "direct|rate_from_level"


def test_individual_product_price_is_not_promoted_to_derived_mapping():
    row = normalize_row({
        "claim_id": "c2",
        "claim_measurement_id": "c2-m1",
        "article_id": "DEV-2",
        "title": "제품 가격 인상",
        "date": "2025-01-01",
        "url": "https://example.test/dev-2",
        "claim_text": "다이제 초코 가격은 2500원에서 2800원으로 12% 올랐다.",
        "prev_sentence": "",
        "next_sentence": "",
        "claim_domain_scope": "국내공식통계",
        "is_recurring_series": "Y",
        "metric_domain": "물가",
        "indicator": "다이제 초코 판매가",
        "industry_or_item": "다이제 초코",
        "measurement_text": "12%",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_indicator": "다이제 초코 판매가",
        "measurement_item": "다이제 초코",
        "measurement_period": "2025",
        "measurement_prd_se": "Y",
        "measurement_role": "증감률",
        "value": "12",
        "unit": "%",
        "value_type": "증감률",
        "direction": "증가",
        "change_base": "전년",
        "needs_review": "N",
    })
    assert row["mapping_gate"] == "REJECT"
    assert row["mapping_exclusion_code"] == "INDIVIDUAL_PRODUCT_PRICE"
    assert row["derived_computation_required"] == "N"


def test_direct_current_value_is_released_from_sibling_batch_review():
    row = normalize_row({
        "claim_id": "c3",
        "claim_measurement_id": "c3-m1",
        "article_id": "DEV-3",
        "title": "고령 자영업자 증가",
        "date": "2024-02-15",
        "url": "https://example.test/dev-3",
        "claim_text": "지난해 60세 이상 자영업자는 207만3000명으로 집계됐다.",
        "prev_sentence": "",
        "next_sentence": "",
        "claim_domain_scope": "국내공식통계",
        "is_recurring_series": "Y",
        "metric_domain": "고용",
        "indicator": "60세 이상 자영업자 수",
        "measurement_text": "207만3000명",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_indicator": "60세 이상 자영업자 수",
        "measurement_item": "",
        "measurement_period": "2023",
        "measurement_prd_se": "Y",
        "measurement_role": "현재값",
        "value": "2073000",
        "unit": "명",
        "value_type": "수준값",
        "extraction_confidence": "high",
        "needs_review": "Y",
        "review_reason": "measurement_binding_fallback:1;measurement_period_ungrounded:1",
    })
    assert row["mapping_gate"] == "READY"
    assert row["period"] == "2023"
    assert row["measurement_review_override"] == "DIRECT_ROW_CONFIRMED_DESPITE_BATCH_REVIEW"


def test_rule_fallback_review_is_not_released():
    row = normalize_row({
        "claim_id": "c4",
        "claim_measurement_id": "c4-m1",
        "article_id": "DEV-4",
        "title": "고령 자영업자 증가",
        "date": "2024-02-15",
        "url": "https://example.test/dev-4",
        "claim_text": "지난해 60세 이상 자영업자는 207만3000명으로 집계됐다.",
        "prev_sentence": "",
        "next_sentence": "",
        "claim_domain_scope": "국내공식통계",
        "is_recurring_series": "Y",
        "metric_domain": "고용",
        "indicator": "60세 이상 자영업자 수",
        "measurement_text": "207만3000명",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_indicator": "60세 이상 자영업자 수",
        "measurement_period": "2023",
        "measurement_prd_se": "Y",
        "measurement_role": "현재값",
        "value": "2073000",
        "unit": "명",
        "value_type": "수준값",
        "extraction_confidence": "high",
        "needs_review": "Y",
        "review_reason": "measurement_rule_fallback:1",
    })
    assert row["mapping_gate"] == "ENRICH"
    assert row["mapping_exclusion_code"] == "MEASUREMENT_REVIEW_REQUIRED"
    assert row["measurement_review_override"] == ""


def test_ungrounded_period_review_without_article_repair_is_not_released():
    row = normalize_row({
        "claim_id": "c5",
        "claim_measurement_id": "c5-m1",
        "article_id": "DEV-5",
        "title": "고령 자영업자 증가",
        "date": "2024-02-15",
        "url": "https://example.test/dev-5",
        "claim_text": "60세 이상 자영업자는 207만3000명으로 집계됐다.",
        "prev_sentence": "",
        "next_sentence": "",
        "claim_domain_scope": "국내공식통계",
        "is_recurring_series": "Y",
        "metric_domain": "고용",
        "indicator": "60세 이상 자영업자 수",
        "measurement_text": "207만3000명",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_indicator": "60세 이상 자영업자 수",
        "measurement_period": "2023",
        "measurement_prd_se": "Y",
        "measurement_role": "현재값",
        "value": "2073000",
        "unit": "명",
        "value_type": "수준값",
        "extraction_confidence": "high",
        "needs_review": "Y",
        "review_reason": "measurement_period_ungrounded:1",
    })
    assert row["mapping_gate"] == "ENRICH"
    assert row["mapping_exclusion_code"] == "MEASUREMENT_REVIEW_REQUIRED"
    assert row["measurement_review_override"] == ""
