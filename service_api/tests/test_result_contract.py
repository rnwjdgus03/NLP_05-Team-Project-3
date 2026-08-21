import json
from pathlib import Path

from app.runner import build_result


def write_jsonl(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_unresolved_is_never_exposed_as_mismatch(tmp_path: Path):
    write_jsonl(tmp_path / "claim_decisions.jsonl", [{
        "claim_measurement_id": "c1-m1", "claim_decision": "UNRESOLVED",
        "selected_coordinate_id": "", "candidate_count": 1,
        "candidate_verdict_counts": {"MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE": 1},
    }])
    write_jsonl(tmp_path / "verified_candidates.jsonl", [{
        "claim_measurement_id": "c1-m1", "coordinate_id": "x",
        "decision_status": "UNRESOLVED", "verdict_code": "MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE",
    }])
    result = build_result("job1", tmp_path)
    assert result["claims"][0]["verdict"] == "UNRESOLVED"
    assert result["summary"]["verdict_counts"] == {"UNRESOLVED": 1}


def test_selected_match_evidence_is_preserved(tmp_path: Path):
    write_jsonl(tmp_path / "claim_decisions.jsonl", [{
        "claim_measurement_id": "c1-m1", "claim_decision": "VERIFIED_MATCH",
        "selected_coordinate_id": "coord1", "candidate_count": 1,
        "candidate_verdict_counts": {"MATCH": 1},
    }])
    write_jsonl(tmp_path / "verified_candidates.jsonl", [{
        "claim_measurement_id": "c1-m1", "coordinate_id": "coord1",
        "decision_status": "VERIFIED_MATCH", "verdict_code": "MATCH",
        "org_id": "101", "tbl_id": "T1", "official_table_name": "테스트표",
        "selected_itm_id": "I1", "official_item_name": "인구", "kosis_actual_value": 10,
    }])
    result = build_result("job1", tmp_path)
    claim = result["claims"][0]
    assert claim["verdict"] == "MATCH"
    assert claim["selected_evidence"]["table"]["tbl_id"] == "T1"
    assert claim["selected_evidence"]["kosis_value"] == 10
