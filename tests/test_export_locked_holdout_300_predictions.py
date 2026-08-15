from __future__ import annotations

from export_locked_holdout_300_predictions import build_article_summary, build_predictions


def test_build_predictions_keeps_all_measurements_and_never_marks_gold_accessed() -> None:
    measurements = [
        {"claim_measurement_id": "M1", "article_id": "A0001", "value": "2.4"},
        {"claim_measurement_id": "M2", "article_id": "A0002", "value": "7"},
    ]
    mapped = [
        {"claim_measurement_id": "M1", "mapping_status": "MAPPING_FAILED", "candidate_rank": "2"},
        {"claim_measurement_id": "M1", "mapping_status": "READY", "candidate_rank": "3", "tbl_id": "T1"},
    ]
    verified = [{"claim_measurement_id": "M1", "mapping_status": "READY", "verdict_code": "MATCH"}]
    rows = build_predictions(measurements, mapped, verified)
    assert len(rows) == 2
    assert rows[0]["pipeline_status"] == "READY"
    assert rows[0]["tbl_id"] == "T1"
    assert rows[0]["verdict_code"] == "MATCH"
    assert rows[1]["pipeline_status"] == "NOT_READY"
    assert all(row["gold_accessed"] == "N" for row in rows)


def test_article_summary_includes_articles_without_measurements() -> None:
    articles = [
        {"holdout_id": "LH300-001", "article_id": "A0001", "기사제목": "one"},
        {"holdout_id": "LH300-002", "article_id": "A0002", "기사제목": "two"},
    ]
    predictions = [{"article_id": "A0001", "pipeline_status": "READY"}]
    rows = build_article_summary(articles, predictions)
    assert rows[0]["article_prediction_status"] == "HAS_READY"
    assert rows[1]["article_prediction_status"] == "NO_MEASUREMENT"
    assert rows[1]["measurement_count"] == 0


def test_prediction_pipeline_version_is_explicitly_overridable() -> None:
    rows = build_predictions(
        [{"claim_measurement_id": "M1", "article_id": "A0001"}], [], [],
        pipeline_version="locked300-v11-dev",
    )
    assert rows[0]["pipeline_version"] == "locked300-v11-dev"
