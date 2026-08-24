import json
from pathlib import Path

from app.runner import build_result, write_gate_only_result_inputs


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
    assert result["claims"][0]["explanation"]["title"] == "판단 보류"
    assert "불일치 판정을 보류" in result["claims"][0]["explanation"]["detail"]


def test_selected_match_evidence_is_preserved(tmp_path: Path):
    (tmp_path / "measurements.csv").write_text(
        "claim_measurement_id,claim_text,measurement_indicator,measurement_period,value,unit\n"
        "c1-m1,지난해 인구는 10명이었다.,인구,2024,10,명\n",
        encoding="utf-8",
    )
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
    assert claim["claim"] == {
        "text": "지난해 인구는 10명이었다.", "indicator": "인구", "item": "",
        "period": "2024", "value": "10", "unit": "명",
    }
    assert claim["explanation"]["title"] == "공식 통계와 일치"


def test_zero_ready_measurements_become_safe_unresolved(tmp_path: Path):
    measurements = tmp_path / "measurements.csv"
    measurements.write_text(
        "claim_measurement_id,mapping_gate,mapping_exclusion_code\n"
        "c1-m1,REJECT,NOT_KOSIS_VALUE\n"
        "c1-m2,ENRICH,PERIOD_MISSING\n",
        encoding="utf-8",
    )
    write_gate_only_result_inputs(measurements, tmp_path)
    result = build_result("job1", tmp_path)
    assert result["summary"] == {
        "measurement_count": 2,
        "ready_measurement_count": 2,
        "result_claim_count": 2,
        "extracted_measurement_count": 2,
        "verdict_counts": {"UNRESOLVED": 2},
    }
    assert all(claim["selected_evidence"] is None for claim in result["claims"])
    assert result["claims"][0]["explanation"]["detail"].startswith("기업 실적")


def test_empty_ready_file_does_not_dilute_service_evidence_denominator(tmp_path: Path):
    measurements = tmp_path / "measurements.csv"
    measurements.write_text(
        "claim_measurement_id,mapping_gate,mapping_exclusion_code\n"
        "c1-m1,REJECT,NOT_KOSIS_VALUE\n"
        "c1-m2,ENRICH,PERIOD_MISSING\n",
        encoding="utf-8",
    )
    (tmp_path / "service_prepared_ready.csv").write_text(
        "claim_measurement_id\n", encoding="utf-8"
    )
    write_gate_only_result_inputs(measurements, tmp_path)
    result = build_result("job1", tmp_path)
    assert result["summary"]["measurement_count"] == 0
    assert result["summary"]["extracted_measurement_count"] == 2
