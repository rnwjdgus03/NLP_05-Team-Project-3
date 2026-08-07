#!/usr/bin/env python3
"""Compare Top-5 and Top-10 coordinate mapping evaluations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


METRICS = (
    "mapping_coverage", "table_accuracy", "item_accuracy", "period_accuracy",
    "full_mapping_accuracy",
)


def load_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top5-summary", type=Path, required=True)
    parser.add_argument("--top10-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    top5 = load_summary(args.top5_summary)
    top10 = load_summary(args.top10_summary)
    rows = []
    for metric in METRICS:
        value5 = top5.get(metric)
        value10 = top10.get(metric)
        rows.append(
            {
                "metric": metric,
                "top5": value5,
                "top10": value10,
                "delta_top10_minus_top5": (
                    None if value5 is None or value10 is None else value10 - value5
                ),
            }
        )
    payload = {row["metric"]: row for row in rows}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "top5_vs_top10.csv", rows)
    (args.output_dir / "top5_vs_top10.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
