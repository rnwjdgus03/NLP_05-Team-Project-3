from __future__ import annotations

from rerank_kosis_tables_with_sqlite_metadata import metadata_document, rerank_group


class FakeStore:
    def table(self, org_id: str, tbl_id: str):
        return {"tbl_name": "성별 고용률", "category_path": "고용"}

    def items(self, org_id: str, tbl_id: str):
        return [{"itm_id": "I", "itm_name": "고용률", "unit_name": "%", "unit_dimension": "rate"}]

    def axes(self, org_id: str, tbl_id: str):
        return [{
            "axis_order": 1, "axis_name": "성별",
            "values": [
                {"obj_code": "0", "obj_name": "계", "parent_obj_code": ""},
                {"obj_code": "F", "obj_name": "여자", "parent_obj_code": ""},
            ],
        }]

    def periodicities(self, org_id: str, tbl_id: str):
        return {"M"}


def test_metadata_document_exposes_official_item_axis_and_claimed_value() -> None:
    document = metadata_document(
        {"claim_text": "여자 고용률은 60%", "measurement_indicator": "고용률", "gender": "여자", "unit_dimension": "rate"},
        {"org_id": "1", "tbl_id": "T", "candidate_rank": "1"},
        FakeStore(),  # type: ignore[arg-type]
    )
    assert "고용률 [%]" in document
    assert "성별" in document
    assert "여자" in document
    assert "수록주기: M" in document


def test_rerank_group_combines_metadata_score_with_upstream_rank() -> None:
    claim = {"claim_text": "여자 고용률은 60%", "measurement_indicator": "고용률", "gender": "여자", "unit_dimension": "rate"}
    candidates = [
        {"org_id": "1", "tbl_id": "A", "candidate_rank": "1"},
        {"org_id": "1", "tbl_id": "B", "candidate_rank": "2"},
    ]
    ranked = rerank_group(
        claim, candidates, FakeStore(), lambda query, docs: [0.1, 0.9],
        metadata_weight=0.8,
    )  # type: ignore[arg-type]
    assert ranked[0]["tbl_id"] == "B"
    assert ranked[0]["candidate_rank"] == 1
    assert ranked[0]["upstream_candidate_rank"] == 2
