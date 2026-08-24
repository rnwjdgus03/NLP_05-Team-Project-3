#!/usr/bin/env python3
"""Evaluate Stage A table recall with all eligible gold rows as denominator."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def text(value: object) -> str:
    value = str(value or "").strip()
    return "" if value.upper() in {"", "-", "N/A", "NA", "NONE", "NULL"} else value


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--details", required=True, type=Path)
    parser.add_argument("--ks", default="1,3,5,10")
    args = parser.parse_args()
    ks = sorted({int(value) for value in args.ks.split(",") if int(value) > 0})
    packets = {
        text(row.get("claim_measurement_id")): row
        for row in read_jsonl(args.predictions)
    }
    with args.gold.open(encoding="utf-8-sig", newline="") as handle:
        source_gold = list(csv.DictReader(handle))
    gold_by_id = {}
    for row in source_gold:
        claim_id = text(row.get("claim_measurement_id"))
        ready = text(row.get("gold_ready")).upper()
        if not claim_id or ready not in {"", "Y"}:
            continue
        if not text(row.get("gold_org_id")) or not text(row.get("gold_tbl_id")):
            continue
        gold_by_id.setdefault(claim_id, row)

    details = []
    ranks = []
    for claim_id, gold in gold_by_id.items():
        packet = packets.get(claim_id) or {}
        candidates = list(packet.get("table_candidates") or [])
        rank = next((
            position for position, candidate in enumerate(candidates, 1)
            if text(candidate.get("org_id")) == text(gold.get("gold_org_id"))
            and text(candidate.get("tbl_id")) == text(gold.get("gold_tbl_id"))
        ), None)
        ranks.append(rank)
        details.append({
            "claim_measurement_id": claim_id,
            "gold_org_id": text(gold.get("gold_org_id")),
            "gold_tbl_id": text(gold.get("gold_tbl_id")),
            "prediction_present": "Y" if claim_id in packets else "N",
            "table_rank": rank or "",
            "item_recall_terms": "|".join(packet.get("item_recall_terms") or []),
            "item_recall_hit_count": packet.get("item_recall_hit_count", 0),
        })
    total = len(ranks)
    def metric_block(values: list[int | None]) -> dict[str, float | int | None]:
        denominator = len(values)
        result: dict[str, float | int | None] = {}
        for k in ks:
            hits = sum(rank is not None and rank <= k for rank in values)
            result[f"hit_at_{k}"] = hits
            result[f"accuracy_at_{k}"] = hits / denominator if denominator else None
        result["mrr"] = (
            sum(1.0 / rank for rank in values if rank is not None) / denominator
            if denominator else None
        )
        return result

    overlap_ranks = [
        rank for rank, detail in zip(ranks, details)
        if detail["prediction_present"] == "Y"
    ]
    summary = {
        "schema_version": "kosis-stage-a-table-recall-eval-v1",
        "gold_rows": len(source_gold),
        "eligible_gold_claims": total,
        "prediction_packets": len(packets),
        "prediction_overlap": sum(row["prediction_present"] == "Y" for row in details),
        "missing_prediction_packets": sum(row["prediction_present"] == "N" for row in details),
        "metrics_all_eligible_gold": metric_block(ranks),
        "input_scope_gold_claims": len(overlap_ranks),
        "metrics_prediction_overlap": metric_block(overlap_ranks),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    args.details.parent.mkdir(parents=True, exist_ok=True)
    with args.details.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(details[0]) if details else ["claim_measurement_id"])
        writer.writeheader()
        writer.writerows(details)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
