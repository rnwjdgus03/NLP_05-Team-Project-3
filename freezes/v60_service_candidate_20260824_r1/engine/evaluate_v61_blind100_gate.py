#!/usr/bin/env python3
"""Evaluate the preregistered v61 blind100 promotion gate without tuning."""

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
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--blind-manifest", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    blind = json.loads(args.blind_manifest.read_text(encoding="utf-8"))
    freeze = json.loads(args.freeze_manifest.read_text(encoding="utf-8"))

    thresholds = blind["preregistered_thresholds"]
    item_top5 = float(summary["metrics"]["item"]["accuracy_at_5"])
    coordinate_top5 = float(
        summary["metrics"]["coordinate"]["accuracy_at_5"]
    )
    eligible_overlap = int(summary.get("eligible_overlap", -1))
    missing = int(summary.get("missing_prediction_packets", -1))
    prediction_claims = int(summary.get("prediction_claims", -1))
    frozen_engine_sha = freeze["components"]["engine"]["tree_sha256"]

    checks = {
        "blind_role": bool(blind.get("blind"))
        and bool(blind.get("evaluation_only"))
        and bool(blind.get("no_tuning_after_unblind")),
        "candidate_frozen_before_gold": bool(
            blind.get("candidate_frozen_before_gold")
        ),
        "candidate_freeze_identity": (
            blind.get("candidate_freeze_id") == freeze.get("freeze_id")
        ),
        "candidate_code_identity": (
            blind.get("candidate_code_tree_sha256") == frozen_engine_sha
        ),
        "eligible_overlap_exact": (
            eligible_overlap == int(thresholds["eligible_overlap_exact"])
        ),
        "prediction_claims_exact": (
            prediction_claims == int(thresholds["eligible_overlap_exact"])
        ),
        "missing_prediction_packets_max": (
            missing <= int(thresholds["missing_prediction_packets_max"])
        ),
        "item_top5_threshold": (
            item_top5 >= float(thresholds["item_accuracy_at_5_min"])
        ),
        "coordinate_top5_threshold": (
            coordinate_top5
            >= float(thresholds["coordinate_accuracy_at_5_min"])
        ),
    }
    passed = all(checks.values())
    artifact = {
        "schema_version": "kosis-v61-blind100-gate-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_role": "BLIND_EVALUATION_ONLY_NO_TUNING",
        "candidate_freeze_id": freeze["freeze_id"],
        "candidate_engine_tree_sha256": frozen_engine_sha,
        "blind_manifest_sha256": sha256(args.blind_manifest),
        "freeze_manifest_sha256": sha256(args.freeze_manifest),
        "evaluation_summary_sha256": sha256(args.summary),
        "eligible_overlap": eligible_overlap,
        "prediction_claims": prediction_claims,
        "missing_prediction_packets": missing,
        "metrics": {
            "item_accuracy_at_5": item_top5,
            "coordinate_accuracy_at_5": coordinate_top5,
        },
        "preregistered_thresholds": thresholds,
        "checks": checks,
        "promotion_gate": "PASS" if passed else "FAIL",
        "post_evaluation_policy": (
            "No candidate rule, weight, prompt, or retrieval change may be "
            "derived from this blind100 result."
        ),
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
