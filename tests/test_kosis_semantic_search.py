import csv

import numpy as np

from kosis_semantic_search import (
    SemanticTableIndex,
    build_claim_query,
    build_semantic_index,
    build_table_document,
    normalized_rrf_score,
)


class FakeEmbedder:
    def encode(self, texts, batch_size=16, show_progress_bar=False):
        vectors = []
        for text in texts:
            vector = np.array(
                [
                    1.0 if "수출" in text else 0.0,
                    1.0 if "항공" in text or "여객" in text else 0.0,
                    1.0 if "물가" in text else 0.0,
                ],
                dtype="float32",
            )
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm else vector)
        return np.asarray(vectors, dtype="float32")


class FailEmbedder:
    def encode(self, texts, batch_size=16, show_progress_bar=False):
        raise AssertionError("완료된 인덱스는 다시 임베딩하면 안 됩니다.")


def write_tables(path):
    rows = [
        {
            "ORG_ID": "1",
            "TBL_ID": "TRADE",
            "TBL_NM": "품목별 수출액",
            "STAT_ID": "S1",
            "path": "무역통계",
        },
        {
            "ORG_ID": "2",
            "TBL_ID": "AIR",
            "TBL_NM": "국제선 여객 실적",
            "STAT_ID": "S2",
            "path": "항공통계",
        },
        {
            "ORG_ID": "3",
            "TBL_ID": "PRICE",
            "TBL_NM": "소비자물가지수",
            "STAT_ID": "S3",
            "path": "물가통계",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_query_and_table_documents_keep_mapping_semantics():
    query = build_claim_query(
        {
            "indicator": "반도체 수출액",
            "industry_or_item": "반도체",
            "semantic_type": "amount",
            "unit": "달러",
            "period": "2024",
            "claim_text": "반도체 수출액은 100억 달러였다.",
        }
    )
    document = build_table_document(
        {
            "org_id": "1",
            "tbl_id": "T1",
            "tbl_name": "품목별 수출액",
            "category_path": "무역통계",
        }
    )
    assert "지표: 반도체 수출액" in query
    assert "단위: 달러" in query
    assert "대한민국 전체 품목별 수출입 공식통계" in query
    assert "기업혁신조사" in query
    assert "통계표: 품목별 수출액" in document
    assert "분류경로: 무역통계" in document


def test_rrf_rewards_overlap_between_lexical_and_semantic_results():
    overlap = normalized_rrf_score(1, 2)
    lexical_only = normalized_rrf_score(1, None)
    semantic_only = normalized_rrf_score(None, 1)
    assert overlap > lexical_only
    assert overlap > semantic_only
    assert 0 < overlap <= 1


def test_build_and_search_small_semantic_index(tmp_path):
    source = tmp_path / "tables.csv"
    index_dir = tmp_path / "index"
    write_tables(source)
    manifest = build_semantic_index(
        source,
        index_dir,
        embedding_model="fake",
        batch_size=2,
        embedder=FakeEmbedder(),
    )
    index = SemanticTableIndex(index_dir, embedder=FakeEmbedder())
    hits = index.search("지표: 국제선 여객 수 | 대상: 항공", top_k=2)

    assert manifest["table_count"] == 3
    assert manifest["dimension"] == 3
    assert hits[0].tbl_id == "AIR"
    assert hits[0].score > hits[1].score

    reused = build_semantic_index(
        source,
        index_dir,
        embedding_model="fake",
        batch_size=2,
        embedder=FailEmbedder(),
    )
    assert reused["source_sha256"] == manifest["source_sha256"]
