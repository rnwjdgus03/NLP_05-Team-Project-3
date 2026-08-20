from __future__ import annotations

import json

from evaluate_coordinate_topk import component_matches
from kosis_coordinate_merge import (
    merge_fallback_coordinate_packets,
    merge_jsonl_files,
    validate_suggestion_packet,
)
from kosis_coordinate_low_memory import BEAM_POOL_SCHEMA, claim_fingerprint
from run_kosis_top5_verification import (
    block_unconfirmed_mismatch,
    local_branch_actionable,
    mismatch_evidence_is_exact,
    verification_input,
)
from write_kosis_run_manifest import code_bundle_digest
from run_kosis_coordinate_stage_a import (
    apply_pre_rerank_metadata,
    metadata_table_score,
)
from run_kosis_coordinate_stage_c import (
    diverse_table_top_k,
    local_fallback_suggestion_packet,
    rerank_coordinate_record,
)
from run_kosis_mcp_coordinate_top2 import mcp_postgres_gate_decision


def exact_mismatch_row(**overrides):
    row = {
        "verdict": "불일치",
        "verdict_code": "VALUE_MISMATCH",
        "verdict_reason": "values differ",
        "coordinate_preflight_valid": True,
        "postgres_coordinate_status": "VALID",
        "period_alignment_state": "exact",
        "postgres_period_in_range": True,
        "unit_precheck_state": "compatible",
        "official_table_name": "품목별 수출액, 수입액",
        "official_item_name": "수출액",
        "repair_history": [],
        "verification_review_required": "N",
        "claim_indicator": "수출액",
        "measurement_indicator": "수출액",
        "indicator": "수출액",
    }
    row.update(overrides)
    return row


def test_exact_mismatch_is_allowed_only_with_matching_item_scope():
    row = exact_mismatch_row()
    assert mismatch_evidence_is_exact(row)
    assert block_unconfirmed_mismatch(row)["verdict_code"] == "VALUE_MISMATCH"


def test_opposite_item_blocks_value_mismatch():
    row = exact_mismatch_row(official_item_name="수입액")
    assert not mismatch_evidence_is_exact(row)
    blocked = block_unconfirmed_mismatch(row)
    assert blocked["verdict_code"] == "MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE"
    assert blocked["original_verdict_code"] == "VALUE_MISMATCH"


def test_unknown_period_range_blocks_value_mismatch():
    row = exact_mismatch_row(postgres_period_in_range=None)
    assert not mismatch_evidence_is_exact(row)


def test_local_actionable_controls_mcp_fallback():
    assert local_branch_actionable([{
        "candidate_sources": "local_reranker",
        "decision_status": "VERIFIED_MATCH",
    }])
    assert not local_branch_actionable([{
        "candidate_sources": "local_reranker",
        "decision_status": "UNRESOLVED",
    }])
    assert not local_branch_actionable([{
        "candidate_sources": "kosis_mcp",
        "decision_status": "VERIFIED_MATCH",
    }])
    assert local_branch_actionable([{
        "candidate_sources": "local_reranker_fallback",
        "decision_status": "VERIFIED_MATCH",
    }])


def test_mcp_uses_same_postgres_preflight_as_local():
    coordinate = {
        "org_id": "360",
        "tbl_id": "TBL",
        "item_id": "ITEM1",
        "axis_values": [
            {"axis_order": 1, "axis_id": "A", "value_id": "ALL"},
        ],
        "prd_se": "Y",
        "target_period": "2024",
        "previous_period": "",
        "aggregation": "",
    }
    packet = {
        "raw_suggestions": [{
            "source": "kosis_mcp",
            "source_rank": 1,
            "coordinate": coordinate,
            "evidence": {"mapping_type": "direct"},
        }],
    }
    candidate = {
        "coordinate": coordinate,
        "coordinate_id": "coord-1",
        "source_support": [{"source": "kosis_mcp", "source_ranks": [1]}],
    }
    catalog = {
        "table": {"tbl_name": "수출 통계"},
        "items": {"ITEM1": {"itm_name": "수출액", "unit": "달러"}},
        "axes": {"A": {
            "axis_id": "A", "axis_name": "품목", "axis_order": 1,
            "values": {"ALL": {"obj_name": "총액"}},
        }},
        "periodicities": {"Y"},
        "periodicity_rows": [{
            "prd_se": "Y", "range_text": "Y:2020~2025",
        }],
    }
    claim = {
        "claim_measurement_id": "C1",
        "claim_indicator": "수출액",
        "canonical_unit": "달러",
        "prd_se": "Y",
        "period": "2024",
    }
    row = verification_input(claim, packet, candidate, catalog)
    assert row["coordinate_preflight_source"] == "postgres_mcp"
    assert row["coordinate_preflight_valid"] is True
    assert row["postgres_coordinate_status"] == "VALID"


def test_full_coordinate_gold_match():
    coordinate = {
        "org_id": "360", "tbl_id": "TBL", "item_id": "ITEM1",
        "axis_values": [{"value_id": "TOTAL"}],
        "prd_se": "Y", "target_period": "2024",
    }
    gold = {
        "gold_org_id": "360", "gold_tbl_id": "TBL",
        "gold_itm_id": "ITEM1", "gold_obj_l1": "TOTAL",
        "gold_prd_se": "Y", "gold_period": "2024",
    }
    assert component_matches(coordinate, gold, "table")
    assert component_matches(coordinate, gold, "item")
    assert component_matches(coordinate, gold, "coordinate")
    assert component_matches(coordinate, gold, "full")


def test_mcp_only_packet_survives_partial_merge():
    coordinate = {
        "org_id": "360", "tbl_id": "TBL", "item_id": "ITEM1",
        "axis_values": [], "prd_se": "Y", "target_period": "2024",
        "previous_period": "", "aggregation": "",
    }
    packet = {
        "schema_version": "kosis-coordinate-suggestions-v1",
        "claim_measurement_id": "C1",
        "source": "kosis_mcp",
        "suggestions": [
            {
                "source": "kosis_mcp", "source_rank": rank,
                "coordinate": {**coordinate, "item_id": f"ITEM{rank}"},
                "score": None, "rationale": "", "evidence": {},
            }
            for rank in (1, 2)
        ],
    }
    merged = merge_fallback_coordinate_packets(None, packet)
    assert merged["available_sources"] == ["kosis_mcp"]
    assert merged["unique_api_candidate_count"] == 2
    assert merged["fallback_policy"] == "LOCAL_PRIMARY_MCP_ONLY_IF_LOCAL_UNRESOLVED"


def test_local_rank45_is_ordered_between_top3_and_mcp():
    coordinate = {
        "org_id": "360", "tbl_id": "TBL", "item_id": "ITEM1",
        "axis_values": [], "prd_se": "Y", "target_period": "2024",
        "previous_period": "", "aggregation": "",
    }

    def packet(source, ranks, prefix):
        return {
            "schema_version": "kosis-coordinate-suggestions-v1",
            "claim_measurement_id": "C1",
            "source": source,
            "suggestions": [
                {
                    "source": source, "source_rank": rank,
                    "coordinate": {**coordinate, "item_id": f"{prefix}{rank}"},
                    "score": None, "rationale": "", "evidence": {},
                }
                for rank in ranks
            ],
        }

    merged = merge_fallback_coordinate_packets(
        packet("local_reranker", (1, 2, 3), "L"),
        packet("kosis_mcp", (1, 2), "M"),
        packet("local_reranker_fallback", (1, 2), "F"),
    )
    assert [row["source"] for row in merged["raw_suggestions"]] == [
        "local_reranker", "local_reranker", "local_reranker",
        "local_reranker_fallback", "local_reranker_fallback",
        "kosis_mcp", "kosis_mcp",
    ]
    assert merged["fallback_policy"] == (
        "LOCAL_TOP3_PRIMARY_LOCAL_RANK45_THEN_MCP_IF_UNRESOLVED"
    )


def test_partial_merge_reports_union_count(tmp_path):
    coordinate = {
        "org_id": "360", "tbl_id": "TBL", "item_id": "ITEM1",
        "axis_values": [], "prd_se": "Y", "target_period": "2024",
        "previous_period": "", "aggregation": "",
    }

    def packet(claim_id, source, ranks):
        return {
            "schema_version": "kosis-coordinate-suggestions-v1",
            "claim_measurement_id": claim_id,
            "source": source,
            "suggestions": [
                {
                    "source": source, "source_rank": rank,
                    "coordinate": {**coordinate, "item_id": f"ITEM{rank}"},
                    "score": None, "rationale": "", "evidence": {},
                }
                for rank in ranks
            ],
        }

    local_path = tmp_path / "local.jsonl"
    mcp_path = tmp_path / "mcp.jsonl"
    output_path = tmp_path / "merged.jsonl"
    local_path.write_text(
        json.dumps(packet("C1", "local_reranker", (1, 2, 3)), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    mcp_path.write_text(
        "".join(
            json.dumps(packet(claim_id, "kosis_mcp", (1, 2)), ensure_ascii=False) + "\n"
            for claim_id in ("C1", "C2")
        ),
        encoding="utf-8",
    )
    count = merge_jsonl_files(local_path, mcp_path, output_path, allow_partial=True)
    assert count == 2
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 2


def test_code_bundle_digest_changes_with_source(tmp_path):
    source = tmp_path / "pipeline.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    first, records = code_bundle_digest(tmp_path)
    assert records[0]["path"] == "pipeline.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    second, _records = code_bundle_digest(tmp_path)
    assert first != second


def test_stage_a_period_filter_rejects_known_mismatch_before_rerank():
    candidates = [
        {"org_id": "1", "tbl_id": "Y", "table": {"tbl_name": "연간 수출", "category_path": "무역"}},
        {"org_id": "1", "tbl_id": "M", "table": {"tbl_name": "월간 수출", "category_path": "무역"}},
        {"org_id": "1", "tbl_id": "U", "table": {"tbl_name": "수출", "category_path": "무역"}},
    ]

    class Store:
        def table_rerank_metadata(self, _candidates):
            return [
                {"org_id": "1", "tbl_id": "Y", "periodicities": ["Y"], "metadata_complete": True},
                {"org_id": "1", "tbl_id": "M", "periodicities": ["M"], "metadata_complete": True},
                {"org_id": "1", "tbl_id": "U", "periodicities": [], "metadata_complete": False},
            ]

    kept, counts = apply_pre_rerank_metadata(
        candidates, {"prd_se": "M", "indicator": "수출", "metric_domain": "무역"},
        Store(), minimum_candidates=2,
    )
    assert [row["tbl_id"] for row in kept] == ["M", "U"]
    assert counts["period_mismatch_rejected"] == 1
    assert kept[0]["pre_rerank_period_state"] == "exact"
    assert kept[1]["pre_rerank_period_state"] == "unknown"


def test_metadata_score_uses_survey_and_classification():
    candidate = {
        "table": {
            "tbl_name": "산업별 현재인원",
            "category_path": "산업기술인력 수급 실태조사 > 조선업",
        }
    }
    score, signals = metadata_table_score(candidate, {
        "survey_name": "산업기술인력 수급 실태조사",
        "industry_or_item": "조선업",
        "indicator": "산업기술인력",
        "metric_domain": "고용",
    })
    assert score > 0.2
    assert any(signal.startswith("survey:") for signal in signals)
    assert "indicator_or_item" in signals


def test_coordinate_top3_preserves_distinct_tables():
    rows = [
        {"coordinate_id": "a1", "org_id": "1", "tbl_id": "A"},
        {"coordinate_id": "a2", "org_id": "1", "tbl_id": "A"},
        {"coordinate_id": "b1", "org_id": "1", "tbl_id": "B"},
        {"coordinate_id": "c1", "org_id": "1", "tbl_id": "C"},
    ]
    selected = diverse_table_top_k(rows, 3)
    assert [row["coordinate_id"] for row in selected] == ["a1", "b1", "c1"]


def test_obj_scope_bonus_promotes_aggregate_coordinate():
    claim = {"claim_measurement_id": "C1", "prd_se": "Y", "period": "2024"}

    def candidate(coordinate_id, obj_code, obj_name):
        return {
            "coordinate_id": coordinate_id,
            "org_id": "360", "tbl_id": "TBL",
            "dense_score": 0.5,
            "mandatory_aggregate": False,
            "target_match_state": "exact",
            "structural_match_state": "exact_or_unknown",
            "candidate_score": 0.5, "table_rank": 1,
            "rerank_document": obj_name,
            "selected_itm_id": "ITEM1", "selected_itm_name": "수출액",
            "selected_itm_unit": "달러", "coordinate_prd_se": "Y",
            "selected_obj_l1": obj_code,
            "selected_obj_l1_name": obj_name,
            "selected_obj_l1_axis_id": "A",
            "selected_obj_l1_axis_name": "품목별",
        }

    record = {
        "schema_version": BEAM_POOL_SCHEMA,
        "claim_measurement_id": "C1",
        "claim_fingerprint": claim_fingerprint(claim),
        "claim": claim,
        "coordinate_candidates": [
            candidate("detail", "D", "세부품목"),
            candidate("total", "A", "총액"),
        ],
    }

    class Reranker:
        def score(self, _query, _documents):
            return [0.9, 0.8]

    selected = rerank_coordinate_record(
        record, Reranker(), final_top_k=1, obj_scope_bonus=0.10,
    )
    assert selected[0]["coordinate_id"] == "total"
    assert selected[0]["obj_scope_exact"] is True
    assert selected[0]["obj_scope_bonus"] == 0.10


def test_local_rank45_packet_uses_separate_valid_source():
    claim = {"claim_measurement_id": "C1", "prd_se": "Y", "period": "2024"}
    rows = [
        {
            "org_id": "360", "tbl_id": "TBL", "selected_itm_id": f"I{rank}",
            "selected_itm_name": "수출액", "selected_itm_unit": "달러",
            "selected_obj_l1": "A", "selected_obj_l1_name": "총액",
            "selected_obj_l1_axis_id": "A", "selected_obj_l1_axis_name": "품목별",
            "coordinate_prd_se": "Y", "reranker_score": 0.8,
            "final_rank_score": 0.8, "base_final_rank_score": 0.7,
            "obj_scope_exact": True, "obj_scope_bonus": 0.1,
        }
        for rank in (4, 5)
    ]
    packet = local_fallback_suggestion_packet(
        "C1", claim, rows, metadata_snapshot_id="S1",
        table_pool_count=5, complete_table_count=5,
    )
    normalized = validate_suggestion_packet(packet)
    assert normalized["source"] == "local_reranker_fallback"
    assert [row["source_rank"] for row in normalized["suggestions"]] == [1, 2]
    assert [row["evidence"]["stage_c_absolute_rank"] for row in normalized["suggestions"]] == [4, 5]


def test_mcp_gate_requires_complete_period_range_and_unit():
    base = {
        "postgres_coordinate_valid": True,
        "period_alignment_state": "exact",
        "postgres_period_in_range": True,
        "unit_precheck_state": "compatible",
    }
    assert mcp_postgres_gate_decision(base, {"structural_compatible": True}) == (
        True, "accepted"
    )
    rejected = {**base, "postgres_period_in_range": None}
    assert mcp_postgres_gate_decision(
        rejected, {"structural_compatible": True}
    ) == (False, "period_range_unconfirmed")
