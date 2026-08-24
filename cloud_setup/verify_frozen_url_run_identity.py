#!/usr/bin/env python3
"""Verify a locked URL run used exactly the candidate bound by its lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--lock-manifest", type=Path, required=True)
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = read(args.lock)
    lock_manifest = read(args.lock_manifest)
    engine = read(args.engine_manifest)
    state = read(args.state)
    summary = read(args.summary)
    expected_id = lock["candidate_freeze_id"]
    expected_sha = lock["candidate_engine_tree_sha256"]
    expected_key = f"{expected_id}|{expected_sha}"
    expected_urls = len(lock["urls"])
    engine_counts = summary.get("engine_counts") or {}
    checks = {
        "lock_hash_matches_manifest": (
            digest(args.lock)
            == lock_manifest["artifact_sha256"]["locked_urls50.json"]
        ),
        "engine_freeze_id": engine.get("freeze_id") == expected_id,
        "engine_code_sha256": engine.get("code_tree_sha256") == expected_sha,
        "locked_url_count": int(summary.get("locked_urls", 0))
        == expected_urls,
        "state_record_count": len(state.get("records") or {}) == expected_urls,
        "single_expected_engine": set(engine_counts) == {expected_key},
        "engine_count_matches_successes": int(
            engine_counts.get(expected_key, -1)
        ) == int(summary.get("jobs_succeeded", -2)),
    }
    passed = all(checks.values())
    result = {
        "schema_version": "kosis-frozen-url-run-identity-v1",
        "status": "PASS" if passed else "FAIL",
        "candidate_freeze_id": expected_id,
        "candidate_engine_tree_sha256": expected_sha,
        "checks": checks,
        "input_sha256": {
            "lock": digest(args.lock),
            "lock_manifest": digest(args.lock_manifest),
            "engine_manifest": digest(args.engine_manifest),
            "state": digest(args.state),
            "summary": digest(args.summary),
        },
    }
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
