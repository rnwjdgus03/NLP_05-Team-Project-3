from __future__ import annotations

from prepare_kosis_mapping_input import align_change_period, normalize_row
from kosis_component_search import apply_candidate_scores, select_diverse_candidates


def test_first_endpoint_keeps_measurement_specific_period() -> None:
    row = {
        "claim_text": "외국인 비율은 2022년 1.5%에서 2023년 4.4%로 증가했다.",
        "value": "1.5",
        "unit": "%",
        "measurement_period": "2022",
        "measurement_prd_se": "Y",
        "claim_period": "2023",
        "claim_prd_se": "Y",
        "measurement_role": "증감률",
        "change_base": "전년",
    }
    assert align_change_period(row) == (
        "2022", "MEASUREMENT_ENDPOINT_PERIOD_PRESERVED",
    )


def test_true_change_measurement_still_aligns_to_target_period() -> None:
    row = {
        "claim_text": "2023년에는 전년보다 13% 증가했다.",
        "value": "13",
        "unit": "%",
        "measurement_period": "2022",
        "measurement_prd_se": "Y",
        "claim_period": "2023",
        "claim_prd_se": "Y",
        "measurement_role": "증감률",
        "change_base": "전년",
    }
    assert align_change_period(row) == ("2023", "COMPARISON_PERIOD_TO_TARGET")


def test_endpoint_is_normalized_as_direct_level_without_comparison_period() -> None:
    row = {
        "claim_measurement_id": "C1-m1",
        "claim_text": "외국인 비율은 2022년 1.5%에서 2023년 4.4%로 증가했다.",
        "measurement_text": "1.5%",
        "value": "1.5",
        "unit": "%",
        "raw_unit": "%",
        "value_type": "증감률",
        "measurement_indicator": "외국인 비율",
        "indicator": "외국인 비율",
        "measurement_period": "2022",
        "measurement_prd_se": "Y",
        "claim_period": "2023",
        "claim_prd_se": "Y",
        "measurement_role": "증감률",
        "change_base": "전년",
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "measurement_binding_source": "hcx",
    }
    normalized = normalize_row(row)
    assert normalized["period"] == "2022"
    assert normalized["semantic_type"] == "rate_level"
    assert normalized["comparison_period"] == ""
    assert normalized["derived_computation_required"] == "N"
    assert normalized["mapping_gate"] == "READY"


def test_ordinary_share_claim_remains_blocked() -> None:
    row = {
        "claim_measurement_id": "C2-m1",
        "claim_text": "전체 취업자 가운데 청년 비율은 18.2%였다.",
        "measurement_text": "18.2%",
        "value": "18.2",
        "unit": "%",
        "raw_unit": "%",
        "value_type": "수준값",
        "measurement_indicator": "청년 비율",
        "indicator": "청년 비율",
        "measurement_period": "2023",
        "measurement_prd_se": "Y",
        "claim_period": "2023",
        "claim_prd_se": "Y",
        "measurement_role": "현재값",
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "measurement_binding_source": "hcx",
    }
    normalized = normalize_row(row)
    assert normalized["mapping_gate"] == "REJECT"
    assert normalized["mapping_exclusion_code"] == "SHARE_CLAIM_UNSUPPORTED"


def test_published_change_rate_endpoint_keeps_change_semantic() -> None:
    row = {
        "claim_measurement_id": "C3-m1",
        "claim_text": "수출 증가율은 2024년 8.2%에서 2025년 1.5%로 낮아졌다.",
        "measurement_text": "8.2%",
        "value": "8.2",
        "unit": "%",
        "raw_unit": "%",
        "value_type": "증감률",
        "measurement_indicator": "수출 증가율",
        "indicator": "수출 증가율",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
        "claim_period": "2025",
        "claim_prd_se": "Y",
        "measurement_role": "증감률",
        "change_base": "전년",
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "measurement_binding_source": "hcx",
    }
    normalized = normalize_row(row)
    assert normalized["period"] == "2024"
    assert normalized["semantic_type"] == "rate_change"
    assert normalized["mapping_gate"] == "READY"


def test_stage_b_review_slot_is_penalized_and_table_is_preserved() -> None:
    primary = {
        "coordinate_id": "1|A|I|1:X",
        "item": {"org_id": "1", "tbl_id": "A"},
        "table": {"org_id": "1", "tbl_id": "A", "rank": 1},
        "component_score": 0.5,
        "target_match_state": "exact",
        "structural_match_state": "exact_or_unknown",
    }
    review = {
        "coordinate_id": "2|B|I|1:Y",
        "item": {"org_id": "2", "tbl_id": "B"},
        "table": {"org_id": "2", "tbl_id": "B", "rank": 2},
        "component_score": 0.9,
        "target_match_state": "semantic_fallback",
        "structural_match_state": "exact_or_unknown",
        "verification_review_required": True,
        "verification_review_reason": "per_table_coordinate_slot",
        "table_slot_fallback": True,
    }
    apply_candidate_scores(primary)
    apply_candidate_scores(review)
    selected = select_diverse_candidates(
        [primary, review], 2, per_table_minimum=1,
    )
    assert {row["item"]["tbl_id"] for row in selected} == {"A", "B"}
    assert review["fallback_penalty"] > primary["fallback_penalty"]
    assert review["verification_review_required"] is True
