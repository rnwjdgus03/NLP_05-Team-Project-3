from __future__ import annotations

from pathlib import Path

from kosis_component_search import obj_hierarchy_scope
from prepare_kosis_mapping_input import normalize_row
from run_kosis_coordinate_stage_a import apply_family_rerank, table_family_identity
from write_kosis_run_manifest import code_bundle_digest


def _table(org: str, tbl: str, name: str, stat: str, score: float) -> dict:
    return {
        "org_id": org,
        "tbl_id": tbl,
        "metadata_rerank_score": score,
        "rrf_score": score,
        "lexical_rank": 1,
        "dense_rank": 1,
        "table": {
            "org_id": org,
            "tbl_id": tbl,
            "tbl_name": name,
            "stat_id": stat,
        },
    }


def test_table_family_ignores_revision_year_but_keeps_semantic_axis():
    a = _table("101", "A", "품목별 수출액(2020 기준)", "S1", 0.8)
    b = _table("101", "B", "품목별 수출액(2025 개편)", "S1", 0.7)
    c = _table("101", "C", "국가별 수출액(2025 개편)", "S1", 0.6)
    assert table_family_identity(a) == table_family_identity(b)
    assert table_family_identity(a) != table_family_identity(c)


def test_family_rerank_reserves_distinct_family_leaders():
    rows = [
        _table("101", "A", "품목별 수출액(2020 기준)", "S1", 0.90),
        _table("101", "B", "품목별 수출액(2025 개편)", "S1", 0.89),
        _table("101", "C", "국가별 수출액", "S1", 0.70),
    ]
    selected = apply_family_rerank(rows, table_pool_top_k=2)
    assert [row["tbl_id"] for row in selected] == ["A", "C"]
    assert all(row.get("table_family_key") for row in selected)


def test_product_obj_hierarchy_rejects_broad_to_detailed_hs_leaf():
    candidate = {
        "item": {"itm_name": "수출액"},
        "objects": {
            1: {"axis_name": "품목별", "obj_name": "기타 집적회로반도체"},
        },
    }
    ok, state, reason = obj_hierarchy_scope(candidate, {"industry_or_item": "반도체"})
    assert not ok and state == "rejected"
    assert "detail_scope_mismatch" in reason


def test_all_products_requires_aggregate_obj():
    detailed = {
        "item": {"itm_name": "수출액"},
        "objects": {1: {"axis_name": "품목별", "obj_name": "반도체"}},
    }
    aggregate = {
        "item": {"itm_name": "수출액"},
        "objects": {1: {"axis_name": "품목별", "obj_name": "총계", "is_aggregate": "Y"}},
    }
    assert not obj_hierarchy_scope(detailed, {"measurement_item": "전체 품목"})[0]
    assert obj_hierarchy_scope(aggregate, {"measurement_item": "전체 품목"})[0]


def _ready_row(**updates) -> dict[str, str]:
    row = {
        "claim_measurement_id": "T-m1",
        "claim_text": "작년 8월(11.4%) 이후 넘어섰다.",
        "date": "2025-01-06",
        "measurement_text": "11.4%",
        "measurement_usage": "KOSIS_VALUE",
        "claim_domain_scope": "국내공식통계",
        "measurement_binding_source": "hcx",
        "measurement_role": "현재값",
        "measurement_indicator": "증가율",
        "measurement_item": "",
        "measurement_period": "202308",
        "measurement_prd_se": "M",
        "period": "202412",
        "prd_se": "M",
        "value": "11.4",
        "unit": "%",
        "value_type": "증감률",
        "change_base": "전년동월",
        "mapping_gate": "READY",
    }
    row.update(updates)
    return row


def test_prepare_repairs_relative_month_in_existing_hcx_csv():
    normalized = normalize_row(_ready_row())
    assert normalized["period"] == "202408"
    assert "RELATIVE_YEAR_MONTH_FROM_ARTICLE_DATE" in normalized["period_alignment_status"]


def test_prepare_moves_comparison_delta_to_target_period():
    normalized = normalize_row(_ready_row(
        claim_text="2022년 기록을 2억 달러 웃돌아 2024년 최대치를 기록했다.",
        measurement_text="2억 달러",
        measurement_role="증감값",
        measurement_period="2022",
        measurement_prd_se="Y",
        period="2024",
        prd_se="Y",
        value="200000000",
        unit="달러",
        value_type="증감량",
        change_base="특정시점",
    ))
    assert normalized["period"] == "2024"
    assert "EXPLICIT_COMPARISON_PERIOD_TO_TARGET" in normalized["period_alignment_status"]


def test_code_digest_ignores_pytest_and_test_tmp(tmp_path: Path):
    (tmp_path / "pipeline.py").write_text("stable", encoding="utf-8")
    baseline, baseline_records = code_bundle_digest(tmp_path)
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "nodeids").write_text("volatile", encoding="utf-8")
    test_tmp = tmp_path / ".test-tmp-v21" / "case"
    test_tmp.mkdir(parents=True)
    (test_tmp / "result.json").write_text("volatile", encoding="utf-8")
    after, after_records = code_bundle_digest(tmp_path)
    assert after == baseline
    assert after_records == baseline_records
    assert [row["path"] for row in after_records] == ["pipeline.py"]
