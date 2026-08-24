#!/usr/bin/env python3
"""Hydrate only reranked KOSIS tables missing local ITEM/OBJ metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from kosis_build_meta_index import RequestRateLimiter, fetch_table
from kosis_postgres_store import PostgresKosisMetadataStore


CHECKPOINT_VERSION = "kosis-selective-hydration-v1"
API_CONTRACT_VERSION = "kosis-getMeta-ITM-PRD-v1"


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def read_packets(path: Path) -> list[dict[str, Any]]:
    packets = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL row {number} must be an object")
                packets.append(value)
    return packets


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_manifest_path(path: Path) -> Path:
    return path.with_name(path.name + ".manifest.json")


def ensure_checkpoint_manifest(
    checkpoint: Path, *, candidates_sha256: str, parent_snapshot_id: str,
) -> dict[str, Any]:
    path = checkpoint_manifest_path(checkpoint)
    expected = {
        "checkpoint_version": CHECKPOINT_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "candidates_sha256": candidates_sha256,
        "parent_snapshot_id": parent_snapshot_id,
        "implementation_sha256": sha256_file(Path(__file__)),
    }
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        mismatch = {
            key: (current.get(key), value) for key, value in expected.items()
            if current.get(key) != value
        }
        if mismatch:
            raise RuntimeError(f"hydration checkpoint fingerprint mismatch: {mismatch}")
        return current
    manifest = dict(expected)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
    return manifest


def prioritized_candidates(path: Path, *, per_claim_limit: int = 3) -> list[dict[str, Any]]:
    """Deduplicate table candidates while preserving useful retrieval priority."""
    aggregate: dict[tuple[str, str], dict[str, Any]] = {}
    for packet in read_packets(path):
        candidates = list(packet.get("table_candidates") or packet.get("candidates") or [])
        for fallback_rank, raw in enumerate(candidates[:per_claim_limit], 1):
            candidate = dict(raw.get("table") or raw)
            key = (text(candidate.get("org_id")), text(candidate.get("tbl_id")))
            if not all(key):
                continue
            rank = int(candidate.get("rank") or raw.get("rank") or fallback_rank)
            scores = dict(candidate.get("scores") or raw.get("scores") or {})
            reranker = scores.get("reranker_score", candidate.get("reranker_score"))
            entry = aggregate.setdefault(key, {
                "org_id": key[0], "tbl_id": key[1],
                "tbl_name": text(candidate.get("tbl_name")),
                "category_path": text(candidate.get("category_path")),
                "claim_count": 0, "best_rank": rank,
                "best_reranker_score": float(reranker) if reranker is not None else None,
            })
            entry["claim_count"] += 1
            entry["best_rank"] = min(entry["best_rank"], rank)
            if reranker is not None:
                value = float(reranker)
                current = entry["best_reranker_score"]
                entry["best_reranker_score"] = value if current is None else max(current, value)
    return sorted(aggregate.values(), key=lambda row: (
        int(row["best_rank"]), -int(row["claim_count"]),
        -(row["best_reranker_score"] if row["best_reranker_score"] is not None else -1e9),
        row["org_id"], row["tbl_id"],
    ))


def periodicities(row: dict[str, Any]) -> list[tuple[str, str]]:
    ranges: dict[str, str] = {}
    for value in filter(None, (text(part) for part in text(row.get("prd_ranges")).split(";"))):
        code, separator, _rest = value.partition(":")
        if separator and text(code):
            ranges.setdefault(text(code), value)
    codes = [text(code) for code in text(row.get("prd_se_list")).split("|") if text(code)]
    for code in ranges:
        if code not in codes:
            codes.append(code)
    return [(code, ranges.get(code, "")) for code in codes]


def normalize_table_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    if not rows:
        raise ValueError("empty metadata rows")
    first = rows[0]
    org_id, tbl_id = text(first.get("org_id")), text(first.get("tbl_id"))
    relations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axes: dict[str, dict[str, Any]] = {}
    periods = set(periodicities(first))
    for index, row in enumerate(rows, 1):
        if (text(row.get("org_id")), text(row.get("tbl_id"))) != (org_id, tbl_id):
            raise ValueError(f"mixed table key at metadata row {index}")
        axis_id = text(row.get("axis_id"))
        code_id = text(row.get("code_id"))
        if not axis_id or not code_id:
            raise ValueError(f"missing axis/code identifier at metadata row {index}")
        periods.update(periodicities(row))
        if axis_id.upper() == "ITEM" or text(row.get("is_item")).upper() == "Y":
            relations["items"].append({
                "org_id": org_id, "tbl_id": tbl_id, "item_id": code_id,
                "item_name": text(row.get("code_name")),
                "parent_item_id": text(row.get("parent_code_id")),
                "unit_id": text(row.get("unit_id")), "unit_name": text(row.get("unit_name")),
                "unit_eng_name": text(row.get("unit_eng_name")),
            })
            continue
        try:
            axis_order = int(float(text(row.get("axis_order"))))
        except ValueError as error:
            raise ValueError(f"invalid axis order at metadata row {index}") from error
        if axis_order <= 0:
            raise ValueError(f"invalid axis order at metadata row {index}")
        axis = {
            "org_id": org_id, "tbl_id": tbl_id, "axis_id": axis_id,
            "axis_name": text(row.get("axis_name")), "axis_order": axis_order,
        }
        if axis_id in axes and axes[axis_id] != axis:
            raise ValueError(f"conflicting axis definition: {axis_id}")
        axes[axis_id] = axis
        relations["axis_values"].append({
            "org_id": org_id, "tbl_id": tbl_id, "axis_id": axis_id,
            "value_id": code_id, "value_name": text(row.get("code_name")),
            "parent_value_id": text(row.get("parent_code_id")),
        })
    relations["axes"] = sorted(axes.values(), key=lambda row: (row["axis_order"], row["axis_id"]))
    relations["periodicities"] = [
        {"org_id": org_id, "tbl_id": tbl_id, "prd_se": code, "range_text": span}
        for code, span in sorted(periods)
    ]
    if not relations["items"]:
        raise ValueError("metadata has no ITEM rows")
    if not relations["axes"]:
        raise ValueError("metadata has no OBJ axes")
    values_by_axis = {row["axis_id"] for row in relations["axis_values"]}
    if any(axis["axis_id"] not in values_by_axis for axis in relations["axes"]):
        raise ValueError("metadata has an OBJ axis without values")
    if not relations["periodicities"]:
        raise ValueError("metadata has no periodicity rows")
    for relation in relations:
        unique = {json.dumps(row, ensure_ascii=False, sort_keys=True): row for row in relations[relation]}
        relations[relation] = [unique[key] for key in sorted(unique)]
    return dict(relations)


def checkpoint_records(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    return {
        (text(row.get("org_id")), text(row.get("tbl_id"))): row
        for row in read_packets(path) if row.get("status") == "complete"
    }


def repair_truncated_jsonl(path: Path) -> bool:
    """Drop only an invalid final line left by an interrupted append."""
    if not path.exists():
        return False
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if not lines:
        return False
    try:
        json.loads(lines[-1].decode("utf-8"))
        return False
    except (UnicodeDecodeError, json.JSONDecodeError):
        if any(not line.strip() for line in lines[:-1]):
            raise RuntimeError(f"corrupt hydration checkpoint: {path}")
        temporary = path.with_suffix(path.suffix + ".repair")
        temporary.write_bytes(b"".join(lines[:-1]))
        temporary.replace(path)
        return True


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--dsn", default=os.environ.get("KOSIS_POSTGRES_DSN", ""))
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--failures", type=Path)
    parser.add_argument("--per-claim-table-limit", type=int, default=3)
    parser.add_argument("--max-tables", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if not args.dsn:
        parser.error("--dsn or KOSIS_POSTGRES_DSN is required")
    if args.per_claim_table_limit <= 0 or not 1 <= args.workers <= 8:
        parser.error("invalid table limit or worker count")
    failures_path = args.failures or args.checkpoint.with_name(args.checkpoint.stem + ".failures.jsonl")

    candidates = prioritized_candidates(
        args.candidates, per_claim_limit=args.per_claim_table_limit,
    )
    with PostgresKosisMetadataStore(args.dsn) as store:
        active = store.active_snapshot()
        if active is None:
            raise RuntimeError("no active KOSIS metadata snapshot")
        repair_truncated_jsonl(args.checkpoint)
        ensure_checkpoint_manifest(
            args.checkpoint, candidates_sha256=sha256_file(args.candidates),
            parent_snapshot_id=text(active["snapshot_id"]),
        )
        missing = set(store.incomplete_component_keys(candidates))
        todo = [row for row in candidates if (row["org_id"], row["tbl_id"]) in missing]
        completed = checkpoint_records(args.checkpoint)
        pending = [row for row in todo if (row["org_id"], row["tbl_id"]) not in completed]
        if args.max_tables:
            pending = pending[:args.max_tables]
        print(
            f"candidate_tables={len(candidates)} incomplete={len(todo)} "
            f"checkpointed={len(completed)} pending={len(pending)}",
            flush=True,
        )
        if args.plan_only:
            return
        if not os.environ.get("KOSIS_API_KEY", "").strip():
            raise RuntimeError("KOSIS_API_KEY is not configured")
        limiter = RequestRateLimiter(args.delay)
        window_size = max(args.workers, args.workers * 4)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            processed = 0
            for start in range(0, len(pending), window_size):
                window = pending[start:start + window_size]
                futures = {
                    executor.submit(fetch_table, row, True, args.retries, limiter): row
                    for row in window
                }
                for future in as_completed(futures):
                    processed += 1
                    result = future.result()
                    table = result["table"]
                    key = (text(table.get("org_id")), text(table.get("tbl_id")))
                    if result["failure"] is not None:
                        append_jsonl(failures_path, {"status": "failed", **result["failure"]})
                        print(f"[{processed}/{len(pending)}] failed={key[0]}/{key[1]}", flush=True)
                        continue
                    try:
                        normalize_table_rows(result["rows"])
                    except ValueError as error:
                        append_jsonl(failures_path, {
                            "status": "invalid_metadata", **table, "error": str(error),
                        })
                        print(f"[{processed}/{len(pending)}] invalid={key[0]}/{key[1]} {error}", flush=True)
                        continue
                    packet = {"status": "complete", **table, "rows": result["rows"]}
                    append_jsonl(args.checkpoint, packet)
                    completed[key] = packet
                    print(f"[{processed}/{len(pending)}] complete={key[0]}/{key[1]} rows={len(result['rows'])}", flush=True)

        successful = {
            key: packet for key, packet in checkpoint_records(args.checkpoint).items()
            if key in missing
        }
        relations: dict[str, list[dict[str, Any]]] = {
            "items": [], "axes": [], "axis_values": [], "periodicities": [],
        }
        digest = hashlib.sha256()
        for key in sorted(successful):
            packet = successful[key]
            normalized = normalize_table_rows(packet["rows"])
            digest.update(json.dumps(packet, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            for relation in relations:
                relations[relation].extend(normalized[relation])
        if not successful:
            print("No successfully fetched metadata to apply.", flush=True)
            return
        summary = store.apply_component_hydration_snapshot(
            relations, hydration_sha256=digest.hexdigest(),
            hydrated_table_keys=sorted(successful),
        )
        remaining = store.incomplete_component_keys(candidates)
        print(json.dumps({**summary, "remaining_incomplete": len(remaining)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
