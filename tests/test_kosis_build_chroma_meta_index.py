import pytest

from kosis_build_chroma_meta_index import build_documents
from kosis_meta_coordinates import (
    SCHEMA_VERSION,
    build_coordinates,
    coordinate_document,
    coordinate_id,
    coordinate_metadata,
    group_meta_rows,
)


META_FIXTURE = [
    {"org_id": "101", "tbl_id": "DT_A", "tbl_name": "전산업생산지수(계절조정지수)",
     "category_path": "생산·산업", "axis_id": "ITEM", "axis_name": "항목",
     "code_id": "T1", "code_name": "계절조정지수", "is_item": "Y", "unit_name": "2020=100"},
    {"org_id": "101", "tbl_id": "DT_A", "axis_id": "B", "axis_name": "산업별",
     "axis_order": "1", "code_id": "1", "code_name": "전산업생산지수", "is_item": "N"},
    {"org_id": "101", "tbl_id": "DT_A", "axis_id": "B", "axis_name": "산업별",
     "axis_order": "1", "code_id": "2", "code_name": "광공업", "is_item": "N"},
    {"org_id": "360", "tbl_id": "DT_B", "tbl_name": "품목별 수출액",
     "axis_id": "ITEM", "code_id": "T1", "code_name": "수출액", "is_item": "Y",
     "unit_name": "천달러"},
    {"org_id": "360", "tbl_id": "DT_B", "axis_id": "A", "axis_name": "품목별",
     "axis_order": "1", "code_id": "A.A", "code_name": "총액", "is_item": "N"},
]


def test_group_meta_rows_splits_items_and_axes():
    tables = group_meta_rows(META_FIXTURE)
    table = tables[("101", "DT_A")]
    assert [item["code"] for item in table["items"]] == ["T1"]
    assert sorted(table["axes"]) == [1]
    assert len(table["axes"][1]["values"]) == 2


def test_axis_without_order_is_skipped():
    rows = META_FIXTURE + [
        {"org_id": "101", "tbl_id": "DT_A", "axis_id": "C", "code_id": "X",
         "code_name": "미상축", "is_item": "N"},
    ]
    table = group_meta_rows(rows)[("101", "DT_A")]
    assert sorted(table["axes"]) == [1]   # order 없는 축은 objL<n> 로 못 바꾸므로 제외


def test_build_coordinates_creates_item_times_axis_documents():
    coordinates = build_coordinates(META_FIXTURE)
    keys = {(c["tbl_id"], c["itm_id"], c["obj_codes"].get(1)) for c in coordinates}
    assert ("DT_A", "T1", "1") in keys
    assert ("DT_A", "T1", "2") in keys
    assert ("DT_B", "T1", "A.A") in keys


def test_coordinate_id_is_deterministic_across_runs():
    first = build_coordinates(META_FIXTURE)
    second = build_coordinates(META_FIXTURE)
    assert [c["coordinate_id"] for c in first] == [c["coordinate_id"] for c in second]


def test_coordinate_id_ignores_dict_order():
    a = coordinate_id("101", "DT_A", "T1", {1: "1", 2: "9"})
    b = coordinate_id("101", "DT_A", "T1", {2: "9", 1: "1"})
    assert a == b


def test_coordinate_id_changes_with_obj_code():
    a = coordinate_id("101", "DT_A", "T1", {1: "1"})
    b = coordinate_id("101", "DT_A", "T1", {1: "2"})
    assert a != b


def test_document_contains_axis_and_unit_labels():
    coordinate = next(c for c in build_coordinates(META_FIXTURE)
                      if c["obj_codes"].get(1) == "1")
    document = coordinate_document(coordinate)
    assert "통계표: 전산업생산지수(계절조정지수)" in document
    assert "항목: 계절조정지수" in document
    assert "산업별: 전산업생산지수" in document
    assert "단위: 2020=100" in document


def test_metadata_is_scalar_only_for_chroma():
    coordinate = build_coordinates(META_FIXTURE)[0]
    metadata = coordinate_metadata(coordinate)
    assert metadata["schema_version"] == SCHEMA_VERSION
    assert all(isinstance(value, (str, int, float, bool))
               for value in metadata.values())
    assert metadata["obj_l1"] and metadata["obj_l8"] == ""


def test_build_documents_deduplicates_ids():
    ids, documents, metadatas = build_documents(
        META_FIXTURE + META_FIXTURE, axis_value_limit=40, max_coordinates_per_table=100)
    assert len(ids) == len(set(ids))
    assert len(ids) == len(documents) == len(metadatas)


def test_axis_value_limit_keeps_aggregate_first():
    rows = [
        {"org_id": "1", "tbl_id": "T", "axis_id": "ITEM", "code_id": "I", "code_name": "값",
         "is_item": "Y", "unit_name": "명"},
        {"org_id": "1", "tbl_id": "T", "axis_id": "A", "axis_order": "1",
         "code_id": "z", "code_name": "지역Z", "is_item": "N"},
        {"org_id": "1", "tbl_id": "T", "axis_id": "A", "axis_order": "1",
         "code_id": "t", "code_name": "전국", "is_item": "N"},
    ]
    coordinates = build_coordinates(rows, axis_value_limit=1)
    assert [c["obj_names"][1] for c in coordinates] == ["전국"]
