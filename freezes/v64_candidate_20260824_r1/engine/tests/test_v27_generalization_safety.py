from __future__ import annotations

from kosis_hybrid_top3 import exact_domain_scope_filter
from kosis_coordinate_merge import validate_suggestion_packet
from kosis_postgres_store import aggregate_component_recall_matches
from prepare_kosis_mapping_input import repair_extracted_contract
from run_kosis_coordinate_stage_c import locked_incumbent_top_k
from run_kosis_coordinate_stage_a import (
    explicit_table_name_recall,
    merge_explicit_table_recall,
    rerank_table_record,
    strong_structured_recall,
)
from run_kosis_top5_verification import (
    block_unconfirmed_mismatch,
    mismatch_measurement_semantics_are_exact,
    resolve_claim,
)


def test_explicit_official_table_name_is_recalled_without_gold_ids() -> None:
    tables = [
        {"org_id": "145", "tbl_id": "wrong", "tbl_name": "지역별 위생물수건 생산현황"},
        {"org_id": "145", "tbl_id": "right", "tbl_name": "지역별 헹굼보조제 생산현황"},
    ]
    hits = explicit_table_name_recall({
        "title": "2024년 위생용품산업현황 지역별 헹굼보조제 생산현황 생산액",
    }, tables)
    assert [(row["org_id"], row["tbl_id"]) for row in hits] == [("145", "right")]
    merged = merge_explicit_table_recall([], hits, {
        (row["org_id"], row["tbl_id"]): row for row in tables
    })
    assert merged[0]["explicit_table_name_match"] is True


def test_sibling_table_cannot_emit_value_mismatch() -> None:
    blocked = block_unconfirmed_mismatch({
        "verdict_code": "VALUE_MISMATCH",
        "coordinate_preflight_valid": True,
        "postgres_coordinate_status": "VALID",
        "period_alignment_state": "exact",
        "postgres_period_in_range": True,
        "unit_precheck_state": "compatible",
        "official_table_name": "지역별 위생물수건 생산현황",
        "official_item_name": "생산액",
        "title": "지역별 헹굼보조제 생산현황 생산액",
        "claim_indicator": "생산액",
        "repair_history": [],
        "verification_review_required": "N",
    })
    assert blocked["verdict_code"] == "MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE"


def test_explicit_table_reservation_never_exceeds_requested_top_k() -> None:
    class Reranker:
        def score(self, _query, documents):
            return [float(index) for index, _ in enumerate(documents)]

    candidates = []
    for index in range(12):
        candidates.append({
            "org_id": "1", "tbl_id": f"T{index}",
            "table": {"org_id": "1", "tbl_id": f"T{index}", "tbl_name": f"표{index}"},
            "rrf_score": 1.0 / (61 + index),
            "semantic_baseline": True,
            "item_recall_rank": index + 1,
            "item_recall_term_count": 2,
            "component_recall_sources": ["ITEM"],
        })
    candidates[0]["explicit_table_name_match"] = True
    candidates[0]["explicit_table_name_rank"] = 1
    record = {
        "schema_version": "kosis-low-memory-table-retrieval-v1",
        "claim_measurement_id": "C1", "claim_fingerprint": "x",
        "claim": {}, "reranker_query": "", "candidates": candidates,
        "item_recall_policy": "balanced",
    }
    result = rerank_table_record(record, Reranker(), table_pool_top_k=10)
    assert len(result["table_candidates"]) == 10


def test_explicit_yoy_text_repairs_stale_month_over_month_contract() -> None:
    repaired, statuses = repair_extracted_contract({
        "date": "2026-07-02",
        "claim_text": "6월 소비자물가지수 전년동월비는 3.2% 증가했다.",
        "indicator": "소비자물가지수 전년동월비",
        "period": "202606",
        "prd_se": "M",
        "change_base": "전월",
        "unit": "%",
        "value_type": "증감률",
    })
    assert repaired["change_base"] == "전년동월"
    assert "CHANGE_BASE_FROM_EXPLICIT_TEXT" in statuses


def test_employment_domain_keeps_economically_active_population_table() -> None:
    rows = [
        {"table": {"tbl_name": "연령별 경제활동인구 총괄", "category_path": "경제활동인구조사"}},
        {"table": {"tbl_name": "고용보조지표", "category_path": "경제활동인구조사"}},
        {"table": {"tbl_name": "주택가격", "category_path": "주택가격동향조사"}},
    ]
    selected = exact_domain_scope_filter(rows, {"metric_domain": "고용"}, minimum_candidates=2)
    assert [row["table"]["tbl_name"] for row in selected] == [
        "연령별 경제활동인구 총괄", "고용보조지표",
    ]


def test_stage_c_really_locks_stage_b_global_top3() -> None:
    # Input order represents Stage-C reranker order and deliberately disagrees
    # with the immutable Stage-B rank.
    rows = [
        {"coordinate_id": "rerank-first", "org_id": "1", "tbl_id": "A", "global_candidate_rank": 8},
        {"coordinate_id": "stage-b-third", "org_id": "1", "tbl_id": "C", "global_candidate_rank": 3},
        {"coordinate_id": "stage-b-first", "org_id": "1", "tbl_id": "B", "global_candidate_rank": 1},
        {"coordinate_id": "stage-b-second", "org_id": "1", "tbl_id": "D", "global_candidate_rank": 2},
        {"coordinate_id": "tail", "org_id": "1", "tbl_id": "E", "global_candidate_rank": 7},
    ]
    selected = locked_incumbent_top_k(rows, 5)
    assert [row["coordinate_id"] for row in selected[:3]] == [
        "stage-b-first", "stage-b-second", "stage-b-third",
    ]


def test_level_item_cannot_auto_mismatch_rate_change_claim() -> None:
    assert not mismatch_measurement_semantics_are_exact({
        "claim_indicator": "소비자물가지수 전월비",
        "semantic_type": "rate_change",
        "change_base": "전월",
        "mapping_type": "rate_from_level",
        "official_item_name": "소비자물가지수(총지수)",
    })
    assert mismatch_measurement_semantics_are_exact({
        "claim_indicator": "소비자물가지수 전월비",
        "semantic_type": "rate_change",
        "change_base": "전월",
        "mapping_type": "direct",
        "official_item_name": "전월비",
    })


def _decision_row(status: str, verdict: str, coordinate: str, score: int) -> dict:
    return {
        "decision_status": status,
        "verdict_code": verdict,
        "coordinate_id": coordinate,
        "coordinate_preflight_valid": True,
        "period_alignment_state": "exact",
        "postgres_period_in_range": True,
        "unit_precheck_state": "compatible",
        "verification_review_required": "N",
        "candidate_sources": "local_reranker",
        "candidate_source_ranks": '{"local_reranker": 1}',
        "normalized_semantic_rank_score": score,
        "candidate_rank": score,
    }


def test_verified_match_dominates_higher_ranked_negative_candidate() -> None:
    mismatch = _decision_row(
        "MISMATCH_EVIDENCE_REVIEW_REQUIRED", "VALUE_MISMATCH", "wrong", 1,
    )
    match = _decision_row("VERIFIED_MATCH", "MATCH", "correct", 5)
    decision = resolve_claim([mismatch, match])
    assert decision["claim_decision"] == "VERIFIED_MATCH"
    assert decision["selected_coordinate_id"] == "correct"
    assert decision["conflicting_negative_candidate_count"] == 1


def test_coordinate_packet_accepts_safe_rank_prefix_and_empty_abstention() -> None:
    empty = validate_suggestion_packet({
        "schema_version": "kosis-coordinate-suggestions-v1",
        "claim_measurement_id": "C-empty",
        "source": "local_reranker",
        "suggestions": [],
    })
    assert empty["suggestions"] == []

    one = validate_suggestion_packet({
        "schema_version": "kosis-coordinate-suggestions-v1",
        "claim_measurement_id": "C-one",
        "source": "local_reranker",
        "suggestions": [{
            "source": "local_reranker",
            "source_rank": 1,
            "coordinate": {
                "org_id": "101", "tbl_id": "T", "item_id": "I",
                "axis_values": [], "prd_se": "M", "target_period": "202601",
                "previous_period": "", "aggregation": "",
            },
            "score": 1.0, "rationale": "", "evidence": {},
        }],
    })
    assert len(one["suggestions"]) == 1


def test_component_recall_accumulates_item_and_obj_evidence_per_table() -> None:
    rows = [
        {
            "input_order": 1, "org_id": "101", "tbl_id": "official",
            "term_rank": 10, "match_quality": 3,
            "matched_item_names": ["실업률"], "matched_component_sources": ["ITEM"],
        },
        {
            "input_order": 2, "org_id": "101", "tbl_id": "official",
            "term_rank": 8, "match_quality": 3,
            "matched_item_names": ["15~29세"], "matched_component_sources": ["OBJ"],
        },
        {
            "input_order": 1, "org_id": "101", "tbl_id": "single",
            "term_rank": 1, "match_quality": 3,
            "matched_item_names": ["실업률"], "matched_component_sources": ["ITEM"],
        },
    ]
    ranked = aggregate_component_recall_matches(rows, limit=10)
    assert ranked[0]["tbl_id"] == "official"
    assert ranked[0]["matched_term_count"] == 2
    assert ranked[0]["matched_component_sources"] == ["ITEM", "OBJ"]


def test_reserved_component_slots_reject_weak_single_axis_literal() -> None:
    assert not strong_structured_recall({
        "item_recall_term_count": 1,
        "component_recall_sources": ["OBJ"],
    })
    assert strong_structured_recall({
        "item_recall_term_count": 2,
        "component_recall_sources": ["OBJ"],
    })
    assert strong_structured_recall({
        "item_recall_term_count": 1,
        "component_recall_sources": ["ITEM", "OBJ"],
    })
