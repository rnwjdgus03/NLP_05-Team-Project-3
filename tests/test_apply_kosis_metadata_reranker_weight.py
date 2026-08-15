from __future__ import annotations

from apply_kosis_metadata_reranker_weight import apply_weight


ROWS = [
    {
        "gold_id": "G1", "tbl_id": "UPSTREAM", "candidate_rank": "1",
        "upstream_candidate_rank": "1", "metadata_reranker_normalized": "0.0",
    },
    {
        "gold_id": "G1", "tbl_id": "METADATA", "candidate_rank": "2",
        "upstream_candidate_rank": "2", "metadata_reranker_normalized": "1.0",
    },
]


def test_zero_weight_reproduces_upstream_order() -> None:
    reranked = apply_weight(ROWS, 0.0)
    assert [row["tbl_id"] for row in reranked] == ["UPSTREAM", "METADATA"]


def test_full_weight_uses_cached_metadata_score() -> None:
    reranked = apply_weight(ROWS, 1.0)
    assert [row["tbl_id"] for row in reranked] == ["METADATA", "UPSTREAM"]
    assert reranked[0]["candidate_rank"] == 1
