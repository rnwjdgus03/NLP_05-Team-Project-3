#!/usr/bin/env python3
"""Merge local Top-3, local rank 4-5 fallback, and KOSIS MCP Top-2.

This module defines the boundary immediately before KOSIS API comparison. It
does not fetch metadata, call KOSIS, or decide whether a claim is true.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Mapping, Sequence


SUGGESTION_SCHEMA_VERSION = "kosis-coordinate-suggestions-v1"
MERGE_SCHEMA_VERSION = "kosis-coordinate-merge-v2"
SOURCE_RANKS = {
    "local_reranker": (1, 2, 3),
    "local_reranker_fallback": (1, 2),
    "kosis_mcp": (1, 2),
}
SOURCE_ORDER = tuple(SOURCE_RANKS)
COORDINATE_FIELDS = (
    "org_id",
    "tbl_id",
    "item_id",
    "axis_values",
    "prd_se",
    "target_period",
    "previous_period",
    "aggregation",
)


class CoordinateContractError(ValueError):
    """Raised when an input JSONL record violates the coordinate contract."""


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def canonical_coordinate(coordinate: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic coordinate representation used for dedupe."""
    if not isinstance(coordinate, Mapping):
        raise CoordinateContractError("coordinate must be an object")
    missing = [field for field in COORDINATE_FIELDS if field not in coordinate]
    if missing:
        raise CoordinateContractError(
            f"coordinate is missing required fields: {', '.join(missing)}"
        )

    org_id = _text(coordinate["org_id"])
    tbl_id = _text(coordinate["tbl_id"])
    item_id = _text(coordinate["item_id"])
    if not org_id or not tbl_id or not item_id:
        raise CoordinateContractError("org_id, tbl_id, and item_id must be non-empty")

    raw_axes = coordinate["axis_values"]
    if not isinstance(raw_axes, list):
        raise CoordinateContractError("axis_values must be an array")
    axes: list[dict[str, Any]] = []
    seen_orders: set[int] = set()
    for raw_axis in raw_axes:
        if not isinstance(raw_axis, Mapping):
            raise CoordinateContractError("each axis_values entry must be an object")
        try:
            axis_order = int(raw_axis["axis_order"])
        except (KeyError, TypeError, ValueError) as error:
            raise CoordinateContractError(
                "axis_order must be a positive integer"
            ) from error
        axis_id = _text(raw_axis.get("axis_id"))
        value_id = _text(raw_axis.get("value_id"))
        if axis_order < 1 or not axis_id or not value_id:
            raise CoordinateContractError(
                "axis_order, axis_id, and value_id must identify every axis value"
            )
        if axis_order in seen_orders:
            raise CoordinateContractError(f"duplicate axis_order: {axis_order}")
        seen_orders.add(axis_order)
        axes.append({
            "axis_order": axis_order,
            "axis_id": axis_id,
            "value_id": value_id,
        })
    axes.sort(key=lambda row: row["axis_order"])

    return {
        "org_id": org_id,
        "tbl_id": tbl_id,
        "item_id": item_id,
        "axis_values": axes,
        "prd_se": _text(coordinate["prd_se"]).upper(),
        "target_period": _text(coordinate["target_period"]),
        "previous_period": _text(coordinate["previous_period"]),
        "aggregation": _text(coordinate["aggregation"]).lower(),
    }


def canonical_coordinate_json(coordinate: Mapping[str, Any]) -> str:
    return json.dumps(
        canonical_coordinate(coordinate),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def coordinate_id(coordinate: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_coordinate_json(coordinate).encode("utf-8"))
    return f"kosis-coordinate-sha256:{digest.hexdigest()}"


def validate_suggestion_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one local or MCP JSONL packet."""
    if not isinstance(packet, Mapping):
        raise CoordinateContractError("suggestion packet must be an object")
    allowed_packet_fields = {
        "schema_version", "claim_measurement_id", "source", "suggestions",
    }
    unknown = set(packet) - allowed_packet_fields
    if unknown:
        raise CoordinateContractError(
            f"unexpected suggestion packet fields: {', '.join(sorted(unknown))}"
        )
    if packet.get("schema_version") != SUGGESTION_SCHEMA_VERSION:
        raise CoordinateContractError(
            f"schema_version must be {SUGGESTION_SCHEMA_VERSION}"
        )
    claim_id = _text(packet.get("claim_measurement_id"))
    source = _text(packet.get("source"))
    if not claim_id:
        raise CoordinateContractError("claim_measurement_id must be non-empty")
    if source not in SOURCE_RANKS:
        raise CoordinateContractError(f"unsupported source: {source!r}")
    suggestions = packet.get("suggestions")
    if not isinstance(suggestions, list):
        raise CoordinateContractError("suggestions must be an array")

    expected_ranks = SOURCE_RANKS[source]
    actual_ranks = tuple(row.get("source_rank") for row in suggestions if isinstance(row, Mapping))
    if len(suggestions) != len(expected_ranks) or actual_ranks != expected_ranks:
        raise CoordinateContractError(
            f"{source} suggestions must contain ranks {list(expected_ranks)} in order"
        )

    normalized: list[dict[str, Any]] = []
    allowed_suggestion_fields = {
        "source", "source_rank", "coordinate", "score", "rationale", "evidence",
    }
    for suggestion in suggestions:
        if not isinstance(suggestion, Mapping):
            raise CoordinateContractError("each suggestion must be an object")
        unknown = set(suggestion) - allowed_suggestion_fields
        if unknown:
            raise CoordinateContractError(
                f"unexpected suggestion fields: {', '.join(sorted(unknown))}"
            )
        if suggestion.get("source") != source:
            raise CoordinateContractError("suggestion source must match packet source")
        score = suggestion.get("score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
            raise CoordinateContractError("score must be a number or null")
        rationale = suggestion.get("rationale", "")
        evidence = suggestion.get("evidence", {})
        if not isinstance(rationale, str):
            raise CoordinateContractError("rationale must be a string")
        if not isinstance(evidence, Mapping):
            raise CoordinateContractError("evidence must be an object")
        normalized.append({
            "source": source,
            "source_rank": int(suggestion["source_rank"]),
            "coordinate": canonical_coordinate(suggestion.get("coordinate", {})),
            "score": score,
            "rationale": rationale,
            "evidence": dict(evidence),
        })

    return {
        "schema_version": SUGGESTION_SCHEMA_VERSION,
        "claim_measurement_id": claim_id,
        "source": source,
        "suggestions": normalized,
    }


def merge_coordinate_packets(
    local_packet: Mapping[str, Any],
    mcp_packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge one claim's local Top-3 and MCP Top-2 without API calls."""
    return merge_fallback_coordinate_packets(local_packet, mcp_packet)


def merge_fallback_coordinate_packets(
    local_packet: Mapping[str, Any] | None,
    mcp_packet: Mapping[str, Any] | None,
    local_fallback_packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve available branches; verifier decides whether MCP fallback runs.

    A missing Local packet must no longer drop the claim before MCP fallback,
    and a missing MCP packet must not invalidate an otherwise usable Local run.
    """
    if local_packet is None and mcp_packet is None and local_fallback_packet is None:
        raise CoordinateContractError("at least one coordinate packet is required")
    packets = {}
    if local_packet is not None:
        packets["local_reranker"] = validate_suggestion_packet(local_packet)
    if local_fallback_packet is not None:
        packets["local_reranker_fallback"] = validate_suggestion_packet(
            local_fallback_packet
        )
    if mcp_packet is not None:
        packets["kosis_mcp"] = validate_suggestion_packet(mcp_packet)
    for expected_source, packet in packets.items():
        if packet["source"] != expected_source:
            raise CoordinateContractError(
                f"expected {expected_source} packet, got {packet['source']}"
            )
    claim_ids = {packet["claim_measurement_id"] for packet in packets.values()}
    if len(claim_ids) != 1:
        raise CoordinateContractError("local and MCP claim_measurement_id must match")

    raw_suggestions = [
        suggestion
        for source in SOURCE_ORDER
        for suggestion in packets.get(source, {}).get("suggestions", [])
    ]
    unique: list[dict[str, Any]] = []
    by_canonical_json: dict[str, dict[str, Any]] = {}
    for raw_index, suggestion in enumerate(raw_suggestions, 1):
        key = canonical_coordinate_json(suggestion["coordinate"])
        candidate = by_canonical_json.get(key)
        if candidate is None:
            candidate = {
                "api_rank": len(unique) + 1,
                "coordinate_id": coordinate_id(suggestion["coordinate"]),
                "coordinate": suggestion["coordinate"],
                "source_support": [],
                "raw_suggestion_indexes": [],
            }
            by_canonical_json[key] = candidate
            unique.append(candidate)
        candidate["raw_suggestion_indexes"].append(raw_index)
        support = next((
            row for row in candidate["source_support"]
            if row["source"] == suggestion["source"]
        ), None)
        if support is None:
            support = {"source": suggestion["source"], "source_ranks": []}
            candidate["source_support"].append(support)
        support["source_ranks"].append(suggestion["source_rank"])

    return {
        "schema_version": MERGE_SCHEMA_VERSION,
        "pipeline_stage": "coordinate-candidate-merge-before-kosis-api",
        "claim_measurement_id": claim_ids.pop(),
        "raw_suggestions": raw_suggestions,
        "unique_api_candidate_count": len(unique),
        "unique_api_candidates": unique,
        "kosis_api_called": False,
        "available_sources": list(packets),
        "fallback_policy": (
            "LOCAL_TOP3_PRIMARY_LOCAL_RANK45_THEN_MCP_IF_UNRESOLVED"
            if local_fallback_packet is not None
            else "LOCAL_PRIMARY_MCP_ONLY_IF_LOCAL_UNRESOLVED"
        ),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise CoordinateContractError(
                    f"{path}:{line_number}: invalid JSON: {error.msg}"
                ) from error
            if not isinstance(row, dict):
                raise CoordinateContractError(f"{path}:{line_number}: row must be an object")
            rows.append(row)
    return rows


def _index_packets(
    rows: Iterable[Mapping[str, Any]], source: str, path: Path,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for line_number, row in enumerate(rows, 1):
        try:
            packet = validate_suggestion_packet(row)
        except CoordinateContractError as error:
            raise CoordinateContractError(f"{path}:{line_number}: {error}") from error
        if packet["source"] != source:
            raise CoordinateContractError(
                f"{path}:{line_number}: expected source {source}, got {packet['source']}"
            )
        claim_id = packet["claim_measurement_id"]
        if claim_id in indexed:
            raise CoordinateContractError(f"{path}: duplicate claim_measurement_id {claim_id}")
        indexed[claim_id] = packet
    return indexed


def merge_jsonl_files(
    local_path: Path, mcp_path: Path, output_path: Path, *, allow_partial: bool = False,
) -> int:
    local = _index_packets(read_jsonl(local_path), "local_reranker", local_path)
    mcp = _index_packets(read_jsonl(mcp_path), "kosis_mcp", mcp_path)
    if local.keys() != mcp.keys() and not allow_partial:
        missing_mcp = sorted(local.keys() - mcp.keys())
        missing_local = sorted(mcp.keys() - local.keys())
        raise CoordinateContractError(
            "input claim sets differ; "
            f"missing_mcp={missing_mcp[:10]}, missing_local={missing_local[:10]}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_path.parent,
            prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_name = handle.name
            claim_ids = sorted(set(local) | set(mcp)) if allow_partial else list(local)
            for claim_id in claim_ids:
                merged = merge_fallback_coordinate_packets(
                    local.get(claim_id), mcp.get(claim_id),
                )
                handle.write(json.dumps(merged, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output_path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return len(set(local) | set(mcp)) if allow_partial else len(local)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge local coordinate Top-3 and KOSIS MCP coordinate Top-2 JSONL.",
    )
    parser.add_argument("--local", required=True, type=Path)
    parser.add_argument("--mcp", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--allow-partial", action="store_true",
        help="keep claims emitted by only one branch for fallback verification",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    count = merge_jsonl_files(
        args.local, args.mcp, args.output, allow_partial=args.allow_partial,
    )
    print(f"merged_claims={count} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
