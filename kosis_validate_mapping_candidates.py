#!/usr/bin/env python3
"""Validate bounded ITEM/OBJ mapping candidates against official KOSIS metadata.

The module deliberately separates pure mapping/validation from HTTP.  Callers fetch
``getMeta(type=ITM)`` themselves and inject a ``data_fetcher(params)`` when they want
to validate data responses.  An API response proves technical availability only; it
is never added to the semantic score.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


READY = "READY"
NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
MAPPING_FAILED = "MAPPING_FAILED"
NO_KOSIS_TABLE = "NO_KOSIS_TABLE"
API_ERROR = "API_ERROR"
NOT_EVALUATED = "NOT_EVALUATED"
API_LIMIT_REACHED = "API_LIMIT_REACHED"
LOW_PRIORITY_CANDIDATE = "LOW_PRIORITY_CANDIDATE"
INVALID_METADATA = "INVALID_METADATA"
INVALID_REQUEST = "INVALID_REQUEST"
RESPONSE_CODE_MISMATCH = "RESPONSE_CODE_MISMATCH"
META_NOT_AVAILABLE = "META_NOT_AVAILABLE"
ITEM_UNRESOLVED = "ITEM_UNRESOLVED"
OBJ_UNRESOLVED = "OBJ_UNRESOLVED"
INVALID_COMBINATION = "INVALID_COMBINATION"
PERIOD_MISSING = "PERIOD_MISSING"
UNIT_MISMATCH = "UNIT_MISMATCH"
EMPTY_RESPONSE = "EMPTY_RESPONSE"

LOW_RISK_DEFAULT_NAMES = ("계", "전체", "총계", "전국")
HIGH_RISK_MISSING_FIELDS = (
    "indicator", "period", "comparison_period", "age", "age_group",
    "industry", "industry_or_item", "comparison_basis",
)


def _first(row: Mapping[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _score(row: Mapping[str, Any]) -> float:
    try:
        return float(_first(row, "semantic_score", "score", "candidate_score", default=0.0))
    except (TypeError, ValueError):
        return 0.0


def _axis_order(row: Mapping[str, Any]) -> int | None:
    raw = _first(row, "OBJ_ID_SN", "obj_id_sn", "axis_order", "obj_level")
    try:
        order = int(float(str(raw)))
        return order if 1 <= order <= 8 else None
    except (TypeError, ValueError):
        return None


def group_official_meta(meta_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Group getMeta(ITM) rows using OBJ_ID_SN/axis_order, never OBJ_ID letters."""
    items: list[dict[str, Any]] = []
    axes: dict[int, dict[str, Any]] = {}
    for source in meta_rows or []:
        row = dict(source)
        obj_id = str(_first(row, "OBJ_ID", "obj_id", "axis_id")).strip()
        code = str(_first(row, "ITM_ID", "itm_id", "code", "code_id")).strip()
        name = str(_first(row, "ITM_NM", "itm_nm", "name", "code_name")).strip()
        if not code:
            continue
        is_item = str(_first(row, "is_item", "IS_ITEM")).strip().upper()
        if obj_id.upper() == "ITEM" or is_item in {"Y", "TRUE", "1"}:
            items.append({"code": code, "name": name, "raw": row})
            continue
        order = _axis_order(row)
        if order is None:
            # An unordered axis cannot safely be converted to objL<n>.
            continue
        axis = axes.setdefault(order, {
            "axis_order": order,
            "obj_id": obj_id,
            "obj_name": str(_first(row, "OBJ_NM", "obj_nm", "axis_name")),
            "values": [],
        })
        axis["values"].append({"code": code, "name": name, "raw": row})
    return {
        "items": items,
        "item_codes": {x["code"] for x in items},
        "axes": dict(sorted(axes.items())),
        "axis_codes": {order: {x["code"] for x in axis["values"]}
                       for order, axis in axes.items()},
    }


def validate_candidate_codes_against_meta(
    candidate: Mapping[str, Any], official_meta: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return per-code validity; invalid official codes must not reach the API."""
    grouped = official_meta if isinstance(official_meta, Mapping) and "axes" in official_meta else group_official_meta(official_meta)  # type: ignore[arg-type]
    itm_id = str(_first(candidate, "itm_id", "ITM_ID", "selected_itm_id"))
    item_valid = bool(itm_id and itm_id in grouped["item_codes"])
    invalid_obj: list[dict[str, Any]] = []
    checked = 0
    for level in range(1, 9):
        code = _first(candidate, f"objL{level}", f"obj_l{level}", f"selected_obj_l{level}")
        if code in (None, ""):
            continue
        checked += 1
        if str(code) not in grouped["axis_codes"].get(level, set()):
            invalid_obj.append({"axis_order": level, "code": str(code)})
    return {
        "item_meta_valid": item_valid,
        "obj_meta_valid": checked > 0 and not invalid_obj,
        "invalid_obj_codes": invalid_obj,
        "metadata_valid": item_valid and checked > 0 and not invalid_obj,
    }


def _normalize_candidates(rows: Iterable[Any]) -> list[dict[str, Any]]:
    normalized = []
    for value in rows or []:
        if isinstance(value, Mapping):
            row = dict(value)
            code = str(_first(row, "code", "itm_id", "ITM_ID", "obj_code"))
            name = str(_first(row, "name", "itm_name", "ITM_NM", "obj_name"))
        else:
            code, name, row = str(value), "", {}
        if code:
            normalized.append({**row, "code": code, "name": name, "semantic_score": _score(row)})
    return sorted(normalized, key=_score, reverse=True)


def _aggregate_default(axis: Mapping[str, Any]) -> dict[str, Any] | None:
    matches = [value for value in axis.get("values", [])
               if str(value.get("name", "")).strip() in LOW_RISK_DEFAULT_NAMES]
    # Defaults are safe only when the official axis has one unambiguous aggregate.
    return dict(matches[0]) if len(matches) == 1 else None


def build_candidate_combinations(
    item_candidates: Iterable[Any], obj_candidates: Mapping[Any, Iterable[Any]],
    official_meta: Mapping[str, Any] | Iterable[Mapping[str, Any]], *,
    item_top_k: int = 3, obj_top_k: int = 2, max_combinations: int = 20,
    claim: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a bounded Cartesian product after official-code filtering.

    ``obj_candidates`` keys are numeric axis orders (or ``objL1`` etc.). Missing
    axes receive only a unique official aggregate default. Ambiguous axes produce
    no combinations rather than a guessed code.
    """
    grouped = official_meta if isinstance(official_meta, Mapping) and "axes" in official_meta else group_official_meta(official_meta)  # type: ignore[arg-type]
    if max_combinations <= 0:
        return []
    items = [x for x in _normalize_candidates(item_candidates)
             if x["code"] in grouped["item_codes"]][:max(0, item_top_k)]
    if not items:
        return []
    by_order: dict[int, Iterable[Any]] = {}
    for key, rows in (obj_candidates or {}).items():
        match = re.search(r"([1-8])$", str(key))
        order = int(match.group(1)) if match else (int(key) if str(key).isdigit() else 0)
        if order:
            by_order[order] = rows
    axes: list[tuple[int, list[dict[str, Any]]]] = []
    for order, axis in grouped["axes"].items():
        choices = [x for x in _normalize_candidates(by_order.get(order, []))
                   if x["code"] in grouped["axis_codes"][order]][:max(0, obj_top_k)]
        if not choices:
            default = _aggregate_default(axis)
            if default is None:
                return []
            choices = [{**default, "semantic_score": 0.0, "is_default": True,
                        "default_field": f"objL{order}", "default_value": default["code"],
                        "default_reason": f"축 '{axis.get('obj_name') or order}'이 미명시되어 공식 메타의 유일한 집계값 적용",
                        "default_risk": "LOW"}]
        axes.append((order, choices))
    per_item: list[list[dict[str, Any]]] = []
    for item in items:
        combinations: list[dict[str, Any]] = []
        products = itertools.product(*(choices for _, choices in axes)) if axes else [()]
        for selected in products:
            defaults = [x for x in selected if x.get("is_default")]
            combo: dict[str, Any] = {
            "itm_id": item["code"], "itm_name": item.get("name", ""),
            "semantic_score": _score(item) + sum(_score(x) for x in selected),
            "default_fields": [{k: x.get(k) for k in ("default_field", "default_value", "default_reason", "default_risk")} for x in defaults],
            "default_reason": "; ".join(str(x["default_reason"]) for x in defaults),
            "default_risk": "LOW" if defaults else "NONE",
        }
            for (order, _), value in zip(axes, selected):
                combo[f"objL{order}"] = value["code"]
                combo[f"objL{order}_name"] = value.get("name", "")
            combo.update(validate_candidate_codes_against_meta(combo, grouped))
            combinations.append(combo)
        per_item.append(sorted(combinations, key=_score, reverse=True))

    # Give every retained ITEM one attempt before filling the remaining budget by
    # joint semantic score. This avoids the former ITEM-1-first truncation bias.
    selected_combinations = [rows.pop(0) for rows in per_item if rows][:max_combinations]
    remaining = sorted((row for rows in per_item for row in rows), key=_score, reverse=True)
    selected_combinations.extend(remaining[:max_combinations - len(selected_combinations)])
    return sorted(selected_combinations, key=_score, reverse=True)


def build_kosis_request(
    org_id: str, tbl_id: str, combination: Mapping[str, Any], *,
    prd_se: str = "Y", periods: Sequence[str] | None = None,
    new_est_prd_cnt: int | None = None,
) -> dict[str, Any]:
    """Create Param API parameters from a metadata-validated combination."""
    if not combination.get("metadata_valid", True):
        raise ValueError(f"{INVALID_METADATA}: candidate contains non-official codes")
    if not combination.get("itm_id"):
        raise ValueError(f"{INVALID_REQUEST}: missing itm_id")
    params: dict[str, Any] = {"method": "getList", "orgId": org_id, "tblId": tbl_id,
                              "itmId": combination.get("itm_id"), "prdSe": prd_se,
                              "format": "json"}
    for level in range(1, 9):
        code = combination.get(f"objL{level}")
        if code not in (None, ""):
            params[f"objL{level}"] = code
    if not any(params.get(f"objL{level}") not in (None, "") for level in range(1, 9)):
        raise ValueError(f"{INVALID_REQUEST}: missing required obj axis")
    wanted = [str(x) for x in periods or [] if x not in (None, "")]
    if wanted:
        params["startPrdDe"], params["endPrdDe"] = min(wanted), max(wanted)
    elif new_est_prd_cnt is not None:
        params["newEstPrdCnt"] = int(new_est_prd_cnt)
    return {key: value for key, value in params.items() if value not in (None, "")}


def response_matches_request(request: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Require one response row to exactly match itmId and every requested objL."""
    rows = list(rows or [])
    matching = []
    for row in rows:
        if str(row.get("ITM_ID", "")) != str(request.get("itmId", "")):
            continue
        if all(str(row.get(f"C{level}", "")) == str(request[f"objL{level}"])
               for level in range(1, 9) if request.get(f"objL{level}") not in (None, "")):
            matching.append(dict(row))
    return {"response_code_valid": bool(matching), "matching_rows": matching,
            "response_row_count": len(rows)}


def _unit_tokens(value: Any) -> set[str]:
    text = re.sub(r"[\s,()]", "", str(value or "")).lower()
    aliases = {
        "%": "percent",
        "%p": "percent_point",
        "퍼센트": "percent",
        "백분율": "percent",
        "퍼센트포인트": "percent_point",
        "명": "person",
        "천명": "person",
        "만명": "person",
        "인": "person",
        "개": "count",
        "개사": "organization_count",
        "사": "organization_count",
        "업체": "organization_count",
        "업체수": "organization_count",
        "기업": "organization_count",
        "기업수": "organization_count",
        "대": "count",
        "건": "count",
        "건수": "count",
        "가구": "count",
        "원": "currency_krw",
        "천원": "currency_krw",
        "만원": "currency_krw",
        "백만원": "currency_krw",
        "억원": "currency_krw",
        "조원": "currency_krw",
        "달러": "currency_usd",
        "천달러": "currency_usd",
        "백만달러": "currency_usd",
        "억달러": "currency_usd",
        "usd": "currency_usd",
    }
    return {aliases.get(text, text)} if text else set()


def validate_unit_and_period(
    rows: Iterable[Mapping[str, Any]], *, expected_unit: str | None = None,
    required_periods: Sequence[str] | None = None,
) -> dict[str, Any]:
    rows = list(rows or [])
    units = {_first(row, "UNIT_NM", "UNIT", "unit") for row in rows}
    unit_valid = True if not expected_unit else any(_unit_tokens(expected_unit) & _unit_tokens(unit) for unit in units)
    available = {str(_first(row, "PRD_DE", "PRD", "period")) for row in rows}
    required = {str(x) for x in required_periods or [] if x not in (None, "")}
    missing = sorted(required - available)
    return {"unit_valid": unit_valid, "period_valid": not missing,
            "available_periods": sorted(available - {""}), "missing_periods": missing,
            "validation_reason": "PERIOD_MISSING" if missing else ("UNIT_MISMATCH" if not unit_valid else "")}


def rank_valid_combinations(combinations: Iterable[Mapping[str, Any]], *, unit_penalty: float = 0.15,
                            period_penalty: float = 0.35, default_penalty: float = 0.05) -> list[dict[str, Any]]:
    """Rank technical-valid candidates without treating API success as semantics."""
    ranked = []
    for source in combinations:
        row = dict(source)
        if not (row.get("metadata_valid") and row.get("response_code_valid")):
            continue
        semantic = _score(row)
        penalty = (0 if row.get("unit_valid", True) else unit_penalty)
        penalty += (0 if row.get("period_valid", True) else period_penalty)
        penalty += (default_penalty if row.get("default_risk") == "LOW" else 0)
        if row.get("default_risk") == "HIGH":
            penalty += 1.0
        row.update({"api_valid": True, "semantic_score": semantic,
                    "ranking_score": semantic - penalty,
                    "final_confidence": semantic - penalty})
        ranked.append(row)
    return sorted(ranked, key=lambda x: x["ranking_score"], reverse=True)


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", str(value or "")).lower()


def find_high_risk_missing(claim: Mapping[str, Any] | None,
                           combination: Mapping[str, Any] | None = None) -> list[str]:
    """Find material missing/unexplained claim constraints without guessing them."""
    if claim is None:
        return []
    missing: list[str] = []
    if not _first(claim, "indicator", "measurement_indicator"):
        missing.append("indicator")
    if not _first(claim, "period", "measurement_period"):
        missing.append("period")
    mapping_type = str(_first(claim, "mapping_type", "semantic_type", "value_type")).lower()
    needs_comparison = mapping_type in {
        "rate_from_level", "difference_from_level", "rate", "difference",
        "rate_change", "absolute_change", "증감률", "증감량",
    }
    if needs_comparison and not _first(claim, "comparison_period"):
        missing.append("comparison_period")
    if needs_comparison and not _first(claim, "comparison_basis", "change_base"):
        missing.append("comparison_basis")
    selected_text = " ".join(str((combination or {}).get(key, ""))
        for key in ["itm_name", *(f"objL{level}_name" for level in range(1, 9))])
    selected_normalized = _normalized_text(selected_text)
    for canonical, aliases in (
        ("age_group", ("age_group", "age")),
        ("industry_or_item", ("industry_or_item", "industry", "item")),
    ):
        value = _first(claim, *aliases)
        if value and _normalized_text(value) not in selected_normalized:
            missing.append(canonical)
    explicit = claim.get("unmapped_claim_fields", claim.get("unmapped_conditions", []))
    if isinstance(explicit, str):
        explicit = [part.strip() for part in explicit.split(",") if part.strip()]
    missing.extend(str(value) for value in explicit or [])
    return list(dict.fromkeys(missing))


def choose_or_abstain(
    ranked: Sequence[Mapping[str, Any]], *, margin_threshold: float = 0.10,
    ready_threshold: float = 0.01, high_risk_missing: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Choose one candidate only with sufficient evidence and separation."""
    ranked = list(ranked)
    base = {"mapping_status": MAPPING_FAILED, "mapping_confidence": 0.0,
            "mapping_reason": "INVALID_COMBINATION", "selected_combination": None}
    if not ranked:
        return base
    first = dict(ranked[0])
    confidence = float(first.get("final_confidence", first.get("ranking_score", 0.0)))
    reason = "validated candidate"
    status = READY
    if not first.get("period_valid", True):
        status, reason = NEEDS_CONFIRMATION, PERIOD_MISSING
    elif not first.get("unit_valid", True):
        status, reason = NEEDS_CONFIRMATION, UNIT_MISMATCH
    elif high_risk_missing or first.get("default_risk") == "HIGH":
        status, reason = NEEDS_CONFIRMATION, "high-risk claim information is missing"
    elif confidence < ready_threshold:
        status, reason = NEEDS_CONFIRMATION, "absolute score is below READY threshold"
    elif len(ranked) > 1:
        margin = confidence - float(ranked[1].get("final_confidence", ranked[1].get("ranking_score", 0.0)))
        if margin < margin_threshold:
            status, reason = NEEDS_CONFIRMATION, f"top candidates have small margin ({margin:.4f})"
    return {"mapping_status": status, "mapping_confidence": confidence,
            "mapping_reason": reason, "selected_combination": first,
            "candidate_count": len(ranked)}


def validate_mapping_candidates(
    *, org_id: str, tbl_id: str, meta_rows: Iterable[Mapping[str, Any]],
    item_candidates: Iterable[Any], obj_candidates: Mapping[Any, Iterable[Any]],
    data_fetcher: Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]],
    expected_unit: str | None = None, required_periods: Sequence[str] | None = None,
    prd_se: str = "Y", item_top_k: int = 3, obj_top_k: int = 2,
    max_combinations: int = 20, margin_threshold: float = 0.10,
    claim: Mapping[str, Any] | None = None, api_call_limit: int = 0,
    api_calls_used: int = 0,
) -> dict[str, Any]:
    """Small orchestration helper. It performs at most ``max_combinations`` calls."""
    item_candidates = list(item_candidates or [])
    grouped = group_official_meta(meta_rows)
    combinations = build_candidate_combinations(item_candidates, obj_candidates, grouped,
        item_top_k=item_top_k, obj_top_k=obj_top_k, max_combinations=max_combinations)
    semantic_type = str(_first(claim or {}, "mapping_type", "semantic_type", "value_type")).lower()
    unit_for_candidate_validation = expected_unit
    if semantic_type in {"rate_from_level", "rate_change", "rate", "증감률"}:
        # A percent change claim is often verified from level data whose KOSIS
        # unit is currency/count/etc. Do not reject technically valid level
        # mappings at candidate-validation time; value verification computes
        # the rate and handles unit compatibility later.
        unit_for_candidate_validation = None
    attempted, api_errors, empty_responses = [], 0, 0
    request_errors, response_mismatches, not_evaluated = 0, 0, 0
    limit_reached = False
    for combo in combinations:
        result = dict(combo)
        try:
            request = build_kosis_request(org_id, tbl_id, combo, prd_se=prd_se, periods=required_periods)
        except ValueError as exc:
            request_errors += 1
            reason = str(exc).split(":", 1)[0]
            result.update({"candidate_status": reason, "status_reason": reason,
                           "response_code_valid": False, "api_valid": False})
            attempted.append(result)
            continue
        if api_call_limit and api_calls_used >= api_call_limit:
            limit_reached = True
            not_evaluated += 1
            result.update({"candidate_status": NOT_EVALUATED, "status_reason": API_LIMIT_REACHED,
                           "response_code_valid": False, "api_valid": False,
                           "not_evaluated": True})
            attempted.append(result)
            continue
        try:
            api_calls_used += 1
            response = list(data_fetcher(request) or [])
            if not response:
                empty_responses += 1
            result.update(response_matches_request(request, response))
            if response and not result.get("response_code_valid"):
                response_mismatches += 1
                result["status_reason"] = RESPONSE_CODE_MISMATCH
            result.update(validate_unit_and_period(result["matching_rows"], expected_unit=unit_for_candidate_validation,
                                                   required_periods=required_periods))
        except Exception as exc:  # caller controls transport; preserve error without hiding other candidates
            api_errors += 1
            result.update({"response_code_valid": False, "api_valid": False,
                           "api_error": f"{type(exc).__name__}: {exc}"})
        attempted.append(result)
    ranked = rank_valid_combinations(attempted)
    high_risk_missing = find_high_risk_missing(claim, ranked[0] if ranked else None)
    decision = choose_or_abstain(ranked, margin_threshold=margin_threshold,
                                 high_risk_missing=high_risk_missing)
    if not grouped["items"] and not grouped["axes"]:
        decision.update(mapping_status=META_NOT_AVAILABLE, mapping_reason=META_NOT_AVAILABLE)
    elif not any(x["code"] in grouped["item_codes"] for x in _normalize_candidates(item_candidates)):
        decision.update(mapping_status=ITEM_UNRESOLVED, mapping_reason=ITEM_UNRESOLVED)
    elif not combinations:
        supplied_obj = any(list(values or []) for values in (obj_candidates or {}).values())
        reason = INVALID_COMBINATION if supplied_obj else OBJ_UNRESOLVED
        decision.update(mapping_status=reason, mapping_reason=reason)
    elif limit_reached and not ranked:
        decision.update(mapping_status=NOT_EVALUATED, mapping_reason=API_LIMIT_REACHED)
    elif limit_reached and decision.get("mapping_status") == READY:
        decision.update(mapping_status=NEEDS_CONFIRMATION,
                        mapping_reason="API limit reached before evaluating all candidate combinations")
    elif request_errors == len(combinations):
        decision.update(mapping_status=INVALID_REQUEST, mapping_reason=INVALID_REQUEST)
    elif api_errors == len(combinations):
        decision.update(mapping_status=API_ERROR, mapping_reason=API_ERROR)
    elif empty_responses == len(combinations):
        decision.update(mapping_status=EMPTY_RESPONSE, mapping_reason=EMPTY_RESPONSE)
    elif response_mismatches == len(combinations):
        decision.update(mapping_status=RESPONSE_CODE_MISMATCH, mapping_reason=RESPONSE_CODE_MISMATCH)
    selected = decision.get("selected_combination") or {}
    official_item_candidates = [x for x in _normalize_candidates(item_candidates)
                                if x["code"] in grouped["item_codes"]][:item_top_k]

    def candidate_summary(row: Mapping[str, Any]) -> dict[str, Any]:
        keys = ["itm_id", "itm_name", "semantic_score", "metadata_valid",
                "response_code_valid", "api_valid", "unit_valid", "period_valid",
                "ranking_score", "final_confidence", "default_reason", "default_risk",
                "validation_reason", "api_error", "candidate_status", "status_reason",
                "not_evaluated"]
        keys.extend(key for level in range(1, 9)
                    for key in (f"objL{level}", f"objL{level}_name"))
        return {key: row[key] for key in keys if key in row}

    output = {
        "candidate_itm_ids": [x["code"] for x in official_item_candidates],
        "candidate_obj_combinations": [candidate_summary(row) for row in attempted],
        "attempted_combination_count": len(attempted),
        "api_valid_combination_count": len(ranked),
        "api_error_count": api_errors,
        "empty_response_count": empty_responses,
        "request_error_count": request_errors,
        "response_mismatch_count": response_mismatches,
        "not_evaluated_count": not_evaluated,
        "api_calls_used": api_calls_used,
        "api_call_limit": api_call_limit,
        "evaluation_complete": not limit_reached and not_evaluated == 0,
        "status_reason": decision.get("mapping_reason", INVALID_COMBINATION),
        "high_risk_missing": high_risk_missing,
        **decision,
        "selected_itm_id": selected.get("itm_id", ""),
        "selected_itm_name": selected.get("itm_name", ""),
        "item_meta_valid": bool(selected.get("item_meta_valid")),
        "obj_meta_valid": bool(selected.get("obj_meta_valid")),
        "response_code_valid": bool(selected.get("response_code_valid")),
        "unit_valid": bool(selected.get("unit_valid")),
        "period_valid": bool(selected.get("period_valid")),
        "metadata_valid": bool(selected.get("metadata_valid")),
        "api_valid": bool(selected.get("api_valid")),
        "semantic_score": selected.get("semantic_score", ""),
        "ranking_score": selected.get("ranking_score", ""),
        "confidence": decision.get("mapping_confidence", 0.0),
        "status": decision.get("mapping_status", MAPPING_FAILED),
        "reason": decision.get("mapping_reason", INVALID_COMBINATION),
        "default_reason": selected.get("default_reason", ""),
        "default_risk": selected.get("default_risk", "NONE"),
    }
    for level in range(1, 9):
        output[f"selected_obj_l{level}"] = selected.get(f"objL{level}", "")
        output[f"selected_obj_l{level}_name"] = selected.get(f"objL{level}_name", "")
    return output


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for source in rows:
            row = dict(source)
            for key, value in row.items():
                if isinstance(value, (list, dict)):
                    row[key] = json.dumps(value, ensure_ascii=False)
            writer.writerow(row)


def _lexical_candidates(values: Iterable[Mapping[str, Any]], text: str) -> list[dict[str, Any]]:
    normalized = re.sub(r"\s+", "", text).lower()
    tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", text.lower()))
    out = []
    for value in values:
        name = str(value.get("name", ""))
        compact_name = re.sub(r"\s+", "", name).lower()
        name_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", name.lower()))
        score = (1.0 if compact_name and compact_name in normalized else 0.0)
        score += len(tokens & name_tokens) / max(1, len(name_tokens))
        out.append({"code": value.get("code", ""), "name": name, "semantic_score": score})
    return sorted(out, key=lambda x: x["semantic_score"], reverse=True)


def _merge_seeded_candidates(
    lexical: Iterable[Mapping[str, Any]], seeded: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Put upstream structured candidates into the pool without trusting them.

    Upstream selected_* values are useful hints, but they are not semantic
    evidence by themselves.  Do not give them an artificial score boost: API
    exact-match later only proves that the code is technically queryable, not
    that it matches the news claim's meaning.
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in lexical:
        code = str(row.get("code", "")).strip()
        if code:
            merged[code] = dict(row)
    for row in seeded:
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        base = merged.get(code, {})
        score = max(_score(base), _score(row))
        merged[code] = {**base, **row, "code": code, "semantic_score": score, "seeded_hint": True}
    return sorted(merged.values(), key=_score, reverse=True)


def _seeded_item_candidates(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    code = str(row.get("selected_itm_id", "")).strip()
    if not code:
        return []
    return [{
        "code": code,
        "name": str(row.get("selected_itm_name", "")).strip(),
        "semantic_score": _score({"semantic_score": row.get("selected_itm_score", "")}),
        "seeded_hint": True,
    }]


def _axis_id_to_order(grouped: Mapping[str, Any]) -> dict[str, int]:
    return {str(axis.get("obj_id", "")): order
            for order, axis in grouped.get("axes", {}).items()
            if str(axis.get("obj_id", ""))}


def _seeded_obj_candidates(row: Mapping[str, Any], grouped: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    by_axis = _axis_id_to_order(grouped)
    seeded: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for level in range(1, 9):
        code = str(row.get(f"selected_obj_l{level}", "")).strip()
        if not code:
            continue
        axis_id = str(row.get(f"selected_obj_l{level}_axis_id", "")).strip()
        order = by_axis.get(axis_id, level)
        if order not in grouped.get("axes", {}):
            continue
        seeded[order].append({
            "code": code,
            "name": str(row.get(f"selected_obj_l{level}_name", "")).strip(),
            "semantic_score": _score({"semantic_score": row.get(f"selected_obj_l{level}_score", "")}),
            "seeded_hint": True,
        })
    return seeded


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def is_low_priority_candidate(row: Mapping[str, Any], *, rank_threshold: int = 3) -> bool:
    rank = _int_or_none(row.get("candidate_rank"))
    status = str(row.get("candidate_status", "")).strip().upper()
    return status == "ALTERNATE" and rank is not None and rank >= rank_threshold


def _rank1_is_decisive(row: Mapping[str, Any]) -> bool:
    rank = _int_or_none(row.get("candidate_rank"))
    if rank != 1:
        return False
    if str(row.get("candidate_status", "")).strip() != READY:
        return False
    score = _float_or_none(row.get("candidate_score"))
    runner_up = _float_or_none(row.get("candidate_runner_up_score"))
    if score is None:
        return False
    if runner_up is None:
        return True
    margin = score - runner_up
    required = max(10.0, score * 0.10)
    return margin >= required


def resolve_measurement_level_ambiguity(outputs: list[dict[str, Any]]) -> None:
    """Keep a decisive rank-1 READY; otherwise send multiple valid mappings to HITL."""
    for row in outputs:
        if row.get("mapping_status") != READY:
            continue
        if _rank1_is_decisive(row):
            continue
        row["mapping_status"] = NEEDS_CONFIRMATION
        row["mapping_reason"] = "upstream table candidate is not decisive rank-1 READY"

    by_measurement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outputs:
        key = str(row.get("claim_measurement_id") or row.get("claim_id") or "")
        by_measurement[key].append(row)
    for candidates in by_measurement.values():
        ready = [row for row in candidates if row.get("mapping_status") == READY]
        if len(ready) <= 1:
            continue
        decisive = [row for row in ready if _rank1_is_decisive(row)]
        if len(decisive) == 1:
            keep = decisive[0]
            keep["mapping_reason"] = (
                "validated rank-1 candidate; lower-ranked technical alternatives require confirmation"
            )
            for row in ready:
                if row is keep:
                    continue
                row["mapping_status"] = NEEDS_CONFIRMATION
                row["mapping_reason"] = "lower-ranked technical alternative to decisive rank-1 mapping"
            continue
        for row in ready:
            row["mapping_status"] = NEEDS_CONFIRMATION
            row["mapping_reason"] = "multiple table/ITEM/OBJ mappings are technically valid"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate bounded KOSIS ITEM/OBJ combinations")
    parser.add_argument("--input", required=True)
    parser.add_argument("--meta-index", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--item-top-k", type=int, default=3)
    parser.add_argument("--obj-top-k", type=int, default=2)
    parser.add_argument("--max-combinations", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Explicit small API sample limit; 0 processes all")
    parser.add_argument("--api-sample-limit", type=int, default=0,
                        help="Candidate-validation data API call cap; 0 means no cap (default)")
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--validate-low-priority", action="store_true",
                        help="Also call KOSIS data API for ALTERNATE candidates with rank >= 3")
    args = parser.parse_args()

    from kosis_api_test import get_stat_data

    rows = _read_csv(Path(args.input))
    meta_by_table: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for meta in _read_csv(Path(args.meta_index)):
        meta_by_table[(str(meta.get("org_id", "")), str(meta.get("tbl_id", "")))].append(meta)
    work = rows[:args.limit] if args.limit else rows
    estimated_max = len(work) * max(0, args.max_combinations)
    api_call_limit = max(0, args.api_sample_limit)
    estimated = min(estimated_max, api_call_limit) if api_call_limit else estimated_max
    print(f"candidate_rows={len(work)} max_combinations_per_row={args.max_combinations} "
          f"candidate_validation_api_call_limit={api_call_limit or 'unlimited'} "
          f"estimated_candidate_validation_api_calls<={estimated} "
          f"value_verification_api_calls=separate_downstream_step")
    outputs: list[dict[str, Any]] = []
    api_calls = 0
    for row in work:
        if not args.validate_low_priority and is_low_priority_candidate(row):
            outputs.append({**row,
                            "mapping_status": NOT_EVALUATED,
                            "mapping_reason": LOW_PRIORITY_CANDIDATE,
                            "status_reason": LOW_PRIORITY_CANDIDATE,
                            "evaluation_complete": "skipped_low_priority",
                            "api_calls_used": api_calls,
                            "api_call_limit": api_call_limit})
            continue
        key = (str(row.get("org_id", "")), str(row.get("tbl_id", "")))
        meta_rows = meta_by_table.get(key, [])
        grouped = group_official_meta(meta_rows)
        claim_text = " ".join(str(row.get(k, "")) for k in (
            "claim_text", "indicator", "measurement_indicator", "measurement", "entity",
            "population", "sex", "gender", "age", "age_group", "industry", "industry_or_item"))
        item_candidates = _merge_seeded_candidates(
            _lexical_candidates(grouped["items"], claim_text),
            _seeded_item_candidates(row),
        )
        seeded_obj = _seeded_obj_candidates(row, grouped)
        obj_candidates = {}
        for order, axis in grouped["axes"].items():
            lexical = _lexical_candidates(axis["values"], claim_text)
            merged = _merge_seeded_candidates(lexical, seeded_obj.get(order, []))
            if any(candidate["semantic_score"] > 0 for candidate in merged):
                obj_candidates[order] = merged
        periods = [str(_first(row, "measurement_period", "period")).strip()]
        comparison = str(row.get("comparison_period", "")).strip()
        if comparison:
            periods.append(comparison)

        def fetch(params: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
            extra = {f"obj_l{level}": params[f"objL{level}"] for level in range(2, 9)
                     if params.get(f"objL{level}") not in (None, "")}
            try:
                return get_stat_data(org_id=params["orgId"], tbl_id=params["tblId"],
                                     obj_l1=params.get("objL1", "ALL"), itm_id=params["itmId"],
                                     prd_se=params.get("prdSe", "Y"),
                                     startPrdDe=params.get("startPrdDe"), endPrdDe=params.get("endPrdDe"),
                                     **extra)
            finally:
                if args.delay > 0:
                    time.sleep(args.delay)

        if not key[1]:
            exhausted = str(row.get("table_search_exhausted", "")).strip().lower() in {"1", "true", "yes", "y"}
            reason = NO_KOSIS_TABLE if exhausted else MAPPING_FAILED
            result = {"mapping_status": reason, "mapping_reason": reason}
        else:
            result = validate_mapping_candidates(
                org_id=key[0], tbl_id=key[1], meta_rows=meta_rows,
                item_candidates=item_candidates, obj_candidates=obj_candidates,
                data_fetcher=fetch, expected_unit=_first(row, "canonical_unit", "unit"),
                required_periods=periods,
                prd_se=str(_first(row, "measurement_prd_se", "prd_se", default="Y")), item_top_k=args.item_top_k,
                obj_top_k=args.obj_top_k, max_combinations=args.max_combinations,
                claim=row, api_call_limit=api_call_limit, api_calls_used=api_calls)
            api_calls = int(result.get("api_calls_used", api_calls))
        outputs.append({**row, **result})
    resolve_measurement_level_ambiguity(outputs)
    _write_csv(Path(args.output), outputs)
    print(f"validated_rows={len(outputs)} api_calls={api_calls} output={args.output}")


if __name__ == "__main__":
    main()
