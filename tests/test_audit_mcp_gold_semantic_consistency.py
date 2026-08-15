from __future__ import annotations

from audit_mcp_gold_semantic_consistency import audit_row, explicit_concept_mismatch


class FakeStore:
    def table(self, org_id: str, tbl_id: str):
        return {"tbl_name": "성별 경제활동인구 총괄", "category_path": "고용"}

    def items(self, org_id: str, tbl_id: str):
        return [
            {"itm_id": "EMP", "itm_name": "취업자", "unit_name": "천명"},
            {"itm_id": "UNEMP", "itm_name": "실업률", "unit_name": "%"},
        ]

    def axes(self, org_id: str, tbl_id: str):
        return [{
            "axis_order": 1, "axis_name": "성별",
            "values": [{"obj_code": "0", "obj_name": "계", "parent_obj_code": ""}],
        }]


def gold(item_id: str, item_name: str, unit: str = "천명") -> dict[str, str]:
    return {
        "gold_org_id": "101", "gold_tbl_id": "T", "gold_tbl_name": "성별 경제활동인구 총괄",
        "gold_itm_id": item_id, "gold_item_name": item_name, "gold_source_unit": unit,
        "gold_obj_l1": "0", "gold_prd_se": "M", "gold_period": "202503",
    }


def claim() -> dict[str, str]:
    return {
        "claim_text": "3월 취업자 수는 19만명 증가했다", "measurement_indicator": "취업자",
        "unit_dimension": "person_count", "semantic_type": "level",
        "prd_se": "M", "period": "202503",
    }


def test_semantic_audit_accepts_matching_official_item() -> None:
    audited = audit_row(gold("EMP", "취업자"), claim(), FakeStore())  # type: ignore[arg-type]
    assert audited["semantic_audit_status"] == "PASS"


def test_semantic_audit_rejects_employment_claim_bound_to_unemployment_rate() -> None:
    audited = audit_row(gold("UNEMP", "실업률", "%"), claim(), FakeStore())  # type: ignore[arg-type]
    assert audited["semantic_audit_status"] == "REVIEW"
    assert "INDICATOR_TABLE_ITEM_MISMATCH" in audited["semantic_audit_reason"]
    assert "DIRECT_UNIT_DIMENSION_MISMATCH" in audited["semantic_audit_reason"]


def test_semantic_audit_rejects_frozen_period_disagreement() -> None:
    bad = gold("EMP", "취업자")
    bad["gold_period"] = "202403"
    audited = audit_row(bad, claim(), FakeStore())  # type: ignore[arg-type]
    assert "TARGET_PERIOD_MISMATCH" in audited["semantic_audit_reason"]


def test_explicit_concept_audit_separates_import_from_export() -> None:
    assert explicit_concept_mismatch("수입액", "전체 수입이 감소했다", "수출액") == (
        "IMPORT_EXPORT_DIRECTION_MISMATCH"
    )
    assert explicit_concept_mismatch("수입액", "전체 수입이 감소했다", "수입액") == ""


def test_explicit_concept_audit_separates_trade_count_from_amount() -> None:
    assert explicit_concept_mismatch(
        "수출", "하이브리드차 수출대수가 증가했다", "수출액"
    ) == "TRADE_COUNT_AMOUNT_MISMATCH"


def test_semantic_audit_requires_gold_period_fields_in_claim_extraction() -> None:
    store = FakeStore()
    gold_row = gold("EMP", "취업자")
    claim_row = claim()
    claim_row["measurement_period"] = ""
    claim_row["period"] = ""
    audited = audit_row(gold_row, claim_row, store)  # type: ignore[arg-type]
    assert "STRUCTURED_TARGET_PERIOD_MISSING" in audited["semantic_audit_reason"]
