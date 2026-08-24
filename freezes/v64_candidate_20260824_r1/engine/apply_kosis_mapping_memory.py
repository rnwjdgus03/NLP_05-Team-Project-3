#!/usr/bin/env python3
"""Prepend exact reusable mapping-cache hits to coordinate candidates."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def text(value: object) -> str:
    return str(value or "").strip()


def normalized(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", text(value).casefold())


def mapping_key(row: dict[str, str], indicator: str) -> str:
    unit = row.get("canonical_unit") or row.get("unit")
    prd_se = row.get("prd_se") or row.get("measurement_prd_se")
    return "\x1f".join(
        normalized(value)
        for value in (row.get("metric_domain"), indicator, unit, prd_se)
    )


def coordinate_key(candidate: dict) -> tuple:
    coordinate = candidate.get("coordinate") or {}
    return (
        text(coordinate.get("org_id")),
        text(coordinate.get("tbl_id")),
        text(coordinate.get("item_id")),
        tuple(text(value.get("value_id")) for value in coordinate.get("axis_values") or []),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--memory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    with args.claims.open(encoding="utf-8-sig", newline="") as handle:
        claims = {row["claim_measurement_id"]: row for row in csv.DictReader(handle)}
    memory = json.loads(args.memory.read_text(encoding="utf-8"))
    assert memory["blind_labels_used"] == 0
    entries = memory["entries"]

    packets = []
    matched = 0
    with args.predictions.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            packet = json.loads(line)
            claim_id = text(packet.get("claim_measurement_id"))
            claim = claims.get(claim_id, {})
            indicators = []
            for column in ("indicator", "measurement_indicator", "claim_indicator"):
                value = text(claim.get(column))
                if value and value not in indicators:
                    indicators.append(value)
            entry = None
            for indicator in indicators:
                entry = entries.get(mapping_key(claim, indicator))
                if entry is not None:
                    break
            candidates = list(packet.get("unique_api_candidates") or [])
            if entry is not None:
                coordinate = dict(entry["coordinate"])
                coordinate["target_period"] = text(claim.get("period") or claim.get("measurement_period"))
                memory_candidate = {
                    "source": "verified_mapping_memory",
                    "source_rank": 1,
                    "coordinate": coordinate,
                    "score": 1.0,
                    "rationale": "검증된 조사명·지표·단위·주기 exact mapping cache",
                    "evidence": entry["evidence"],
                    "mapping_memory_exact": True,
                }
                candidates = [memory_candidate, *candidates]
                matched += 1
            selected, seen = [], set()
            for candidate in candidates:
                key = coordinate_key(candidate)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(candidate)
                if len(selected) >= args.top_k:
                    break
            packets.append({
                **packet,
                "unique_api_candidates": selected,
                "mapping_memory_applied": entry is not None,
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(packet, ensure_ascii=False) + "\n" for packet in packets),
        encoding="utf-8",
    )
    summary = {
        "schema_version": "kosis-mapping-memory-application-v1",
        "prediction_packets": len(packets),
        "memory_matches": matched,
        "memory_match_rate": matched / len(packets) if packets else 0.0,
        "top_k": args.top_k,
        "blind_labels_used": 0,
    }
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
