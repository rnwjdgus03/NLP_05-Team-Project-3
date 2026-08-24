#!/usr/bin/env python3
"""Assess whether a locked real-URL E2E run is ready for PoC promotion."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-urls", type=int, default=30)
    parser.add_argument("--min-fetch-rate", type=float, default=0.90)
    parser.add_argument("--min-job-rate", type=float, default=0.95)
    parser.add_argument("--min-evidence-rate", type=float, default=0.10)
    parser.add_argument("--min-evidence-articles", type=int, default=5)
    parser.add_argument("--max-p95-run-seconds", type=float, default=600.0)
    args = parser.parse_args()

    summary = load_json(args.summary)
    audit = load_json(args.audit)
    with args.details.open(encoding="utf-8-sig", newline="") as handle:
        details = list(csv.DictReader(handle))

    locked = int(summary.get("locked_urls", 0))
    fetch_rate = float(summary.get("article_fetch_success_rate", 0.0))
    job_rate = float(summary.get("job_success_rate_given_fetch", 0.0))
    evidence_rate = float(summary.get("selected_evidence_rate", 0.0))
    evidence_articles = sum(int(row.get("selected_evidence") or 0) > 0 for row in details)
    p95_run = float((summary.get("run_latency_seconds") or {}).get("p95") or 0.0)
    engine_counts = summary.get("engine_counts") or {}
    measurements = int(summary.get("measurements", 0))
    ready_measurements = int((audit.get("counts") or {}).get("ready_measurements", 0))

    checks = [
        ("locked_url_count", locked >= args.min_urls, locked, f">= {args.min_urls}"),
        ("article_fetch_success_rate", fetch_rate >= args.min_fetch_rate, fetch_rate, f">= {args.min_fetch_rate}"),
        ("job_success_rate_given_fetch", job_rate >= args.min_job_rate, job_rate, f">= {args.min_job_rate}"),
        ("selected_evidence_rate", evidence_rate >= args.min_evidence_rate, evidence_rate, f">= {args.min_evidence_rate}"),
        ("articles_with_selected_evidence", evidence_articles >= args.min_evidence_articles, evidence_articles, f">= {args.min_evidence_articles}"),
        ("run_latency_p95_seconds", 0 < p95_run <= args.max_p95_run_seconds, p95_run, f"0 < value <= {args.max_p95_run_seconds}"),
        ("single_frozen_engine", len(engine_counts) == 1, len(engine_counts), "== 1"),
        ("measurements_extracted", measurements > 0, measurements, "> 0"),
        ("kosis_ready_measurements", ready_measurements > 0, ready_measurements, "> 0"),
    ]
    failed = [name for name, passed, *_ in checks if not passed]
    status = "PASS" if not failed else "FAIL"
    result = {
        "schema_version": "kosis-real-url-service-readiness-v1",
        "status": status,
        "checks": [
            {"name": name, "passed": passed, "actual": actual, "expected": expected}
            for name, passed, actual, expected in checks
        ],
        "failed_checks": failed,
        "promotion_allowed": status == "PASS",
        "note": (
            "모든 기준을 충족했습니다. 동결·승격 전 표본별 근거 내용을 최종 확인하세요."
            if status == "PASS"
            else "현재 후보는 서비스 승격 금지입니다. 이 잠금셋에 맞춰 튜닝하지 말고 별도 개발셋에서 실패 원인을 개선하세요."
        ),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if status == "PASS" else 2)


if __name__ == "__main__":
    main()
