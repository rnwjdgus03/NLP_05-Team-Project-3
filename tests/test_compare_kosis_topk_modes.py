from compare_kosis_topk_modes import compare


def row(k, hits, ready=0):
    return {
        "top_k": str(k),
        "retrieval_hits": str(hits),
        "retrieval_gold": "24",
        "retrieval_recall": str(hits / 24),
        "ready_rows": str(ready),
    }


def test_compare_selects_best_mode_and_smallest_knee():
    combined, decision = compare(
        [row(1, 13), row(2, 15), row(5, 15)],
        [row(1, 12), row(2, 14), row(5, 14)],
    )

    assert len(combined) == 6
    assert decision["winner_mode"] == "lexical"
    assert decision["winner_top_k"] == 2
    assert decision["winner_hits"] == 15
    assert decision["deployment_ready"] is False


def test_compare_prefers_lexical_when_retrieval_results_tie():
    _, decision = compare([row(2, 14)], [row(2, 14)])
    assert decision["winner_mode"] == "lexical"
