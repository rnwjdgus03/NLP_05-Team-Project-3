#!/usr/bin/env python3
"""Select the first API-matching branch while keeping the primary as default.

This is an evaluation-only cascade. A fallback packet is never interpreted as
READY merely because it was selected; downstream verification remains the
source of truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def index_jsonl(path: Path, key: str = "claim_measurement_id") -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[str(row[key])] = row
    return rows


def verified(decisions: dict[str, dict], claim_id: str) -> bool:
    return str(decisions.get(claim_id, {}).get("claim_decision") or "") == "VERIFIED_MATCH"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-candidates", type=Path, required=True)
    parser.add_argument("--primary-decisions", type=Path, required=True)
    parser.add_argument("--tail-candidates", type=Path, required=True)
    parser.add_argument("--tail-decisions", type=Path, required=True)
    parser.add_argument("--metadata-candidates", type=Path, required=True)
    parser.add_argument("--metadata-decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    primary = index_jsonl(args.primary_candidates)
    primary_decisions = index_jsonl(args.primary_decisions)
    tail = index_jsonl(args.tail_candidates)
    tail_decisions = index_jsonl(args.tail_decisions)
    metadata = index_jsonl(args.metadata_candidates)
    metadata_decisions = index_jsonl(args.metadata_decisions)
    counts = {
        "PRIMARY_API_MATCH": 0,
        "RANK_6_10_API_FALLBACK": 0,
        "METADATA_RECALL_API_FALLBACK": 0,
        "PRIMARY_UNRESOLVED": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for claim_id, primary_packet in primary.items():
            if verified(primary_decisions, claim_id):
                packet = dict(primary_packet)
                state = "PRIMARY_API_MATCH"
            elif claim_id in tail and verified(tail_decisions, claim_id):
                packet = dict(tail[claim_id])
                state = "RANK_6_10_API_FALLBACK"
            elif claim_id in metadata and verified(metadata_decisions, claim_id):
                packet = dict(metadata[claim_id])
                state = "METADATA_RECALL_API_FALLBACK"
            else:
                packet = dict(primary_packet)
                state = "PRIMARY_UNRESOLVED"
            packet["api_verified_fallback_state"] = state
            packet["api_verified_fallback_policy"] = (
                "primary-then-rank6-10-then-metadata-recall-if-no-api-match-v1"
            )
            handle.write(json.dumps(packet, ensure_ascii=False) + "\n")
            counts[state] += 1

    manifest = {
        "schema_version": "kosis-api-verified-multibranch-fallback-v1",
        "claims": len(primary),
        "counts": counts,
        "branch_priority": ["primary", "rank_6_10", "metadata_recall"],
        "automatic_ready_from_fallback": False,
        "policy": "Fallback is selected only when all earlier branches lack VERIFIED_MATCH.",
    }
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
