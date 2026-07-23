import csv

from score_gold import retrieval_metrics, score_retrieval, score_verdict


def test_retrieval_without_candidate_artifact_is_not_reported_as_zero(capsys):
    score_retrieval(
        [{"claim_measurement_id": "m1", "gold_tbl_id": "T1"}],
        [],
    )

    output = capsys.readouterr().out
    assert "candidate CSV" in output
    assert "0.0%" not in output


def test_verdict_without_verified_artifact_is_not_reported_as_zero(capsys):
    score_verdict(
        [{"claim_measurement_id": "m1", "gold_verdict": "일치"}],
        [],
    )

    output = capsys.readouterr().out
    assert "verified CSV" in output
    assert "0.0%" not in output


def test_retrieval_metrics_compare_top_1_to_top_3():
    gold = [
        {"claim_measurement_id": "m1", "gold_tbl_id": "T1"},
        {"claim_measurement_id": "m2", "gold_tbl_id": "T2"},
        {"claim_measurement_id": "m3", "gold_tbl_id": "T3"},
    ]
    candidates = [
        {"claim_measurement_id": "m1", "tbl_id": "T1", "candidate_rank": "1"},
        {"claim_measurement_id": "m1", "tbl_id": "TX", "candidate_rank": "2"},
        {"claim_measurement_id": "m2", "tbl_id": "TX", "candidate_rank": "1"},
        {"claim_measurement_id": "m2", "tbl_id": "T2", "candidate_rank": "2"},
    ]

    metrics = retrieval_metrics(gold, candidates, ks=(1, 2, 3))

    assert [row["hits"] for row in metrics] == [1, 2, 2]
    assert [row["candidate_rows"] for row in metrics] == [2, 4, 4]
    assert all(row["gold_candidate_covered"] == 2 for row in metrics)


def test_retrieval_metrics_can_be_written(tmp_path):
    output = tmp_path / "topk.csv"
    score_retrieval(
        [{"claim_measurement_id": "m1", "gold_tbl_id": "T1"}],
        [{"claim_measurement_id": "m1", "tbl_id": "T1", "candidate_rank": "1"}],
        ks=(1, 2, 3),
        metrics_out=output,
    )

    with output.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["top_k"] for row in rows] == ["1", "2", "3"]
    assert rows[0]["recall"] == "1.0"


def test_retrieval_candidate_slices_are_written(tmp_path):
    candidates = [
        {"claim_measurement_id": "m1", "tbl_id": "T1", "candidate_rank": "1"},
        {"claim_measurement_id": "m1", "tbl_id": "T2", "candidate_rank": "2"},
        {"claim_measurement_id": "m1", "tbl_id": "T3", "candidate_rank": "3"},
    ]
    score_retrieval(
        [{"claim_measurement_id": "m1", "gold_tbl_id": "T1"}],
        candidates,
        ks=(1, 2, 3),
        slices_dir=tmp_path,
    )

    counts = []
    for k in (1, 2, 3):
        with (tmp_path / f"kosis_table_candidates_top{k}.csv").open(
            encoding="utf-8-sig", newline=""
        ) as f:
            counts.append(len(list(csv.DictReader(f))))
    assert counts == [1, 2, 3]
