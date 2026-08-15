from __future__ import annotations

import csv
import inspect
from pathlib import Path

from kosis_sqlite_metadata import connect, counts, create_schema, import_meta_index
from kosis_sqlite_resolver import MetadataStore, aggregate_value, resolve, resolve_axis
import run_kosis_sqlite_exact_pipeline as sqlite_pipeline


FIELDS = [
    "org_id", "tbl_id", "tbl_name", "category_path", "axis_id", "axis_name",
    "axis_order", "code_id", "code_name", "parent_code_id", "is_item",
    "unit_id", "unit_name", "unit_eng_name", "prd_se_list", "prd_ranges",
]


def write_meta(path: Path) -> None:
    rows = [
        ["101", "T1", "연령·교육정도별 실업률", "고용", "ITEM", "항목", "", "I1", "실업률", "", "Y", "U1", "%", "%", "M|Y", ""],
        ["101", "T1", "연령·교육정도별 실업률", "고용", "A", "연령", "1", "A0", "계", "", "N", "", "", "", "M|Y", ""],
        ["101", "T1", "연령·교육정도별 실업률", "고용", "A", "연령", "1", "A1", "20~29세", "", "N", "", "", "", "M|Y", ""],
        ["101", "T1", "연령·교육정도별 실업률", "고용", "A", "연령", "1", "A2", "25~29세", "", "N", "", "", "", "M|Y", ""],
        ["101", "T1", "연령·교육정도별 실업률", "고용", "B", "교육정도", "2", "B0", "계", "", "N", "", "", "", "M|Y", ""],
        ["101", "T1", "연령·교육정도별 실업률", "고용", "B", "교육정도", "2", "B1", "고졸", "", "N", "", "", "", "M|Y", ""],
        ["101", "T1", "연령·교육정도별 실업률", "고용", "B", "교육정도", "2", "B2", "대졸 이상", "", "N", "", "", "", "M|Y", ""],
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(rows)


def test_sqlite_metadata_import_is_idempotent(tmp_path: Path) -> None:
    meta = tmp_path / "meta.csv"
    db = tmp_path / "meta.sqlite"
    write_meta(meta)
    connection = connect(db)
    create_schema(connection)
    assert import_meta_index(connection, meta) == 7
    assert import_meta_index(connection, meta) == 7
    assert counts(connection)["kosis_tables"] == 1
    assert counts(connection)["kosis_items"] == 1
    assert counts(connection)["kosis_axes"] == 2
    assert counts(connection)["kosis_axis_values"] == 6
    assert counts(connection)["metadata_imports"] == 1
    connection.close()


def test_resolver_selects_exact_item_and_typed_obj_axes(tmp_path: Path) -> None:
    meta = tmp_path / "meta.csv"
    db = tmp_path / "meta.sqlite"
    write_meta(meta)
    connection = connect(db)
    create_schema(connection)
    import_meta_index(connection, meta)
    connection.close()

    claims = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m1", "article_id": "A0001",
        "claim_text": "25~29세 대졸 이상 실업률은 7%다.",
        "measurement_indicator": "실업률", "age_group": "25~29세",
        "education_level": "대졸 이상", "unit": "%", "unit_dimension": "rate",
        "measurement_prd_se": "Y",
    }]
    table_candidates = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m1", "candidate_rank": "1",
        "org_id": "101", "tbl_id": "T1", "tbl_name": "연령·교육정도별 실업률",
    }]
    store = MetadataStore(db)
    try:
        candidates, selected, failures = resolve(claims, table_candidates, store)
    finally:
        store.close()
    assert not failures
    assert candidates
    assert len(selected) == 1
    row = selected[0]
    assert row["selected_itm_id"] == "I1"
    assert row["selected_obj_l1"] == "A2"
    assert row["selected_obj_l2"] == "B2"
    assert row["sqlite_obj_strict_match"] == "Y"
    assert row["selection_backend"] == "sqlite_exact_item_obj_v1"


def test_resolver_can_lock_selection_to_reranked_top_table(tmp_path: Path) -> None:
    meta = tmp_path / "meta.csv"
    db = tmp_path / "meta.sqlite"
    rows = [
        ["101", "TOP", "상위표", "고용", "ITEM", "항목", "", "I1", "고용률", "", "Y", "U", "%", "", "Y", ""],
        ["101", "TOP", "상위표", "고용", "A", "성별", "1", "A0", "계", "", "N", "", "", "", "Y", ""],
        ["101", "LOW", "하위표", "고용", "ITEM", "항목", "", "I2", "실업률", "", "Y", "U", "%", "", "Y", ""],
        ["101", "LOW", "하위표", "고용", "A", "성별", "1", "A0", "계", "", "N", "", "", "", "Y", ""],
    ]
    with meta.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    connection = connect(db)
    create_schema(connection)
    import_meta_index(connection, meta)
    connection.close()
    claims = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m1",
        "measurement_indicator": "실업률", "unit_dimension": "rate",
    }]
    tables = [
        {"claim_id": "C1", "claim_measurement_id": "C1-m1", "candidate_rank": "1", "org_id": "101", "tbl_id": "TOP"},
        {"claim_id": "C1", "claim_measurement_id": "C1-m1", "candidate_rank": "2", "org_id": "101", "tbl_id": "LOW"},
    ]
    store = MetadataStore(db)
    try:
        _, selected, _ = resolve(claims, tables, store, selection_mode="table_locked")
    finally:
        store.close()
    assert selected[0]["tbl_id"] == "TOP"
    assert selected[0]["sqlite_selection_mode"] == "table_locked"


def test_resolver_rejects_person_density_for_person_count(tmp_path: Path) -> None:
    meta = tmp_path / "density.csv"
    db = tmp_path / "density.sqlite"
    rows = [
        ["101", "D1", "인구밀도", "인구", "ITEM", "항목", "", "I1", "인구밀도", "", "Y", "U1", "명/㎢", "", "Y", ""],
        ["101", "D1", "인구밀도", "인구", "A", "지역", "1", "A0", "전국", "", "N", "", "", "", "Y", ""],
    ]
    with meta.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    connection = connect(db)
    create_schema(connection)
    import_meta_index(connection, meta)
    connection.close()
    claims = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m1",
        "measurement_indicator": "총인구", "unit": "명",
        "unit_dimension": "person_count", "measurement_prd_se": "Y",
    }]
    candidates = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m1", "candidate_rank": "1",
        "org_id": "101", "tbl_id": "D1", "tbl_name": "인구밀도",
    }]
    store = MetadataStore(db)
    try:
        all_candidates, selected, _ = resolve(claims, candidates, store)
    finally:
        store.close()
    assert all_candidates[0]["sqlite_unit_compatible"] == "N"
    assert selected[0]["sqlite_unit_compatible"] == "N"


def test_exact_pipeline_pins_the_resolved_item_during_value_verification() -> None:
    source = inspect.getsource(sqlite_pipeline.main)
    assert '"--use-pinned-item"' in source


def test_aggregate_value_prefers_named_root_total_over_dash_leaf() -> None:
    selected = aggregate_value([
        {"obj_code": "A.91", "obj_name": "-", "parent_obj_code": "A.9"},
        {"obj_code": "A.A", "obj_name": "총액", "parent_obj_code": ""},
    ])
    assert selected is not None
    assert selected["obj_code"] == "A.A"


def test_aggregate_value_prefers_explicit_sum_over_contextual_subtotal() -> None:
    selected = aggregate_value([
        {"obj_code": "B.0001", "obj_name": "합계", "parent_obj_code": ""},
        {"obj_code": "B.0002", "obj_name": "계", "parent_obj_code": ""},
    ])
    assert selected is not None
    assert selected["obj_code"] == "B.0001"


def test_resolve_axis_can_bind_metric_stored_as_obj() -> None:
    selected, status, targets, _ = resolve_axis(
        {
            "claim_text": "가구당 월평균 소득은 535만원이다.",
            "measurement_indicator": "가구당 월평균 소득",
        },
        {
            "axis_name": "가계수지항목별",
            "values": [
                {"obj_code": "A1", "obj_name": "가구원수"},
                {"obj_code": "A2", "obj_name": "소득"},
                {"obj_code": "A3", "obj_name": "소비지출"},
            ],
        },
    )
    assert selected is not None
    assert selected["obj_code"] == "A2"
    assert status == "EXACT_TARGET"
    assert targets == ("소득",)


def test_resolver_uses_claimed_official_cause_instead_of_total(tmp_path: Path) -> None:
    meta = tmp_path / "cause.csv"
    db = tmp_path / "cause.sqlite"
    rows = [
        ["101", "C1", "영아사망원인별 사망자수", "인구", "ITEM", "항목", "", "I1", "사망자수", "", "Y", "U1", "명", "", "Y", ""],
        ["101", "C1", "영아사망원인별 사망자수", "인구", "A", "영아사망원인별", "1", "A0", "계", "", "N", "", "", "", "Y", ""],
        ["101", "C1", "영아사망원인별 사망자수", "인구", "A", "영아사망원인별", "1", "A1", "영아돌연사증후군", "", "N", "", "", "", "Y", ""],
    ]
    with meta.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    connection = connect(db)
    create_schema(connection)
    import_meta_index(connection, meta)
    connection.close()
    claims = [{
        "claim_id": "X1", "claim_measurement_id": "X1-m1",
        "claim_text": "영아돌연사증후군으로 인한 영아 사망자 수는 47명이다.",
        "measurement_indicator": "영아돌연사증후군으로 인한 영아 사망자 수",
        "unit": "명", "unit_dimension": "person_count", "measurement_prd_se": "Y",
    }]
    candidates = [{
        "claim_id": "X1", "claim_measurement_id": "X1-m1", "candidate_rank": "1",
        "org_id": "101", "tbl_id": "C1", "tbl_name": "영아사망원인별 사망자수",
    }]
    store = MetadataStore(db)
    try:
        _, selected, _ = resolve(claims, candidates, store)
    finally:
        store.close()
    assert selected[0]["selected_obj_l1"] == "A1"
    assert selected[0]["selected_obj_l1_dynamic_target_terms"] == "영아돌연사증후군"
