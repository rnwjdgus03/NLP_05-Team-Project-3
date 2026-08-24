#!/usr/bin/env python3
"""Evaluate promotion readiness on the table-disjoint development set.

This gate only reads already-produced artifacts.  It does not touch blind
labels or alter predictions.  Promotion requires both the declared retrieval
targets and evidence that the development set is disjoint from historical
gold tables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-summary", type=Path, required=True)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-claims", type=int, default=600)
    parser.add_argument("--item-top5-min", type=float, default=0.75)
    parser.add_argument("--coordinate-top5-min", type=float, default=0.70)
    return parser.parse_args()


def metric(summary: dict, component: str) -> float:
    return float(summary["metrics"][component]["accuracy_at_5"])


def main() -> int:
    args = parse_args()
    candidate = read_json(args.candidate_summary)
    baseline = read_json(args.baseline_summary)
    manifest = read_json(args.development_manifest)

    candidate_item = metric(candidate, "item")
    candidate_coordinate = metric(candidate, "coordinate")
    baseline_item = metric(baseline, "item")
    baseline_coordinate = metric(baseline, "coordinate")
    overlap = int(candidate.get("eligible_overlap", -1))
    missing = int(candidate.get("missing_prediction_packets", 0))

    checks = {
        "development_only": manifest.get("development_only") is True,
        "not_blind_evidence": manifest.get("not_blind_evidence") is True,
        "blind_labels_unused": int(
            manifest.get("blind_label_rows_used_for_tuning", -1)
        ) == 0,
        "historical_table_overlap_zero": int(
            manifest.get("historical_table_overlap", -1)
        ) == 0,
        "manifest_rows_exact": int(manifest.get("rows", -1))
        == args.expected_claims,
        "eligible_overlap_exact": overlap == args.expected_claims,
        "missing_prediction_packets_zero": missing == 0,
        "item_top5_threshold": candidate_item >= args.item_top5_min,
        "coordinate_top5_threshold": (
            candidate_coordinate >= args.coordinate_top5_min
        ),
        "item_no_regression": candidate_item >= baseline_item,
        "coordinate_no_regression": candidate_coordinate
        >= baseline_coordinate,
    }
    passed = all(checks.values())
    artifact = {
        "schema_version": "kosis-table-disjoint-dev600-promotion-gate-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_role": "DEVELOPMENT_ONLY_NOT_BLIND",
        "inputs": {
            "candidate_summary": str(args.candidate_summary),
            "candidate_summary_sha256": file_sha256(args.candidate_summary),
            "baseline_summary": str(args.baseline_summary),
            "baseline_summary_sha256": file_sha256(args.baseline_summary),
            "development_manifest": str(args.development_manifest),
            "development_manifest_sha256": file_sha256(
                args.development_manifest
            ),
        },
        "expected_claims": args.expected_claims,
        "thresholds": {
            "item_accuracy_at_5_min": args.item_top5_min,
            "coordinate_accuracy_at_5_min": args.coordinate_top5_min,
        },
        "candidate": {
            "eligible_overlap": overlap,
            "missing_prediction_packets": missing,
            "item_accuracy_at_5": candidate_item,
            "coordinate_accuracy_at_5": candidate_coordinate,
        },
        "baseline": {
            "item_accuracy_at_5": baseline_item,
            "coordinate_accuracy_at_5": baseline_coordinate,
        },
        "delta_vs_baseline": {
            "item_accuracy_at_5": candidate_item - baseline_item,
            "coordinate_accuracy_at_5": candidate_coordinate
            - baseline_coordinate,
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
