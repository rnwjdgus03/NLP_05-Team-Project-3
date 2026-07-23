#!/usr/bin/env python3
"""Compare lexical and BGE Top-K summaries produced under identical conditions."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def best_row(rows: Iterable[dict[str, str]]) -> dict[str, str]:
    rows = list(rows)
    if not rows:
        raise ValueError("Top-K summary is empty")
    max_hits = max(number(row, "retrieval_hits") for row in rows)
    return min(
        (row for row in rows if number(row, "retrieval_hits") == max_hits),
        key=lambda row: number(row, "top_k"),
    )


def compare(
    lexical_rows: list[dict[str, str]], bge_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    combined: list[dict[str, object]] = []
    for mode, rows in (("lexical", lexical_rows), ("hybrid", bge_rows)):
        for row in rows:
            combined.append({**row, "retrieval_mode": mode})

    lexical_best = best_row(lexical_rows)
    bge_best = best_row(bge_rows)
    contenders = [("lexical", lexical_best), ("hybrid", bge_best)]
    winner_mode, winner = sorted(
        contenders,
        key=lambda item: (
            -number(item[1], "retrieval_hits"),
            number(item[1], "top_k"),
            0 if item[0] == "lexical" else 1,
        ),
    )[0]
    decision = {
        "winner_mode": winner_mode,
        "winner_top_k": int(number(winner, "top_k")),
        "winner_hits": int(number(winner, "retrieval_hits")),
        "winner_gold": int(number(winner, "retrieval_gold")),
        "winner_recall": number(winner, "retrieval_recall"),
        "lexical_best_top_k": int(number(lexical_best, "top_k")),
        "lexical_best_hits": int(number(lexical_best, "retrieval_hits")),
        "bge_best_top_k": int(number(bge_best, "top_k")),
        "bge_best_hits": int(number(bge_best, "retrieval_hits")),
        "deployment_ready": any(
            number(row, "ready_rows") > 0 for row in lexical_rows + bge_rows
        ),
    }
    return combined, decision


def write_report(
    path: Path, combined: list[dict[str, object]], decision: dict[str, object],
) -> None:
    lines = [
        "# KOSIS lexical vs BGE-M3 comparison",
        "",
        "| Retrieval | K | TBL recall | Technically valid | READY | ITEM/OBJ gold hit |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in combined:
        lines.append(
            f"| {row['retrieval_mode']} | {row['top_k']} | "
            f"{row['retrieval_hits']}/{row['retrieval_gold']} "
            f"({float(row['retrieval_recall']):.1%}) | "
            f"{row['technical_valid_rows']} | {row['ready_rows']} | "
            f"{row['technical_item_obj_hits']}/{row['technical_item_obj_gold']} |"
        )
    lines.extend([
        "",
        f"Retrieval winner: **{decision['winner_mode']} "
        f"Top-{decision['winner_top_k']}** "
        f"({decision['winner_hits']}/{decision['winner_gold']}, "
        f"{float(decision['winner_recall']):.1%})",
        "",
        (
            "No READY rows were produced. Apply this decision only to table retrieval; "
            "Mapping-end deployment remains blocked."
            if not decision["deployment_ready"]
            else
            "READY rows exist, so ITEM/OBJ and verdict accuracy must also be considered."
        ),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lexical-summary", required=True)
    parser.add_argument("--bge-summary", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-report", required=True)
    args = parser.parse_args()

    combined, decision = compare(
        read_csv(Path(args.lexical_summary)), read_csv(Path(args.bge_summary)),
    )
    write_csv(Path(args.out_csv), combined)
    write_report(Path(args.out_report), combined, decision)
    print(
        f"winner={decision['winner_mode']} top_k={decision['winner_top_k']} "
        f"recall={decision['winner_recall']:.4f}"
    )
    print(f"comparison_csv={Path(args.out_csv).resolve()}")
    print(f"comparison_report={Path(args.out_report).resolve()}")


if __name__ == "__main__":
    main()
