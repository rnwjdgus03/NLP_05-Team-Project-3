#!/usr/bin/env python3
"""Lock a fresh Chosun URL50 only after the new blind100 gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


CATEGORIES = (
    "employment_population",
    "industry",
    "prices_income",
    "trade_goods",
    "ratio_other",
)
PER_CATEGORY = 10
EXPECTED_FREEZE_ID = "v64_candidate_20260824_r1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_url(value: object) -> str:
    return str(value or "").strip().rstrip("/")


def urls_in_json(path: Path) -> set[str]:
    result: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            url = normalized_url(value.get("url"))
            if url:
                result.add(url)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(json.loads(path.read_text(encoding="utf-8")))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-pool", type=Path, required=True)
    parser.add_argument("--public-preflight", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--blind-gate", type=Path, required=True)
    parser.add_argument(
        "--exclude-lock", type=Path, action="append", default=[],
        help="Prior URL lock/partition JSON. May be supplied repeatedly.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)

    freeze = json.loads(args.freeze_manifest.read_text(encoding="utf-8"))
    blind_gate = json.loads(args.blind_gate.read_text(encoding="utf-8"))
    if freeze.get("freeze_id") != EXPECTED_FREEZE_ID:
        raise RuntimeError("unexpected frozen candidate")
    if freeze.get("status") != "FROZEN_CANDIDATE_PENDING_NEW_BLIND100":
        raise RuntimeError("candidate is not an immutable pre-blind freeze")
    if blind_gate.get("promotion_gate") != "PASS":
        raise RuntimeError("new blind100 did not pass")
    if blind_gate.get("candidate_freeze_id") != freeze.get("freeze_id"):
        raise RuntimeError("blind100 was not evaluated with this freeze")
    expected_tree = freeze["components"]["engine"]["tree_sha256"]
    if blind_gate.get("candidate_engine_tree_sha256") != expected_tree:
        raise RuntimeError("blind100 engine hash mismatch")

    pool = json.loads(args.candidate_pool.read_text(encoding="utf-8"))["urls"]
    preflight_rows = json.loads(
        args.public_preflight.read_text(encoding="utf-8")
    )["results"]
    preflight = {
        normalized_url(row.get("url")): row for row in preflight_rows
    }
    excluded: set[str] = set()
    for path in args.exclude_lock:
        excluded.update(urls_in_json(path))

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in pool:
        url = normalized_url(row.get("url"))
        category = str(row.get("category") or "")
        check = preflight.get(url, {})
        eligible = check.get("eligibility") == "ELIGIBLE" or (
            check.get("status") == "SUCCEEDED"
            and int(check.get("extracted_claims") or 0) > 0
        )
        if category in CATEGORIES and url and eligible:
            grouped[category].append(dict(row))

    selected: list[dict[str, object]] = []
    for category in CATEGORIES:
        ranked = sorted(
            grouped.get(category, []),
            key=lambda row: (
                hashlib.sha256(normalized_url(row["url"]).encode()).hexdigest(),
                normalized_url(row["url"]),
            ),
        )
        available = [
            (rank, row)
            for rank, row in enumerate(ranked, 1)
            if normalized_url(row["url"]) not in excluded
        ]
        if len(available) < PER_CATEGORY:
            raise RuntimeError(
                f"insufficient fresh URLs for {category}: "
                f"{len(available)} < {PER_CATEGORY}"
            )
        for rank, row in available[:PER_CATEGORY]:
            selected.append(
                {
                    "category": category,
                    "url": row["url"],
                    "hash_rank_within_category": rank,
                }
            )

    selected.sort(key=lambda row: (str(row["category"]), str(row["url"])))
    for index, row in enumerate(selected, 1):
        row["index"] = index
    selected_urls = {normalized_url(row["url"]) for row in selected}
    if len(selected) != 50 or len(selected_urls) != 50:
        raise RuntimeError("fresh service lock must contain 50 unique URLs")
    if selected_urls & excluded:
        raise RuntimeError("fresh service lock overlaps a prior URL partition")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    lock_path = args.output_dir / "locked_urls50.json"
    manifest_path = args.output_dir / "lock_manifest.json"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": "chosun-v66-final-service-url50-lock-v1",
                "status": "LOCKED_AFTER_BLIND_PASS_BEFORE_SERVICE_RUN",
                "engine_outputs_inspected": False,
                "candidate_freeze_id": freeze["freeze_id"],
                "candidate_engine_tree_sha256": expected_tree,
                "urls": selected,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "chosun-v66-final-service-url50-manifest-v1",
        "status": "SEALED_BEFORE_FINAL_SERVICE_RUN",
        "locked_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_freeze_id": freeze["freeze_id"],
        "candidate_engine_tree_sha256": expected_tree,
        "new_blind100_gate": "PASS",
        "blind_gate_sha256": digest(args.blind_gate),
        "freeze_manifest_sha256": digest(args.freeze_manifest),
        "selection_algorithm": (
            "10 per category by ascending sha256(url), after excluding every "
            "supplied prior URL lock"
        ),
        "selected_count": 50,
        "selected_category_counts": dict(
            Counter(str(row["category"]) for row in selected)
        ),
        "excluded_url_count": len(excluded),
        "prior_partition_overlap": 0,
        "source_sha256": {
            "candidate_pool": digest(args.candidate_pool),
            "public_preflight": digest(args.public_preflight),
            "exclude_locks": {
                str(path): digest(path) for path in args.exclude_lock
            },
        },
        "artifact_sha256": {"locked_urls50.json": digest(lock_path)},
        "post_run_policy": (
            "Use for final service QA only; do not tune retrieval or mapping "
            "rules from per-URL outcomes."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for path in (lock_path, manifest_path):
        os.chmod(path, 0o444)
    os.chmod(args.output_dir, 0o555)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
