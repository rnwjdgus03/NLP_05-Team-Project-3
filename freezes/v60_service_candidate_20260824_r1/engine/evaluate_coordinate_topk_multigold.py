#!/usr/bin/env python3
"""Claim-level Top-k evaluation against one or more official gold coordinates."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping


EMPTY = {"", "-", "N/A", "NA", "NONE", "NULL"}


def text(value: Any) -> str:
    result = "" if value is None else str(value).strip()
    return "" if result.upper() in EMPTY else result


def normalize_period(value: Any, prd_se: Any = "") -> str:
    raw = text(value)
    if not raw:
        return ""
    digits = "".join(re.findall(r"\d", raw))
    periodicity = text(prd_se).upper()
    if periodicity == "Y":
        return digits[:4]
    if periodicity == "M" and len(digits) >= 6:
        return digits[:6]
    if periodicity == "Q" and len(digits) >= 5:
        return digits[:6]
    return digits or raw.upper()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_gold(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def gold_axes(row: Mapping[str, Any]) -> list[str]:
    values = []
    for level in range(1, 9):
        value = text(row.get(f"gold_obj_l{level}"))
        if value:
            values.append(value)
    return values


def coordinate_axis_values(coordinate: Mapping[str, Any]) -> set[str]:
    return {
        text(value.get("value_id"))
        for value in coordinate.get("axis_values") or []
        if text(value.get("value_id"))
    }


def component_matches(
    coordinate: Mapping[str, Any], gold: Mapping[str, Any], level: str,
) -> bool:
    table = (
        text(coordinate.get("org_id")) == text(gold.get("gold_org_id"))
        and text(coordinate.get("tbl_id")) == text(gold.get("gold_tbl_id"))
    )
    if level == "table":
        return table
    item = table and (
        text(coordinate.get("item_id")) == text(gold.get("gold_itm_id"))
    )
    if level == "item":
        return item
    axes = gold_axes(gold)
    obj = item and all(
        value in coordinate_axis_values(coordinate) for value in axes
    )
    if level == "coordinate":
        return obj
    gold_prd = text(gold.get("gold_prd_se")).upper()
    predicted_prd = text(coordinate.get("prd_se")).upper()
    period = obj and (not gold_prd or predicted_prd == gold_prd)
    gold_period = normalize_period(gold.get("gold_period"), gold_prd)
    predicted_period = normalize_period(
        coordinate.get("target_period"), predicted_prd,
    )
    return period and (not gold_period or predicted_period == gold_period)


def first_rank_any(
    candidates: list[dict[str, Any]], gold_options: list[Mapping[str, Any]], level: str,
) -> int | None:
    for rank, candidate in enumerate(candidates, 1):
        if any(component_matches(candidate.get("coordinate") or {}, gold, level)
               for gold in gold_options):
            return rank
    return None


def metric_block(ranks: list[int | None], ks: list[int]) -> dict[str, Any]:
    total = len(ranks)
    block = {
        f"hit_at_{k}": sum(rank is not None and rank <= k for rank in ranks)
        for k in ks
    }
    block.update({
        f"accuracy_at_{k}": (
            block[f"hit_at_{k}"] / total if total else None
        )
        for k in ks
    })
    block["mrr"] = (
        sum(1.0 / rank for rank in ranks if rank is not None) / total
        if total else None
    )
    return block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--details", required=True, type=Path)
    parser.add_argument("--ks", default="1,3,5")
    args = parser.parse_args()
    ks = sorted({int(value) for value in args.ks.split(",") if int(value) > 0})

    packets = {
        text(row.get("claim_measurement_id")): row
        for row in read_jsonl(args.predictions)
    }
    gold_rows = read_gold(args.gold)
    eligible = [
        row for row in gold_rows
        if text(row.get("gold_ready")).upper() in {"", "Y"}
        and all(text(row.get(key)) for key in (
            "gold_org_id", "gold_tbl_id", "gold_itm_id",
        ))
    ]
    gold_by_claim: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in eligible:
        gold_by_claim[text(row.get("claim_measurement_id"))].append(row)
    prediction_overlap = sum(claim_id in packets for claim_id in gold_by_claim)

    levels = ("table", "item", "coordinate", "full")
    ranks_by_level: dict[str, list[int | None]] = {level: [] for level in levels}
    overlap_ranks_by_level: dict[str, list[int | None]] = {level: [] for level in levels}
    details = []
    for claim_id, gold_options in gold_by_claim.items():
        gold = gold_options[0]
        packet = packets.get(claim_id)
        prediction_present = packet is not None
        packet = packet or {}
        candidates = list(packet.get("unique_api_candidates") or [])
        detail = {
            "claim_measurement_id": claim_id,
            "gold_option_count": len(gold_options),
            "gold_coordinate_status": "|".join(sorted({text(row.get("gold_coordinate_status")) for row in gold_options})),
            "gold_coordinate_keys": " || ".join("/".join(coordinate_key) for coordinate_key in (
                (text(row.get("gold_org_id")), text(row.get("gold_tbl_id")), text(row.get("gold_itm_id")), *gold_axes(row))
                for row in gold_options
            )),
            "prediction_present": "Y" if prediction_present else "N",
            "candidate_count": len(candidates),
        }
        for level in levels:
            rank = first_rank_any(candidates, gold_options, level)
            ranks_by_level[level].append(rank)
            if prediction_present:
                overlap_ranks_by_level[level].append(rank)
            detail[f"{level}_rank"] = rank or ""
        details.append(detail)

    summary = {
        "schema_version": "kosis-coordinate-topk-multigold-claim-eval-v1",
        "prediction_file": str(args.predictions),
        "gold_file": str(args.gold),
        "prediction_claims": len(packets),
        "gold_rows": len(gold_rows),
        "eligible_gold_rows": len(eligible),
        "eligible_gold_claims": len(gold_by_claim),
        "prediction_overlap": prediction_overlap,
        # Retained as a compatibility alias. Unlike v1, its denominator is all
        # eligible gold rows, including rows with no prediction packet.
        "eligible_overlap": len(gold_by_claim),
        "missing_prediction_packets": len(gold_by_claim) - prediction_overlap,
        "ks": ks,
        "gold_coordinate_status_row_counts": dict(Counter(
            text(row.get("gold_coordinate_status")) for row in eligible
        )),
        "metrics_all_eligible_gold": {
            level: metric_block(ranks_by_level[level], ks) for level in levels
        },
        "metrics_prediction_overlap": {
            level: metric_block(overlap_ranks_by_level[level], ks) for level in levels
        },
    }
    summary["metrics"] = summary["metrics_all_eligible_gold"]
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.details.parent.mkdir(parents=True, exist_ok=True)
    with args.details.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(details[0]) if details else ["claim_measurement_id"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(details)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
