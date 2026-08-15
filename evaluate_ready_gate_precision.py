#!/usr/bin/env python3
"""Measure READY precision and correct coverage against frozen coordinate gold."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from evaluate_mcp_gold_200_mapping import evaluate_mapping, read_csv, write_csv
from kosis_validate_mapping_candidates import apply_semantic_ready_gate


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def apply_gate(rows: list[dict[str, str]], enabled: bool) -> list[dict[str, Any]]:
    output = []
    for source in rows:
        row: dict[str, Any] = dict(source)
        row["mapping_status"] = row.get("mapping_status") or "READY"
        if enabled:
            row = apply_semantic_ready_gate(row, row)
        output.append(row)
    return output


def ready_metrics(
    gold_rows: list[dict[str, str]],
    mapped_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evaluated, _, _ = evaluate_mapping(gold_rows, mapped_rows)
    ready = [row for row in evaluated if row.get("mapping_status") == "READY"]
    table_correct = sum(row["table_correct"] == "Y" for row in ready)
    coordinate_correct = sum(
        row["table_correct"] == "Y" and row["item_correct"] == "Y"
        for row in ready
    )
    full_correct = sum(row["full_mapping_correct"] == "Y" for row in ready)
    summary = {
        "gold_rows": len(gold_rows),
        "mapped_rows": len(mapped_rows),
        "ready_rows": len(ready),
        "abstained_gold_rows": len(gold_rows) - len(ready),
        "ready_table_correct": table_correct,
        "ready_coordinate_correct": coordinate_correct,
        "ready_full_correct": full_correct,
        "ready_table_precision": rate(table_correct, len(ready)),
        "ready_coordinate_precision": rate(coordinate_correct, len(ready)),
        "ready_full_precision": rate(full_correct, len(ready)),
        "ready_table_correct_coverage": rate(table_correct, len(gold_rows)),
        "ready_coordinate_correct_coverage": rate(coordinate_correct, len(gold_rows)),
        "ready_full_correct_coverage": rate(full_correct, len(gold_rows)),
        "mapping_status_counts": dict(Counter(
            str(row.get("mapping_status") or "<blank>") for row in mapped_rows
        )),
    }
    return summary, evaluated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply-semantic-gate", action="store_true")
    args = parser.parse_args()

    gold_rows = read_csv(args.gold)
    mapped_rows = apply_gate(read_csv(args.mapped), args.apply_semantic_gate)
    summary, evaluated = ready_metrics(gold_rows, mapped_rows)
    summary["semantic_gate_applied"] = args.apply_semantic_gate
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if evaluated:
        write_csv(args.output_dir / "evaluated.csv", evaluated, evaluated[0].keys())
    if mapped_rows:
        fields: list[str] = []
        for row in mapped_rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        write_csv(args.output_dir / "rescored_mappings.csv", mapped_rows, fields)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
