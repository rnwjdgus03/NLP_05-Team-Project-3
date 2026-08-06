import csv
from pathlib import Path

from chatbot.services.kosis_pipeline import (
    merge_kosis_results,
    run_kosis_pipeline,
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    if not fields:
        fields = ["claim_id", "claim_measurement_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def measurement(measurement_id: str = "A0001-C001-m1") -> dict[str, str]:
    return {
        "claim_id": "A0001-C001",
        "claim_measurement_id": measurement_id,
        "claim_text": "소비자물가는 2.3% 상승했다.",
        "measurement_text": "2.3%",
        "value": "2.3",
        "unit": "%",
    }


def article_result(rows: list[dict[str, str]]) -> dict:
    return {
        "article_id": "A0001",
        "splitter": "regex",
        "sentence_count": 1,
        "claim_count": 1,
        "sentences": [],
        "claims": [],
        "measurement_count": len(rows),
        "measurement_row_count": len(rows),
        "measurements": rows,
    }


def test_merge_kosis_results_preserves_rejected_measurement_reason():
    source = measurement()
    rejected = {
        **source,
        "mapping_exclusion_code": "PERIOD_MISSING",
        "mapping_exclusion_reason": "measurement period 없음",
    }

    result = merge_kosis_results([source], rejected=[rejected])[0]

    assert result["stage"] == "gate"
    assert result["status"] == "검증대상 아님"
    assert result["status_code"] == "PERIOD_MISSING"
    assert result["status_reason"] == "measurement period 없음"
    assert result["final_status"] == "NOT_KOSIS"


def test_merge_kosis_results_preserves_enrichment_action():
    source = measurement()
    enrichment = {
        **source,
        "mapping_exclusion_code": "PERIOD_MISSING",
        "mapping_exclusion_reason": "measurement period 없음",
        "enrichment_actions": "RESOLVE_PERIOD_FROM_CONTEXT",
    }

    result = merge_kosis_results([source], enrichments=[enrichment])[0]

    assert result["stage"] == "enrich"
    assert result["status"] == "보강 필요"
    assert result["final_status"] == "REVIEW"
    assert result["enrichment"]["enrichment_actions"] == "RESOLVE_PERIOD_FROM_CONTEXT"


def test_merge_kosis_results_prefers_verification_over_candidate():
    source = measurement()
    candidate = {
        **source,
        "candidate_rank": "1",
        "candidate_status": "READY",
        "candidate_status_code": "READY",
        "tbl_id": "DT_TEST",
    }
    verified = {
        **source,
        "verdict": "일치",
        "verdict_code": "MATCH",
        "verdict_reason": "차이율=0.2%",
    }

    result = merge_kosis_results(
        [source], candidates=[candidate], verified=[verified]
    )[0]

    assert result["stage"] == "verification"
    assert result["status"] == "일치"
    assert result["status_code"] == "MATCH"
    assert result["candidates"][0]["tbl_id"] == "DT_TEST"


def test_run_kosis_pipeline_table_mode_uses_existing_cli_contract(tmp_path):
    table_index = tmp_path / "tables.csv"
    write_csv(
        table_index,
        [{"ORG_ID": "101", "TBL_ID": "DT_TEST", "TBL_NM": "소비자물가"}],
    )
    source = measurement()
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        input_path = Path(command[command.index("--input") + 1])
        out_dir = Path(command[command.index("--out-dir") + 1])
        stem = input_path.stem
        write_csv(out_dir / f"{stem}_kosis_ready.csv", [source])
        write_csv(out_dir / f"{stem}_kosis_enrich.csv", [])
        write_csv(out_dir / f"{stem}_kosis_rejected.csv", [])
        write_csv(
            out_dir / f"{stem}_kosis_table_candidates.csv",
            [
                {
                    **source,
                    "candidate_rank": "1",
                    "candidate_status": "TABLE_ONLY",
                    "candidate_status_code": "META_NOT_LOADED",
                    "candidate_status_reason": "통계표 메타 조회 전 후보",
                    "tbl_id": "DT_TEST",
                }
            ],
        )

    result = run_kosis_pipeline(
        article_result([source]),
        mode="table",
        table_index=table_index,
        artifact_dir=tmp_path / "request",
        command_runner=fake_runner,
    )

    assert len(calls) == 1
    assert "--skip-meta" in calls[0][0]
    assert "--retrieval-mode" in calls[0][0]
    assert "auto" in calls[0][0]
    assert "--semantic-index" in calls[0][0]
    assert result["eligible_count"] == 1
    assert result["candidate_count"] == 1
    assert result["results"][0]["stage"] == "candidate"
    assert result["results"][0]["status_code"] == "META_NOT_LOADED"


def test_run_kosis_pipeline_skips_command_when_measurements_are_empty():
    called = False

    def fake_runner(command, **kwargs):
        nonlocal called
        called = True

    result = run_kosis_pipeline(
        article_result([]),
        mode="verify",
        command_runner=fake_runner,
    )

    assert called is False
    assert result["measurement_count"] == 0
    assert result["results"] == []
