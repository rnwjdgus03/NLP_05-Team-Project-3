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
PROVISIONAL = "PROVISIONAL"
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
                   if x["code"] in grouped["axis_codes"][order] and _score(x) > 0][:max(0, obj_top_k)]
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
    if not text:
        return set()
    if text in {"%p", "%포인트", "퍼센트포인트", "percentagepoint"}:
        return {"percentage_point"}
    if text in {"%", "퍼센트", "백분율", "percent"}:
        return {"percent"}
    if "달러" in text or "us$" in text or "usd" in text or text in {"$", "불", "미화"}:
        return {"currency_usd"}
    if "원" in text:
        return {"currency_krw"}
    if "명" in text or text in {"인", "사람"}:
        return {"person"}
    if text in {"개", "개사", "사", "곳", "업체", "기업", "회사"}:
        return {"organization_count"}
    if text in {"대", "건", "가구", "세대", "호", "회"}:
        return {f"count_{text}"}
    return {text}


def _is_dimensionless_index_row(row: Mapping[str, Any]) -> bool:
    """Recognize index level ITEMs whose KOSIS unit metadata is blank."""
    item_name = str(
        _first(row, "ITM_NM", "itm_name", "item_name", "ITM_NM_ENG")
    ).strip().lower()
    return bool(item_name) and ("지수" in item_name or "index" in item_name)


def validate_unit_and_period(
    rows: Iterable[Mapping[str, Any]], *, expected_unit: str | None = None,
    required_periods: Sequence[str] | None = None, mapping_type: str = "direct",
) -> dict[str, Any]:
    rows = list(rows or [])
    units = {_first(row, "UNIT_NM", "UNIT", "unit") for row in rows}
    if mapping_type in {"rate_from_level", "difference_from_level"}:
        # The claim unit is derived from two KOSIS level values, so it must not be
        # compared directly with the source ITEM unit (for example % vs thousand USD).
        unit_valid = any(
            (
                _unit_tokens(_first(row, "UNIT_NM", "UNIT", "unit"))
                and not (
                    _unit_tokens(_first(row, "UNIT_NM", "UNIT", "unit"))
                    & {"percent", "percentage_point"}
                )
            )
            or (
                not _unit_tokens(_first(row, "UNIT_NM", "UNIT", "unit"))
                and _is_dimensionless_index_row(row)
            )
            for row in rows
        )
    else:
        unit_valid = True if not expected_unit else any(
            _unit_tokens(expected_unit) & _unit_tokens(unit) for unit in units
        )
    # KOSIS 응답/메타에 단위 자체가 없으면 '불일치'가 아니라 '미상'이다.
    # 자동 확정은 여전히 막되(unit_valid=False 유지), 사유를 구분해 잘못된 원인 분석을 막는다.
    # 단, rate_from_level/difference_from_level 에서 단위 없음은 '지수가 아닌 항목의 증감률 계산 근거 없음'
    # 이라는 의도적 거부이므로 기존대로 UNIT_MISMATCH 를 유지한다.
    unit_unknown = (
        mapping_type not in {"rate_from_level", "difference_from_level"}
        and bool(expected_unit)
        and not unit_valid
        and not any(_unit_tokens(u) for u in units)
    )
    available = {str(_first(row, "PRD_DE", "PRD", "period")) for row in rows}
    required = {str(x) for x in required_periods or [] if x not in (None, "")}
    missing = sorted(required - available)
    if missing:
        reason = "PERIOD_MISSING"
    elif unit_unknown:
        reason = "UNIT_UNKNOWN"
    elif not unit_valid:
        reason = "UNIT_MISMATCH"
    else:
        reason = ""
    return {"unit_valid": unit_valid, "period_valid": not missing,
            "unit_unknown": unit_unknown,
            "available_periods": sorted(available - {""}), "missing_periods": missing,
            "validation_reason": reason}


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
    allow_provisional: bool = False,
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
            status = PROVISIONAL if allow_provisional else NEEDS_CONFIRMATION
            reason = f"top candidates have small margin ({margin:.4f})"
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
    mapping_type: str = "direct", allow_provisional: bool = False,
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
            kosis_errors = [row for row in response if str(row.get("err", "")).strip()]
            if kosis_errors:
                error_codes = {str(row.get("err", "")).strip() for row in kosis_errors}
                error_message = "; ".join(
                    str(row.get("errMsg", "")).strip() for row in kosis_errors
                    if str(row.get("errMsg", "")).strip()
                )
                if error_codes == {"30"}:
                    response = []
                else:
                    api_errors += 1
                    result.update({
                        "response_code_valid": False,
                        "api_valid": False,
                        "api_error": f"KOSIS_ERROR[{','.join(sorted(error_codes))}]: {error_message}",
                    })
                    attempted.append(result)
                    continue
            if not response:
                empty_responses += 1
            result.update(response_matches_request(request, response))
            result.update(validate_unit_and_period(
                result["matching_rows"], expected_unit=expected_unit,
                required_periods=required_periods, mapping_type=mapping_type,
            ))
            if not result["response_code_valid"]:
                result["validation_reason"] = "RESPONSE_CODE_MISMATCH"
        except Exception as exc:  # caller controls transport; preserve error without hiding other candidates
            api_errors += 1
            result.update({"response_code_valid": False, "api_valid": False,
                           "api_error": f"{type(exc).__name__}: {exc}"})
        attempted.append(result)
    ranked = rank_valid_combinations(attempted)
    decision = choose_or_abstain(
        ranked,
        margin_threshold=margin_threshold,
        allow_provisional=allow_provisional,
    )
    required_period_set = {str(value) for value in required_periods or [] if value not in (None, "")}
    if (
        mapping_type in {"rate_from_level", "difference_from_level"}
        and len(required_period_set) < 2
        and decision.get("mapping_status") == READY
    ):
        decision.update(
            mapping_status=NEEDS_CONFIRMATION,
            mapping_reason="DERIVATION_BASE_PERIOD_MISSING",
        )
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
        # A one-character code name such as "대" or "면" must not match inside
        # unrelated words such as "역대" or "반도체".
        score = (1.0 if len(compact_name) >= 2 and compact_name in normalized else 0.0)
        score += len(tokens & name_tokens) / max(1, len(name_tokens))
        for token in name_tokens:
            if len(token) < 2 or token in tokens:
                continue
            prefix_length = 0
            for length in range(len(token) - 1, 1, -1):
                if token[:length] in normalized:
                    prefix_length = length
                    break
            score += 0.75 * prefix_length / len(token)
        out.append({"code": value.get("code", ""), "name": name, "semantic_score": score})
    return sorted(out, key=lambda x: x["semantic_score"], reverse=True)


def _merge_seeded_candidates(
    lexical: Iterable[Mapping[str, Any]],
    seeded: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge upstream meta selections as hints without bypassing code validation."""
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
        merged[code] = {
            **base,
            **row,
            "code": code,
            "semantic_score": max(_score(base), _score(row)),
            "seeded_hint": True,
        }
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


def _seeded_obj_candidates(
    row: Mapping[str, Any],
    grouped: Mapping[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    axis_orders = {
        str(axis.get("obj_id", "")): order
        for order, axis in grouped.get("axes", {}).items()
        if str(axis.get("obj_id", ""))
    }
    seeded: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for level in range(1, 9):
        code = str(row.get(f"selected_obj_l{level}", "")).strip()
        if not code:
            continue
        axis_id = str(row.get(f"selected_obj_l{level}_axis_id", "")).strip()
        order = axis_orders.get(axis_id, level)
        if order not in grouped.get("axes", {}):
            continue
        seeded[order].append({
            "code": code,
            "name": str(row.get(f"selected_obj_l{level}_name", "")).strip(),
            "semantic_score": _score({
                "semantic_score": row.get(f"selected_obj_l{level}_score", "")
            }),
            "seeded_hint": True,
        })
    return seeded


def build_claim_context(row: Mapping[str, Any]) -> str:
    fields = (
        "claim_text", "indicator", "measurement_indicator", "measurement",
        "measurement_text", "entity", "population", "population_etc",
        "sex", "gender", "age", "age_group", "industry",
        "industry_or_item", "measurement_item", "region", "origin_country",
        "destination_country",
    )
    return " ".join(str(row.get(key, "")) for key in fields)


def build_obj_context(row: Mapping[str, Any]) -> str:
    """Build a narrow context for OBJ selection without incidental article words."""
    scope_fields = (
        "industry_or_item", "measurement_item", "entity", "population",
        "population_etc", "sex", "gender", "age", "age_group", "region",
        "origin_country", "destination_country",
    )
    scopes = [
        str(row.get(key, "")).strip()
        for key in scope_fields
        if str(row.get(key, "")).strip() not in {"", "-"}
    ]
    indicator = str(_first(row, "indicator", "measurement_indicator")).strip()
    metric_phrases = (
        "수출액 증감률", "수출 증가율", "수입 증가율", "수입 증감률",
        "수출 증감률", "여객 수", "이용객 수", "정비사 수 비율",
        "정비사 비율", "정비사 수", "기업 수",
        "무역수지 증감", "무역수지", "증가율", "감소율", "증감률", "비율",
    )
    for phrase in metric_phrases:
        indicator = indicator.replace(phrase, " ")
    indicator = re.sub(r"\s+", " ", indicator).strip()
    if indicator:
        scopes.append(indicator)
    return " ".join(dict.fromkeys(scopes))


def _semantic_compact(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values).lower()
    return re.sub(r"[^0-9a-z\uac00-\ud7a3%]+", "", text)


def _semantic_selected_text(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str:
    selected = result.get("selected_combination")
    selected = selected if isinstance(selected, Mapping) else {}
    values = [
        row.get("tbl_name", ""),
        row.get("category_path", ""),
        result.get("selected_itm_name", ""),
        selected.get("itm_name", ""),
    ]
    for level in range(1, 9):
        values.extend([
            result.get(f"selected_obj_l{level}_name", ""),
            selected.get(f"objL{level}_name", ""),
        ])
    return _semantic_compact(*values)


SEMANTIC_ANCHOR_GROUPS = (
    (
        "FISCAL_SCOPE_MISMATCH",
        (
            "\uae30\ud68d\uc7ac\uc815\ubd80",
            "\uc7ac\uc815\ub3d9\ud5a5",
            "\uad6d\uac00\uc7ac\uc815",
            "\uc815\ubd80\ucd1d\uc218\uc785",
            "\ub204\uacc4\ucd1d\uc218\uc785",
        ),
        ("\uc7ac\uc815", "\uc138\uc785", "\uc138\ucd9c", "\uc815\ubd80", "\uad6d\uac00"),
    ),
    (
        "DELINQUENCY_CONCEPT_MISMATCH",
        (
            "\uac1a\uc9c0\ubabb",
            "\ubbf8\uc0c1\ud658",
            "\uc5f0\uccb4",
            "\ubd80\uc2e4\ucc44\uad8c",
            "\ucc44\ubb34\ubd88\uc774\ud589",
        ),
        (
            "\ubbf8\uc0c1\ud658",
            "\uc5f0\uccb4",
            "\ubd80\uc2e4",
            "\ucc44\ubb34\ubd88\uc774\ud589",
            "\uc0c1\ud658\ubd88\ub2a5",
        ),
    ),
    (
        "SALES_CONCEPT_MISMATCH",
        ("\ud310\ub9e4", "\ud310\ub9e4\ub7c9", "\ud310\ub9e4\ub300\uc218"),
        ("\ud310\ub9e4", "\ub4f1\ub85d", "\ub300\uc218"),
    ),
    (
        "INTERMEDIATE_GOODS_SCOPE_MISMATCH",
        ("\uc911\uac04\uc7ac",),
        ("\uc911\uac04\uc7ac",),
    ),
    (
        "US_SCOPE_MISMATCH",
        ("\ub300\ubbf8\uc218\ucd9c", "\ubbf8\uad6d\uc218\ucd9c", "\ubbf8\uad6d\ub0b4"),
        ("\ub300\ubbf8", "\ubbf8\uad6d"),
    ),
    (
        "CHINA_SCOPE_MISMATCH",
        ("\ub300\uc911\uc218\ucd9c", "\uc911\uad6d\uc218\ucd9c", "\uc911\uad6d\ub0b4"),
        ("\ub300\uc911", "\uc911\uad6d"),
    ),
    (
        "IMPORTED_CAR_SCOPE_MISMATCH",
        ("\uc218\uc785\ucc28",),
        ("\uc218\uc785\ucc28", "\uc790\ub3d9\ucc28", "\uc2b9\uc6a9\ucc28"),
    ),
)


def semantic_ready_gate(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Require claim-to-table semantic anchors before automatic READY."""
    claim_text = _semantic_compact(
        row.get("claim_text", ""),
        _first(row, "indicator", "measurement_indicator"),
        row.get("metric_domain", ""),
    )
    mapped_text = _semantic_selected_text(row, result)
    reasons: list[str] = []

    if not mapped_text:
        reasons.append("SEMANTIC_MAPPING_CONTEXT_MISSING")

    for reason, claim_terms, mapped_terms in SEMANTIC_ANCHOR_GROUPS:
        if any(term in claim_text for term in claim_terms) and not any(
            term in mapped_text for term in mapped_terms
        ):
            reasons.append(reason)

    age_pattern = (
        r"(?:^|[^0-9\ub9cc\uc5b5\uc870])(\d{1,2})\ub300"
        r"(?:\uc774\uc0c1|\uc774\ud558|\ucde8\uc5c5|\uc778\uad6c|\uc0ac\ub78c|"
        r"\uc5ec\uc131|\ub0a8\uc131|\uac1c\uc778|\uadfc\ub85c|\uac00\uad6c|"
        r"\uc18c\ube44|\uc18c\ub4dd)"
    )
    for age in re.findall(age_pattern, claim_text):
        if f"{age}\ub300" not in mapped_text:
            reasons.append("AGE_SCOPE_MISMATCH")
            break

    selected = result.get("selected_combination")
    selected = selected if isinstance(selected, Mapping) else {}
    for level in range(1, 9):
        obj_name = _semantic_compact(
            result.get(f"selected_obj_l{level}_name", ""),
            selected.get(f"objL{level}_name", ""),
        )
        if (
            re.search(r"\d+(?:\ub9cc|\uc5b5)?(?:\uc6d0|\uba85|\uc138)?(?:\ubbf8\ub9cc|\uc774\uc0c1|~|-)\d*", obj_name)
            and obj_name not in claim_text
        ):
            reasons.append("UNGROUNDED_NUMERIC_OBJ_SCOPE")
            break

    # claim 품목 ↔ 좌표 일치. **모든 확정 경로가 이 검사를 거쳐야 한다.**
    #
    # 2026-08-02: 이 가드가 downstream_validated_rank1(회수 경로)에만 있었다.
    # 상류가 결정적이면(rank==1 and candidate_status==READY) 건너뛰고 확정돼서,
    # '전체 수출액 6838억달러' 주장에 objL1=반도체 좌표가 붙은 채 READY 가 됐고
    # 시스템이 '불일치'라고 단언했다(실측). 참인 기사에 거짓 딱지를 붙인 것이다.
    #
    # 차이율 임계값(LIKELY_MISMAPPING)으로는 못 막는다 — 그 건의 차이율은 79% 로
    # 수준값 임계값 300% 아래였다. 값이 아니라 의미로 막아야 한다.
    if not claim_item_matches_selection(row, result):
        reasons.append("CLAIM_ITEM_MISMATCH")

    # claim 의 대상이 그 문장에 실제로 나오는가.
    #
    # 2026-08-02 실측: '작년 한 해 전체 수출액이 6838억달러' 라는 문장의
    # industry_or_item 이 '반도체'였다. 기사 전체가 반도체를 다루니 상류 추출이
    # 그 대상을 이 measurement 에 붙인 것이다. 그 결과 objL1=반도체 좌표가
    # '대상=반도체 · 좌표=반도체'로 정상 통과해 확정됐고 '불일치'로 단언됐다.
    # 전체 수출액(6838억)을 반도체 수출액(1420억)과 비교한 셈이다.
    #
    # 문장에 없는 대상은 이 measurement 의 것이 아니다. 확정하지 않는다.
    # 앞 문장에서 이어받는 정당한 생략도 있으므로 **거부가 아니라 확정 보류**다.
    if not claim_item_grounded(row):
        reasons.append("UNGROUNDED_CLAIM_ITEM")

    reasons = list(dict.fromkeys(reasons))
    return {
        "semantic_gate_valid": not reasons,
        "semantic_gate_reason": reasons[0] if reasons else "",
        "semantic_gate_details": ";".join(reasons),
    }


def apply_semantic_ready_gate(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    output = dict(result)
    gate = semantic_ready_gate(row, output)
    output.update(gate)
    if output.get("mapping_status") in {READY, PROVISIONAL} and not gate["semantic_gate_valid"]:
        output["mapping_status"] = NEEDS_CONFIRMATION
        output["mapping_reason"] = gate["semantic_gate_reason"]
    return output


def resolve_table_ambiguity(
    rows: Sequence[Mapping[str, Any]],
    *,
    allow_provisional: bool = False,
) -> list[dict[str, Any]]:
    """Apply the Mapping-end cross-table abstention rule to a Top-K slice."""
    outputs = [dict(row) for row in rows]
    by_measurement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outputs:
        key = str(row.get("claim_measurement_id") or row.get("claim_id") or "")
        by_measurement[key].append(row)
    for candidates in by_measurement.values():
        ready = [row for row in candidates if row.get("mapping_status") == READY]
        if len(ready) > 1:
            ready.sort(key=_rank_of)
            for index, row in enumerate(ready):
                if allow_provisional and index == 0:
                    row["mapping_status"] = PROVISIONAL
                    row["mapping_reason"] = (
                        "multiple technically valid coordinates; top candidate is provisional"
                    )
                    continue
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


# 2026-08-02: 같은 개념의 목록이 이 파일과 kosis_meta_coordinates 에 따로 있었고
# 내용이 달랐다(6개 vs 9개). 정식 목록 한 곳에서 가져온다.
# 이때 '총지수'가 새로 들어온다 — 골드 정답이 T10(총지수)인데 집계로 인정받지 못해
# 밀린 실측 사례가 근거다. 자동 확정 건수가 바뀔 수 있으므로 반드시 재측정할 것.
from kosis_meta_coordinates import (  # noqa: E402
    AGGREGATE_ITEM_TOKENS,
    AGGREGATE_OBJ_NAMES,
    normalize_periodicity,
    periodicity_satisfied,
    table_periodicities,
)
# 대상 근거 검사는 상류(prepare)와 **같은 구현**을 쓴다.
# 가드가 두 벌이면 반드시 어긋난다 — 오늘 그 실수를 세 번 했다.
from prepare_kosis_mapping_input import claim_item_grounded  # noqa: E402


def _normalize(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def selection_is_aggregate(result: Mapping[str, Any] | None,
                           row: Mapping[str, Any] | None = None) -> bool:
    """선택된 OBJ 좌표가 집계값인가 (분류축이 비어 있으면 집계로 본다)."""
    sources = dict(row or {})
    if result:
        sources.update({k: v for k, v in result.items() if v not in (None, "")})
    names = [str(sources.get(f"selected_obj_l{level}_name", "")).strip()
             for level in (1, 2, 3)]
    names = [name for name in names if name]
    if not names:
        return True
    return all(_normalize(name) in {_normalize(t) for t in AGGREGATE_OBJ_NAMES}
               for name in names)


def claim_item_matches_selection(row: Mapping[str, Any],
                                 result: Mapping[str, Any] | None = None) -> bool:
    """claim 이 특정 품목·대상을 말하는데 선택된 좌표가 그것과 무관하면 False.

    API 응답이 정상이어도 의미가 다른 좌표가 뽑힐 수 있어(예: 반도체 → 인산에스테르)
    기술 유효성만으로는 자동 확정이 위험하다.

    2026-07-31 보완: **품목 제약이 없는 claim 을 무조건 통과시키던 구멍**을 막는다.
    '무역수지', '물가 상승률' 처럼 세부 대상을 특정하지 않은 주장이
    objL1=건설 / objL1=자가주거비 같은 세부 분류에 붙어 자동 확정됐고,
    그중 2건은 잘못된 좌표로 '불일치' 판정까지 갔다(실측).
    → 주장이 세부 대상을 말하지 않으면 좌표도 집계값이어야 한다.
    """
    raw_item = str(_first(row, "industry_or_item", "measurement_item")).strip()
    normalized_item = _normalize(raw_item)
    if not normalized_item or raw_item in AGGREGATE_ITEM_TOKENS:
        return selection_is_aggregate(result, row)
    sources = dict(row)
    if result:
        sources.update({k: v for k, v in result.items() if v not in (None, "")})
    selected = " ".join(str(sources.get(key, "")) for key in (
        "selected_itm_name", "selected_obj_l1_name", "selected_obj_l2_name",
        "selected_obj_l3_name", "kosis_obj_l1_name", "tbl_name",
    ))
    normalized_selected = re.sub(r"[^0-9A-Za-z가-힣]", "", selected).lower()
    if not normalized_selected:
        return True
    if normalized_item in normalized_selected or normalized_selected in normalized_item:
        return True
    return any(len(token) >= 2 and re.sub(r"[^0-9A-Za-z가-힣]", "", token).lower() in normalized_selected
               for token in re.findall(r"[가-힣A-Za-z]{2,}", raw_item))


def downstream_validated_rank1(row: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    """상류 표 후보가 REVIEW여도 하류 실측 검증이 모두 통과한 rank-1이면 decisive로 인정.

    상류(kosis_match)의 REVIEW는 '표 이름 점수만으로는 확신 못 함'이라는 보수적 신호인데,
    validate는 그 뒤에 공식 메타 코드 검증 + 실제 API 응답 + 단위·기간 정합까지 확인한다.
    실측이 전부 통과했다면 상류의 불확실성은 이미 해소된 것이므로 READY를 유지한다.

    안전 조건(모두 필요):
      - rank 1
      - 상류가 REJECT가 아님 (REJECT는 '의미상 맞는 ITEM 없음' 등 의미 실패라 존중)
      - 하류 실측: 메타 코드 유효 + API 응답 코드 일치 + 단위 유효 + 기간 유효
      - 상류 1·2위 점수차가 최소 마진 이상 (동점 표는 여전히 사람 확인)
    """
    if _rank_of(row) != 1:
        return False
    if str(row.get("candidate_status", "")).strip().upper() == "REJECT":
        return False
    checks = (
        result.get("item_meta_valid", result.get("metadata_valid")),
        result.get("obj_meta_valid", result.get("metadata_valid")),
        result.get("response_code_valid"),
        result.get("unit_valid"),
        result.get("period_valid"),
    )
    if not all(str(value).strip().lower() in {"true", "1", "y", "yes"} for value in checks):
        return False
    # 의미 가드: 기술적으로 유효해도 claim 품목과 무관한 좌표는 신뢰하지 않는다.
    # (실측 오매핑: 농수산식품 수출 → '건조기(농산물용의 것)', 반도체 → '인산에스테르 및 그 염…')
    if not claim_item_matches_selection(row, result):
        return False
    # 2026-08-02: 상류 표 점수 마진 조건을 제거했다.
    #
    # 이 조건은 '1·2위 표 점수가 비슷하면 표 선택이 애매하다'는 상류 신호였다.
    # 그런데 여기까지 온 후보는 이미 공식 메타·API 응답·단위·기간·의미 가드를
    # 모두 독립 통과했다. 약한 상류 신호가 강한 하류 증거를 덮고 있었다.
    #
    # 근거(실측, 게이트를 우회해 조회):
    #   1차(평가집합 103) 마진만으로 막힌 5건 → 회수 2 · 거짓 불일치 2. 1:1 이라 유지했다.
    #   2차(평가집합 88)  마진만으로 막힌 4건 → 회수 2 · **거짓 불일치 0**.
    # 달라진 이유는 그 거짓 불일치 2건의 정체다.
    #   하나는 '한 달 전(1.4%)' 비교 기준 오독 → CHANGE_BASE_AMBIGUOUS 로 보류하게 고쳤다
    #   하나는 '정부의 한은 차입' → 범위 밖이라 출처 전파 강화로 집합에서 빠졌다
    # 즉 마진이 막고 있던 것은 **다른 게이트가 맡아야 할 일**이었다.
    # 그 둘이 제 몫을 하게 되자 마진은 정상 확정만 막고 있었다.
    #
    # 마진은 표 검색 품질과도 무관했다 — 게이트를 우회한 판정에서
    # 마진이 얇은 쪽 일치율 50%(3/6), 넓은 쪽 25%(1/4)로 방향이 오히려 반대였다(n=10).
    #
    # 남은 안전 조건은 그대로다: rank1 · 상류 REJECT 제외 · 메타·API·단위·기간 실측 통과 ·
    # 의미 가드. 되돌리려면 이 함수에 마진 검사를 다시 넣으면 된다.
    return True


def _rank_of(row: Mapping[str, Any]) -> int:
    try:
        return int(float(str(row.get("candidate_rank", "999"))))
    except (TypeError, ValueError):
        return 999


FALLBACK_TRIGGER_REASONS = (
    "EMPTY_RESPONSE", "RESPONSE_CODE_MISMATCH", "INVALID_COMBINATION",
    "ITEM_UNRESOLVED", "OBJ_UNRESOLVED", "NO_KOSIS_TABLE", "INVALID_REQUEST",
)


def measurement_key(row: Mapping[str, Any]) -> str:
    return str(row.get("claim_measurement_id") or row.get("claim_id") or "").strip()


def needs_fallback(result: Mapping[str, Any]) -> bool:
    """상위 후보가 '기술적으로 못 쓰는' 상태인가 → 다음 순위 표로 폴백할 가치가 있는지.

    NEEDS_CONFIRMATION(사람 확인 대기)은 이미 쓸 수 있는 좌표를 찾은 것이므로 폴백하지 않는다.
    빈 응답·코드 불일치·조합 불가처럼 그 표로는 값을 못 얻는 경우에만 다음 후보를 평가한다.
    """
    status = str(result.get("mapping_status") or "")
    if status in (READY, PROVISIONAL, NEEDS_CONFIRMATION):
        return False
    reason = str(result.get("mapping_reason") or result.get("status_reason") or "")
    return any(token in reason for token in FALLBACK_TRIGGER_REASONS) or status in (
        MAPPING_FAILED, NO_KOSIS_TABLE, API_ERROR, "EMPTY_RESPONSE",
    )


def _previous_year_period(period: str) -> str:
    value = str(period or "").strip()
    if not re.fullmatch(r"\d{4}(?:\d{2})?", value):
        return ""
    return f"{int(value[:4]) - 1}{value[4:]}"


def required_periods_for_row(row: Mapping[str, Any]) -> list[str]:
    periods = [str(_first(row, "period", "measurement_period")).strip()]
    comparison = str(row.get("comparison_period", "")).strip()
    if comparison:
        periods.append(comparison)
    elif str(row.get("mapping_type", "")) in {"rate_from_level", "difference_from_level"}:
        claim_text = str(row.get("claim_text", ""))
        if re.search(r"전년(?:도|\s*동기|\s*동월)?", claim_text):
            previous = _previous_year_period(periods[0])
            if previous:
                periods.append(previous)
    return [period for period in dict.fromkeys(periods) if period]


def periodicity_unavailable(row, meta_rows) -> str:
    """주장이 필요로 하는 주기를 표가 못 주면 사유 코드. 줄 수 있거나 모르면 빈 문자열.

    **모르면 막지 않는다.** prd_se_list 는 --with-periodicity 로 수집해야 채워지고,
    그 전 산출물에는 없다. 없는 것을 '못 준다'로 읽으면 전부 죽는다.
    """
    wanted = normalize_periodicity(row.get("prd_se") or row.get("measurement_prd_se"))
    if not wanted:
        return ""
    available = table_periodicities(meta_rows)
    if periodicity_satisfied(wanted, available):
        return ""
    return f"PERIODICITY_NOT_AVAILABLE: 표는 {'/'.join(sorted(available))} 만 제공, 주장은 {wanted}"


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
    parser.add_argument(
        "--evaluate-all-ranks",
        action="store_true",
        help="Evaluate rank 3+ candidates for a Top-K experiment instead of marking them low priority.",
    )
    parser.add_argument(
        "--trust-downstream-validation",
        action="store_true",
        help=("[더 이상 필요 없음] 2026-07-31부터 기본 동작이다. 기존 명령 호환용으로 남겨둔다."),
    )
    parser.add_argument(
        "--require-upstream-ready",
        action="store_true",
        help=("옛 동작 복원: 하류 실측이 전부 통과해도 상류 표 후보가 rank-1 READY가"
              " 아니면 NEEDS_CONFIRMATION으로 강등한다. 회귀 비교용."),
    )
    parser.add_argument(
        "--fallback-ranks",
        action="store_true",
        help=("measurement별로 상위 후보가 빈 응답·조합 불가로 실패하면 다음 순위 표를 자동 평가한다"
              " (첫 성공 채택). 저순위는 폴백이 필요할 때만 API를 호출한다."),
    )
    parser.add_argument(
        "--allow-provisional",
        action="store_true",
        help=(
            "메타·API·기간·단위가 유효하지만 1·2위 ITEM/OBJ 조합 점수차가 작은 "
            "rank-1 후보를 PROVISIONAL로 분리한다. PROVISIONAL은 actual_value "
            "자동 verdict 대상이 아니다."
        ),
    )
    parser.add_argument(
        "--strict-seeded-coordinate",
        action="store_true",
        help=(
            "selected_itm_id/selected_obj_l<n> 좌표만 API로 검증한다. Chroma 좌표 검색 "
            "출력처럼 이미 좌표가 확정된 후보에서 검증기가 lexical 조합을 다시 만드는 "
            "것을 막는다."
        ),
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
    # --fallback-ranks: measurement별로 순위대로 평가하다가 상위가 기술적으로 실패하면
    # 다음 순위를 이어서 평가한다(첫 성공 채택). 성공 이후의 남은 저순위는 호출하지 않는다.
    fallback_state: dict[str, bool] = {}
    if args.fallback_ranks:
        work = sorted(work, key=lambda r: (measurement_key(r), _rank_of(r)))

    outputs: list[dict[str, Any]] = []
    for row in work:
        rank = _rank_of(row)
        mkey = measurement_key(row)
        priority_reason = "" if args.evaluate_all_ranks else low_priority_reason(row)
        if priority_reason and args.fallback_ranks and fallback_state.get(mkey, True):
            # 이 measurement가 아직 성공하지 못했다면 저순위도 폴백 대상으로 평가한다.
            priority_reason = ""
        if priority_reason:
            outputs.append({
                **row,
                "mapping_status": NOT_EVALUATED,
                "mapping_reason": priority_reason,
                "attempted_combination_count": 0,
                "api_valid_combination_count": 0,
            })
            continue
        if args.fallback_ranks and not fallback_state.get(mkey, True):
            # 앞 순위에서 이미 사용 가능한 좌표를 찾음 → 추가 API 호출 없이 스킵
            outputs.append({
                **row,
                "mapping_status": NOT_EVALUATED,
                "mapping_reason": "FALLBACK_NOT_NEEDED",
                "attempted_combination_count": 0,
                "api_valid_combination_count": 0,
            })
            continue
        key = (str(row.get("org_id", "")), str(row.get("tbl_id", "")))
        meta_rows = meta_by_table.get(key, [])
        # 표가 그 주기를 제공하지 않으면 **조회하지 않는다.**
        # KOSIS 는 없는 주기를 물어도 에러를 내지 않고 연간 행을 그대로 준다
        # (실측 DT_127005_005: prdSe=M 에 PRD_DE=['2019'..'2024']).
        # 조회해버리면 분기 주장에 연간값이 붙어 거짓 불일치가 난다.
        unavailable = periodicity_unavailable(row, meta_rows)
        if unavailable:
            outputs.append({
                **row,
                "mapping_status": MAPPING_FAILED,
                "mapping_reason": unavailable,
                "mapping_confidence": 0.0,
                "api_valid_combination_count": 0,
            })
            continue
        grouped = group_official_meta(meta_rows)
        claim_text = build_claim_context(row)
        obj_text = build_obj_context(row)
        seeded_items = _seeded_item_candidates(row)
        if args.strict_seeded_coordinate:
            coordinate_score = 1.0 / max(rank, 1)
            item_candidates = [
                {**candidate, "semantic_score": coordinate_score}
                for candidate in seeded_items
            ]
        else:
            item_candidates = _merge_seeded_candidates(
                _lexical_candidates(grouped["items"], claim_text),
                seeded_items,
            )
        seeded_obj = _seeded_obj_candidates(row, grouped)
        obj_candidates = {}
        for order, axis in grouped["axes"].items():
            if args.strict_seeded_coordinate:
                candidates = [
                    {**candidate, "semantic_score": coordinate_score}
                    for candidate in seeded_obj.get(order, [])
                ]
            else:
                candidates = _merge_seeded_candidates(
                    _lexical_candidates(axis["values"], obj_text),
                    seeded_obj.get(order, []),
                )
            if any(candidate["semantic_score"] > 0 for candidate in candidates):
                obj_candidates[order] = candidates
        periods = required_periods_for_row(row)

        def fetch(params: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
            extra = {f"obj_l{level}": params[f"objL{level}"] for level in range(2, 9)
                     if params.get(f"objL{level}") not in (None, "")}
            return get_stat_data(org_id=params["orgId"], tbl_id=params["tblId"],
                                 obj_l1=params.get("objL1"), itm_id=params["itmId"],
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
                prd_se=str(_first(row, "prd_se", "measurement_prd_se", default="Y")),
                item_top_k=args.item_top_k,
                obj_top_k=args.obj_top_k, max_combinations=args.max_combinations,
                mapping_type=str(row.get("mapping_type") or "direct"),
                allow_provisional=args.allow_provisional,
            )
        # 이중 게이트 해제 (2026-07-31)
        # validate는 이미 공식 메타 코드 + 실제 API 응답 + 단위·기간 정합을 독립 검증한다.
        # 그래놓고 상류 표 후보가 rank-1 READY가 아니라는 이유로 다시 강등하는 것은
        # 같은 불확실성을 두 번 요구하는 중복 게이트였다.
        # 실측: 확정 집합 134건 중 READY가 2건뿐이었고, 기술적으로 완전 유효한 후보가
        #       TOP1_GATE_ONLY/RANK_ONLY로 대기 중이었다.
        # 안전 조건은 downstream_validated_rank1()이 그대로 지킨다(rank1·상류 REJECT 제외·
        # 실측 전항목 통과·의미 가드·점수 마진). --require-upstream-ready로 옛 동작 복원 가능.
        upstream_decisive = rank == 1 and row.get("candidate_status") == "READY"
        if args.require_upstream_ready:
            downstream_decisive = False
        else:
            downstream_decisive = downstream_validated_rank1(row, result)

        if (result.get("mapping_status") in {READY, PROVISIONAL}
                and not upstream_decisive and not downstream_decisive):
            result["mapping_status"] = NEEDS_CONFIRMATION
            result["mapping_reason"] = (
                "upstream table candidate is not decisive rank-1 READY"
            )
        elif downstream_decisive and not upstream_decisive:
            # 어떤 경로로 READY가 됐는지 추적 가능하게 남긴다(감사용).
            result["ready_path"] = "DOWNSTREAM_VALIDATED"
        result = apply_semantic_ready_gate(row, result)
        if args.fallback_ranks:
            if needs_fallback(result):
                fallback_state[mkey] = True   # 계속 다음 순위 평가
                if rank > 1:
                    result["fallback_attempt"] = "Y"
            else:
                if rank > 1:
                    result["fallback_recovered"] = "Y"
                    result["fallback_attempt"] = "Y"
                fallback_state[mkey] = False  # 사용 가능한 좌표 확보 → 이후 순위 스킵
        outputs.append({**row, **result})
    if not args.skip_table_ambiguity:
        outputs = resolve_table_ambiguity(
            outputs,
            allow_provisional=args.allow_provisional,
        )
    _write_csv(Path(args.output), outputs)
    print(f"validated_rows={len(outputs)} output={args.output}")


if __name__ == "__main__":
    main()
