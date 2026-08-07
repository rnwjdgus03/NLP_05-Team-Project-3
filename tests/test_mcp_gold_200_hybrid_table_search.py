from rerank_mcp_gold_200_table_candidates import (
    merge_candidate_pool,
    normalized_reranker_scores,
    rerank_claim_candidates,
)
from enrich_mcp_gold_200_inputs import choose_period, enrich_row, extract_structured_targets
from select_mcp_gold_200_two_stage_coordinates import select_two_stage
from search_mcp_gold_200_chroma_bge import (
    build_gold_free_table_query,
    infer_table_search_profile,
    select_claim_unit,
)


def test_gold_free_query_uses_public_input_fields():
    query = build_gold_free_table_query(
        {
            "title": "2024년 수출 역대 최대",
            "claim_text": "수출이 6838억 달러를 기록했다.",
            "claim_type": "LEVEL",
            "claim_value": "6838",
            "claim_unit": "억 달러",
        }
    )
    assert "2024년 수출 역대 최대" in query
    assert "LEVEL" in query
    assert "6838" in query
    assert "억 달러" in query


def test_gold_free_query_rejects_answer_columns():
    try:
        build_gold_free_table_query({"claim_text": "x", "gold_tbl_id": "SECRET"})
    except ValueError as exc:
        assert "gold_tbl_id" in str(exc)
    else:
        raise AssertionError("gold field must be rejected")


def test_claim_unit_is_selected_next_to_claim_value():
    assert select_claim_unit(
        {
            "claim_text": "2024년 수출은 6838억 달러로 전년보다 8.2% 증가했다.",
            "claim_value": "6838.0",
            "claim_unit": "['년', '%']",
            "claim_type": "LEVEL",
        }
    ) == "억 달러"
    assert select_claim_unit(
        {
            "claim_text": "고용률은 전년보다 0.3%포인트 올랐다.",
            "claim_value": "0.3",
            "claim_unit": "['년', '%']",
            "claim_type": "CHANGE_RATE",
        }
    ) == "%포인트"


def test_claim_unit_prefers_rate_over_same_number_used_as_month():
    assert select_claim_unit(
        {
            "claim_text": "2월 소비자물가는 전년 동월 대비 2％ 상승했다.",
            "claim_value": "2.0",
            "claim_unit": "['월', '%']",
            "claim_type": "CHANGE_RATE",
        }
    ) == "%"


def test_domain_profile_prefers_canonical_trade_table_and_penalizes_surveys():
    profile = infer_table_search_profile(
        {"title": "수출 역대 최대", "claim_text": "전체 수출액은 6838억 달러다."}
    )
    assert profile["aliases"] == ("품목별 수출액 수입액",)
    assert "기업혁신조사" in profile["negative_terms"]
    country = infer_table_search_profile(
        {"title": "대미 수출 증가", "claim_text": "미국 수출액이 늘었다."}
    )
    assert country["aliases"] == ("국가별 수출액 수입액",)


def test_reranker_probabilities_are_normalized_per_query():
    calibrated = normalized_reranker_scores([0.01, 0.5, 0.99])
    assert calibrated[0][1] == 0.0
    assert abs(calibrated[1][1] - 0.5) < 1e-12
    assert calibrated[2][1] == 1.0


def test_period_extraction_resolves_relative_month_from_publication_date():
    prd_se, period, previous, source = choose_period(
        {
            "date": "2025-06-11",
            "claim_text": "고용률은 지난달 63.8%로 1년 전보다 0.3%포인트 늘었다.",
            "claim_value": "63.8",
        }
    )
    assert (prd_se, period, source) == ("M", "202505", "previous_month")
    assert previous == "202405"


def test_period_extraction_uses_period_nearest_to_claim_value():
    prd_se, period, previous, source = choose_period(
        {
            "date": "2025-07-02",
            "claim_text": "지난달 상승률은 2.5%였고 2022년 1월에는 15.8%였다.",
            "claim_value": "15.8",
        }
    )
    assert (prd_se, period, source) == ("M", "202201", "explicit_year_month")


def test_enriched_row_adds_pipeline_period_and_unit_fields():
    row = enrich_row(
        {
            "gold_id": "G1",
            "date": "2025-01-01",
            "claim_text": "2024년 수출은 6838억 달러였다.",
            "claim_value": "6838.0",
            "claim_unit": "['년']",
            "claim_type": "LEVEL",
        }
    )
    assert row["period"] == "2024"
    assert row["prd_se"] == "Y"
    assert row["unit"] == "억 달러"
    assert row["canonical_unit"] == "억달러"
    assert row["unit_dimension"] == "currency"
    assert row["semantic_type"] == "amount"
    assert row["input_quality_status"] == "READY"
    assert row["claim_measurement_id"] == ""
    assert row["value"] == "6838.0"


def test_enriched_change_rate_recovers_structural_mapping_inputs():
    row = enrich_row(
        {
            "gold_id": "G2",
            "claim_id": "C2",
            "date": "2025-06-11",
            "claim_text": "지난달 수출액은 전년 동월보다 8.2% 증가했다.",
            "claim_value": "8.2",
            "claim_unit": "%",
            "claim_type": "CHANGE_RATE",
        }
    )
    assert row["semantic_type"] == "rate_change"
    assert row["value_type"] == "증감률"
    assert row["measurement_role"] == "증감률"
    assert row["change_base"] == "전년동월"
    assert row["comparison_period"] == "202405"
    assert row["claim_measurement_id"] == "C2"
    assert row["mapping_type"] == ""


def test_count_change_becomes_absolute_change_not_rate_change():
    row = enrich_row(
        {
            "gold_id": "G4",
            "claim_id": "C4",
            "date": "2025-02-14",
            "claim_text": "지난달 취업자 수는 전년 동월 대비 13만5000명 늘었다.",
            "claim_value": "5000",
            "claim_unit": "['월', '명']",
            "claim_type": "CHANGE_RATE",
        }
    )
    assert row["unit"] == "명"
    assert row["semantic_type"] == "absolute_change"
    assert row["value_type"] == "증감량"
    assert row["input_quality_status"] == "READY"


def test_bad_temporal_level_value_is_quarantined():
    row = enrich_row(
        {
            "gold_id": "G3",
            "claim_id": "C3",
            "date": "2025-01-01",
            "claim_text": "2위 생산국이 2023년 이후 수출을 재개했다.",
            "claim_value": "2.0",
            "claim_unit": "['년']",
            "claim_type": "LEVEL",
        }
    )
    assert row["input_quality_status"] == "NEEDS_INPUT_REVIEW"
    assert row["input_quality_reason"] == "LEVEL_VALUE_LOOKS_TEMPORAL"


def test_structured_targets_bind_country_age_and_product_to_obj_fields():
    country = extract_structured_targets(
        {"claim_text": "대미 수출액은 1278억달러였다.", "claim_value": "1278"}
    )
    assert country["destination_country"] == "미국"
    assert country["obj_target_terms"] == "미국"
    product = extract_structured_targets(
        {"claim_text": "반도체 수출액은 1419억달러였다.", "claim_value": "1419"}
    )
    assert product["industry_or_item"] == "반도체"
    assert product["obj_target_terms"] == "반도체"
    age = extract_structured_targets(
        {"claim_text": "15~29세 청년 실업률은 7.5%였다.", "claim_value": "7.5"}
    )
    assert age["age_group"] == "15 - 29세"


def test_two_stage_selection_chooses_item_before_matching_obj():
    claim = {
        "claim_text": "미국 수출액은 10억달러였다.",
        "item_intent_terms": "수출액",
        "obj_target_terms": "미국",
    }
    candidates = [
        {
            "org_id": "1", "tbl_id": "T", "selected_itm_id": "IMP",
            "selected_itm_name": "수입액", "selected_obj_l1_name": "미국",
            "candidate_rank": "1", "table_rank": "1", "prd_se_match": "True",
        },
        {
            "org_id": "1", "tbl_id": "T", "selected_itm_id": "EXP",
            "selected_itm_name": "수출액", "selected_obj_l1_name": "계",
            "candidate_rank": "2", "table_rank": "1", "prd_se_match": "True",
        },
        {
            "org_id": "1", "tbl_id": "T", "selected_itm_id": "EXP",
            "selected_itm_name": "수출액", "selected_obj_l1_name": "미국",
            "candidate_rank": "3", "table_rank": "1", "prd_se_match": "True",
        },
    ]
    selected = select_two_stage(claim, candidates, item_top_k=2)
    assert selected["selected_itm_id"] == "EXP"
    assert selected["selected_obj_l1_name"] == "미국"
    assert selected["original_candidate_rank"] == "3"


def test_two_stage_selection_prefers_aggregate_when_claim_has_no_obj_target():
    claim = {"claim_text": "전체 수출액은 10억달러였다.", "item_intent_terms": "수출액"}
    candidates = [
        {
            "org_id": "1", "tbl_id": "T", "selected_itm_id": "EXP",
            "selected_itm_name": "수출액", "selected_obj_l1_name": "감 초",
            "candidate_rank": "1", "table_rank": "1", "prd_se_match": "True",
        },
        {
            "org_id": "1", "tbl_id": "T", "selected_itm_id": "EXP",
            "selected_itm_name": "수출액", "selected_obj_l1_name": "-",
            "candidate_rank": "3", "table_rank": "1", "prd_se_match": "True",
        },
    ]
    selected = select_two_stage(claim, candidates)
    assert selected["selected_obj_l1_name"] == "-"
    assert selected["two_stage_obj_aggregate"] == "Y"


def test_pool_deduplicates_and_preserves_both_ranks():
    lexical = [
        {
            "gold_id": "G1",
            "org_id": "101",
            "tbl_id": "T1",
            "tbl_name": "수출액",
            "candidate_rank": "2",
            "candidate_score": "9.5",
        }
    ]
    dense = [
        {
            "gold_id": "G1",
            "org_id": "101",
            "tbl_id": "T1",
            "candidate_rank": "1",
            "semantic_score": "0.8",
            "candidate_document": "통계표: 수출액",
        }
    ]
    pool = merge_candidate_pool(lexical, dense, lexical_top_k=50, dense_top_k=20)
    assert len(pool["G1"]) == 1
    assert pool["G1"][0]["lexical_rank"] == 2
    assert pool["G1"][0]["dense_rank"] == 1
    assert pool["G1"][0]["semantic_score"] == 0.8


def test_lexical_guard_keeps_dense_only_candidate_out_of_primary_results():
    claim = {
        "gold_id": "G1",
        "title": "수출 통계",
        "claim_text": "수출액이 증가했다.",
        "claim_type": "LEVEL",
        "claim_value": "10",
        "claim_unit": "억 달러",
    }
    candidates = [
        {
            "org_id": "1",
            "tbl_id": "LEX",
            "tbl_name": "품목별 수출액",
            "category_path": "무역",
            "lexical_rank": 10,
            "dense_rank": None,
        },
        {
            "org_id": "2",
            "tbl_id": "DENSE",
            "tbl_name": "수출 설문",
            "category_path": "기업조사",
            "lexical_rank": None,
            "dense_rank": 1,
        },
    ]

    def fake_scores(query, documents):
        assert "수출 통계" in query
        return [0.1, 0.99]

    rows = rerank_claim_candidates(claim, candidates, fake_scores, final_top_k=2)
    assert [row["tbl_id"] for row in rows] == ["LEX", "DENSE"]
    assert rows[0]["retrieval_backend"] == "lexical-first+bge-reranker+chroma-audit"
