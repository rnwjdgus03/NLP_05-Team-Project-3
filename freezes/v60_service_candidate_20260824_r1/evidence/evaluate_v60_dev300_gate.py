#!/usr/bin/env python3
"""Build the immutable v60 development-regression gate artifact.

This script does not tune or rewrite predictions.  It consumes the evaluator
summary produced from the separate 300-claim development set and records the
predeclared promotion thresholds together with an informational v58 delta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-summary", type=Path, required=True)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-claims", type=int, default=300)
    parser.add_argument("--item-top5-min", type=float, default=0.75)
    parser.add_argument("--coordinate-top5-min", type=float, default=0.70)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = json.loads(args.candidate_summary.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_summary.read_text(encoding="utf-8"))

    candidate_item = float(candidate["metrics"]["item"]["accuracy_at_5"])
    candidate_coordinate = float(
        candidate["metrics"]["coordinate"]["accuracy_at_5"]
    )
    baseline_item = float(baseline["metrics"]["item"]["accuracy_at_5"])
    baseline_coordinate = float(
        baseline["metrics"]["coordinate"]["accuracy_at_5"]
    )
    overlap = int(candidate.get("eligible_overlap", -1))
    missing = int(candidate.get("missing_prediction_packets", -1))

    checks = {
        "eligible_overlap_exact": overlap == args.expected_claims,
        "missing_prediction_packets_zero": missing == 0,
        "item_top5_threshold": candidate_item >= args.item_top5_min,
        "coordinate_top5_threshold": (
            candidate_coordinate >= args.coordinate_top5_min
        ),
    }
    passed = all(checks.values())
    artifact = {
        "schema_version": "kosis-v60-dev300-regression-gate-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_role": "DEVELOPMENT_ONLY_NOT_BLIND",
        "candidate_summary": str(args.candidate_summary),
        "candidate_summary_sha256": sha256(args.candidate_summary),
        "baseline_summary": str(args.baseline_summary),
        "baseline_summary_sha256": sha256(args.baseline_summary),
        "expected_claims": args.expected_claims,
        "eligible_overlap": overlap,
        "missing_prediction_packets": missing,
        "thresholds": {
            "item_accuracy_at_5_min": args.item_top5_min,
            "coordinate_accuracy_at_5_min": args.coordinate_top5_min,
        },
        "candidate": {
            "item_accuracy_at_5": candidate_item,
            "coordinate_accuracy_at_5": candidate_coordinate,
        },
        "baseline_v58": {
            "item_accuracy_at_5": baseline_item,
            "coordinate_accuracy_at_5": baseline_coordinate,
        },
        "delta_vs_v58": {
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
