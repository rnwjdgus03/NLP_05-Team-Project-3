from __future__ import annotations

from kosis_sqlite_resolver import MetadataStore
from audit_mcp_gold_coordinate_consistency import audit_row


class FakeStore:
    def table(self, org_id: str, tbl_id: str):
        return {"tbl_name": "품목별 수출액"}

    def items(self, org_id: str, tbl_id: str):
        return [{"itm_id": "EXP", "itm_name": "수출액", "unit_name": "천달러"}]

    def axes(self, org_id: str, tbl_id: str):
        return [{
            "axis_order": 1, "axis_name": "품목별",
            "values": [
                {"obj_code": "TOTAL", "obj_name": "총액", "parent_obj_code": ""},
                {"obj_code": "CHIP", "obj_name": "반도체", "parent_obj_code": ""},
            ],
        }]


def test_audit_flags_nonaggregate_gold_when_claim_has_no_typed_target() -> None:
    gold = {
        "gold_org_id": "1", "gold_tbl_id": "T", "gold_itm_id": "EXP",
        "gold_obj_l1": "CHIP",
    }
    claim = {"claim_text": "지난해 전체 수출액은 6838억달러였다", "measurement_indicator": "수출액"}
    audited = audit_row(gold, claim, FakeStore())  # type: ignore[arg-type]
    assert audited["audit_status"] == "REVIEW"
    assert "NON_AGGREGATE_OBJ_WITHOUT_TYPED_TARGET" in audited["audit_reason"]


def test_audit_accepts_official_total_for_unsegmented_claim() -> None:
    gold = {
        "gold_org_id": "1", "gold_tbl_id": "T", "gold_itm_id": "EXP",
        "gold_obj_l1": "TOTAL",
    }
    claim = {"claim_text": "지난해 전체 수출액은 6838억달러였다", "measurement_indicator": "수출액"}
    audited = audit_row(gold, claim, FakeStore())  # type: ignore[arg-type]
    assert audited["audit_status"] == "PASS"
