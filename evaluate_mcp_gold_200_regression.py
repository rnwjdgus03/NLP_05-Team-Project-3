"""Evaluate pipeline predictions against the MCP full gold 200 set.

This is a development regression evaluator: it never calls KOSIS and never
rewrites the gold labels.  It compares a prediction CSV to the frozen
``data/gold/mcp_full_gold_200.csv`` labels, then writes summary, confusion, and
failure artifacts that can be checked after pipeline changes.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parent
DEFAULT_GOLD = ROOT / "data" / "gold" / "mcp_full_gold_200.csv"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "regression" / "mcp_full_gold_200"
LABELS = ("SUPPORTS", "REFUTES")
INPUT_FIELDS = (
    "gold_id",
    "claim_id",
    "article_id",
    "title",
    "date",
    "url",
    "claim_text",
    "claim_type",
    "claim_value",
    "claim_unit",
)
PREDICTION_LABEL_COLUMNS = (
    "predicted_label",
    "prediction_label",
    "auto_label",
    "label",
    "gold_label",
    "verdict",
    "auto_verdict",
    "refined_verdict",
    "kosis_verdict",
    "verdict_code",
)
COORDINATE_FIELDS = {
    "org_id": ("predicted_org_id", "auto_org_id", "kosis_org_id", "org_id", "gold_org_id"),
    "tbl_id": ("predicted_tbl_id", "auto_tbl_id", "kosis_tbl_id", "tbl_id", "gold_tbl_id"),
    "obj_l1": ("predicted_obj_l1", "auto_obj_l1", "kosis_obj_l1", "obj_l1", "gold_obj_l1"),
    "obj_l2": ("predicted_obj_l2", "auto_obj_l2", "kosis_obj_l2", "obj_l2", "gold_obj_l2"),
    "itm_id": ("predicted_itm_id", "auto_itm_id", "kosis_itm_id", "itm_id", "item_id", "gold_itm_id"),
    "prd_se": ("predicted_prd_se", "auto_prd_se", "kosis_prd_se", "prd_se", "gold_prd_se"),
    "period": ("predicted_period", "auto_period", "kosis_period", "period", "target_period", "gold_period"),
}
ACTUAL_VALUE_COLUMNS = (
    "predicted_actual_value",
    "auto_actual_value",
    "kosis_actual_value",
    "actual_value",
    "gold_actual_value",
)


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in {"", "-", "None", "nan", "NaN"} else text


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_label(value: object) -> str:
    text = clean(value)
    upper = text.upper()
    compact = upper.replace(" ", "").replace("_", "")
    if compact in {"SUPPORTS", "SUPPORT", "SUPPORTED", "TRUE", "MATCH", "MATCHES", "CORRECT"}:
        return "SUPPORTS"
    if compact in {"REFUTES", "REFUTE", "REFUTED", "FALSE", "MISMATCH", "MISMATCHES", "INCORRECT"}:
        return "REFUTES"
    if text in {"일치", "맞음", "참", "사실", "지원"}:
        return "SUPPORTS"
    if text in {"불일치", "다름", "거짓", "반박"}:
        return "REFUTES"
    return ""


def choose_value(row: Mapping[str, Any], candidates: Iterable[str]) -> tuple[str, str]:
    for column in candidates:
        value = clean(row.get(column))
        if value:
            return value, column
    return "", ""


def prediction_key(row: Mapping[str, Any]) -> tuple[str, str]:
    for column in ("gold_id", "claim_id"):
        value = clean(row.get(column))
        if value:
            return column, value
    return "", ""


def prediction_maps(rows: list[dict[str, str]]) -> dict[str, dict[str, dict[str, str]]]:
    maps = {"gold_id": {}, "claim_id": {}}
    for row in rows:
        for column in maps:
            key = clean(row.get(column))
            if key and key not in maps[column]:
                maps[column][key] = row
    return maps


def find_prediction(
    gold_row: Mapping[str, Any],
    maps: Mapping[str, Mapping[str, dict[str, str]]],
) -> tuple[dict[str, str] | None, str, str]:
    for column in ("gold_id", "claim_id"):
        key = clean(gold_row.get(column))
        if key and key in maps[column]:
            return maps[column][key], column, key
    return None, "", ""


def decimal_value(value: object) -> Decimal | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 6)


def label_metrics(evaluated: list[dict[str, Any]], *, covered_only: bool) -> list[dict[str, Any]]:
    source = [row for row in evaluated if row["predicted_label"]] if covered_only else evaluated
    metrics: list[dict[str, Any]] = []
    for label in LABELS:
        tp = sum(row["gold_label"] == label and row["predicted_label"] == label for row in source)
        fp = sum(row["gold_label"] != label and row["predicted_label"] == label for row in source)
        fn = sum(row["gold_label"] == label and row["predicted_label"] != label for row in source)
        precision = safe_rate(tp, tp + fp)
        recall = safe_rate(tp, tp + fn)
        metrics.append(
            {
                "label": label,
                "support": sum(row["gold_label"] == label for row in source),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1(precision, recall),
            }
        )
    return metrics


def macro_f1(metrics: list[dict[str, Any]]) -> float | None:
    values = [row["f1"] for row in metrics if row["f1"] is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def coordinate_result(gold: Mapping[str, Any], pred: Mapping[str, Any] | None) -> dict[str, Any]:
    if pred is None:
        return {"coordinate_checked": False, "coordinate_full_exact": ""}
    checked = 0
    correct = 0
    details: dict[str, str] = {}
    for suffix, candidates in COORDINATE_FIELDS.items():
        gold_value = clean(gold.get(f"gold_{suffix}"))
        pred_value, pred_column = choose_value(pred, candidates)
        if not pred_value:
            details[f"{suffix}_correct"] = ""
            continue
        checked += 1
        is_correct = gold_value == pred_value
        correct += int(is_correct)
        details[f"{suffix}_correct"] = "Y" if is_correct else "N"
        details[f"{suffix}_pred_col"] = pred_column
    if checked == 0:
        return {"coordinate_checked": False, "coordinate_full_exact": "", **details}
    return {
        "coordinate_checked": True,
        "coordinate_fields_checked": checked,
        "coordinate_fields_correct": correct,
        "coordinate_full_exact": "Y" if checked == len(COORDINATE_FIELDS) and correct == checked else "N",
        **details,
    }


def actual_value_result(gold: Mapping[str, Any], pred: Mapping[str, Any] | None) -> dict[str, Any]:
    if pred is None:
        return {"actual_value_checked": False, "actual_abs_error": ""}
    pred_value, pred_column = choose_value(pred, ACTUAL_VALUE_COLUMNS)
    expected = decimal_value(gold.get("gold_actual_value"))
    actual = decimal_value(pred_value)
    if expected is None or actual is None:
        return {"actual_value_checked": False, "actual_abs_error": "", "actual_pred_col": pred_column}
    return {
        "actual_value_checked": True,
        "actual_abs_error": str(abs(expected - actual)),
        "actual_pred_col": pred_column,
    }


def evaluate(
    gold_rows: list[dict[str, str]],
    prediction_rows: list[dict[str, str]],
    prediction_label_col: str = "",
) -> dict[str, Any]:
    maps = prediction_maps(prediction_rows)
    evaluated: list[dict[str, Any]] = []
    for gold in gold_rows:
        pred, matched_by, matched_key = find_prediction(gold, maps)
        raw_label = ""
        label_source = ""
        if pred is not None:
            if prediction_label_col:
                raw_label = clean(pred.get(prediction_label_col))
                label_source = prediction_label_col
            else:
                raw_label, label_source = choose_value(pred, PREDICTION_LABEL_COLUMNS)
        predicted_label = normalize_label(raw_label)
        gold_label = normalize_label(gold.get("gold_label"))
        if pred is None:
            error_type = "uncovered"
        elif not predicted_label:
            error_type = "invalid_label"
        elif predicted_label != gold_label:
            error_type = "label_mismatch"
        else:
            error_type = ""
        row = {
            "gold_id": clean(gold.get("gold_id")),
            "claim_id": clean(gold.get("claim_id")),
            "article_id": clean(gold.get("article_id")),
            "title": clean(gold.get("title")),
            "url": clean(gold.get("url")),
            "claim_text": clean(gold.get("claim_text")),
            "claim_type": clean(gold.get("claim_type")),
            "claim_value": clean(gold.get("claim_value")),
            "gold_label": gold_label,
            "predicted_label": predicted_label,
            "raw_prediction_label": raw_label,
            "prediction_label_col": label_source,
            "matched_by": matched_by,
            "matched_key": matched_key,
            "correct": "Y" if predicted_label and predicted_label == gold_label else "N",
            "error_type": error_type,
            "gold_tbl_id": clean(gold.get("gold_tbl_id")),
            "gold_itm_id": clean(gold.get("gold_itm_id")),
            "gold_period": clean(gold.get("gold_period")),
            "gold_actual_value": clean(gold.get("gold_actual_value")),
            "gold_evidence_url": clean(gold.get("gold_evidence_url")),
        }
        row.update(coordinate_result(gold, pred))
        row.update(actual_value_result(gold, pred))
        evaluated.append(row)

    total = len(evaluated)
    covered = sum(bool(row["predicted_label"]) for row in evaluated)
    correct = sum(row["correct"] == "Y" for row in evaluated)
    strict = label_metrics(evaluated, covered_only=False)
    decided = label_metrics(evaluated, covered_only=True)
    confusion = Counter(
        (row["gold_label"] or "<blank>", row["predicted_label"] or "<missing>")
        for row in evaluated
    )
    coordinate_checked = [row for row in evaluated if row.get("coordinate_checked")]
    actual_checked = [row for row in evaluated if row.get("actual_value_checked")]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_rows": total,
        "prediction_rows": len(prediction_rows),
        "matched_predictions": sum(bool(row["matched_by"]) for row in evaluated),
        "covered_labels": covered,
        "uncovered": sum(row["error_type"] == "uncovered" for row in evaluated),
        "invalid_labels": sum(row["error_type"] == "invalid_label" for row in evaluated),
        "correct": correct,
        "strict_accuracy": safe_rate(correct, total),
        "decided_accuracy": safe_rate(correct, covered),
        "strict_macro_f1": macro_f1(strict),
        "decided_macro_f1": macro_f1(decided),
        "gold_label_counts": dict(Counter(row["gold_label"] for row in evaluated)),
        "predicted_label_counts": dict(Counter(row["predicted_label"] or "<missing>" for row in evaluated)),
        "error_counts": dict(Counter(row["error_type"] or "correct" for row in evaluated)),
        "coordinate_checked": len(coordinate_checked),
        "coordinate_full_exact": sum(row.get("coordinate_full_exact") == "Y" for row in coordinate_checked),
        "actual_value_checked": len(actual_checked),
    }
    return {
        "summary": summary,
        "evaluated": evaluated,
        "per_label_strict": strict,
        "per_label_decided": decided,
        "confusion": [
            {"gold_label": gold, "predicted_label": predicted, "count": count}
            for (gold, predicted), count in sorted(confusion.items())
        ],
        "failures": [row for row in evaluated if row["correct"] != "Y"],
    }


def markdown_report(result: Mapping[str, Any], gold_path: Path, predictions_path: Path | None) -> str:
    summary = result["summary"]
    predictions = str(predictions_path) if predictions_path else "<none>"
    lines = [
        "# MCP Full Gold 200 Regression Evaluation",
        "",
        f"- Gold: `{gold_path}`",
        f"- Predictions: `{predictions}`",
        f"- Generated: `{summary['generated_at']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key in (
        "gold_rows",
        "prediction_rows",
        "matched_predictions",
        "covered_labels",
        "uncovered",
        "invalid_labels",
        "correct",
        "strict_accuracy",
        "decided_accuracy",
        "strict_macro_f1",
        "decided_macro_f1",
        "coordinate_checked",
        "coordinate_full_exact",
        "actual_value_checked",
    ):
        value = summary.get(key)
        lines.append(f"| {key} | {value if value is not None else '-'} |")
    lines.extend(["", "## Per Label Strict", "", "| Label | Support | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|"])
    for row in result["per_label_strict"]:
        lines.append(f"| {row['label']} | {row['support']} | {row['precision']} | {row['recall']} | {row['f1']} |")
    lines.extend(["", "## Confusion", "", "| Gold | Predicted | Count |", "|---|---|---:|"])
    for row in result["confusion"]:
        lines.append(f"| {row['gold_label']} | {row['predicted_label']} | {row['count']} |")
    return "\n".join(lines) + "\n"


def write_input_fixture(path: Path, gold_rows: list[dict[str, str]]) -> None:
    rows = [{field: row.get(field, "") for field in INPUT_FIELDS} for row in gold_rows]
    write_csv(path, rows, INPUT_FIELDS)


def enforce_thresholds(args: argparse.Namespace, summary: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    checks = [
        ("strict_accuracy", args.min_strict_accuracy),
        ("decided_accuracy", args.min_decided_accuracy),
        ("strict_macro_f1", args.min_strict_macro_f1),
        ("covered_labels", args.min_covered_labels),
    ]
    for metric, threshold in checks:
        if threshold is None:
            continue
        value = summary.get(metric)
        if value is None or value < threshold:
            failures.append(f"{metric}={value} < {threshold}")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score predictions against MCP full gold 200.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", type=Path, default=None)
    parser.add_argument("--prediction-label-col", default="")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--input-fixture-out", type=Path, default=None)
    parser.add_argument("--min-strict-accuracy", type=float, default=None)
    parser.add_argument("--min-decided-accuracy", type=float, default=None)
    parser.add_argument("--min-strict-macro-f1", type=float, default=None)
    parser.add_argument("--min-covered-labels", type=int, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    gold_path = args.gold.expanduser()
    prediction_path = args.predictions.expanduser() if args.predictions else None
    output_dir = args.output_dir.expanduser()
    gold_rows = read_csv(gold_path)
    prediction_rows = read_csv(prediction_path) if prediction_path else []

    if args.input_fixture_out:
        write_input_fixture(args.input_fixture_out.expanduser(), gold_rows)

    result = evaluate(gold_rows, prediction_rows, args.prediction_label_col)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    report_md = output_dir / "report.md"
    evaluated_csv = output_dir / "evaluated_rows.csv"
    failures_csv = output_dir / "failures.csv"
    confusion_csv = output_dir / "confusion.csv"
    per_label_csv = output_dir / "per_label_strict.csv"

    summary_json.write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(markdown_report(result, gold_path, prediction_path), encoding="utf-8")
    write_csv(evaluated_csv, result["evaluated"], result["evaluated"][0].keys() if result["evaluated"] else [])
    write_csv(failures_csv, result["failures"], result["evaluated"][0].keys() if result["evaluated"] else [])
    write_csv(confusion_csv, result["confusion"], ("gold_label", "predicted_label", "count"))
    write_csv(per_label_csv, result["per_label_strict"], ("label", "support", "tp", "fp", "fn", "precision", "recall", "f1"))

    print(f"summary={summary_json}")
    print(f"report={report_md}")
    print(f"failures={failures_csv}")
    print(
        "strict_accuracy={strict_accuracy} decided_accuracy={decided_accuracy} "
        "strict_macro_f1={strict_macro_f1} covered={covered_labels}/{gold_rows}".format(
            **result["summary"]
        )
    )

    threshold_failures = enforce_thresholds(args, result["summary"])
    if threshold_failures:
        for failure in threshold_failures:
            print(f"THRESHOLD_FAIL {failure}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
