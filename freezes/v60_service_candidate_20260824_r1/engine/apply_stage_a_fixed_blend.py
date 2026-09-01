#!/usr/bin/env python3
"""Apply the v36 fixed Stage-A rank blend without gold labels."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


WEIGHTS = {
    "item_rank": 0.25,
    "rrf": 0.50,
    "structural": 0.25,
    "item_source": 0.50,
}
POLICY = "v36-fixed-rank-blend-r1"


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def minmax(values):
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [0.0 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


def blend_candidates(candidates, top_k=12):
    candidates = list(candidates or [])
    base = minmax([
        number(row.get("metadata_rerank_score") or row.get("reranker_score"))
        for row in candidates
    ])
    rrf = minmax([number(row.get("rrf_score")) for row in candidates])
    structural = minmax([number(row.get("v16_structural_score")) for row in candidates])
    scores = []
    for idx, row in enumerate(candidates):
        rank = number(row.get("item_recall_rank"), 0)
        item = 1.0 / math.log2(rank + 1.0) if rank > 0 else 0.0
        sources = row.get("component_recall_sources") or []
        source = 1.0 if "ITEM" in sources else 0.0
        scores.append(
            base[idx]
            + WEIGHTS["item_rank"] * item
            + WEIGHTS["rrf"] * rrf[idx]
            + WEIGHTS["structural"] * structural[idx]
            + WEIGHTS["item_source"] * source
        )
    order = sorted(range(len(scores)), key=lambda idx: (-scores[idx], idx))
    result = []
    for rank, idx in enumerate(order[:top_k], 1):
        row = dict(candidates[idx])
        row["v36_blend_score"] = scores[idx]
        row["rank"] = rank
        result.append(row)
    return result


def transform_packet(packet, top_k=12):
    result = dict(packet)
    result["table_candidates"] = blend_candidates(packet.get("table_candidates"), top_k=top_k)
    result["v36_rank_blend_policy"] = POLICY
    result["v36_rank_blend_weights"] = dict(WEIGHTS)
    result["v36_rank_blend_input_candidates"] = len(packet.get("table_candidates") or [])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()
    packets = 0
    with args.input.open(encoding="utf-8") as source, args.output.open("w", encoding="utf-8") as target:
        for line in source:
            if not line.strip():
                continue
            packet = transform_packet(json.loads(line), top_k=args.top_k)
            target.write(json.dumps(packet, ensure_ascii=False) + "\n")
            packets += 1
    print(f"fixed_blend_packets={packets} policy={POLICY} top_k={args.top_k}")


if __name__ == "__main__":
    main()
