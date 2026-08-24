#!/usr/bin/env python3
"""Submit a locked URL set through the public BFF and audit E2E reliability."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def request_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 75) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=body, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def iso_seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def error_detail(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        try:
            payload = json.loads(error.read().decode("utf-8", errors="replace"))
            return f"HTTP {error.code}: {payload.get('detail', payload)}"
        except Exception:
            return f"HTTP {error.code}: {error.reason}"
    return f"{type(error).__name__}: {error}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:3101")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--allow-small-dev", action="store_true",
                        help="allow fewer than 30 URLs for a clearly labeled development smoke only")
    args = parser.parse_args()
    locked = json.loads(args.input.read_text(encoding="utf-8"))
    urls = list(locked["urls"])
    valid_size = 1 <= len(urls) <= 50 if args.allow_small_dev else 30 <= len(urls) <= 50
    if not valid_size or len({row["url"] for row in urls}) != len(urls):
        raise ValueError("locked URL set must contain 30-50 unique URLs")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / "qa_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "schema_version": "kosis-real-url-e2e-state-v1", "base_url": args.base_url,
        "started_at": datetime.now().astimezone().isoformat(), "records": {},
    }
    records = state["records"]

    # The public route performs SSRF-safe fetch, HTML extraction, claim creation,
    # and backend job submission. Persist after every URL for restart safety.
    for index, row in enumerate(urls, 1):
        key = str(index)
        if key in records:
            continue
        started = time.monotonic()
        record = {**row, "index": index, "submitted_at": datetime.now().astimezone().isoformat()}
        try:
            accepted = request_json(
                f"{args.base_url}/api/article-verifications", {"url": row["url"]}, timeout=75,
            )
            record.update({
                "article_fetch_status": "SUCCEEDED", "job_id": accepted["job_id"],
                "article": accepted.get("article") or {},
                "fetch_submit_seconds": time.monotonic() - started,
                "job_status": "QUEUED",
            })
        except Exception as error:
            record.update({
                "article_fetch_status": "FAILED", "error": error_detail(error),
                "fetch_submit_seconds": time.monotonic() - started,
                "job_status": "NOT_SUBMITTED",
            })
        records[key] = record
        atomic_json(state_path, state)
        print(f"[submit] {index}/{len(urls)} fetch={record['article_fetch_status']} job={record.get('job_id','-')}", flush=True)

    pending = {key for key, row in records.items() if row.get("job_id") and row.get("job_status") not in {"SUCCEEDED", "FAILED"}}
    results_dir = args.output_dir / "results"
    results_dir.mkdir(exist_ok=True)
    while pending:
        for key in list(pending):
            record = records[key]
            try:
                status = request_json(f"{args.base_url}/api/verifications/{record['job_id']}")
            except Exception as error:
                record["last_poll_error"] = error_detail(error)
                continue
            record.update({
                "job_status": status["status"], "progress_step": status.get("progress_step"),
                "created_at": status.get("created_at"), "started_at": status.get("started_at"),
                "completed_at": status.get("completed_at"), "job_error": status.get("error"),
            })
            if status["status"] == "SUCCEEDED":
                result = request_json(f"{args.base_url}/api/verifications/{record['job_id']}/result")
                result_path = results_dir / f"{record['job_id']}.json"
                atomic_json(result_path, result)
                record.update({
                    "result_path": str(result_path), "engine": result.get("engine"),
                    "measurement_count": result.get("summary", {}).get("measurement_count", 0),
                    "ready_measurement_count": result.get("summary", {}).get("ready_measurement_count", 0),
                    "extracted_measurement_count": result.get("summary", {}).get("extracted_measurement_count", 0),
                    "verdict_counts": result.get("summary", {}).get("verdict_counts", {}),
                    "selected_evidence_count": sum(bool(claim.get("selected_evidence")) for claim in result.get("claims", [])),
                })
                pending.remove(key)
            elif status["status"] == "FAILED":
                pending.remove(key)
        atomic_json(state_path, state)
        counts = Counter(records[key].get("job_status") for key in records)
        print(f"[poll] pending={len(pending)} states={dict(counts)}", flush=True)
        if pending:
            time.sleep(args.poll_seconds)

    fetch_success = [row for row in records.values() if row.get("article_fetch_status") == "SUCCEEDED"]
    job_success = [row for row in fetch_success if row.get("job_status") == "SUCCEEDED"]
    fetch_latencies = [float(row["fetch_submit_seconds"]) for row in records.values()]
    queue_latencies = [value for row in job_success if (value := iso_seconds(row.get("created_at"), row.get("started_at"))) is not None]
    run_latencies = [value for row in job_success if (value := iso_seconds(row.get("started_at"), row.get("completed_at"))) is not None]
    verdicts = Counter()
    engines = Counter()
    measurement_count = evidence_count = extracted_measurement_count = 0
    for row in job_success:
        verdicts.update(row.get("verdict_counts") or {})
        measurement_count += int(row.get("measurement_count") or 0)
        extracted_measurement_count += int(row.get("extracted_measurement_count") or 0)
        evidence_count += int(row.get("selected_evidence_count") or 0)
        engine = row.get("engine") or {}
        engines[f"{engine.get('freeze_id')}|{engine.get('code_tree_sha256')}"] += 1
    summary = {
        "schema_version": "kosis-real-url-e2e-summary-v1",
        "locked_urls": len(urls),
        "article_fetch_succeeded": len(fetch_success),
        "article_fetch_failed": len(urls) - len(fetch_success),
        "article_fetch_success_rate": len(fetch_success) / len(urls),
        "jobs_succeeded": len(job_success),
        "jobs_failed": len(fetch_success) - len(job_success),
        "job_success_rate_given_fetch": len(job_success) / len(fetch_success) if fetch_success else 0,
        "measurements": measurement_count,
        "ready_measurements": measurement_count,
        "extracted_measurements": extracted_measurement_count,
        "verdict_counts": dict(verdicts),
        "selected_evidence_count": evidence_count,
        "selected_evidence_rate": evidence_count / measurement_count if measurement_count else 0,
        "fetch_submit_latency_seconds": {
            "p50": percentile(fetch_latencies, 0.50), "p95": percentile(fetch_latencies, 0.95),
            "max": max(fetch_latencies) if fetch_latencies else None,
        },
        "queue_latency_seconds": {"p50": percentile(queue_latencies, 0.50), "p95": percentile(queue_latencies, 0.95)},
        "run_latency_seconds": {"p50": percentile(run_latencies, 0.50), "p95": percentile(run_latencies, 0.95), "max": max(run_latencies) if run_latencies else None},
        "engine_counts": dict(engines),
        "fetch_error_counts": dict(Counter(row.get("error") for row in records.values() if row.get("article_fetch_status") == "FAILED")),
        "job_error_counts": dict(Counter(row.get("job_error") for row in fetch_success if row.get("job_status") == "FAILED")),
        "completed_at": datetime.now().astimezone().isoformat(),
    }
    atomic_json(args.output_dir / "qa_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
