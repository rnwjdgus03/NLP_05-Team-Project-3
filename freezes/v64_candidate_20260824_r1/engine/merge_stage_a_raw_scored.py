#!/usr/bin/env python3
"""Protect raw recall order while restoring cross-encoder scores from a wider run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path: Path) -> dict[str, dict]:
    # Stage A intentionally emits no packets when every candidate channel is
    # empty.  Some worker paths do not materialize a zero-byte JSONL in that
    # case, so a missing input is equivalent to an empty channel.  A partial
    # channel mismatch is still rejected by the claim-set check in main().
    if not path.is_file():
        return {}
    return {row["claim_measurement_id"]: row for row in (
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )}


def key(row: dict) -> tuple[str, str]:
    table = row.get("table") or row
    return str(row.get("org_id") or table.get("org_id") or ""), str(
        row.get("tbl_id") or table.get("tbl_id") or ""
    )


def interleave(left: list[dict], right: list[dict]) -> list[dict]:
    output = []
    for index in range(max(len(left), len(right))):
        if index < len(left): output.append(left[index])
        if index < len(right): output.append(right[index])
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("legacy", "balanced", "legacy_raw", "balanced_raw", "legacy_scored", "balanced_scored"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-slots", type=int, default=7)
    parser.add_argument("--raw-slots", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()
    sources = {name: read(getattr(args, name)) for name in (
        "legacy", "balanced", "legacy_raw", "balanced_raw", "legacy_scored", "balanced_scored"
    )}
    claim_ids = list(sources["legacy"])
    if any(set(source) != set(claim_ids) for source in sources.values()):
        raise ValueError("Stage A channel claim sets differ")
    packets, restored, missing = [], 0, 0
    for claim_id in claim_ids:
        legacy = sources["legacy"][claim_id]
        balanced = sources["balanced"][claim_id]
        raw = interleave(
            list(sources["legacy_raw"][claim_id].get("candidates") or []),
            list(sources["balanced_raw"][claim_id].get("candidates") or []),
        )
        score_lookup = {}
        for channel in ("legacy_scored", "balanced_scored"):
            packet = sources[channel][claim_id]
            for row in packet.get("scored_candidates") or packet.get("table_candidates") or []:
                score_lookup.setdefault(key(row), row)
        selected, seen = [], set()
        reranked_limit = args.top_k - args.raw_slots

        def append(rows: list[dict], limit: int, source: str, restore: bool = False) -> None:
            nonlocal restored, missing
            for raw_row in rows:
                if len(selected) >= limit: return
                table_key = key(raw_row)
                if not all(table_key) or table_key in seen: continue
                row = dict(raw_row)
                if restore:
                    scored = score_lookup.get(table_key)
                    if scored is not None:
                        row = {**row, **scored}
                        restored += 1
                    else:
                        row["verification_review_required"] = True
                        row["verification_review_reason"] = "raw_candidate_without_cross_encoder_score"
                        missing += 1
                row["stage_a_merge_source"] = source
                selected.append(row); seen.add(table_key)

        append(list(legacy.get("table_candidates") or [])[:args.legacy_slots],
               min(args.legacy_slots, reranked_limit), "LEGACY_PROTECTED")
        append(list(balanced.get("table_candidates") or []), reranked_limit, "BALANCED_STRUCTURED")
        append(list(legacy.get("table_candidates") or []), reranked_limit, "LEGACY_BACKFILL")
        append(raw, args.top_k, "RAW_RECALL_SCORED", restore=True)
        append(interleave(list(legacy.get("table_candidates") or []),
                          list(balanced.get("table_candidates") or [])),
               args.top_k, "RERANK_BACKFILL")
        selected = [{**row, "rank": rank, "table_family_rank": rank}
                    for rank, row in enumerate(selected[:args.top_k], 1)]
        packets.append({**legacy, "item_recall_policy": "v34_raw_scored_protected",
                        "stage_a_merge_legacy_slots": args.legacy_slots,
                        "stage_a_merge_raw_slots": args.raw_slots,
                        "table_candidates": selected})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in packets), encoding="utf-8")
    print(f"merged_packets={len(packets)} scored_restored={restored} score_missing={missing}")


if __name__ == "__main__":
    main()
