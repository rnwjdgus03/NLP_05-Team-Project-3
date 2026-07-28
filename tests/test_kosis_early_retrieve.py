from types import SimpleNamespace

from kosis_early_retrieve import candidate_rows, context_payload, rerank_hits
from kosis_semantic_search import SemanticHit, build_early_claim_query


class FakeRuntime:
    def __init__(self):
        self.index = SimpleNamespace(
            tables=[
                {
                    "org_id": "1",
                    "tbl_id": "T1",
                    "tbl_name": "Export table",
                    "stat_id": "S1",
                    "category_path": "Trade",
                },
                {
                    "org_id": "2",
                    "tbl_id": "T2",
                    "tbl_name": "Passenger table",
                    "stat_id": "S2",
                    "category_path": "Transport",
                },
            ]
        )

    def rerank(self, query, table_rows):
        assert "claim:" in query
        return [0.1, 0.9]


def test_early_query_uses_article_context_but_not_publication_date():
    query = build_early_claim_query(
        {
            "claim_text": "LCC passengers increased.",
            "title": "International aviation",
            "prev_sentence": "The previous sentence.",
            "next_sentence": "The next sentence.",
            "date": "2025-01-01",
        }
    )

    assert "claim: LCC passengers increased." in query
    assert "title: International aviation" in query
    assert "previous_context: The previous sentence." in query
    assert "next_context: The next sentence." in query
    assert "2025-01-01" not in query


def test_reranker_reorders_dense_hits_and_context_is_compact_json():
    runtime = FakeRuntime()
    hits = [
        SemanticHit(org_id="1", tbl_id="T1", score=0.95, rank=1),
        SemanticHit(org_id="2", tbl_id="T2", score=0.85, rank=2),
    ]

    entries = rerank_hits(runtime, "claim: passengers", hits, rerank_top_k=2)
    rows = candidate_rows(
        "C1",
        entries,
        {("2", "T2"): ["International passengers [person]"]},
    )
    payload = context_payload(rows, context_top_k=1)

    assert rows[0]["tbl_id"] == "T2"
    assert rows[0]["candidate_rank"] == 1
    assert rows[0]["dense_rank"] == 2
    assert '"tbl_id":"T2"' in payload
    assert "International passengers [person]" in payload
