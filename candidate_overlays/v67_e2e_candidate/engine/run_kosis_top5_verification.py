#!/usr/bin/env python3
"""Verify Local Top-3, Local rank 4-5, then exact-validated MCP fallback."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from kosis_coordinate_merge import canonical_coordinate_json, coordinate_id, read_jsonl
from kosis_hybrid_top3 import read_csv
from kosis_meta_coordinates import normalize_periodicity
from kosis_metadata_store import SQLiteAPIResponseCache, SQLiteKosisRequestLimiter
from kosis_postgres_store import PostgresKosisMetadataStore
from kosis_period_range import period_in_ranges
from kosis_verify_claim_values import parse_period, unit_factor, verify_row


LOCAL_SOURCES = {"local_reranker", "local_reranker_fallback"}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def prepared_claim_id(row: Mapping[str, Any]) -> str:
    claim_id = _text(row.get("claim_measurement_id") or row.get("claim_id"))
    return "" if claim_id in {"", "-"} else claim_id


def decision_failure_counts(
    claim: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Keep the prepare/retrieval reason when no coordinate was produced."""
    verdicts = Counter(_text(row.get("verdict_code")) for row in rows)
    stages = Counter(_text(row.get("verdict_stage")) or "unknown" for row in rows)
    if rows:
        return dict(verdicts), dict(stages)
    code = _text(claim.get("mapping_exclusion_code"))
    if code and code != "ELIGIBLE":
        verdicts[code] += 1
        stages["gate"] += 1
    else:
        fallback = _text(claim.get("retrieval_fallback_code"))
        verdicts[fallback or "RETRIEVAL_NO_CANDIDATE"] += 1
        stages["retrieval"] += 1
    return dict(verdicts), dict(stages)


def hydrate_postgres_catalog(
    store: PostgresKosisMetadataStore,
    tables: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], dict[str, Any]]]:
    """Return verifier metadata plus an exact ITEM/OBJ/periodicity catalog."""
    if not tables:
        return {}, {}
    with store.metadata_read_guard():
        bundle = store.hydrate_component_bundle(tables)

    meta_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    for table in bundle["tables"]:
        key = (_text(table.get("org_id")), _text(table.get("tbl_id")))
        catalog[key] = {
            "table": dict(table), "items": {}, "axes": {},
            "periodicities": {
                normalize_periodicity(value)
                for value in _text(table.get("prd_se")).split("|")
                if normalize_periodicity(value)
            },
            "periodicity_rows": list(table.get("periodicities") or []),
        }

    for item in bundle["items"]:
        key = (_text(item.get("org_id")), _text(item.get("tbl_id")))
        if key not in catalog:
            continue
        item_id = _text(item.get("itm_id"))
        catalog[key]["items"][item_id] = dict(item)
        meta_cache.setdefault(key, []).append({
            "OBJ_ID": "ITEM", "OBJ_NM": "항목", "OBJ_ID_SN": "0",
            "ITM_ID": item_id, "ITM_NM": _text(item.get("itm_name")),
            "UP_ITM_ID": _text(item.get("parent_code_id")),
            "UNIT_ID": "", "UNIT_NM": _text(item.get("unit")),
            "UNIT_ENG_NM": "",
        })

    for obj in bundle["objects"]:
        key = (_text(obj.get("org_id")), _text(obj.get("tbl_id")))
        if key not in catalog:
            continue
        axis_id = _text(obj.get("axis_id"))
        value_id = _text(obj.get("obj_code"))
        axis = catalog[key]["axes"].setdefault(axis_id, {
            "axis_id": axis_id,
            "axis_name": _text(obj.get("axis_name")),
            "axis_order": int(obj.get("axis_order") or 0),
            "values": {},
        })
        axis["values"][value_id] = dict(obj)
        meta_cache.setdefault(key, []).append({
            "OBJ_ID": axis_id, "OBJ_NM": axis["axis_name"],
            "OBJ_ID_SN": str(axis["axis_order"]),
            "ITM_ID": value_id, "ITM_NM": _text(obj.get("obj_name")),
            "UP_ITM_ID": _text(obj.get("parent_code_id")),
            "UNIT_ID": "", "UNIT_NM": "", "UNIT_ENG_NM": "",
        })
    return meta_cache, catalog


def evidence_for_coordinate(
    packet: Mapping[str, Any], coordinate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    key = canonical_coordinate_json(coordinate)
    return [
        dict(suggestion)
        for suggestion in packet.get("raw_suggestions") or []
        if canonical_coordinate_json(suggestion.get("coordinate") or {}) == key
    ]


def align_period(
    coordinate: Mapping[str, Any], claim: Mapping[str, Any], supported: set[str],
) -> dict[str, str]:
    requested = normalize_periodicity(
        coordinate.get("prd_se") or claim.get("prd_se")
        or claim.get("measurement_prd_se")
    )
    aggregation = _text(
        coordinate.get("aggregation") or claim.get("period_aggregation")
    ).lower()
    target_raw = (
        coordinate.get("target_period") or claim.get("period")
        or claim.get("measurement_period")
    )
    previous_raw = (
        coordinate.get("previous_period") or claim.get("comparison_period")
        or claim.get("previous_period")
    )
    target_shape = parse_period(target_raw)
    previous_shape = parse_period(previous_raw)
    target = normalize_api_period(
        target_raw, requested,
    )
    previous = normalize_api_period(
        previous_raw, requested,
    )
    if requested in supported:
        api_prd_se, state = requested, "exact"
    elif requested == "Y" and aggregation in {"sum", "latest"}:
        api_prd_se = "M" if "M" in supported else "Q" if "Q" in supported else ""
        state = "aggregate_compatible" if api_prd_se else "mismatch"
    elif len(target_shape) == 4 and "Y" in supported:
        api_prd_se, state = "Y", "period_shape_inference"
        target = normalize_api_period(target, api_prd_se)
        previous = normalize_api_period(previous, api_prd_se)
    elif len(target_shape) == 6 and "M" in supported:
        api_prd_se, state = "M", "period_shape_inference"
        target = normalize_api_period(target_raw, api_prd_se)
        previous = normalize_api_period(previous_raw, api_prd_se)
    elif not requested and len(supported) == 1:
        api_prd_se, state = next(iter(supported)), "single_supported_inference"
        target = normalize_api_period(target, api_prd_se)
        previous = normalize_api_period(previous, api_prd_se)
    else:
        api_prd_se, state = "", "mismatch"
    return {
        "requested_prd_se": requested,
        "api_prd_se": api_prd_se,
        "period_alignment_state": state,
        "normalized_target_period": target,
        "normalized_previous_period": previous,
        "supported_periodicities": "|".join(sorted(supported)),
    }


def normalize_api_period(value: Any, prd_se: str) -> str:
    """Normalize Korean year/month/quarter labels for the KOSIS API."""
    raw = _text(value)
    if not raw:
        return ""
    year_match = re.search(r"((?:19|20)\d{2})", raw)
    if not year_match:
        return parse_period(raw)
    year = year_match.group(1)
    if prd_se == "Y":
        return year
    quarter = re.search(r"Q\s*([1-4])|([1-4])\s*분기", raw, re.I)
    if prd_se == "Q" and quarter:
        return f"{year}0{quarter.group(1) or quarter.group(2)}"
    month = re.search(r"(?:19|20)\d{2}\D*(1[0-2]|0?[1-9])", raw)
    if prd_se == "M" and month:
        return f"{year}{int(month.group(1)):02d}"
    return year


def mcp_independent_preflight(
    coordinate: Mapping[str, Any], claim: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare an MCP-only coordinate without consulting PostgreSQL.

    The official KOSIS metadata and data APIs remain responsible for validating
    the ITEM/OBJ codes.  This preserves the intended independence of the MCP
    branch instead of turning PostgreSQL coverage into an MCP recall filter.
    """
    prd_se = normalize_periodicity(
        coordinate.get("prd_se") or claim.get("prd_se")
        or claim.get("measurement_prd_se")
    )
    if not prd_se:
        parsed = parse_period(
            coordinate.get("target_period") or claim.get("period")
            or claim.get("measurement_period")
        )
        prd_se = "M" if len(parsed) == 6 else "Y" if len(parsed) == 4 else ""
    target = normalize_api_period(
        coordinate.get("target_period") or claim.get("period")
        or claim.get("measurement_period"), prd_se,
    )
    previous = normalize_api_period(
        coordinate.get("previous_period") or claim.get("comparison_period")
        or claim.get("previous_period"), prd_se,
    )
    valid = bool(
        _text(coordinate.get("org_id"))
        and _text(coordinate.get("tbl_id"))
        and _text(coordinate.get("item_id"))
    )
    return {
        "requested_prd_se": prd_se,
        "api_prd_se": prd_se,
        "period_alignment_state": "mcp_declared",
        "normalized_target_period": target,
        "normalized_previous_period": previous,
        "supported_periodicities": "",
        "postgres_coordinate_status": "NOT_APPLICABLE_MCP_INDEPENDENT",
        "postgres_coordinate_valid": False,
        "coordinate_preflight_source": "kosis_mcp",
        "coordinate_preflight_valid": valid,
        "postgres_period_in_range": None,
        "repaired_axis_values": list(coordinate.get("axis_values") or []),
        "repair_history": [],
        "unit_precheck_state": "official_api_validation_pending",
        "official_item_name": "",
        "official_item_unit": "",
        "official_table_name": "",
        "preflight_reason": (
            "MCP-only candidate bypasses PostgreSQL; official KOSIS metadata/API "
            "validates the coordinate"
        ),
    }


def _period_in_range(target: str, rows: Sequence[Mapping[str, Any]], prd_se: str) -> bool | None:
    return period_in_ranges(target, rows, prd_se)


def postgres_preflight(
    coordinate: Mapping[str, Any], claim: Mapping[str, Any],
    table_catalog: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if table_catalog is None:
        return {
            "postgres_coordinate_status": "TABLE_NOT_COMPLETE_IN_POSTGRES",
            "postgres_coordinate_valid": False,
            "period_alignment_state": "unknown",
            "unit_precheck_state": "unknown",
            "preflight_reason": "candidate table has no complete PostgreSQL component bundle",
        }
    item = table_catalog["items"].get(_text(coordinate.get("item_id")))
    if item is None:
        return {
            "postgres_coordinate_status": "ITEM_NOT_IN_POSTGRES",
            "postgres_coordinate_valid": False,
            "period_alignment_state": "unknown",
            "unit_precheck_state": "unknown",
            "preflight_reason": "MCP/local ITEM code is absent from official PostgreSQL metadata",
        }

    candidate_axes = list(coordinate.get("axis_values") or [])
    candidate_axis_ids = [_text(axis.get("axis_id")) for axis in candidate_axes]
    candidate_axis_orders = [_text(axis.get("axis_order")) for axis in candidate_axes]
    duplicate_axis_ids = sorted({
        axis_id for axis_id in candidate_axis_ids
        if axis_id and candidate_axis_ids.count(axis_id) > 1
    })
    duplicate_axis_orders = sorted({
        order for order in candidate_axis_orders
        if order and candidate_axis_orders.count(order) > 1
    })
    supplied = {
        _text(axis.get("axis_id")): _text(axis.get("value_id"))
        for axis in candidate_axes
    }
    official_axes = table_catalog["axes"]
    axis_order_mismatches = sorted(
        axis_id for axis_id, axis in zip(candidate_axis_ids, candidate_axes)
        if axis_id in official_axes
        and str(official_axes[axis_id].get("axis_order"))
        != _text(axis.get("axis_order"))
    )
    repaired_axes = candidate_axes
    repair_history: list[str] = []
    missing_axes = sorted(set(official_axes) - set(supplied))
    for axis_id in list(missing_axes):
        aggregate_values = [
            value for value in official_axes[axis_id]["values"].values()
            if value.get("is_aggregate")
        ]
        if len(aggregate_values) != 1:
            continue
        value = aggregate_values[0]
        supplied[axis_id] = _text(value.get("obj_code"))
        repaired_axes.append({
            "axis_order": official_axes[axis_id]["axis_order"],
            "axis_id": axis_id,
            "value_id": supplied[axis_id],
        })
        missing_axes.remove(axis_id)
        repair_history.append(
            f"default_axis:{axis_id}={supplied[axis_id]}({_text(value.get('obj_name'))})"
        )
    unknown_axes = sorted(set(supplied) - set(official_axes))
    invalid_values = sorted(
        axis_id for axis_id, value_id in supplied.items()
        if axis_id in official_axes and value_id not in official_axes[axis_id]["values"]
    )
    valid = not (
        missing_axes or unknown_axes or invalid_values
        or duplicate_axis_ids or duplicate_axis_orders or axis_order_mismatches
    )
    repaired_axes.sort(key=lambda axis: int(axis.get("axis_order") or 999))
    period = align_period(coordinate, claim, set(table_catalog["periodicities"]))
    mapping_type = _text(claim.get("mapping_type")) or "direct"
    claim_unit = claim.get("canonical_unit") or claim.get("unit")
    if mapping_type == "rate_from_level":
        factor, unit_reason = 1.0, "level values may derive a rate"
    elif (
        mapping_type == "difference_from_level"
        and _text(item.get("canonical_unit") or item.get("unit")) == "%"
        and _text(claim_unit) == "%p"
    ):
        factor, unit_reason = 1.0, "percentage-level difference derives percentage points"
    else:
        factor, unit_reason = unit_factor(item.get("unit"), claim_unit)
    unit_state = "compatible" if factor is not None else "incompatible"
    reasons = []
    if missing_axes:
        reasons.append("missing_axes=" + ",".join(missing_axes))
    if unknown_axes:
        reasons.append("unknown_axes=" + ",".join(unknown_axes))
    if invalid_values:
        reasons.append("invalid_values=" + ",".join(invalid_values))
    if duplicate_axis_ids:
        reasons.append("duplicate_axis_ids=" + ",".join(duplicate_axis_ids))
    if duplicate_axis_orders:
        reasons.append("duplicate_axis_orders=" + ",".join(duplicate_axis_orders))
    if axis_order_mismatches:
        reasons.append("axis_order_mismatches=" + ",".join(axis_order_mismatches))
    if period["period_alignment_state"] == "mismatch":
        reasons.append("periodicity_mismatch")
    period_in_range = _period_in_range(
        period["normalized_target_period"],
        table_catalog.get("periodicity_rows") or [],
        period["api_prd_se"],
    )
    if period_in_range is False:
        reasons.append("period_out_of_range")
    if unit_state == "incompatible":
        reasons.append(unit_reason)
    return {
        **period,
        "postgres_coordinate_status": (
            "REPAIRED_DEFAULT_AXIS" if valid and repair_history else
            "VALID" if valid else "INVALID_AXIS_COORDINATE"
        ),
        "postgres_coordinate_valid": valid,
        "postgres_period_in_range": period_in_range,
        "repaired_axis_values": repaired_axes,
        "repair_history": repair_history,
        "unit_precheck_state": unit_state,
        "official_item_name": _text(item.get("itm_name")),
        "official_item_unit": _text(item.get("unit")),
        "official_table_name": _text(table_catalog["table"].get("tbl_name")),
        "preflight_reason": " | ".join(reasons),
    }


def verification_input(
    claim: Mapping[str, Any], packet: Mapping[str, Any], candidate: Mapping[str, Any],
    table_catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    coordinate = dict(candidate["coordinate"])
    suggestions = evidence_for_coordinate(packet, coordinate)
    evidence = dict(suggestions[0].get("evidence") or {}) if suggestions else {}
    sources = sorted({row.get("source", "") for row in suggestions if row.get("source")})
    preflight_claim = dict(claim)
    preflight_claim["mapping_type"] = (
        _text(evidence.get("mapping_type"))
        or _text(claim.get("mapping_type")) or "direct"
    )
    # v19: MCP is no longer exempt from the exact metadata contract.  Both
    # branches must prove that the table, ITEM, every OBJ value and periodicity
    # exist in the same active PostgreSQL snapshot before an API comparison.
    preflight = postgres_preflight(coordinate, preflight_claim, table_catalog)
    preflight["coordinate_preflight_source"] = (
        "postgres_mcp" if sources == ["kosis_mcp"] else "postgres_local"
    )
    preflight["coordinate_preflight_valid"] = bool(
        preflight.get("postgres_coordinate_valid")
    )
    if preflight.get("repaired_axis_values"):
        coordinate["axis_values"] = preflight["repaired_axis_values"]
    object_evidence = {
        int(obj.get("axis_order")): obj
        for obj in evidence.get("objects") or []
        if str(obj.get("axis_order") or "").isdigit()
    }
    source_ranks = {
        source: min(int(row["source_rank"]) for row in suggestions if row.get("source") == source)
        for source in sources
    }
    review_reasons = set(filter(None, (
        _text((row.get("evidence") or {}).get("verification_review_reason"))
        for row in suggestions
    )))
    review_required = any(
        _text((row.get("evidence") or {}).get("verification_review_required")).upper() == "Y"
        for row in suggestions
    )
    if _text(claim.get("verification_review_required")).upper() == "Y":
        review_required = True
        review_reasons.add(
            _text(claim.get("verification_review_reason"))
            or "claim_level_review_required"
        )
    if preflight.get("period_alignment_state") == "single_supported_inference":
        review_required = True
        review_reasons.add("periodicity_single_supported_inference")
    if preflight.get("period_alignment_state") == "period_shape_inference":
        review_reasons.add("periodicity_inferred_from_period_shape")
    if preflight.get("repair_history"):
        review_required = True
        review_reasons.add("postgres_default_axis_repair")

    row = dict(claim)
    row.update({
        "candidate_rank": "1", "candidate_status": "READY",
        "verified_without_confirmation": "Y",
        "org_id": coordinate["org_id"], "tbl_id": coordinate["tbl_id"],
        "tbl_name": preflight.get("official_table_name") or evidence.get("tbl_name", ""),
        "selected_itm_id": coordinate["item_id"],
        "selected_itm_name": preflight.get("official_item_name") or evidence.get("item_name", ""),
        "selected_itm_unit": preflight.get("official_item_unit") or evidence.get("unit", ""),
        "mapping_type": _text(evidence.get("mapping_type"))
        or _text(claim.get("mapping_type")) or "direct",
        "prd_se": preflight.get("requested_prd_se") or coordinate.get("prd_se"),
        "api_prd_se": preflight.get("api_prd_se"),
        "period": preflight.get("normalized_target_period")
        or coordinate.get("target_period") or claim.get("measurement_period") or claim.get("period"),
        "previous_period": preflight.get("normalized_previous_period")
        or coordinate.get("previous_period") or claim.get("previous_period"),
        # kosis_verify_claim_values.verify_row consumes comparison_period.
        # Keep previous_period for the public coordinate contract, but also
        # bridge the value to the verifier's canonical input field.
        "comparison_period": preflight.get("normalized_previous_period")
        or coordinate.get("previous_period") or claim.get("comparison_period")
        or claim.get("previous_period"),
        "period_aggregation": coordinate.get("aggregation") or claim.get("period_aggregation"),
        "source_coordinate_id": candidate["coordinate_id"],
        "coordinate_id": coordinate_id(coordinate),
        "source_support": json.dumps(candidate.get("source_support") or [], ensure_ascii=False),
        "candidate_sources": "|".join(sources),
        "candidate_source_ranks": json.dumps(source_ranks, ensure_ascii=False, sort_keys=True),
        "verification_review_required": "Y" if review_required else "N",
        "verification_review_reason": "|".join(sorted(review_reasons)),
        **preflight,
    })
    official_axes = (table_catalog or {}).get("axes", {})
    for axis in coordinate.get("axis_values") or []:
        level = int(axis["axis_order"])
        local = object_evidence.get(level, {})
        official = official_axes.get(axis["axis_id"], {}).get("values", {}).get(
            axis["value_id"], {}
        )
        row[f"selected_obj_l{level}"] = axis["value_id"]
        row[f"selected_obj_l{level}_name"] = (
            _text(official.get("obj_name")) or _text(local.get("value_name"))
        )
        row[f"selected_obj_l{level}_axis_id"] = axis["axis_id"]
        row[f"selected_obj_l{level}_axis_name"] = (
            _text(official.get("axis_name")) or _text(local.get("axis_name"))
        )
    return row


def normalized_semantic_rank_score(row: Mapping[str, Any]) -> int:
    """Compare heterogeneous retrievers only by within-source rank percentile."""
    ranks = json.loads(_text(row.get("candidate_source_ranks")) or "{}")
    scores = []
    source_sizes = {
        "local_reranker": 3,
        "local_reranker_fallback": 2,
        "kosis_mcp": 2,
    }
    for source, raw_rank in ranks.items():
        size = source_sizes.get(source)
        if not size:
            continue
        rank = max(1, min(size, int(raw_rank)))
        percentile = 1.0 if size == 1 else (size - rank) / (size - 1)
        scores.append(percentile)
    return round(1000 * max(scores, default=0.0))


def coordinate_preflight_valid(row: Mapping[str, Any]) -> bool:
    value = row.get("coordinate_preflight_valid")
    if value is None:
        value = row.get("postgres_coordinate_valid")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _text(value).lower() in {"1", "true", "t", "yes", "y"}


def selection_priority(row: Mapping[str, Any]) -> tuple[int, int, int, int, int, int, int]:
    sources = set(_text(row.get("candidate_sources")).split("|")) - {""}
    ranks = json.loads(_text(row.get("candidate_source_ranks")) or "{}")
    best_rank = min((int(value) for value in ranks.values()), default=99)
    return (
        int(coordinate_preflight_valid(row)),
        int(
            row.get("period_alignment_state") in {
                "exact", "aggregate_compatible", "period_shape_inference",
            }
            and row.get("postgres_period_in_range") is not False
        ),
        1 if row.get("unit_precheck_state") == "compatible"
        else 0 if row.get("unit_precheck_state") == "incompatible"
        else 0,
        int(_text(row.get("verification_review_required")).upper() != "Y"),
        normalized_semantic_rank_score(row),
        2 if len(sources) > 1 else 1 if sources & LOCAL_SOURCES else 0,
        -best_rank,
    )


def verification_fingerprint(row: Mapping[str, Any]) -> tuple[Any, ...]:
    axes = []
    for level in range(1, 9):
        axis_id = _text(row.get(f"selected_obj_l{level}_axis_id"))
        value_id = _text(row.get(f"selected_obj_l{level}"))
        if axis_id or value_id:
            axes.append((level, axis_id, value_id))
    return (
        _text(row.get("org_id")),
        _text(row.get("tbl_id")),
        _text(row.get("selected_itm_id")),
        tuple(axes),
        _text(row.get("api_prd_se") or row.get("prd_se")),
        _text(row.get("period")),
        _text(row.get("previous_period") or row.get("comparison_period")),
        _text(row.get("mapping_type")),
        _text(row.get("period_aggregation")),
    )


def classify(verified: Mapping[str, Any]) -> str:
    review = _text(verified.get("verification_review_required")).upper() == "Y"
    preflight_ok = coordinate_preflight_valid(verified) and (
        verified.get("period_alignment_state") in {
            "exact", "aggregate_compatible", "period_shape_inference",
        }
    ) and verified.get("postgres_period_in_range") is not False
    code = _text(verified.get("verdict_code"))
    if code == "MATCH" and not review and preflight_ok:
        return "VERIFIED_MATCH"
    if code == "MATCH":
        return "MATCH_EVIDENCE_REVIEW_REQUIRED"
    if code == "VALUE_MISMATCH" and mismatch_evidence_is_exact(verified):
        return "MISMATCH_EVIDENCE_REVIEW_REQUIRED"
    return "UNRESOLVED"


SEMANTIC_ANCHORS = (
    "수출", "수입", "무역수지", "소매판매", "판매", "매출", "생산",
    "출하", "고용", "취업", "실업", "물가", "인구", "가구", "소득",
    "자동차", "완성차", "로봇", "반도체", "항공", "관광", "주택",
    "미분양", "혼인", "출생", "사망",
)


def semantic_anchor_set(value: Any) -> set[str]:
    compact = re.sub(r"\s+", "", _text(value)).lower()
    return {anchor for anchor in SEMANTIC_ANCHORS if anchor in compact}


def item_scope_is_explicit(row: Mapping[str, Any]) -> bool:
    """Require a claim anchor in the official ITEM before negative evidence.

    This deliberately favors UNRESOLVED over a false accusation.  Positive
    MATCH evidence still follows the normal verifier rules, while MISMATCH is
    allowed only when the selected official ITEM explicitly names the claimed
    concept (for example 수출→수출액, not 수출→수입액).
    """
    claim_scope = " ".join(_text(row.get(key)) for key in (
        "claim_indicator", "measurement_indicator", "indicator",
        "claim_industry_or_item", "industry_or_item", "measurement_item",
    ))
    official_item = _text(
        row.get("official_item_name") or row.get("selected_itm_name")
    )
    claim_anchors = semantic_anchor_set(claim_scope)
    item_anchors = semantic_anchor_set(official_item)
    if not claim_anchors or not item_anchors:
        return False
    # Directional and population concepts must match the ITEM itself.  This
    # blocks common paired-code errors such as 수출 claim → 수입 ITEM.
    return bool(claim_anchors & item_anchors)


def mismatch_measurement_semantics_are_exact(row: Mapping[str, Any]) -> bool:
    """Require an exact published measurement semantics for negative evidence.

    A level ITEM may be useful as a positive/derived candidate, but it is unsafe
    negative evidence for a rate-change claim: another official table can carry
    the directly published 전월비/전년동월비 value.  Likewise, a diffusion index
    is not interchangeable with a production index merely because both contain
    the word 생산.  These cases must remain UNRESOLVED.
    """
    claim_text = re.sub(r"\s+", "", " ".join(_text(row.get(key)) for key in (
        "claim_indicator", "measurement_indicator", "indicator", "claim_text",
    )))
    official_item = re.sub(r"\s+", "", _text(
        row.get("official_item_name") or row.get("selected_itm_name")
    ))
    mapping_type = _text(row.get("mapping_type"))
    change_base = _text(row.get("change_base"))
    semantic_type = _text(row.get("semantic_type"))
    if semantic_type == "rate_change" or change_base:
        expected_cues = {
            "전월": ("전월비", "전월대비"),
            "전년동월": ("전년동월비", "전년동월대비"),
            "전년동기": ("전년동기비", "전년동기대비"),
            "전분기": ("전분기비", "전분기대비"),
            "전년": ("전년비", "전년대비"),
        }.get(change_base, ())
        if mapping_type != "direct" or not expected_cues:
            return False
        if not any(cue in official_item for cue in expected_cues):
            return False
    if "확산" in official_item and "확산" not in claim_text:
        return False
    return True


OFFICIAL_STATISTICS_SOURCES = (
    "kosis", "국가통계포털", "통계청", "국가데이터처", "국가통계",
)


def mismatch_claim_block_reasons(row: Mapping[str, Any]) -> list[str]:
    """Return claim-level reasons that make automatic negative evidence unsafe.

    A valid KOSIS coordinate is not enough to accuse an article of being wrong.
    The quoted value must also be an exact point estimate and the article must
    not explicitly attribute it to a non-KOSIS report.  Positive MATCH remains
    unaffected; only automatic VALUE_MISMATCH is made conservative.
    """
    text = " ".join(_text(row.get(key)) for key in (
        "claim_text", "prev_sentence", "next_sentence", "title",
    )).lower()
    reasons: list[str] = []
    approximate_patterns = (
        r"(?:약|약간|대략|가량|정도|안팎|내외)\s*\d",
        r"\d+(?:\.\d+)?\s*%?\s*(?:대|초반|중반|후반|중후반|초중반|이상|이하|미만|초과)",
        r"\d+(?:\.\d+)?\s*(?:~|∼|～|-|에서)\s*\d+(?:\.\d+)?",
    )
    if _text(row.get("value_approximate")).upper() == "Y" or any(
        re.search(pattern, text) for pattern in approximate_patterns
    ):
        reasons.append("claim_value_is_range_or_approximation")

    attribution_cue = bool(re.search(
        r"(?:보고서|연구소|협회|연구원|기업|회사|은행).{0,40}(?:따르면|집계|발표|분석)",
        text,
    ))
    official_source = any(source in text for source in OFFICIAL_STATISTICS_SOURCES)
    if attribution_cue and not official_source:
        reasons.append("claim_explicitly_attributed_to_non_kosis_source")
    return reasons


def mismatch_evidence_is_exact(row: Mapping[str, Any]) -> bool:
    """True only when negative evidence has a complete exact provenance chain."""
    return bool(
        coordinate_preflight_valid(row)
        and _text(row.get("postgres_coordinate_status")) == "VALID"
        and _text(row.get("period_alignment_state")) == "exact"
        and row.get("postgres_period_in_range") is True
        and _text(row.get("unit_precheck_state")) == "compatible"
        and _text(row.get("official_table_name"))
        and mismatch_table_scope_is_explicit(row)
        and _text(row.get("official_item_name"))
        and not list(row.get("repair_history") or [])
        and _text(row.get("verification_review_required")).upper() != "Y"
        and item_scope_is_explicit(row)
        and mismatch_measurement_semantics_are_exact(row)
        and not mismatch_claim_block_reasons(row)
    )


def mismatch_table_scope_is_explicit(row: Mapping[str, Any]) -> bool:
    """Require the official table identity to be explicit for negative evidence.

    A valid ITEM/OBJ coordinate in a sibling table is technically queryable but
    does not prove that the article referred to that table. Positive matches can
    still use semantic retrieval; automatic mismatch requires the stricter
    table-level provenance link.
    """
    table_name = re.sub(r"[^0-9A-Za-z가-힣]", "", _text(
        row.get("official_table_name") or row.get("tbl_name")
    )).lower()
    if len(table_name) < 5:
        return False
    evidence = re.sub(r"[^0-9A-Za-z가-힣]", "", " ".join(
        _text(row.get(field)) for field in (
            "title", "claim_text", "prev_sentence", "next_sentence",
            "statistics_name", "stat_name", "keywords",
        )
    )).lower()
    return table_name in evidence


def block_unconfirmed_mismatch(row: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(row)
    if _text(value.get("verdict_code")) != "VALUE_MISMATCH":
        return value
    if mismatch_evidence_is_exact(value):
        value["mismatch_exact_gate"] = "PASS"
        return value
    value["original_verdict"] = value.get("verdict")
    value["original_verdict_code"] = "VALUE_MISMATCH"
    value["original_verdict_reason"] = value.get("verdict_reason", "")
    claim_block_reasons = mismatch_claim_block_reasons(value)
    value.update({
        "verdict": "판단불가",
        "verdict_code": "MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE",
        "verdict_stage": "mismatch_gate",
        "mismatch_exact_gate": "BLOCK",
        "mismatch_claim_block_reasons": "|".join(claim_block_reasons),
        "verdict_reason": (
            "정확한 표·ITEM·OBJ·기간·단위·기사 출처·수치 정밀도가 모두 확정되지 않아 "
            "VALUE_MISMATCH 자동 판정을 차단함 | "
            + _text(value.get("verdict_reason"))
        ),
    })
    return value


def local_branch_actionable(rows: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        row.get("decision_status") in {
            "VERIFIED_MATCH", "MATCH_EVIDENCE_REVIEW_REQUIRED",
            "MISMATCH_EVIDENCE_REVIEW_REQUIRED",
        }
        for row in rows
        if LOCAL_SOURCES & set(_text(row.get("candidate_sources")).split("|"))
    )


def resolve_claim(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    actionable = [
        row for row in rows
        if row.get("decision_status") in {
            "VERIFIED_MATCH", "MATCH_EVIDENCE_REVIEW_REQUIRED",
            "MISMATCH_EVIDENCE_REVIEW_REQUIRED",
        }
    ]
    if not actionable:
        return {"claim_decision": "UNRESOLVED", "selected_coordinate_id": ""}
    # Positive evidence dominates a contradictory negative candidate.  A
    # verified MATCH proves that at least one complete official coordinate
    # supports the article; choosing a higher-scored mismapped table as the
    # claim verdict would create a false accusation.
    verified_matches = [
        row for row in actionable if row.get("decision_status") == "VERIFIED_MATCH"
    ]
    if verified_matches:
        leader = max(verified_matches, key=lambda row: (
            selection_priority(row), _text(row.get("coordinate_id")),
        ))
        return {
            "claim_decision": "VERIFIED_MATCH",
            "selected_coordinate_id": _text(leader.get("coordinate_id")),
            "leader_priority": list(selection_priority(leader)),
            "leader_count": len(verified_matches),
            "conflicting_negative_candidate_count": sum(
                row.get("decision_status") == "MISMATCH_EVIDENCE_REVIEW_REQUIRED"
                for row in actionable
            ),
        }
    priorities = {id(row): selection_priority(row) for row in actionable}
    best_priority = max(priorities.values())
    leaders = [row for row in actionable if priorities[id(row)] == best_priority]
    outcomes = {
        "MATCH" if row.get("verdict_code") == "MATCH" else "MISMATCH"
        for row in leaders
    }
    if len(outcomes) > 1:
        decision = "CANDIDATE_CONFLICT_REVIEW_REQUIRED"
        selected = ""
    else:
        leader = sorted(leaders, key=lambda row: _text(row.get("coordinate_id")))[0]
        selected = _text(leader.get("coordinate_id"))
        if leader.get("decision_status") == "VERIFIED_MATCH":
            decision = "VERIFIED_MATCH"
        elif leader.get("verdict_code") == "MATCH":
            decision = "MATCH_EVIDENCE_REVIEW_REQUIRED"
        else:
            decision = "MISMATCH_EVIDENCE_REVIEW_REQUIRED"
    return {
        "claim_decision": decision,
        "selected_coordinate_id": selected,
        "leader_priority": list(best_priority),
        "leader_count": len(leaders),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--claim-output", type=Path)
    parser.add_argument("--postgres-dsn", default=os.environ.get("KOSIS_POSTGRES_DSN"))
    parser.add_argument("--sqlite-cache", required=True, type=Path)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or KOSIS_POSTGRES_DSN is required")
    if args.claim_output is None:
        args.claim_output = args.output.with_name(args.output.stem + "_claims.jsonl")

    claims = {}
    for row in read_csv(args.claims):
        claim_id = prepared_claim_id(row)
        if claim_id:
            claims[claim_id] = row
    packets = read_jsonl(args.candidates)
    tables, seen_tables = [], set()
    for packet in packets:
        for candidate in packet.get("unique_api_candidates") or []:
            coordinate = candidate["coordinate"]
            key = (coordinate["org_id"], coordinate["tbl_id"])
            if key not in seen_tables:
                seen_tables.add(key)
                tables.append({"org_id": key[0], "tbl_id": key[1], "rank": len(tables) + 1})

    with PostgresKosisMetadataStore(args.postgres_dsn) as store:
        meta_cache, catalog = hydrate_postgres_catalog(store, tables)
    data_cache = SQLiteAPIResponseCache(args.sqlite_cache)
    limiter = SQLiteKosisRequestLimiter(args.sqlite_cache, interval=max(args.delay, 0.5))

    output_rows: list[dict[str, Any]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for packet in packets:
            claim_id = packet["claim_measurement_id"]
            claim = claims.get(claim_id)
            if claim is None:
                raise KeyError(f"claim not found: {claim_id}")
            prepared_local = []
            prepared_local_fallback = []
            prepared_mcp = []
            for candidate in packet.get("unique_api_candidates") or []:
                coordinate = candidate["coordinate"]
                key = (coordinate["org_id"], coordinate["tbl_id"])
                pair = (candidate, verification_input(
                    claim, packet, candidate, catalog.get(key),
                ))
                sources = set(_text(pair[1].get("candidate_sources")).split("|"))
                if "local_reranker" in sources:
                    prepared_local.append(pair)
                elif "local_reranker_fallback" in sources:
                    prepared_local_fallback.append(pair)
                else:
                    prepared_mcp.append(pair)
            prepared_local.sort(
                key=lambda pair: selection_priority(pair[1]), reverse=True,
            )
            prepared_mcp.sort(
                key=lambda pair: selection_priority(pair[1]), reverse=True,
            )
            prepared_local_fallback.sort(
                key=lambda pair: selection_priority(pair[1]), reverse=True,
            )
            previous_code = ""
            seen_fingerprints: set[tuple[Any, ...]] = set()
            claim_verified: list[dict[str, Any]] = []

            def verify_group(
                pairs: Sequence[tuple[Mapping[str, Any], dict[str, Any]]],
                *, fallback_state: str,
            ) -> None:
                nonlocal previous_code
                for candidate, row in pairs:
                    fingerprint = verification_fingerprint(row)
                    if fingerprint in seen_fingerprints:
                        print(
                            f"[verify] claim={claim_id} duplicate coordinate skipped "
                            f"source={row.get('candidate_sources')} fallback={fallback_state}",
                            flush=True,
                        )
                        continue
                    seen_fingerprints.add(fingerprint)
                    attempt_rank = len(claim_verified) + 1
                    row["api_attempt_rank"] = attempt_rank
                    row["retry_from_previous_code"] = previous_code
                    row["fallback_state"] = fallback_state
                    if not coordinate_preflight_valid(row):
                        verified = {**row, "verdict": "판단불가",
                            "verdict_code": "POSTGRES_COORDINATE_INVALID",
                            "verdict_stage": "preflight",
                            "verdict_reason": row.get("preflight_reason", "")}
                    elif (
                        row.get("period_alignment_state") == "mismatch"
                        or row.get("postgres_period_in_range") is False
                    ):
                        verified = {**row, "verdict": "판단불가",
                            "verdict_code": "PERIODICITY_NOT_AVAILABLE",
                            "verdict_stage": "period",
                            "verdict_reason": row.get("preflight_reason", "")}
                    else:
                        try:
                            verified = verify_row(
                                row, meta_cache, args.delay, use_pinned_item=True,
                                data_cache=data_cache, request_limiter=limiter,
                            )
                        except Exception as error:
                            verified = {**row, "verdict": "판단불가",
                                "verdict_code": "KOSIS_API_ERROR",
                                "verdict_stage": "api", "verdict_reason": str(error)}
                    verified = block_unconfirmed_mismatch(verified)
                    verified["claim_measurement_id"] = claim_id
                    verified["coordinate_id"] = row["coordinate_id"]
                    verified["decision_status"] = classify(verified)
                    verified["selection_priority"] = list(selection_priority(verified))
                    claim_verified.append(verified)
                    output_rows.append(verified)
                    handle.write(json.dumps(verified, ensure_ascii=False) + "\n")
                    handle.flush()
                    previous_code = _text(verified.get("verdict_code"))
                    print(
                        f"[verify] claim={claim_id} attempt={attempt_rank} "
                        f"source={verified.get('candidate_sources')} "
                        f"fallback={fallback_state} "
                        f"status={verified['decision_status']} code={previous_code}",
                        flush=True,
                    )

            # Local Top-3 is primary. Absolute Stage C ranks 4-5 run only when
            # Top-3 remains unresolved, and MCP runs only when both Local
            # groups remain unresolved. Every branch uses the same PostgreSQL
            # coordinate/period/unit preflight.
            verify_group(prepared_local, fallback_state="LOCAL_PRIMARY")
            local_actionable = local_branch_actionable(claim_verified)
            if not local_actionable:
                verify_group(
                    prepared_local_fallback,
                    fallback_state="LOCAL_RANK_4_5_FALLBACK",
                )
                local_actionable = local_branch_actionable(claim_verified)
            if not local_actionable:
                verify_group(prepared_mcp, fallback_state="MCP_FALLBACK")
            elif prepared_mcp:
                print(
                    f"[verify] claim={claim_id} MCP skipped: Local Top-3/"
                    "rank4-5 produced actionable exact evidence",
                    flush=True,
                )

    by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in output_rows:
        by_claim[row["claim_measurement_id"]].append(row)
    claim_rows = []
    # Emit one decision for every prepared claim, including packets with zero
    # coordinates.  Abstention is an explicit product state, not a missing row.
    for claim_id in sorted(claims):
        rows = by_claim.get(claim_id, [])
        resolved = resolve_claim(rows)
        verdict_counts, stage_counts = decision_failure_counts(claims[claim_id], rows)
        claim_rows.append({
            "claim_measurement_id": claim_id, **resolved,
            "candidate_count": len(rows),
            "candidate_verdict_counts": verdict_counts,
            "failure_stage_counts": stage_counts,
            "retryable_candidate_count": sum(
                _text(row.get("verdict_code")) in {
                    "KOSIS_API_ERROR", "EMPTY_RESPONSE", "VALUE_MISSING",
                }
                for row in rows
            ),
        })
    with args.claim_output.open("w", encoding="utf-8") as handle:
        for row in claim_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("candidate_output=" + str(args.output))
    print("claim_output=" + str(args.claim_output))
    print("claim_decisions=" + json.dumps(dict(Counter(
        row["claim_decision"] for row in claim_rows
    )), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
