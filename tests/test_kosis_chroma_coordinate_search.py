from kosis_chroma_coordinate_search import (
    build_coordinate_documents,
    build_coordinate_query,
    coordinate_hits_to_candidates,
    fuse_coordinate_hits,
    lexical_coordinate_search,
)


def meta_rows():
    return [
        {
            "org_id": "101",
            "tbl_id": "DT_TRADE",
            "tbl_name": "품목별 수출액",
            "category_path": "무역 > 품목",
            "OBJ_ID": "ITEM",
            "ITM_ID": "EXP",
            "ITM_NM": "수출액",
            "unit_dimension": "currency",
            "prd_se": "M",
        },
        {
            "org_id": "101",
            "tbl_id": "DT_TRADE",
            "tbl_name": "품목별 수출액",
            "category_path": "무역 > 품목",
            "OBJ_ID": "C1",
            "OBJ_NM": "품목",
            "OBJ_ID_SN": "1",
            "ITM_ID": "SEMICON",
            "ITM_NM": "반도체",
            "unit_dimension": "currency",
            "prd_se": "M",
        },
    ]


def test_coordinate_document_is_stable_and_path_level():
    docs = build_coordinate_documents(meta_rows())
    again = build_coordinate_documents(meta_rows())

    assert len(docs) == 1
    assert docs[0]["coordinate_id"] == again[0]["coordinate_id"]
    assert docs[0]["metadata"]["itm_id"] == "EXP"
    assert docs[0]["metadata"]["obj_l1"] == "SEMICON"
    assert docs[0]["metadata"]["axis_path"] == "품목"
    assert docs[0]["metadata"]["obj_path"] == "반도체"
    assert "품목별 수출액" in docs[0]["metadata"]["coordinate_label"]
    assert "측정항목명: 수출액" in docs[0]["document"]
    assert "행열좌표1: 품목=반도체" in docs[0]["document"]


def test_query_uses_structured_measurement_fields():
    query = build_coordinate_query(
        {
            "claim_text": "반도체 수출이 늘었다.",
            "measurement_indicator": "수출액",
            "measurement_item": "반도체",
            "unit_dimension": "currency",
            "measurement_prd_se": "M",
        }
    )

    assert "문장: 반도체 수출이 늘었다." in query
    assert "지표: 수출액" in query
    assert "항목: 반도체" in query
    assert "단위차원: currency" in query
    assert "주기: M" in query


def test_lexical_search_applies_hard_filters_and_candidates_convert():
    docs = build_coordinate_documents(meta_rows())
    claim = {"measurement_item": "반도체", "unit_dimension": "currency", "measurement_prd_se": "M"}
    hits = lexical_coordinate_search(docs, "항목: 반도체 | 지표: 수출액", top_k=5, tbl_ids={"DT_TRADE"}, claim=claim)
    fused = fuse_coordinate_hits([], hits)
    items, objs = coordinate_hits_to_candidates(fused)

    assert hits
    assert items[0]["code"] == "EXP"
    assert objs[1][0]["code"] == "SEMICON"

    blocked = lexical_coordinate_search(docs, "반도체", tbl_ids={"OTHER"}, claim=claim)
    assert blocked == []
