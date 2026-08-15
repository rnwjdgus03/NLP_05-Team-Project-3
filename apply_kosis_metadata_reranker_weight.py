#!/usr/bin/env python3
"""Recompute table order from cached SQLite-metadata reranker scores."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Mapping

from kosis_sqlite_metadata import clean


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def key(row: Mapping[str, object]) -> str:
    return clean(row.get("gold_id") or row.get("claim_measurement_id") or row.get("claim_id"))


def number(row: Mapping[str, object], field: str, default: float = 0.0) -> float:
    try:
        return float(clean(row.get(field)))
    except ValueError:
        return default


def upstream_rank(row: Mapping[str, object]) -> int:
    value = number(row, "upstream_candidate_rank", number(row, "candidate_rank", 999.0))
    return max(1, int(value))


def rank_score(rank: int) -> float:
    return 1.0 / math.log2(rank + 1.0)


def apply_weight(rows: list[dict[str, str]], weight: float) -> list[dict[str, object]]:
    if not 0.0 <= weight <= 1.0:
        raise ValueError("weight must be between 0 and 1")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for row in rows:
        row_key = key(row)
        if not row_key:
            continue
        if row_key not in grouped:
            order.append(row_key)
        grouped[row_key].append(row)

    output: list[dict[str, object]] = []
    for row_key in order:
        reranked = []
        for row in grouped[row_key]:
            rank = upstream_rank(row)
            metadata_score = number(row, "metadata_reranker_normalized")
            fusion = weight * metadata_score + (1.0 - weight) * rank_score(rank)
            reranked.append({
                **row,
                "upstream_candidate_rank": rank,
                "metadata_fusion_score": fusion,
                "metadata_weight": weight,
            })
        reranked.sort(key=lambda row: (
            -float(row["metadata_fusion_score"]),
            int(row["upstream_candidate_rank"]),
            clean(row.get("tbl_id")),
        ))
        for index, row in enumerate(reranked, 1):
            row["candidate_rank"] = index
            output.append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weight", type=float, required=True)
    args = parser.parse_args()
    output = apply_weight(read_csv(args.input), args.weight)
    write_csv(args.output, output)
    print(f"rows={len(output)} weight={args.weight:g} output={args.output}")


if __name__ == "__main__":
    main()
