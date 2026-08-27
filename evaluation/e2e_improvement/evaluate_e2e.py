#!/usr/bin/env python3
"""Leakage-aware end-to-end evaluation for KOSIS mapping outputs.

The evaluator joins the complete gold universe to predictions.  Missing
predictions are failures, not silently dropped rows.  It intentionally uses
only Python's standard library so the metric calculation is reproducible in a
minimal environment.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


TRUE_VALUES = {"1", "true", "t", "y", "yes", "ready", "match", "일치"}
FALSE_VALUES = {"0", "false", "f", "n", "no", "reject", "rejected", "no_match"}
GOLD_VERDICTS = {"MATCH", "MISMATCH", "UNVERIFIABLE", "일치", "불일치", "판단불가"}


def norm(value: object) -> str:
    return str(value or "").strip()


def truth(value: object) -> bool | None:
    text = norm(value).lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def unique_index(rows: list[dict[str, str]], id_col: str, source: str) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    duplicates: list[str] = []
    for row in rows:
        row_id = norm(row.get(id_col))
        if not row_id:
            raise ValueError(f"{source}: empty {id_col}")
        if row_id in indexed:
            duplicates.append(row_id)
        indexed[row_id] = row
    if duplicates:
        sample = ", ".join(sorted(set(duplicates))[:10])
        raise ValueError(f"{source}: duplicate {id_col}: {sample}")
    return indexed


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def exact(gold: dict[str, str], pred: dict[str, str] | None, gold_col: str, pred_col: str) -> bool:
    return bool(pred) and norm(gold.get(gold_col)) != "" and norm(gold.get(gold_col)) == norm(pred.get(pred_col))


def metric(successes: int, total: int) -> dict[str, object]:
    return {"correct": successes, "total": total, "score": safe_ratio(successes, total), "ci95": wilson(successes, total)}


def evaluate(args: argparse.Namespace) -> dict[str, object]:
    gold_rows = read_csv(Path(args.gold))
    pred_rows = read_csv(Path(args.predictions))
    gold_by_id = unique_index(gold_rows, args.id_col, "gold")
    pred_by_id = unique_index(pred_rows, args.id_col, "predictions")
    missing_ids = sorted(set(gold_by_id) - set(pred_by_id))
    extra_ids = sorted(set(pred_by_id) - set(gold_by_id))
    if missing_ids or extra_ids:
        raise ValueError(
            "prediction ID conservation failed: "
            f"missing={len(missing_ids)} extra={len(extra_ids)}; "
            "emit an explicit NO_MATCH/ERROR row for every gold ID"
        )
    counts = Counter()
    labeled = 0
    missing_predictions = 0
    stage_totals = Counter()
    stage_correct = Counter()

    for gold in gold_by_id.values():
        row_id = norm(gold.get(args.id_col))
        prediction = pred_by_id.get(row_id)
        if prediction is None:  # guarded by the conservation assertion above
            missing_predictions += 1

        gold_ready = truth(gold.get(args.gold_verifiable_col))
        if gold_ready is not None:
            labeled += 1
            predicted_ready = truth(prediction.get(args.pred_ready_col)) if prediction else False
            predicted_ready = bool(predicted_ready)
            if gold_ready and predicted_ready:
                counts["TP"] += 1
            elif not gold_ready and predicted_ready:
                counts["FP"] += 1
            elif gold_ready and not predicted_ready:
                counts["FN"] += 1
            else:
                counts["TN"] += 1

        # Conditional metrics are only defined where the prerequisite gold
        # field exists. Missing predictions stay in the denominator.
        if norm(gold.get(args.gold_tbl_col)):
            stage_totals["tbl"] += 1
            if exact(gold, prediction, args.gold_tbl_col, args.pred_tbl_col):
                stage_correct["tbl"] += 1
        if norm(gold.get(args.gold_item_col)):
            stage_totals["item"] += 1
            if exact(gold, prediction, args.gold_item_col, args.pred_item_col):
                stage_correct["item"] += 1
        if norm(gold.get(args.gold_obj_col)):
            stage_totals["obj"] += 1
            if exact(gold, prediction, args.gold_obj_col, args.pred_obj_col):
                stage_correct["obj"] += 1
        if norm(gold.get(args.gold_verdict_col)) in GOLD_VERDICTS:
            stage_totals["verdict"] += 1
            if exact(gold, prediction, args.gold_verdict_col, args.pred_verdict_col):
                stage_correct["verdict"] += 1

    tp, fp, fn, tn = (counts[key] for key in ("TP", "FP", "FN", "TN"))
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    accuracy = safe_ratio(tp + tn, labeled)

    return {
        "dataset": {"gold_rows": len(gold_rows), "prediction_rows": len(pred_rows), "duplicate_prediction_ids": 0, "missing_predictions": missing_predictions},
        "ready_gate": {
            "labeled_rows": labeled,
            "confusion": {key: counts[key] for key in ("TP", "FP", "FN", "TN")},
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": accuracy,
            "false_negative_rate": safe_ratio(fn, tp + fn),
            "false_positive_rate": safe_ratio(fp, fp + tn),
            "recall_ci95": wilson(tp, tp + fn),
            "accuracy_ci95": wilson(tp + tn, labeled),
        },
        "conditional_exact_match": {
            stage: metric(stage_correct[stage], stage_totals[stage])
            for stage in ("tbl", "item", "obj", "verdict")
        },
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--gold", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--output")
    p.add_argument("--id-col", default="claim_measurement_id")
    p.add_argument("--gold-verifiable-col", default="gold_verifiable")
    p.add_argument("--pred-ready-col", default="mapping_status")
    p.add_argument("--gold-tbl-col", default="gold_tbl_id")
    p.add_argument("--pred-tbl-col", default="tbl_id")
    p.add_argument("--gold-item-col", default="gold_itm_id")
    p.add_argument("--pred-item-col", default="selected_itm_id")
    p.add_argument("--gold-obj-col", default="gold_obj_l1")
    p.add_argument("--pred-obj-col", default="selected_obj_l1")
    p.add_argument("--gold-verdict-col", default="gold_verdict")
    p.add_argument("--pred-verdict-col", default="verdict")
    return p


def main() -> None:
    args = parser().parse_args()
    result = evaluate(args)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
