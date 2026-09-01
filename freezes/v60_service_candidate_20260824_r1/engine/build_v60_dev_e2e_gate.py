#!/usr/bin/env python3
"""Summarize the v60 real-article *development* replay promotion gate.

The output is explicitly labelled development-only and must never be reported
as blind performance.  It verifies that every READY measurement received a
decision and that verified matches cover enough distinct source articles.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL {path}:{line_number}") from exc
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-ready", type=int, default=60)
    parser.add_argument("--match-min", type=int, default=6)
    parser.add_argument("--article-min", type=int, default=5)
    parser.add_argument("--match-rate-min", type=float, default=0.10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.ready.open(encoding="utf-8-sig", newline="") as handle:
        ready_rows = list(csv.DictReader(handle))
    decisions = jsonl(args.decisions)

    ready_ids = [row["claim_measurement_id"] for row in ready_rows]
    if len(ready_ids) != len(set(ready_ids)):
        raise ValueError("duplicate claim_measurement_id in READY input")
    article_by_measurement = {
        row["claim_measurement_id"]: row.get("article_id", "")
        for row in ready_rows
    }
    decision_by_measurement: dict[str, dict] = {}
    for row in decisions:
        measurement_id = row["claim_measurement_id"]
        if measurement_id in decision_by_measurement:
            raise ValueError(f"duplicate decision: {measurement_id}")
        decision_by_measurement[measurement_id] = row

    missing = sorted(set(ready_ids) - set(decision_by_measurement))
    unexpected = sorted(set(decision_by_measurement) - set(ready_ids))
    counts = Counter(
        decision_by_measurement[mid].get("claim_decision", "")
        for mid in ready_ids
        if mid in decision_by_measurement
    )
    matched_ids = [
        mid
        for mid in ready_ids
        if decision_by_measurement.get(mid, {}).get("claim_decision")
        == "VERIFIED_MATCH"
    ]
    matched_articles = sorted(
        {article_by_measurement[mid] for mid in matched_ids if article_by_measurement[mid]}
    )
    ready_count = len(ready_rows)
    match_count = len(matched_ids)
    match_rate = match_count / ready_count if ready_count else 0.0

    checks = {
        "ready_count_exact": ready_count == args.expected_ready,
        "decision_coverage_complete": not missing and not unexpected,
        "verified_match_min": match_count >= args.match_min,
        "distinct_matched_articles_min": len(matched_articles) >= args.article_min,
        "verified_match_rate_min": match_rate >= args.match_rate_min,
    }
    passed = all(checks.values())
    artifact = {
        "schema_version": "kosis-v60-real-article-development-gate-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_role": "DEVELOPMENT_E2E_NOT_BLIND",
        "ready_file": str(args.ready),
        "ready_file_sha256": sha256(args.ready),
        "decisions_file": str(args.decisions),
        "decisions_file_sha256": sha256(args.decisions),
        "ready_measurements": ready_count,
        "decision_rows": len(decisions),
        "decision_status_counts": dict(sorted(counts.items())),
        "verified_matches": match_count,
        "verified_match_rate": match_rate,
        "matched_distinct_articles": len(matched_articles),
        "matched_article_ids": matched_articles,
        "missing_decisions": missing,
        "unexpected_decisions": unexpected,
        "thresholds": {
            "expected_ready": args.expected_ready,
            "verified_match_min": args.match_min,
            "distinct_matched_articles_min": args.article_min,
            "verified_match_rate_min": args.match_rate_min,
        },
        "checks": checks,
        "promotion_gate": "PASS" if passed else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
