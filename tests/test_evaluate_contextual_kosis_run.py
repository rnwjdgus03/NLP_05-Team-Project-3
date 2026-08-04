import csv

from evaluate_contextual_kosis_run import evaluate_run, metric_rows


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_evaluation_uses_measurements_not_topk_rows_as_denominator(tmp_path):
    write_csv(
        tmp_path / "01_sentences.csv",
        [
            {"article_id": "A1", "claim_id": "C1"},
            {"article_id": "A1", "claim_id": "C2"},
            {"article_id": "A2", "claim_id": "C3"},
        ],
    )
    write_csv(tmp_path / "02_chunks.csv", [{"article_id": "A1"}, {"article_id": "A2"}])
    write_csv(
        tmp_path / "03_claim_spans.csv",
        [{"claim_id": "C1"}, {"claim_id": "C2"}],
    )
    write_csv(
        tmp_path / "03_claim_contexts.csv",
        [{"claim_id": "C1"}, {"claim_id": "C2"}],
    )
    write_csv(
        tmp_path / "05_hcx_measurements.csv",
        [
            {"claim_id": "C1", "claim_measurement_id": "M1"},
            {"claim_id": "C2", "claim_measurement_id": "M2"},
            {"claim_id": "C2", "claim_measurement_id": "M3"},
            {"claim_id": "C2", "claim_measurement_id": "M4"},
        ],
    )
    write_csv(
        tmp_path / "06_mapping_ready.csv",
        [
            {"claim_measurement_id": "M1"},
            {"claim_measurement_id": "M2"},
        ],
    )
    write_csv(
        tmp_path / "06_mapping_enrich.csv",
        [
            {
                "claim_measurement_id": "M3",
                "mapping_gate": "ENRICH",
                "mapping_exclusion_code": "PERIOD_MISSING",
                "enrichment_actions": "기간 보강",
            }
        ],
    )
    write_csv(
        tmp_path / "06_mapping_reject.csv",
        [
            {
                "claim_measurement_id": "M4",
                "mapping_gate": "REJECT",
                "mapping_exclusion_code": "OUT_OF_KOSIS_SCOPE",
                "mapping_gate_reason": "OUT_OF_KOSIS_SCOPE",
            }
        ],
    )
    write_csv(
        tmp_path / "07_mapping/05_hcx_measurements_kosis_validated_mappings.csv",
        [
            {
                "claim_measurement_id": "M1",
                "candidate_rank": "1",
                "mapping_status": "READY",
                "mapping_reason": "validated",
                "candidate_status_reason": "",
            },
            {
                "claim_measurement_id": "M1",
                "candidate_rank": "2",
                "mapping_status": "NOT_EVALUATED",
                "mapping_reason": "LOW_PRIORITY_CANDIDATE",
                "candidate_status_reason": "",
            },
            {
                "claim_measurement_id": "M2",
                "candidate_rank": "1",
                "mapping_status": "NEEDS_CONFIRMATION",
                "mapping_reason": "AMBIGUOUS_TABLE",
                "candidate_status_reason": "small margin",
            },
        ],
    )
    write_csv(
        tmp_path / "07_mapping/05_hcx_measurements_kosis_verified.csv",
        [
            {
                "claim_measurement_id": "M1",
                "verdict": "일치",
                "verdict_code": "MATCH",
                "verdict_reason": "within tolerance",
            }
        ],
    )

    result = evaluate_run(tmp_path)

    assert result["counts"]["articles"] == 2
    assert result["counts"]["claim_contexts"] == 2
    assert result["counts"]["measurements"] == 4
    assert result["counts"]["gate_ready"] == 2
    assert result["counts"]["validated_measurements"] == 2
    assert result["counts"]["validated_ready"] == 1
    assert result["counts"]["conclusive_verdicts"] == 1
    assert result["rates"]["ready_reach_pct"] == 50.0
    assert result["rates"]["mapping_ready_pct"] == 50.0
    assert result["rates"]["verification_success_pct"] == 100.0
    assert result["rates"]["end_to_end_conclusive_pct"] == 25.0
    assert any(
        row["reason_code"] == "AMBIGUOUS_TABLE" for row in result["reasons"]
    )

    metrics = {row["metric"]: row for row in metric_rows(result)}
    assert metrics["READY reach"]["denominator"] == 4
    assert metrics["validated READY"]["denominator"] == 2
