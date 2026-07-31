import pytest

from kosis_chroma_hybrid_search import (
    InMemoryCoordinateSearcher,
    build_output_row,
    fuse_candidates,
    lexical_search,
    load_table_candidates,
    search_measurement,
)
from kosis_meta_coordinates import (
    build_chroma_where,
    build_coordinate_query,
    passes_hard_filter,
    prd_se_compatible,
    unit_dimension_compatible,
)


META = [
    {"org_id": "101", "tbl_id": "T_IDX", "tbl_name": "전산업생산지수",
     "axis_id": "ITEM", "code_id": "I1", "code_name": "계절조정지수",
     "is_item": "Y", "unit_name": "2020=100"},
    {"org_id": "101", "tbl_id": "T_IDX", "axis_id": "B", "axis_name": "산업별",
     "axis_order": "1", "code_id": "1", "code_name": "전산업생산지수", "is_item": "N"},
    {"org_id": "101", "tbl_id": "T_IDX", "axis_id": "B", "axis_name": "산업별",
     "axis_order": "1", "code_id": "2", "code_name": "광공업", "is_item": "N"},
    {"org_id": "999", "tbl_id": "T_OTHER", "tbl_name": "소비자물가",
     "axis_id": "ITEM", "code_id": "I9", "code_name": "지수", "is_item": "Y",
     "unit_name": "2020=100"},
]

CLAIM = {
    "claim_measurement_id": "M1",
    "claim_text": "9월 전산업생산지수는 전월 대비 0.4% 감소했다",
    "measurement_indicator": "산업생산지수",
    "value_type": "증감률",
    "unit": "%",
    "unit_dimension": "rate",
    "measurement_period": "202409",
    "measurement_prd_se": "M",
    "mapping_type": "rate_from_level",
}

TABLES = [{"rank": 1, "org_id": "101", "tbl_id": "T_IDX", "tbl_name": "전산업생산지수",
           "candidate_status": "REVIEW", "candidate_score": "600",
           "candidate_runner_up_score": "500"}]


def test_query_includes_structured_fields_not_only_claim_text():
    query = build_coordinate_query(CLAIM)
    assert "주장:" in query and "지표: 산업생산지수" in query
    assert "주기: M" in query and "값유형: 증감률" in query


def test_query_skips_empty_fields():
    query = build_coordinate_query({"claim_text": "값", "region": "", "gender": "-"})
    assert "지역" not in query and "성별" not in query


def test_chroma_where_restricts_tbl_id_first():
    where = build_chroma_where(CLAIM, ["T_IDX", "T_B"])
    payload = where["$and"] if "$and" in where else [where]
    assert {"tbl_id": {"$in": ["T_IDX", "T_B"]}} in payload


def test_prd_se_filter_allows_missing_coordinate_period():
    assert prd_se_compatible("M", "M")
    assert prd_se_compatible("M", "")      # 좌표 주기 미상은 배제하지 않음
    assert not prd_se_compatible("M", "Y")


def test_unit_dimension_filter_and_rate_exception():
    assert unit_dimension_compatible("currency", "currency")
    assert not unit_dimension_compatible("currency", "person_count")
    # 증감률은 수준값에서 계산하므로 단위 차원이 달라도 허용
    assert unit_dimension_compatible("rate", "currency", "rate_from_level")


def test_hard_filter_excludes_other_tables():
    searcher = InMemoryCoordinateSearcher(META)
    pool = searcher.pool_for_tables(["T_IDX"])
    assert pool and all(e["metadata"]["tbl_id"] == "T_IDX" for e in pool)
    other = [e for e in searcher.entries if e["metadata"]["tbl_id"] == "T_OTHER"][0]
    assert not passes_hard_filter(CLAIM, other["metadata"], ["T_IDX"])


def test_lexical_pool_limit_is_applied_per_table():
    searcher = InMemoryCoordinateSearcher(META)
    pool = searcher.pool_for_tables(["T_IDX", "T_OTHER"], limit=1)
    assert [entry["metadata"]["tbl_id"] for entry in pool] == ["T_IDX", "T_OTHER"]


def test_dense_result_shape_from_stub_searcher():
    class StubSearcher(InMemoryCoordinateSearcher):
        def search(self, query, where, top_k):
            return [{**self.entries[0], "dense_score": 0.9}][:top_k]

    searcher = StubSearcher(META)
    candidates, stats = search_measurement(
        CLAIM, TABLES, searcher, dense_top_k=5, lexical_top_k=5,
        rerank_top_k=5, final_top_k=5)
    assert stats["dense_count"] == 1
    assert all({"coordinate_id", "document", "metadata"} <= set(c) for c in candidates)


def test_dense_and_lexical_duplicates_are_merged_by_coordinate_id():
    shared = {"coordinate_id": "C1", "document": "문서", "metadata": {},
              "dense_score": 0.8, "lexical_score": None}
    lexical_copy = {**shared, "dense_score": None, "lexical_score": 0.5}
    fused = fuse_candidates([shared], [lexical_copy])
    assert len(fused) == 1
    assert fused[0]["dense_rank"] == 1 and fused[0]["lexical_rank"] == 1
    assert fused[0]["fusion_score"] > 0


def test_lexical_search_scores_and_truncates():
    searcher = InMemoryCoordinateSearcher(META)
    pool = searcher.pool_for_tables(["T_IDX"])
    hits = lexical_search("항목: 계절조정지수 산업별: 광공업", pool, top_k=1)
    assert len(hits) == 1 and hits[0]["lexical_score"] > 0


def test_output_row_matches_validate_input_schema():
    searcher = InMemoryCoordinateSearcher(META)
    candidates, _ = search_measurement(
        CLAIM, TABLES, searcher, dense_top_k=5, lexical_top_k=5,
        rerank_top_k=5, final_top_k=1)
    row = build_output_row(CLAIM, TABLES[0], candidates[0], 1)
    for field in ("org_id", "tbl_id", "candidate_rank", "candidate_status",
                  "selected_itm_id", "selected_obj_l1", "selected_obj_l1_axis_id",
                  "mapping_type", "unit", "period", "claim_measurement_id"):
        assert field in row
    assert row["candidate_rank"] == 1
    assert row["selected_obj_l1_axis_id"] == "B"
    assert row["period"] == "202409"
    assert row["prd_se"] == "M"


def test_reranker_reorders_and_records_score():
    class Reranker:
        def score(self, query, documents):
            return list(reversed([0.1 * (i + 1) for i in range(len(documents))]))

    searcher = InMemoryCoordinateSearcher(META)
    candidates, _ = search_measurement(
        CLAIM, TABLES, searcher, dense_top_k=5, lexical_top_k=5,
        rerank_top_k=5, final_top_k=5, reranker=Reranker())
    assert all("reranker_score" in c for c in candidates)
    scores = [c["final_rank_score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_missing_reranker_dependency_raises_clear_error():
    from kosis_semantic_search import TransformerReranker
    try:
        import transformers  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="requirements-ml"):
            TransformerReranker("BAAI/bge-reranker-v2-m3")
    else:
        pytest.skip("transformers 설치 환경에서는 fallback 경로를 검증하지 않는다")


def test_load_table_candidates_orders_and_truncates(tmp_path):
    path = tmp_path / "cand.csv"
    path.write_text(
        "claim_measurement_id,candidate_rank,org_id,tbl_id,tbl_name,candidate_status\n"
        "M1,2,101,B,두번째,ALTERNATE\n"
        "M1,1,101,A,첫번째,READY\n"
        "M1,3,101,C,세번째,ALTERNATE\n",
        encoding="utf-8-sig")
    tables = load_table_candidates(str(path), top_k=2)
    assert [t["tbl_id"] for t in tables["M1"]] == ["A", "B"]
