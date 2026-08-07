"""Build a prediction CSV for MCP gold 200 using fixed gold coordinates.

This file is intentionally not an end-to-end retrieval/mapping run.  It keeps
the gold set's KOSIS coordinates and MCP actual values fixed, then reruns the
current value-comparison rule to produce ``predicted_label``.  Use it as the
first regression artifact for the verdict/value-comparison layer, not as a
claim-to-KOSIS retrieval benchmark.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "gold" / "mcp_full_gold_200.csv"
DEFAULT_OUTPUT = (
    ROOT
    / "outputs"
    / "runs"
    / "mcp_gold_200_gold_coordinate_verifier"
    / "predictions.csv"
)
DEFAULT_SUMMARY = DEFAULT_OUTPUT.with_name("prediction_summary.json")
OUTPUT_FIELDS = [
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
    "predicted_label",
    "raw_prediction_verdict",
    "predicted_actual_value",
    "predicted_source_value",
    "predicted_previous_source_value",
    "predicted_source_unit",
    "predicted_org_id",
    "predicted_tbl_id",
    "predicted_tbl_name",
    "predicted_obj_l1",
    "predicted_obj_l2",
    "predicted_itm_id",
    "predicted_prd_se",
    "predicted_period",
    "predicted_previous_period",
    "prediction_abs_error",
    "prediction_relative_error_pct",
    "prediction_rule",
    "prediction_mode",
    "prediction_source",
    "prediction_generated_at",
]


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in {"", "-", "None", "nan", "NaN"} else text


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(value: object) -> Decimal | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def predict_label(
    claim_value: Decimal | None,
    actual_value: Decimal | None,
    *,
    tolerance_pct: Decimal,
    review_pct: Decimal,
) -> tuple[str, str, Decimal | None, Decimal | None, str]:
    if claim_value is None or actual_value is None:
        return "", "UNVERIFIABLE", None, None, "missing claim or actual value"
    abs_error = abs(actual_value - claim_value)
    denominator = max(abs(claim_value), Decimal("1e-9"))
    relative_pct = abs_error / denominator * Decimal("100")
    if relative_pct <= tolerance_pct:
        return "SUPPORTS", "MATCH", abs_error, relative_pct, (
            f"relative_error_pct <= {tolerance_pct}"
        )
    if relative_pct <= review_pct:
        return "REFUTES", "WITHIN_UNCERTAINTY_BAND_AS_REFUTES", abs_error, relative_pct, (
            f"{tolerance_pct} < relative_error_pct <= {review_pct}"
        )
    return "REFUTES", "VALUE_MISMATCH", abs_error, relative_pct, (
        f"relative_error_pct > {review_pct}"
    )


def build_predictions(
    rows: list[dict[str, str]],
    *,
    tolerance_pct: Decimal,
    review_pct: Decimal,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    generated_at = datetime.now(timezone.utc).isoformat()
    predictions: list[dict[str, Any]] = []
    for row in rows:
        claim_value = number(row.get("claim_value"))
        actual_value = number(row.get("gold_actual_value"))
        label, verdict, abs_error, relative_pct, rule = predict_label(
            claim_value,
            actual_value,
            tolerance_pct=tolerance_pct,
            review_pct=review_pct,
        )
        predictions.append(
            {
                "gold_id": row.get("gold_id", ""),
                "claim_id": row.get("claim_id", ""),
                "article_id": row.get("article_id", ""),
                "title": row.get("title", ""),
                "date": row.get("date", ""),
                "url": row.get("url", ""),
                "claim_text": row.get("claim_text", ""),
                "claim_type": row.get("claim_type", ""),
                "claim_value": row.get("claim_value", ""),
                "claim_unit": row.get("claim_unit", ""),
                "predicted_label": label,
                "raw_prediction_verdict": verdict,
                "predicted_actual_value": row.get("gold_actual_value", ""),
                "predicted_source_value": row.get("gold_source_value", ""),
                "predicted_previous_source_value": row.get("gold_previous_source_value", ""),
                "predicted_source_unit": row.get("gold_source_unit", ""),
                "predicted_org_id": row.get("gold_org_id", ""),
                "predicted_tbl_id": row.get("gold_tbl_id", ""),
                "predicted_tbl_name": row.get("gold_tbl_name", ""),
                "predicted_obj_l1": row.get("gold_obj_l1", ""),
                "predicted_obj_l2": row.get("gold_obj_l2", ""),
                "predicted_itm_id": row.get("gold_itm_id", ""),
                "predicted_prd_se": row.get("gold_prd_se", ""),
                "predicted_period": row.get("gold_period", ""),
                "predicted_previous_period": row.get("gold_previous_period", ""),
                "prediction_abs_error": decimal_text(abs_error),
                "prediction_relative_error_pct": decimal_text(relative_pct),
                "prediction_rule": rule,
                "prediction_mode": "GOLD_COORDINATE_VALUE_VERIFIER",
                "prediction_source": "mcp_full_gold_200.csv coordinates and actual values; gold_label not read",
                "prediction_generated_at": generated_at,
            }
        )
    summary = {
        "generated_at": generated_at,
        "row_count": len(predictions),
        "prediction_mode": "GOLD_COORDINATE_VALUE_VERIFIER",
        "label_counts": dict(Counter(row["predicted_label"] or "<blank>" for row in predictions)),
        "verdict_counts": dict(Counter(row["raw_prediction_verdict"] for row in predictions)),
        "tolerance_pct": str(tolerance_pct),
        "review_pct": str(review_pct),
        "important_caveat": (
            "This fixes gold KOSIS coordinates and actual values, so it evaluates "
            "only the value-comparison/verdict layer, not retrieval or mapping."
        ),
    }
    return predictions, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--tolerance-pct", type=Decimal, default=Decimal("1.5"))
    parser.add_argument("--review-pct", type=Decimal, default=Decimal("4.0"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    rows = read_csv(args.input.expanduser())
    predictions, summary = build_predictions(
        rows,
        tolerance_pct=args.tolerance_pct,
        review_pct=args.review_pct,
    )
    write_csv(args.output.expanduser(), predictions, OUTPUT_FIELDS)
    summary_path = args.summary.expanduser()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"predictions={args.output}")
    print(f"summary={summary_path}")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
