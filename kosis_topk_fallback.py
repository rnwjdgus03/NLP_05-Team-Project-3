#!/usr/bin/env python3
"""Prepare and merge a bounded Top-5 -> Top-10 KOSIS fallback.

Only measurements whose Top-5 validation failed technically are copied into the
Top-10 validation input. READY/PROVISIONAL/NEEDS_CONFIRMATION rows never trigger
additional API calls. A result recovered from ranks 6-10 is always held for
confirmation even if the validator itself returned READY/PROVISIONAL.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from kosis_validate_mapping_candidates import (
    NEEDS_CONFIRMATION,
    PROVISIONAL,
    READY,
    measurement_key,
    needs_fallback,
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields = list(dict.fromkeys(key for row in materialized for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)


def _rank(row: Mapping[str, Any]) -> int:
    try:
        return int(float(str(row.get("candidate_rank", "999"))))
    except (TypeError, ValueError):
        return 999


def best_by_measurement(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        key = measurement_key(row)
        if key:
            grouped[key].append(row)
    return {
        key: sorted(group, key=_rank)[0]
        for key, group in grouped.items()
    }


def prepare_fallback(
    primary_validated: Iterable[Mapping[str, Any]],
    fallback_candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    primary = best_by_measurement(primary_validated)
    output: list[dict[str, Any]] = []
    for source in fallback_candidates:
        row = dict(source)
        key = measurement_key(row)
        first = primary.get(key)
        if not first or not needs_fallback(first):
            continue
        row.update({
            "topk_fallback_triggered": "Y",
            "topk_primary_status": str(first.get("mapping_status", "")),
            "topk_primary_reason": str(first.get("mapping_reason", "")),
            "topk_primary_tbl_id": str(first.get("tbl_id", "")),
        })
        output.append(row)
    return output


def merge_fallback(
    primary_validated: Iterable[Mapping[str, Any]],
    fallback_validated: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    primary = best_by_measurement(primary_validated)
    fallback = best_by_measurement(fallback_validated)
    output: list[dict[str, Any]] = []
    for key, first in primary.items():
        chosen = dict(first)
        second = fallback.get(key)
        attempted = bool(second and needs_fallback(first))
        recovered = bool(attempted and not needs_fallback(second or {}))
        if recovered and second:
            chosen = dict(second)
        fallback_raw_status = str((second or {}).get("mapping_status", ""))
        auto_ready_blocked = bool(
            recovered and fallback_raw_status in {READY, PROVISIONAL}
        )
        if auto_ready_blocked:
            chosen["mapping_status"] = NEEDS_CONFIRMATION
            chosen["mapping_reason"] = "TOP10_FALLBACK_REQUIRES_CONFIRMATION"
        chosen.update({
            "topk_source": "TOP10_FALLBACK" if recovered else "TOP5_PRIMARY",
            "topk_fallback_attempted": "Y" if attempted else "N",
            "topk_fallback_recovered": "Y" if recovered else "N",
            "topk_fallback_auto_ready_blocked": "Y" if auto_ready_blocked else "N",
            "topk_primary_status": str(first.get("mapping_status", "")),
            "topk_primary_reason": str(first.get("mapping_reason", "")),
            "topk_fallback_status": fallback_raw_status,
            "topk_fallback_reason": str((second or {}).get("mapping_reason", "")),
        })
        output.append(chosen)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--primary-validated", type=Path, required=True)
    prepare.add_argument("--fallback-candidates", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)

    merge = subparsers.add_parser("merge")
    merge.add_argument("--primary-validated", type=Path, required=True)
    merge.add_argument("--fallback-validated", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        rows = prepare_fallback(
            read_csv(args.primary_validated), read_csv(args.fallback_candidates)
        )
    else:
        rows = merge_fallback(
            read_csv(args.primary_validated), read_csv(args.fallback_validated)
        )
    write_csv(args.output, rows)
    print(f"command={args.command} rows={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
