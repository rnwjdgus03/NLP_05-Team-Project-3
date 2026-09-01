from apply_stage_a_fixed_blend import POLICY, WEIGHTS, blend_candidates, transform_packet


def candidate(table, base, rrf, structural, item_rank=0, sources=None):
    return {
        "org_id": "1",
        "tbl_id": table,
        "metadata_rerank_score": base,
        "rrf_score": rrf,
        "v16_structural_score": structural,
        "item_recall_rank": item_rank,
        "component_recall_sources": sources or [],
    }


def test_item_evidence_can_promote_candidate():
    rows = [
        candidate("semantic", 1.0, 1.0, 1.0),
        candidate("item", 1.0, 1.0, 1.0, item_rank=1, sources=["ITEM"]),
    ]
    ranked = blend_candidates(rows, top_k=2)
    assert ranked[0]["tbl_id"] == "item"
    assert ranked[0]["rank"] == 1


def test_schema_is_preserved_and_policy_recorded():
    packet = {"schema_version": "kosis-low-memory-table-pool-v1", "table_candidates": []}
    result = transform_packet(packet)
    assert result["schema_version"] == packet["schema_version"]
    assert result["v36_rank_blend_policy"] == POLICY
    assert result["v36_rank_blend_weights"] == WEIGHTS
    assert result["table_candidates"] == []


def test_top_k_and_tie_order_are_deterministic():
    rows = [candidate(str(i), 1.0, 1.0, 1.0) for i in range(20)]
    ranked = blend_candidates(rows, top_k=12)
    assert len(ranked) == 12
    assert [row["tbl_id"] for row in ranked] == [str(i) for i in range(12)]
