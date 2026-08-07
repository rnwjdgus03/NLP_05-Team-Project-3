"""Evaluate KOSIS retrieval and coordinate mapping against MCP full gold 200.

This evaluator does not call KOSIS and does not read ``gold_label`` for scoring.
It compares pipeline-produced table candidates and final mapped coordinates to
the frozen gold coordinates in ``data/gold/mcp_full_gold_200.csv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parent
DEFAULT_GOLD = ROOT / "data" / "gold" / "mcp_full_gold_200.csv"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "regression" / "mcp_full_gold_200" / "mapping"
DEFAULT_KS = (1, 3, 5, 10, 20)
KEY_COLUMNS = ("gold_id", "claim_id", "claim_measurement_id")
RANK_COLUMNS = ("candidate_rank", "rank", "table_rank", "retrieval_rank")
FIELD_COLUMNS = {
    "org_id": ("predicted_org_id", "auto_org_id", "kosis_org_id", "org_id", "gold_org_id"),
    "tbl_id": ("predicted_tbl_id", "auto_tbl_id", "kosis_tbl_id", "tbl_id", "gold_tbl_id"),
    "obj_l1": ("predicted_obj_l1", "auto_obj_l1", "kosis_obj_l1", "selected_obj_l1", "obj_l1", "gold_obj_l1"),
    "obj_l2": ("predicted_obj_l2", "auto_obj_l2", "kosis_obj_l2", "selected_obj_l2", "obj_l2", "gold_obj_l2"),
    "itm_id": ("predicted_itm_id", "auto_itm_id", "kosis_itm_id", "selected_itm_id", "itm_id", "item_id", "gold_itm_id"),
    "prd_se": ("predicted_prd_se", "auto_prd_se", "kosis_prd_se", "coordinate_prd_se", "prd_se", "gold_prd_se"),
    "period": ("predicted_period", "auto_period", "kosis_period", "period", "target_period", "gold_period"),
    "previous_period": (
        "predicted_previous_period",
        "auto_previous_period",
        "kosis_previous_period",
        "previous_period",
        "prev_period",
        "comparison_period",
        "gold_previous_period",
    ),
}
OUTPUT_FIELDS = (
    "gold_id",
    "claim_id",
    "title",
    "claim_type",
    "gold_org_id",
    "pred_org_id",
    "org_id_correct",
    "gold_tbl_id",
    "pred_tbl_id",
    "tbl_id_correct",
    "gold_obj_l1",
    "pred_obj_l1",
    "obj_l1_correct",
    "gold_obj_l2",
    "pred_obj_l2",
    "obj_l2_correct",
    "gold_itm_id",
    "pred_itm_id",
    "itm_id_correct",
    "gold_prd_se",
    "pred_prd_se",
    "prd_se_correct",
    "gold_period",
    "pred_period",
    "period_correct",
    "gold_previous_period",
    "pred_previous_period",
    "previous_period_correct",
    "table_correct",
    "item_correct",
    "period_group_correct",
    "full_mapping_correct",
    "matched_by",
    "matched_key",
    "mapping_status",
    "candidate_rank",
)


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in {"", "-", "None", "nan", "NaN", "N/A", "NA"} else text


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


def rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    for column in KEY_COLUMNS:
        value = clean(row.get(column))
        if value:
            return column, value
    return "", ""


def build_key_maps(rows: list[dict[str, str]]) -> dict[str, dict[str, list[dict[str, str]]]]:
    maps: dict[str, dict[str, list[dict[str, str]]]] = {
        column: defaultdict(list) for column in KEY_COLUMNS
    }
    for row in rows:
        for column in KEY_COLUMNS:
            value = clean(row.get(column))
            if value:
                maps[column][value].append(row)
    return maps


def rows_for_gold(
    gold: Mapping[str, Any],
    maps: Mapping[str, Mapping[str, list[dict[str, str]]]],
) -> tuple[list[dict[str, str]], str, str]:
    for column in ("gold_id", "claim_id", "claim_measurement_id"):
        value = clean(gold.get(column))
        if value and value in maps.get(column, {}):
            return list(maps[column][value]), column, value
    return [], "", ""


def choose_value(row: Mapping[str, Any], columns: Iterable[str]) -> tuple[str, str]:
    for column in columns:
        value = clean(row.get(column))
        if value:
            return value, column
    return "", ""


def candidate_rank(row: Mapping[str, Any]) -> int:
    value, _ = choose_value(row, RANK_COLUMNS)
    if not value:
        return 1
    try:
        return int(float(value))
    except ValueError:
        return 999


def candidate_tbl_id(row: Mapping[str, Any]) -> str:
    value, _ = choose_value(row, FIELD_COLUMNS["tbl_id"])
    return value


def candidate_org_id(row: Mapping[str, Any]) -> str:
    value, _ = choose_value(row, FIELD_COLUMNS["org_id"])
    return value


def table_matches(gold: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    gold_tbl = clean(gold.get("gold_tbl_id"))
    pred_tbl = candidate_tbl_id(candidate)
    if not gold_tbl or not pred_tbl or gold_tbl != pred_tbl:
        return False
    gold_org = clean(gold.get("gold_org_id"))
    pred_org = candidate_org_id(candidate)
    return not pred_org or not gold_org or pred_org == gold_org


def retrieval_metrics(
    gold_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    ks: Iterable[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    maps = build_key_maps(candidate_rows)
    denominator = sum(bool(clean(row.get("gold_tbl_id"))) for row in gold_rows)
    metrics: list[dict[str, Any]] = []
    misses_by_k: dict[int, list[dict[str, Any]]] = {}
    for k in sorted(set(ks)):
        hits = 0
        covered = 0
        misses: list[dict[str, Any]] = []
        candidate_rows_at_k = 0
        for gold in gold_rows:
            rows, matched_by, matched_key = rows_for_gold(gold, maps)
            rows_at_k = [row for row in rows if candidate_rank(row) <= k]
            candidate_rows_at_k += len(rows_at_k)
            if rows_at_k:
                covered += 1
            if any(table_matches(gold, row) for row in rows_at_k):
                hits += 1
            else:
                misses.append(
                    {
                        "gold_id": clean(gold.get("gold_id")),
                        "claim_id": clean(gold.get("claim_id")),
                        "title": clean(gold.get("title")),
                        "gold_org_id": clean(gold.get("gold_org_id")),
                        "gold_tbl_id": clean(gold.get("gold_tbl_id")),
                        "matched_by": matched_by,
                        "matched_key": matched_key,
                        "candidate_count_at_k": len(rows_at_k),
                        "top_candidate_tbl_id": candidate_tbl_id(rows_at_k[0]) if rows_at_k else "",
                    }
                )
        metrics.append(
            {
                "top_k": k,
                "gold_labeled": denominator,
                "candidate_covered": covered,
                "hits": hits,
                "table_recall": rate(hits, denominator),
                "candidate_coverage": rate(covered, denominator),
                "candidate_rows_at_k": candidate_rows_at_k,
            }
        )
        misses_by_k[k] = misses
    largest_k = max(sorted(set(ks))) if ks else 0
    return metrics, misses_by_k.get(largest_k, [])


def mapping_priority(row: Mapping[str, Any]) -> tuple[int, int]:
    status = clean(row.get("mapping_status")).upper()
    status_score = 0 if status == "READY" else 1
    return status_score, candidate_rank(row)


def select_mapped_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = row_key(row)
        if key[1]:
            grouped[key].append(row)
    return {key: sorted(group, key=mapping_priority)[0] for key, group in grouped.items()}


def find_mapped_row(
    gold: Mapping[str, Any],
    selected: Mapping[tuple[str, str], dict[str, str]],
) -> tuple[dict[str, str] | None, str, str]:
    for column in ("gold_id", "claim_id", "claim_measurement_id"):
        value = clean(gold.get(column))
        key = (column, value)
        if value and key in selected:
            return selected[key], column, value
    return None, "", ""


def compare_field(gold: Mapping[str, Any], pred: Mapping[str, Any] | None, suffix: str) -> tuple[str, str, str]:
    gold_value = clean(gold.get(f"gold_{suffix}"))
    if pred is None:
        return gold_value, "", "N"
    pred_value, _ = choose_value(pred, FIELD_COLUMNS[suffix])
    return gold_value, pred_value, "Y" if gold_value == pred_value else "N"


def evaluate_mapping(
    gold_rows: list[dict[str, str]],
    mapped_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    selected = select_mapped_rows(mapped_rows)
    evaluated: list[dict[str, Any]] = []
    for gold in gold_rows:
        pred, matched_by, matched_key = find_mapped_row(gold, selected)
        values: dict[str, tuple[str, str, str]] = {
            suffix: compare_field(gold, pred, suffix) for suffix in FIELD_COLUMNS
        }
        row = {
            "gold_id": clean(gold.get("gold_id")),
            "claim_id": clean(gold.get("claim_id")),
            "title": clean(gold.get("title")),
            "claim_type": clean(gold.get("claim_type")),
            "matched_by": matched_by,
            "matched_key": matched_key,
            "mapping_status": clean(pred.get("mapping_status")) if pred else "",
            "candidate_rank": candidate_rank(pred) if pred else "",
        }
        for suffix, (gold_value, pred_value, correct) in values.items():
            row[f"gold_{suffix}"] = gold_value
            row[f"pred_{suffix}"] = pred_value
            row[f"{suffix}_correct"] = correct
        row["table_correct"] = "Y" if row["org_id_correct"] == "Y" and row["tbl_id_correct"] == "Y" else "N"
        row["item_correct"] = "Y" if all(
            row[f"{field}_correct"] == "Y" for field in ("obj_l1", "obj_l2", "itm_id")
        ) else "N"
        row["period_group_correct"] = "Y" if all(
            row[f"{field}_correct"] == "Y" for field in ("prd_se", "period", "previous_period")
        ) else "N"
        row["full_mapping_correct"] = "Y" if all(
            row[field] == "Y" for field in ("table_correct", "item_correct", "period_group_correct")
        ) else "N"
        evaluated.append(row)

    metrics: list[dict[str, Any]] = []

    def add(metric: str, correct: int, denominator: int, definition: str) -> None:
        metrics.append(
            {
                "metric": metric,
                "correct": correct,
                "denominator": denominator,
                "rate": rate(correct, denominator),
                "definition": definition,
            }
        )

    denominator = len(evaluated)
    mapped_count = sum(bool(row["matched_by"]) for row in evaluated)
    add("mapping_coverage", mapped_count, denominator, "gold rows with a final mapped row")
    for field in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "period", "previous_period"):
        add(
            f"{field}_accuracy",
            sum(row[f"{field}_correct"] == "Y" for row in evaluated),
            denominator,
            f"strict {field} exact match over all gold rows",
        )
    add("table_accuracy", sum(row["table_correct"] == "Y" for row in evaluated), denominator, "org_id + tbl_id exact")
    add("item_accuracy", sum(row["item_correct"] == "Y" for row in evaluated), denominator, "obj_l1 + obj_l2 + itm_id exact")
    add("period_accuracy", sum(row["period_group_correct"] == "Y" for row in evaluated), denominator, "prd_se + period + previous_period exact")
    add("full_mapping_accuracy", sum(row["full_mapping_correct"] == "Y" for row in evaluated), denominator, "table + item + period exact")
    failures = [row for row in evaluated if row["full_mapping_correct"] != "Y"]
    return evaluated, metrics, failures


def markdown_report(
    summary: Mapping[str, Any],
    retrieval: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    gold_path: Path,
    candidates_path: Path | None,
    mapped_path: Path | None,
) -> str:
    lines = [
        "# MCP Full Gold 200 Retrieval/Mapping Evaluation",
        "",
        f"- Gold: `{gold_path}`",
        f"- Candidates: `{candidates_path if candidates_path else '<none>'}`",
        f"- Mapped: `{mapped_path if mapped_path else '<none>'}`",
        f"- Generated: `{summary['generated_at']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in summary.items():
        if key.endswith("_counts") or key == "generated_at":
            continue
        lines.append(f"| {key} | {value if value is not None else '-'} |")
    if retrieval:
        lines.extend(["", "## Retrieval", "", "| Top-k | Hits | Gold | Recall | Coverage |", "|---:|---:|---:|---:|---:|"])
        for row in retrieval:
            lines.append(
                f"| {row['top_k']} | {row['hits']} | {row['gold_labeled']} | "
                f"{row['table_recall']} | {row['candidate_coverage']} |"
            )
    if mapping:
        lines.extend(["", "## Mapping", "", "| Metric | Correct | Denominator | Rate |", "|---|---:|---:|---:|"])
        for row in mapping:
            lines.append(f"| {row['metric']} | {row['correct']} | {row['denominator']} | {row['rate']} |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score retrieval and mapping against MCP full gold 200.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--candidates", type=Path, default=None, help="Top-k table candidate CSV")
    parser.add_argument("--mapped", type=Path, default=None, help="Final mapped/prediction CSV")
    parser.add_argument(
        "--input-fixture", type=Path, default=None,
        help="Gold-free enriched input; enables READY-only scorable metrics",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ks", type=int, nargs="+", default=list(DEFAULT_KS))
    parser.add_argument("--min-table-recall-at", type=int, default=None)
    parser.add_argument("--min-table-recall", type=float, default=None)
    parser.add_argument("--min-full-mapping-accuracy", type=float, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    gold_path = args.gold.expanduser()
    candidates_path = args.candidates.expanduser() if args.candidates else None
    mapped_path = args.mapped.expanduser() if args.mapped else None
    input_path = args.input_fixture.expanduser() if args.input_fixture else None
    output_dir = args.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    gold_rows = read_csv(gold_path)
    candidate_rows = read_csv(candidates_path) if candidates_path else []
    mapped_rows = read_csv(mapped_path) if mapped_path else []
    input_rows = read_csv(input_path) if input_path else []
    forbidden_input_fields = {
        field
        for row in input_rows[:1]
        for field in row
        if field.lower().startswith("gold_") and field.lower() != "gold_id"
    }
    if forbidden_input_fields:
        raise SystemExit(
            "input fixture contains forbidden gold fields: "
            + ", ".join(sorted(forbidden_input_fields))
        )
    ready_keys = {
        row_key(row)
        for row in input_rows
        if clean(row.get("input_quality_status")).upper() == "READY" and row_key(row)[1]
    }
    scorable_gold = [row for row in gold_rows if row_key(row) in ready_keys] if input_rows else []

    retrieval_rows: list[dict[str, Any]] = []
    retrieval_misses: list[dict[str, Any]] = []
    if candidate_rows:
        retrieval_rows, retrieval_misses = retrieval_metrics(gold_rows, candidate_rows, args.ks)

    evaluated_mapping: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    mapping_failures: list[dict[str, Any]] = []
    if mapped_rows:
        evaluated_mapping, mapping_rows, mapping_failures = evaluate_mapping(gold_rows, mapped_rows)

    scorable_retrieval_rows: list[dict[str, Any]] = []
    scorable_mapping_rows: list[dict[str, Any]] = []
    if scorable_gold and candidate_rows:
        scorable_retrieval_rows, _ = retrieval_metrics(scorable_gold, candidate_rows, args.ks)
    if scorable_gold and mapped_rows:
        _, scorable_mapping_rows, _ = evaluate_mapping(scorable_gold, mapped_rows)

    retrieval_by_k = {int(row["top_k"]): row for row in retrieval_rows}
    mapping_by_name = {row["metric"]: row for row in mapping_rows}
    scorable_retrieval_by_k = {int(row["top_k"]): row for row in scorable_retrieval_rows}
    scorable_mapping_by_name = {row["metric"]: row for row in scorable_mapping_rows}
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_rows": len(gold_rows),
        "scorable_rows": len(scorable_gold) if input_rows else None,
        "needs_input_review_rows": (len(input_rows) - len(scorable_gold)) if input_rows else None,
        "candidate_rows": len(candidate_rows),
        "mapped_rows": len(mapped_rows),
        "table_recall_at_1": retrieval_by_k.get(1, {}).get("table_recall"),
        "table_recall_at_3": retrieval_by_k.get(3, {}).get("table_recall"),
        "table_recall_at_5": retrieval_by_k.get(5, {}).get("table_recall"),
        "table_recall_at_20": retrieval_by_k.get(20, {}).get("table_recall"),
        "mapping_coverage": mapping_by_name.get("mapping_coverage", {}).get("rate"),
        "table_accuracy": mapping_by_name.get("table_accuracy", {}).get("rate"),
        "item_accuracy": mapping_by_name.get("item_accuracy", {}).get("rate"),
        "period_accuracy": mapping_by_name.get("period_accuracy", {}).get("rate"),
        "full_mapping_accuracy": mapping_by_name.get("full_mapping_accuracy", {}).get("rate"),
        "table_recall_at_20_scorable": scorable_retrieval_by_k.get(20, {}).get("table_recall"),
        "full_mapping_accuracy_scorable": scorable_mapping_by_name.get("full_mapping_accuracy", {}).get("rate"),
        "mapping_failure_count": len(mapping_failures),
        "retrieval_miss_count_at_max_k": len(retrieval_misses),
        "mapping_status_applicable": bool(mapped_rows and "mapping_status" in mapped_rows[0]),
        "mapped_status_counts": (
            dict(Counter(clean(row.get("mapping_status")) or "<blank>" for row in mapped_rows))
            if mapped_rows and "mapping_status" in mapped_rows[0]
            else {"<not_applicable_coordinate_predictions>": len(mapped_rows)} if mapped_rows else {}
        ),
    }
    for top_k, row in sorted(retrieval_by_k.items()):
        summary[f"table_recall_at_{top_k}"] = row.get("table_recall")

    write_csv(output_dir / "retrieval_metrics.csv", retrieval_rows, (
        "top_k",
        "gold_labeled",
        "candidate_covered",
        "hits",
        "table_recall",
        "candidate_coverage",
        "candidate_rows_at_k",
    ))
    write_csv(output_dir / "retrieval_misses_at_max_k.csv", retrieval_misses, (
        "gold_id",
        "claim_id",
        "title",
        "gold_org_id",
        "gold_tbl_id",
        "matched_by",
        "matched_key",
        "candidate_count_at_k",
        "top_candidate_tbl_id",
    ))
    write_csv(output_dir / "mapping_metrics.csv", mapping_rows, ("metric", "correct", "denominator", "rate", "definition"))
    write_csv(output_dir / "scorable_retrieval_metrics.csv", scorable_retrieval_rows, (
        "top_k", "gold_labeled", "candidate_covered", "hits", "table_recall",
        "candidate_coverage", "candidate_rows_at_k",
    ))
    write_csv(output_dir / "scorable_mapping_metrics.csv", scorable_mapping_rows, (
        "metric", "correct", "denominator", "rate", "definition",
    ))
    write_csv(output_dir / "evaluated_mappings.csv", evaluated_mapping, OUTPUT_FIELDS)
    write_csv(output_dir / "mapping_failures.csv", mapping_failures, OUTPUT_FIELDS)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(
        markdown_report(summary, retrieval_rows, mapping_rows, gold_path, candidates_path, mapped_path),
        encoding="utf-8",
    )

    print(f"summary={output_dir / 'summary.json'}")
    print(f"report={output_dir / 'report.md'}")
    print(
        "table_recall_at_5={table_recall_at_5} full_mapping_accuracy={full_mapping_accuracy}".format(
            **summary
        )
    )

    failures: list[str] = []
    if args.min_table_recall_at is not None and args.min_table_recall is not None:
        value = retrieval_by_k.get(args.min_table_recall_at, {}).get("table_recall")
        if value is None or value < args.min_table_recall:
            failures.append(f"table_recall@{args.min_table_recall_at}={value} < {args.min_table_recall}")
    if args.min_full_mapping_accuracy is not None:
        value = summary.get("full_mapping_accuracy")
        if value is None or value < args.min_full_mapping_accuracy:
            failures.append(f"full_mapping_accuracy={value} < {args.min_full_mapping_accuracy}")
    if failures:
        for failure in failures:
            print(f"THRESHOLD_FAIL {failure}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
