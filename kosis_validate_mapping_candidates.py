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
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


READY = "READY"
NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
MAPPING_FAILED = "MAPPING_FAILED"
NO_KOSIS_TABLE = "NO_KOSIS_TABLE"
API_ERROR = "API_ERROR"
NOT_EVALUATED = "NOT_EVALUATED"

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
        if obj_id.upper() == "ITEM":
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
    combinations: list[dict[str, Any]] = []
    products = itertools.product(*(choices for _, choices in axes)) if axes else [()]
    for item, selected in itertools.product(items, products):
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
        if len(combinations) >= max(0, max_combinations):
            return combinations
    return combinations


def build_kosis_request(
    org_id: str, tbl_id: str, combination: Mapping[str, Any], *,
    prd_se: str = "Y", periods: Sequence[str] | None = None,
    new_est_prd_cnt: int | None = None,
) -> dict[str, Any]:
    """Create Param API parameters from a metadata-validated combination."""
    if not combination.get("metadata_valid", True):
        raise ValueError("INVALID_COMBINATION: candidate contains non-official codes")
    params: dict[str, Any] = {"method": "getList", "orgId": org_id, "tblId": tbl_id,
                              "itmId": combination.get("itm_id"), "prdSe": prd_se,
                              "format": "json"}
    for level in range(1, 9):
        code = combination.get(f"objL{level}")
        if code not in (None, ""):
            params[f"objL{level}"] = code
    wanted = [str(x) for x in periods or [] if x not in (None, "")]
    if wanted:
        params["startPrdDe"], params["endPrdDe"] = min(wanted), max(wanted)
    elif new_est_prd_cnt is not None:
        params["newEstPrdCnt"] = int(new_est_prd_cnt)
    return params


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
    aliases = {"%": "percent", "퍼센트": "percent", "백분율": "percent",
               "명": "person", "천명": "person", "만명": "person",
               "원": "currency", "천원": "currency", "백만원": "currency", "억원": "currency"}
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
        status, reason = MAPPING_FAILED, "PERIOD_MISSING"
    elif not first.get("unit_valid", True):
        status, reason = NEEDS_CONFIRMATION, "UNIT_MISMATCH"
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
) -> dict[str, Any]:
    """Small orchestration helper. It performs at most ``max_combinations`` calls."""
    item_candidates = list(item_candidates or [])
    grouped = group_official_meta(meta_rows)
    combinations = build_candidate_combinations(item_candidates, obj_candidates, grouped,
        item_top_k=item_top_k, obj_top_k=obj_top_k, max_combinations=max_combinations)
    attempted, api_errors, empty_responses = [], 0, 0
    for combo in combinations:
        request = build_kosis_request(org_id, tbl_id, combo, prd_se=prd_se, periods=required_periods)
        result = dict(combo)
        try:
            response = list(data_fetcher(request) or [])
            if not response:
                empty_responses += 1
            result.update(response_matches_request(request, response))
            result.update(validate_unit_and_period(result["matching_rows"], expected_unit=expected_unit,
                                                   required_periods=required_periods))
        except Exception as exc:  # caller controls transport; preserve error without hiding other candidates
            api_errors += 1
            result.update({"response_code_valid": False, "api_valid": False,
                           "api_error": f"{type(exc).__name__}: {exc}"})
        attempted.append(result)
    ranked = rank_valid_combinations(attempted)
    decision = choose_or_abstain(ranked, margin_threshold=margin_threshold)
    if not combinations:
        decision.update(mapping_status=MAPPING_FAILED, mapping_reason="INVALID_COMBINATION")
    elif api_errors == len(combinations):
        decision.update(mapping_status=API_ERROR, mapping_reason="all candidate API calls failed")
    elif empty_responses == len(combinations):
        decision.update(mapping_status=MAPPING_FAILED, mapping_reason="EMPTY_RESPONSE")
    selected = decision.get("selected_combination") or {}
    output = {
        "candidate_itm_ids": [x["code"] for x in _normalize_candidates(item_candidates)[:item_top_k]],
        "candidate_obj_combinations": attempted,
        "attempted_combination_count": len(attempted),
        "api_valid_combination_count": len(ranked),
        "api_error_count": api_errors,
        "empty_response_count": empty_responses,
        **decision,
        "selected_itm_id": selected.get("itm_id", ""),
        "selected_itm_name": selected.get("itm_name", ""),
        "item_meta_valid": bool(selected.get("item_meta_valid")),
        "obj_meta_valid": bool(selected.get("obj_meta_valid")),
        "response_code_valid": bool(selected.get("response_code_valid")),
        "unit_valid": bool(selected.get("unit_valid")),
        "period_valid": bool(selected.get("period_valid")),
        "default_reason": selected.get("default_reason", ""),
        "default_risk": selected.get("default_risk", "NONE"),
    }
    for level in range(1, 4):
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


def resolve_table_ambiguity(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Apply the Mapping-end cross-table abstention rule to a Top-K slice."""
    outputs = [dict(row) for row in rows]
    by_measurement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outputs:
        key = str(row.get("claim_measurement_id") or row.get("claim_id") or "")
        by_measurement[key].append(row)
    for candidates in by_measurement.values():
        ready = [row for row in candidates if row.get("mapping_status") == READY]
        if len(ready) > 1:
            for row in ready:
                row["mapping_status"] = NEEDS_CONFIRMATION
                row["mapping_reason"] = (
                    "multiple table/ITEM/OBJ mappings are technically valid"
                )
    return outputs


def low_priority_reason(row: Mapping[str, Any]) -> str:
    try:
        rank = int(str(row.get("candidate_rank", "999")))
    except ValueError:
        rank = 999
    if row.get("candidate_status") == "ALTERNATE" and rank >= 3:
        return "LOW_PRIORITY_CANDIDATE"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate bounded KOSIS ITEM/OBJ combinations")
    parser.add_argument("--input", required=True)
    parser.add_argument("--meta-index", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--item-top-k", type=int, default=3)
    parser.add_argument("--obj-top-k", type=int, default=2)
    parser.add_argument("--max-combinations", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Explicit small API sample limit; 0 processes all")
    parser.add_argument(
        "--skip-table-ambiguity",
        action="store_true",
        help="Top-K sweep에서 재사용할 row별 기술 검증 상태를 보존",
    )
    args = parser.parse_args()

    from kosis_api_test import get_stat_data

    rows = _read_csv(Path(args.input))
    meta_by_table: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for meta in _read_csv(Path(args.meta_index)):
        meta_by_table[(str(meta.get("org_id", "")), str(meta.get("tbl_id", "")))].append(meta)
    work = rows[:args.limit] if args.limit else rows
    estimated = len(work) * max(0, args.max_combinations)
    print(f"candidate_rows={len(work)} max_combinations_per_row={args.max_combinations} estimated_api_calls<={estimated}")
    outputs: list[dict[str, Any]] = []
    for row in work:
        try:
            rank = int(str(row.get("candidate_rank", "999")))
        except ValueError:
            rank = 999
        priority_reason = low_priority_reason(row)
        if priority_reason:
            outputs.append({
                **row,
                "mapping_status": NOT_EVALUATED,
                "mapping_reason": priority_reason,
                "attempted_combination_count": 0,
                "api_valid_combination_count": 0,
            })
            continue
        key = (str(row.get("org_id", "")), str(row.get("tbl_id", "")))
        meta_rows = meta_by_table.get(key, [])
        grouped = group_official_meta(meta_rows)
        claim_text = " ".join(str(row.get(k, "")) for k in (
            "claim_text", "indicator", "measurement", "entity", "population", "sex", "age", "industry"))
        item_candidates = _lexical_candidates(grouped["items"], claim_text)
        obj_candidates = {order: _lexical_candidates(axis["values"], claim_text)
                          for order, axis in grouped["axes"].items()
                          if any(x["semantic_score"] > 0 for x in _lexical_candidates(axis["values"], claim_text))}
        periods = [str(row.get("period", "")).strip()]
        comparison = str(row.get("comparison_period", "")).strip()
        if comparison:
            periods.append(comparison)

        def fetch(params: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
            extra = {f"obj_l{level}": params[f"objL{level}"] for level in range(2, 9)
                     if params.get(f"objL{level}") not in (None, "")}
            return get_stat_data(org_id=params["orgId"], tbl_id=params["tblId"],
                                 obj_l1=params.get("objL1", "ALL"), itm_id=params["itmId"],
                                 prd_se=params.get("prdSe", "Y"),
                                 startPrdDe=params.get("startPrdDe"), endPrdDe=params.get("endPrdDe"),
                                 **extra)

        if not key[1]:
            result = {"mapping_status": NO_KOSIS_TABLE, "mapping_reason": "NO_KOSIS_TABLE"}
        else:
            result = validate_mapping_candidates(
                org_id=key[0], tbl_id=key[1], meta_rows=meta_rows,
                item_candidates=item_candidates, obj_candidates=obj_candidates,
                data_fetcher=fetch, expected_unit=row.get("unit"), required_periods=periods,
                prd_se=str(row.get("prd_se") or "Y"), item_top_k=args.item_top_k,
                obj_top_k=args.obj_top_k, max_combinations=args.max_combinations)
        if (
            result.get("mapping_status") == READY
            and not (rank == 1 and row.get("candidate_status") == "READY")
        ):
            result["mapping_status"] = NEEDS_CONFIRMATION
            result["mapping_reason"] = (
                "upstream table candidate is not decisive rank-1 READY"
            )
        outputs.append({**row, **result})
    if not args.skip_table_ambiguity:
        outputs = resolve_table_ambiguity(outputs)
    _write_csv(Path(args.output), outputs)
    print(f"validated_rows={len(outputs)} output={args.output}")


if __name__ == "__main__":
    main()
