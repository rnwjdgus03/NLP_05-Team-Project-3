#!/usr/bin/env python3
"""Freeze a gold-blind, measurement-level prediction file for locked holdout 300."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


VERSION = "locked300-v9-20260810"
KEY = "claim_measurement_id"
PREDICTION_FIELDS = (
    "prediction_id", "pipeline_version", "gold_accessed", "article_id", "title", "date", "url",
    "claim_id", KEY, "claim_text", "measurement_text", "measurement_indicator", "measurement_item",
    "value", "unit", "measurement_period", "measurement_prd_se", "region", "age_group", "gender",
    "origin_country", "destination_country", "pipeline_status", "mapping_status", "mapping_reason",
    "org_id", "tbl_id", "tbl_name", "candidate_rank", "selected_itm_id", "selected_itm_name",
    "selected_itm_unit", "selected_obj_l1", "selected_obj_l1_name", "selected_obj_l2",
    "selected_obj_l2_name", "selected_obj_l3", "selected_obj_l3_name", "coordinate_prd_se",
    "obj_target_match", "prd_se_match", "topk_fallback_attempted", "topk_fallback_recovered",
    "obj_relaxation_used", "verdict", "verdict_code", "verdict_reason", "kosis_period_used",
    "kosis_actual_value", "value_diff",
)


def read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank(row: dict[str, str]) -> tuple[int, int]:
    status_order = {"READY": 0, "NEEDS_CONFIRMATION": 1, "MAPPING_FAILED": 2, "API_ERROR": 3}
    try:
        candidate_rank = int(float(row.get("candidate_rank", "999") or "999"))
    except ValueError:
        candidate_rank = 999
    return status_order.get(row.get("mapping_status", ""), 9), candidate_rank


def best_by_measurement(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get(KEY):
            grouped[row[KEY]].append(row)
    return {key: min(values, key=rank) for key, values in grouped.items()}


def build_predictions(
    measurements: list[dict[str, str]],
    mapped: list[dict[str, str]],
    verified: list[dict[str, str]],
    pipeline_version: str = VERSION,
) -> list[dict[str, str]]:
    mapped_by_key = best_by_measurement(mapped)
    verified_by_key = best_by_measurement(verified)
    predictions = []
    for index, measurement in enumerate(measurements, start=1):
        key = measurement.get(KEY, "")
        mapping = mapped_by_key.get(key, {})
        verification = verified_by_key.get(key, {})
        status = mapping.get("mapping_status", "") or "NOT_READY"
        row = {field: "" for field in PREDICTION_FIELDS}
        for source in (measurement, mapping, verification):
            for field in PREDICTION_FIELDS:
                if source.get(field, "") != "":
                    row[field] = source[field]
        row.update(
            prediction_id=f"LP300-{index:05d}",
            pipeline_version=pipeline_version,
            gold_accessed="N",
            pipeline_status=status,
            mapping_status=status,
            mapping_reason=row.get("mapping_reason") or "NO_MAPPING_ROW_AFTER_GATE",
        )
        predictions.append(row)
    return predictions


def build_article_summary(
    articles: list[dict[str, str]], predictions: list[dict[str, str]]
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in predictions:
        grouped[row.get("article_id", "")].append(row)
    output = []
    for article in articles:
        article_id = article.get("article_id", "")
        rows = grouped.get(article_id, [])
        statuses = Counter(row.get("pipeline_status", "") for row in rows)
        output.append({
            "holdout_id": article.get("holdout_id", ""),
            "article_id": article_id,
            "title": article.get("기사제목", ""),
            "date": article.get("date_iso", ""),
            "url": article.get("URL", ""),
            "measurement_count": len(rows),
            "ready_count": statuses.get("READY", 0),
            "needs_confirmation_count": statuses.get("NEEDS_CONFIRMATION", 0),
            "mapping_failed_count": statuses.get("MAPPING_FAILED", 0),
            "not_ready_count": statuses.get("NOT_READY", 0),
            "article_prediction_status": "NO_MEASUREMENT" if not rows else (
                "HAS_READY" if statuses.get("READY", 0) else "NO_READY"
            ),
            "gold_accessed": "N",
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--verified", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--article-output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pipeline-version", default=VERSION)
    args = parser.parse_args()

    articles = read_csv(args.articles)
    measurements = read_csv(args.measurements)
    predictions = build_predictions(
        measurements, read_csv(args.mapped), read_csv(args.verified),
        pipeline_version=args.pipeline_version,
    )
    article_rows = build_article_summary(articles, predictions)
    article_fields = (
        "holdout_id", "article_id", "title", "date", "url", "measurement_count", "ready_count",
        "needs_confirmation_count", "mapping_failed_count", "not_ready_count",
        "article_prediction_status", "gold_accessed",
    )
    write_csv(args.output, predictions, PREDICTION_FIELDS)
    write_csv(args.article_output, article_rows, article_fields)
    manifest = {
        "schema_version": 1,
        "pipeline_version": args.pipeline_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gold_accessed": False,
        "article_count": len(articles),
        "measurement_prediction_count": len(predictions),
        "article_status_counts": dict(Counter(str(row["article_prediction_status"]) for row in article_rows)),
        "mapping_status_counts": dict(Counter(row["pipeline_status"] for row in predictions)),
        "predictions_sha256": sha256(args.output),
        "article_predictions_sha256": sha256(args.article_output),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
