#!/usr/bin/env python3
"""Gate a development-supervised exact mapping cache for candidate freezing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-manifest", required=True, type=Path)
    parser.add_argument("--memory", required=True, type=Path)
    parser.add_argument("--application", required=True, type=Path)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = load(args.dev_manifest)
    memory = load(args.memory)
    application = load(args.application)
    metrics = load(args.metrics)
    baseline = load(args.baseline)
    candidate_item = metrics["metrics_all_eligible_gold"]["item"]["accuracy_at_5"]
    candidate_coordinate = metrics["metrics_all_eligible_gold"]["coordinate"]["accuracy_at_5"]
    baseline_item = baseline["metrics_all_eligible_gold"]["item"]["accuracy_at_5"]
    baseline_coordinate = baseline["metrics_all_eligible_gold"]["coordinate"]["accuracy_at_5"]
    checks = {
        "development_only": manifest["development_only"] is True,
        "blind_labels_used_zero": (
            int(manifest["blind_label_rows_used_for_tuning"]) == 0
            and int(memory["blind_labels_used"]) == 0
            and int(application["blind_labels_used"]) == 0
        ),
        "historical_table_overlap_zero": int(manifest["historical_table_overlap"]) == 0,
        "claims_exact_600": int(metrics["eligible_gold_claims"]) == 600,
        "missing_predictions_zero": int(metrics["missing_prediction_packets"]) == 0,
        "memory_role_explicit": memory["dataset_role"] == "DEVELOPMENT_SUPERVISED_CACHE",
        "memory_entries_at_least_500": int(memory["entry_count"]) >= 500,
        "item_top5_at_least_075": candidate_item >= 0.75,
        "coordinate_top5_at_least_070": candidate_coordinate >= 0.70,
        "item_improves_baseline": candidate_item > baseline_item,
        "coordinate_improves_baseline": candidate_coordinate > baseline_coordinate,
    }
    result = {
        "schema_version": "kosis-v64-mapping-memory-promotion-gate-v1",
        "dataset_role": "DEVELOPMENT_ONLY_NOT_BLIND",
        "evaluation_mode": "SUPERVISED_EXACT_MAPPING_CACHE_RESUBSTITUTION",
        "promotion_gate": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "expected_claims": 600,
        "candidate": {
            "item_accuracy_at_5": candidate_item,
            "coordinate_accuracy_at_5": candidate_coordinate,
            "memory_match_rate": application["memory_match_rate"],
            "memory_entries": memory["entry_count"],
        },
        "baseline": {
            "item_accuracy_at_5": baseline_item,
            "coordinate_accuracy_at_5": baseline_coordinate,
        },
        "delta": {
            "item_accuracy_at_5": candidate_item - baseline_item,
            "coordinate_accuracy_at_5": candidate_coordinate - baseline_coordinate,
        },
        "disclosure": (
            "The cache was built and evaluated on the same development600 rows. "
            "These are development/resubstitution metrics, not blind generalization metrics."
        ),
        "blind_labels_used": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["promotion_gate"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
