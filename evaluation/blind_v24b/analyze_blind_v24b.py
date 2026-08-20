#!/usr/bin/env python3
"""Recompute blind metrics over all locked rows and produce a failure funnel."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "extracted/runs/blind_v24b_official_release31_20260820"
GOLD = ROOT / "blind_official_release_coordinate_gold31_locked.csv"
OUT_JSON = ROOT / "blind_v24b_all31_analysis.json"
OUT_CSV = ROOT / "blind_v24b_all31_details.csv"


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def integer(value: str) -> int | None:
    return int(value) if str(value or "").strip() else None


def wilson(success: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    p = success / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [center - margin, center + margin]


def metrics(rows: list[dict], field: str) -> dict:
    ranks = [row[field] for row in rows]
    result = {"n": len(ranks)}
    for k in (1, 3, 5, 10):
        hit = sum(rank is not None and rank <= k for rank in ranks)
        result[f"hit_at_{k}"] = hit
        result[f"accuracy_at_{k}"] = hit / len(ranks) if ranks else None
        result[f"wilson95_at_{k}"] = wilson(hit, len(ranks))
    result["mrr"] = sum(1 / rank for rank in ranks if rank is not None) / len(ranks) if ranks else None
    return result


gold = csv_rows(GOLD)
official_details = {
    row["claim_measurement_id"]: row for row in csv_rows(RUN / "coordinate_topk_blind_details.csv")
}
stage_a = {row["claim_measurement_id"]: row for row in jsonl(RUN / "stage_a_table_pool.jsonl")}
predictions = {row["claim_measurement_id"]: row for row in jsonl(RUN / "kosis_api_candidates_fallback.jsonl")}
decisions = {row["claim_measurement_id"]: row for row in jsonl(RUN / "hybrid_top5_claim_decisions.jsonl")}

details = []
for row in gold:
    claim_id = row["claim_measurement_id"]
    old = official_details.get(claim_id, {})
    packet = stage_a.get(claim_id, {})
    stage_a_rank = None
    for candidate in packet.get("table_candidates") or []:
        table = candidate.get("table") or {}
        if table.get("org_id") == row["gold_org_id"] and table.get("tbl_id") == row["gold_tbl_id"]:
            stage_a_rank = int(candidate.get("rank") or 0) or None
            break
    detail = {
        "claim_measurement_id": claim_id,
        "article_id": row["article_id"],
        "domain": "CPI" if row["article_id"].startswith("B26CPI") else "EMPLOYMENT",
        "gold_tbl_id": row["gold_tbl_id"],
        "gold_itm_id": row["gold_itm_id"],
        "gold_obj_l1": row["gold_obj_l1"],
        "development_table_overlap": row["development_table_overlap"],
        "stage_a_rank": stage_a_rank,
        "prediction_packet": claim_id in predictions,
        "table_rank": integer(old.get("table_rank", "")),
        "item_rank": integer(old.get("item_rank", "")),
        "coordinate_rank": integer(old.get("coordinate_rank", "")),
        "full_rank": integer(old.get("full_rank", "")),
        "claim_decision": decisions.get(claim_id, {}).get("claim_decision", "NO_PACKET"),
    }
    if not detail["prediction_packet"]:
        failure = "NO_FINAL_PACKET"
    elif detail["full_rank"] is not None:
        failure = "FULL_HIT"
    elif detail["stage_a_rank"] is None:
        failure = "STAGE_A_GOLD_TABLE_MISS"
    elif detail["table_rank"] is None:
        failure = "DOWNSTREAM_TABLE_LOSS"
    elif detail["item_rank"] is None:
        failure = "ITEM_MISS"
    elif detail["coordinate_rank"] is None:
        failure = "OBJ_MISS"
    else:
        failure = "PERIOD_MISS"
    detail["failure_stage"] = failure
    details.append(detail)

assert len(details) == 31
with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(details[0]))
    writer.writeheader()
    writer.writerows(details)

strata = {}
for field in ("domain", "gold_tbl_id", "development_table_overlap"):
    groups = defaultdict(list)
    for row in details:
        groups[str(row[field])].append(row)
    strata[field] = {
        name: {level: metrics(group, f"{level}_rank") for level in ("table", "item", "coordinate", "full")}
        for name, group in sorted(groups.items())
    }

analysis = {
    "schema_version": "v24b-blind-all-locked-rows-analysis-v1",
    "denominator_policy": "all 31 locked gold rows; missing prediction packet is failure",
    "gold_rows": len(gold), "prediction_packets": len(predictions),
    "stage_a_gold_table_hit_at_10": sum(row["stage_a_rank"] is not None and row["stage_a_rank"] <= 10 for row in details),
    "stage_a_gold_table_accuracy_at_10": sum(row["stage_a_rank"] is not None and row["stage_a_rank"] <= 10 for row in details) / len(details),
    "failure_stage_counts": dict(Counter(row["failure_stage"] for row in details)),
    "claim_decision_counts_all31": dict(Counter(row["claim_decision"] for row in details)),
    "metrics_all31": {level: metrics(details, f"{level}_rank") for level in ("table", "item", "coordinate", "full")},
    "strata": strata,
    "dependence_warning": "31 measurements are clustered within 9 documents and only 3 KOSIS tables; row-level Wilson intervals are descriptive, not independent-sample inference.",
}
OUT_JSON.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(analysis, ensure_ascii=False, indent=2))
