#!/usr/bin/env python3
"""Lossless ITEM/OBJ component retrieval with dynamic coordinate assembly.

The index stores ITEMs and individual OBJ values, never their Cartesian
product.  At query time only components belonging to upstream table
candidates are read, scored with one BGE-M3 query vector, and combined with a
bounded beam before optional cross-encoder reranking.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from kosis_match_claims_to_index import item_mapping_type

from kosis_meta_coordinates import (
    AGGREGATE_OBJ_NAMES,
    build_coordinate_query,
    claim_target_terms,
    read_csv_rows as read_meta_csv_rows,
    target_terms_match_text,
)
from kosis_taxonomy import (
    CATEGORY,
    COMPANY_SIZE,
    CURRENT_TOTAL,
    FOREIGN,
    INDUSTRY,
    POPULATION_ATTRIBUTE,
    SEX,
    WOMEN,
    claim_population_requirements,
    industry_label_equivalent,
    infer_axis_role,
    role_aware_coordinate_scope,
    regional_table_scope_matches,
)


MAX_AXIS = 8
RETRIEVAL_STAGE = "bge_component_beam"
TABLE_PRIOR_WEIGHT = 0.60
COORDINATE_SCORE_WEIGHT = 0.35
MAX_STRUCTURAL_BONUS = 0.05
TARGET_FALLBACK_PENALTY = 0.12
STRUCTURAL_FALLBACK_PENALTY = 0.18
TABLE_SLOT_FALLBACK_PENALTY = 0.25
BASE_CLAIM_FIELDS = (
    "gold_id", "claim_id", "claim_measurement_id", "article_id", "title",
    "claim_text", "date", "indicator",
    "measurement_indicator", "metric_domain", "industry_or_item", "measurement_item",
    "value", "unit", "raw_unit", "canonical_unit", "unit_dimension", "semantic_type",
    "unit_dimension_hypotheses", "retrieval_fallback_code",
    "indicator_fallback_source", "derived_computation_required",
    "verification_review_required",
    "verification_review_reason",
    "allowed_mapping_types",
    "entity_type", "value_type", "measurement_role", "measurement_usage",
    "period", "measurement_period", "prd_se", "measurement_prd_se", "previous_period",
    "change_base", "comparison_period", "period_aggregation", "mapping_type",
    "period_span_start", "period_span_end", "period_alignment_status",
    "survey_name", "source_survey", "statistics_name", "stat_name", "keywords",
    "claim_domain_scope", "obj_target_terms", "claim_indicator",
    "claim_industry_or_item", "claim_period", "claim_prd_se",
    "region", "age_group", "gender", "origin_country", "destination_country",
    "input_quality_status", "input_quality_reason",
)
COMPONENT_TRACE_FIELDS = (
    "component_tables_seen",
    "component_item_rows",
    "component_obj_rows",
    "component_tables_with_item_rows",
    "compatible_item_tables",
    "compatible_item_rows",
    "missing_official_axis_tables",
    "regional_scope_rejected_tables",
    "beam_candidate_coordinates",
    "target_rejected_coordinates",
    "obj_hierarchy_rejected_coordinates",
    "per_table_slot_candidates",
    "per_table_slot_recovered_tables",
    "component_candidates_before_final",
    "rerank_pool_coordinates",
    "selected_coordinates",
    "dropped_by_final_top_k",
)

COMPONENT_FAILURE_REASONS = {
    "NO_TABLE_COMPONENT_ROWS": "후보 통계표에서 검색 가능한 ITEM 컴포넌트 행을 찾지 못함",
    "NO_UNIT_OR_PERIOD_COMPATIBLE_ITEM": "후보 ITEM이 요청 단위 또는 수록주기 구조와 호환되지 않음",
    "TARGET_LITERAL_NOT_FOUND": "동적 좌표 후보의 ITEM/OBJ에 주장 대상이 직접 나타나지 않음",
    "OBJ_HIERARCHY_SCOPE_MISMATCH": "전체 품목/산업 대상과 세부 HS 품목 OBJ의 계층 범위가 일치하지 않음",
    "MISSING_OFFICIAL_AXIS": "공식 OBJ 축 중 검색 가능한 값이 없는 축이 있어 완전한 좌표를 만들 수 없음",
    "BEAM_EMPTY": "호환 ITEM과 OBJ 축은 있으나 동적 beam 조합 결과가 비어 있음",
    "DROPPED_BY_FINAL_TOP_K": "좌표 후보가 생성됐지만 최종 Top-K 선택에서 모두 제외됨",
    "NO_COMPONENT_COORDINATE_CANDIDATE": "구조 필터와 동적 컴포넌트 조합을 통과한 좌표가 없음",
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clamp_unit_interval(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def table_prior_score(table: Mapping[str, Any]) -> float:
    """Blend the upstream table score with a smooth, bounded rank prior."""
    try:
        candidate_score = float(table.get("candidate_score") or 0.0)
    except (TypeError, ValueError):
        candidate_score = 0.0
    # Production table scores are emitted on a 0..1000 scale. Accepting 0..1
    # also keeps hand-authored indexes and older fixtures backward compatible.
    if candidate_score > 1.0:
        candidate_score /= 1000.0
    candidate_score = _clamp_unit_interval(candidate_score)
    try:
        rank = max(1, int(float(table.get("rank") or 1)))
    except (TypeError, ValueError):
        rank = 1
    rank_prior = 1.0 / math.log2(rank + 1.0)
    return 0.85 * candidate_score + 0.15 * rank_prior


def coordinate_relevance_score(
    component_score: Any,
    reranker_score: Any | None = None,
) -> float:
    """Return a bounded coordinate score from cosine and cross-encoder evidence."""
    try:
        cosine = float(component_score)
    except (TypeError, ValueError):
        cosine = -1.0
    normalized_cosine = _clamp_unit_interval((cosine + 1.0) / 2.0)
    if reranker_score is None:
        return normalized_cosine
    return 0.70 * _clamp_unit_interval(reranker_score) + 0.30 * normalized_cosine


def apply_candidate_scores(
    candidate: dict[str, Any],
    reranker_score: Any | None = None,
) -> None:
    """Attach auditable table, coordinate, and structural score components."""
    if reranker_score is not None:
        candidate["reranker_score"] = float(reranker_score)
    table_score = table_prior_score(candidate.get("table", {}))
    coordinate_score = coordinate_relevance_score(
        candidate.get("component_score"), reranker_score
    )
    structural_bonus = (
        MAX_STRUCTURAL_BONUS
        if candidate.get("mandatory_aggregate")
        or candidate.get("mandatory_target_default")
        else 0.0
    )
    fallback_penalty = 0.0
    if candidate.get("target_match_state") == "semantic_fallback":
        fallback_penalty += TARGET_FALLBACK_PENALTY
    if candidate.get("structural_match_state") == "hypothesis_fallback":
        fallback_penalty += STRUCTURAL_FALLBACK_PENALTY
    if candidate.get("table_slot_fallback"):
        fallback_penalty += TABLE_SLOT_FALLBACK_PENALTY
    candidate["table_prior_score"] = table_score
    candidate["coordinate_score"] = coordinate_score
    candidate["structural_bonus"] = structural_bonus
    candidate["fallback_penalty"] = fallback_penalty
    candidate["final_rank_score"] = (
        TABLE_PRIOR_WEIGHT * table_score
        + COORDINATE_SCORE_WEIGHT * coordinate_score
        + structural_bonus
        - fallback_penalty
    )


def measurement_key(row: Mapping[str, Any]) -> str:
    return _text(row.get("claim_measurement_id") or row.get("claim_id"))


def table_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return _text(row.get("org_id")), _text(row.get("tbl_id"))


def load_table_candidates(path: str | Path, top_k: int) -> dict[str, list[dict[str, Any]]]:
    by_measurement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_meta_csv_rows(path):
        key = measurement_key(row)
        if not key:
            continue
        try:
            rank = int(float(_text(row.get("candidate_rank")) or "999"))
        except ValueError:
            rank = 999
        by_measurement[key].append({
            "rank": rank,
            "org_id": _text(row.get("org_id")),
            "tbl_id": _text(row.get("tbl_id")),
            "tbl_name": _text(row.get("tbl_name")),
            "candidate_status": _text(row.get("candidate_status")),
            "candidate_score": _text(row.get("candidate_score")),
            "candidate_runner_up_score": _text(row.get("candidate_runner_up_score")),
        })
    return {
        key: sorted(rows, key=lambda row: row["rank"])[:top_k]
        for key, rows in by_measurement.items()
    }


def normalize_prd_se(value: Any) -> str:
    raw = _text(value).upper()
    aliases = {
        "월": "M", "월간": "M", "MONTH": "M", "MONTHLY": "M",
        "분기": "Q", "분기별": "Q", "QUARTER": "Q", "QUARTERLY": "Q",
        "년": "Y", "연": "Y", "연간": "Y", "YEAR": "Y", "ANNUAL": "Y",
    }
    return aliases.get(raw, raw)


def periodicities(value: Any) -> set[str]:
    raw = _text(value).replace(",", "|").replace("/", "|")
    return {
        normalized
        for part in raw.split("|")
        if (normalized := normalize_prd_se(part))
    }


def currency_family(value: Any) -> str:
    normalized = _text(value).lower().replace(" ", "")
    families = (
        ("krw", ("krw", "원")),
        ("usd", ("usd", "달러", "불")),
        ("eur", ("eur", "유로")),
        ("jpy", ("jpy", "엔")),
        ("cny", ("cny", "위안", "인민폐")),
    )
    for family, markers in families:
        if any(marker in normalized for marker in markers):
            return family
    return ""


def item_structure_state(claim: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
    """Return explicit unit/period compatibility; unknown metadata is retained."""
    wanted_period = normalize_prd_se(
        claim.get("prd_se") or claim.get("measurement_prd_se")
    )
    item_periods = periodicities(item.get("prd_se"))
    if not wanted_period:
        period_state = "not_applicable"
    elif not item_periods:
        period_state = "unknown"
    elif (
        wanted_period == "Y"
        and item_periods & {"M", "Q"}
        and _text(claim.get("period_aggregation")).lower() in {"sum", "latest"}
    ):
        period_state = "aggregate_compatible"
    else:
        period_state = "match" if wanted_period in item_periods else "mismatch"

    claim_dimension = _text(claim.get("unit_dimension")).lower()
    claim_dimensions = {
        value.strip().lower()
        for value in _text(claim.get("unit_dimension_hypotheses")).split("|")
        if value.strip()
    }
    if claim_dimension:
        claim_dimensions.add(claim_dimension)
    item_dimension = _text(item.get("unit_dimension")).lower()
    if not item_dimension or item_dimension == "unknown":
        item_dimension = infer_item_unit_dimension(item.get("unit"))
    mapping_type = _text(claim.get("mapping_type")).lower()
    allowed_mapping_types = {
        value.strip().lower()
        for value in _text(claim.get("allowed_mapping_types")).split("|")
        if value.strip()
    }
    resolved_mapping_type = ""
    resolved_unit_hypothesis = ""
    hypothesis_reason = ""
    if allowed_mapping_types:
        hypotheses = claim_dimensions or {claim_dimension}
        for hypothesis in sorted(value for value in hypotheses if value):
            hypothesis_claim = dict(claim)
            hypothesis_claim["unit_dimension"] = hypothesis
            candidate_type, candidate_reason = item_mapping_type(
                hypothesis_claim,
                item.get("unit", ""),
                item.get("itm_name", ""),
            )
            if candidate_type in allowed_mapping_types:
                resolved_mapping_type = candidate_type
                resolved_unit_hypothesis = hypothesis
                hypothesis_reason = candidate_reason
                break
        mapping_type = resolved_mapping_type
    derived = mapping_type in {"rate_from_level", "difference_from_level"}
    if allowed_mapping_types and not resolved_mapping_type:
        unit_state = "mismatch"
    elif derived:
        unit_state = "match"
    elif not claim_dimensions:
        unit_state = "not_applicable"
    elif not item_dimension or item_dimension == "unknown":
        unit_state = "unknown"
    else:
        unit_state = (
            "match" if item_dimension in claim_dimensions else "mismatch"
        )
    if unit_state == "match" and claim_dimension == "currency" and not derived:
        claim_currency = currency_family(claim.get("canonical_unit") or claim.get("unit"))
        item_currency = currency_family(item.get("canonical_unit") or item.get("unit"))
        if claim_currency and item_currency and claim_currency != item_currency:
            unit_state = "mismatch"

    reasons = [
        name for name, state in (("period", period_state), ("unit_dimension", unit_state))
        if state == "mismatch"
    ]
    return {
        "period_structural_state": period_state,
        "unit_structural_state": unit_state,
        "structural_compatible": not reasons,
        "structural_filter_reasons": "|".join(f"{name}_mismatch" for name in reasons),
        "resolved_mapping_type": resolved_mapping_type or mapping_type,
        "resolved_unit_hypothesis": resolved_unit_hypothesis or claim_dimension,
        "hypothesis_evidence": hypothesis_reason,
    }


def infer_item_unit_dimension(unit: Any) -> str:
    """Infer only high-confidence dimensions from official ITEM unit text."""
    value = re.sub(r"\s+", "", _text(unit)).lower()
    if not value:
        return "unknown"
    if any(marker in value for marker in ("㎡", "m²", "m2", "평방미터", "제곱미터")):
        return "area"
    if value in {"동(호)수", "동호수", "호", "건", "건수", "개", "대", "가구", "세대"}:
        return "count"
    if value in {"명", "천명", "만명", "백만명"}:
        return "person_count"
    if value in {"%", "%p"}:
        return "rate"
    if any(marker in value for marker in ("원", "달러", "엔", "유로")):
        return "currency"
    return "unknown"


def cosine_scores(query_vector: Any, matrix: Any, embedding_rows: Sequence[int]) -> list[float]:
    """Cosine-score selected mmap rows without copying the full embedding matrix."""
    import numpy as np

    if not embedding_rows:
        return []
    query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    query_norm = float(np.linalg.norm(query))
    if not query_norm:
        raise ValueError("query embedding has zero norm")
    selected = np.asarray(matrix[embedding_rows], dtype=np.float32)
    if selected.ndim != 2 or selected.shape[1] != query.shape[0]:
        raise ValueError(
            f"embedding dimension mismatch: query={query.shape[0]}, matrix={selected.shape}"
        )
    norms = np.linalg.norm(selected, axis=1)
    denominators = norms * query_norm
    dots = selected @ query
    return [float(dot / denom) if denom else -1.0 for dot, denom in zip(dots, denominators)]


def score_component_rows(
    rows: Sequence[Mapping[str, Any]], matrix: Any, query_vector: Any
) -> list[dict[str, Any]]:
    valid: list[tuple[Mapping[str, Any], int]] = []
    for row in rows:
        try:
            embedding_row = int(row.get("embedding_row"))
        except (TypeError, ValueError):
            continue
        if 0 <= embedding_row < len(matrix):
            valid.append((row, embedding_row))
    scores = cosine_scores(query_vector, matrix, [index for _, index in valid])
    return [{**dict(row), "component_score": score} for (row, _), score in zip(valid, scores)]


def _is_aggregate(row: Mapping[str, Any]) -> bool:
    explicit = _text(row.get("is_aggregate")).lower()
    if explicit in {"1", "true", "y", "yes"}:
        return True
    name = _text(row.get("obj_name"))
    return name in AGGREGATE_OBJ_NAMES or name.startswith("전규모")


def _population_traits(value: Any) -> frozenset[str]:
    """Return only explicit population semantics safe for structural anchoring."""
    normalized = re.sub(r"[^0-9A-Za-z가-힣]", "", _text(value)).lower()
    if normalized in {"현재인원", "현원", "전체인원", "총인원"}:
        return frozenset({CURRENT_TOTAL})
    traits = set()
    if "외국인" in normalized:
        traits.add(FOREIGN)
    if normalized in {"여", "여성", "여자", "여성인력", "여자인력"} or "여성" in normalized:
        traits.add(WOMEN)
    return frozenset(traits)


def _industry_target_terms(
    claim: Mapping[str, Any], fallback: Sequence[str],
) -> tuple[str, ...]:
    """Return only the structured industry/item target for an INDUSTRY axis."""
    for field in ("industry_or_item", "measurement_item"):
        raw = _text(claim.get(field))
        if raw and raw != "-":
            return tuple(part.strip() for part in re.split(r"[|,;]", raw) if part.strip())
    return tuple(fallback)


def _obj_hierarchy_target_terms(claim: Mapping[str, Any]) -> tuple[str, ...]:
    """Return product/industry targets only; never mix region/sex target axes."""
    values: list[str] = []
    for field in ("industry_or_item", "measurement_item"):
        raw = _text(claim.get(field))
        if raw and raw != "-":
            values.extend(part.strip() for part in re.split(r"[|,;]", raw) if part.strip())
    return tuple(dict.fromkeys(values))


def _hierarchy_label(value: Any) -> str:
    text = re.sub(r"^\s*(?:HS)?\s*\d{2,10}\s*[-.:)]?\s*", "", _text(value), flags=re.I)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def obj_hierarchy_scope(
    candidate: Mapping[str, Any], claim: Mapping[str, Any],
) -> tuple[bool, str, str]:
    """Reject a detailed HS/OBJ leaf when the claim asks for a broader product.

    Similarity containment (for example `반도체` -> `기타 집적회로반도체`)
    is not coordinate equality.  Product and industry axes therefore require
    exact normalized scope, while an explicit all-products target requires the
    official aggregate value.
    """
    targets = _obj_hierarchy_target_terms(claim)
    if not targets:
        return True, "not_applicable", ""
    relevant = [
        obj for obj in candidate.get("objects", {}).values()
        if infer_axis_role(obj.get("axis_name", "")) in {INDUSTRY, CATEGORY}
    ]
    if not relevant:
        return True, "axis_not_present", ""

    all_terms = {"전체", "전체품목", "전품목", "총품목", "품목계", "총계", "계"}
    failures: list[str] = []
    for target in targets:
        normalized_target = _hierarchy_label(target)
        if normalized_target in all_terms:
            if not any(_is_aggregate(obj) for obj in relevant):
                failures.append(f"aggregate_required:{target}")
            continue
        matched = False
        detail_only = False
        for obj in relevant:
            label = _hierarchy_label(obj.get("obj_name", ""))
            role = infer_axis_role(obj.get("axis_name", ""))
            exact = (
                industry_label_equivalent(target, obj.get("obj_name", ""))
                if role == INDUSTRY
                else bool(normalized_target and normalized_target == label)
            )
            if exact:
                matched = True
                break
            if normalized_target and normalized_target in label:
                detail_only = True
        if not matched:
            failures.append(
                f"detail_scope_mismatch:{target}" if detail_only
                else f"obj_scope_not_exact:{target}"
            )
    if failures:
        return False, "rejected", "|".join(failures)
    return True, "exact", ""


def _role_anchor_rows(
    rows: Sequence[Mapping[str, Any]],
    claim: Mapping[str, Any],
    target_terms: Sequence[str],
) -> list[dict[str, Any]]:
    """Choose deterministic structural anchors for one official OBJ axis."""
    if not rows:
        return []
    role = infer_axis_role(rows[0].get("axis_name", ""))
    if role == INDUSTRY:
        industry_targets = _industry_target_terms(claim, target_terms)
        anchors = [
            dict(row) for row in rows
            if industry_targets and all(
                industry_label_equivalent(target, row.get("obj_name", ""))
                for target in industry_targets
            )
        ]
    elif role in {POPULATION_ATTRIBUTE, SEX}:
        required = claim_population_requirements(claim)
        anchors = [
            dict(row) for row in rows
            if _population_traits(row.get("obj_name", "")) & required
        ]
        anchors.extend(dict(row) for row in rows if _is_aggregate(row))
    else:
        anchors = [dict(row) for row in rows if _is_aggregate(row)]

    best_by_traits: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in anchors:
        traits = tuple(sorted(_population_traits(row.get("obj_name", ""))))
        key = traits or ("aggregate",)
        current = best_by_traits.get(key)
        if current is None or float(row.get("component_score", -1.0)) > float(
            current.get("component_score", -1.0)
        ):
            best_by_traits[key] = row
    return list(best_by_traits.values())


def mandatory_role_aware_combinations(
    items: Sequence[Mapping[str, Any]],
    objects_by_axis: Mapping[int, Sequence[Mapping[str, Any]]],
    claim: Mapping[str, Any],
    target_terms: Sequence[str],
) -> list[dict[str, Any]]:
    """Build exact role-aware coordinates outside the similarity-pruned beam."""
    if not claim_population_requirements(claim):
        return []
    axis_choices: list[tuple[int, list[dict[str, Any]]]] = []
    for axis, rows in sorted(objects_by_axis.items()):
        choices = _role_anchor_rows(rows, claim, target_terms)
        if not choices:
            return []
        for choice in choices:
            choice["rank_score"] = float(choice.get("component_score", -1.0))
        axis_choices.append((axis, choices))

    combinations = []
    choice_sets = [choices for _, choices in axis_choices]
    for raw_item in items:
        item = dict(raw_item)
        for selected in product(*choice_sets) if choice_sets else [()]:
            objects = {
                axis: dict(obj) for (axis, _), obj in zip(axis_choices, selected)
            }
            candidate = {"item": item, "objects": objects}
            if not candidate_matches_targets(candidate, target_terms, claim):
                continue
            score_sum = float(item["rank_score"]) + sum(
                float(obj["rank_score"]) for obj in objects.values()
            )
            parts = 1 + len(objects)
            combinations.append({
                **candidate,
                "score_sum": score_sum,
                "parts": parts,
                "component_score": score_sum / parts,
                "mandatory_role_scope": True,
            })
    return combinations


def item_statistic_operator_bonus(
    claim: Mapping[str, Any], item: Mapping[str, Any],
) -> float:
    """Align explicit mean/median semantics before the ITEM beam cutoff.

    Mean and median share the same unit, period and topic, so embedding
    similarity alone can swap them.  The bound measurement indicator is the
    authoritative local phrase: a literal operator match receives a bounded
    bonus and its mutually exclusive counterpart receives the same penalty.
    No operator is inferred from generic article context.
    """
    indicator = re.sub(
        r"[^0-9A-Za-z가-힣]", "", _text(
            claim.get("measurement_indicator") or claim.get("indicator")
        )
    ).lower()
    item_name = re.sub(
        r"[^0-9A-Za-z가-힣]", "", _text(item.get("itm_name"))
    ).lower()
    if not indicator or not item_name:
        return 0.0
    claim_mean = "평균" in indicator
    claim_median = "중앙값" in indicator or "중위" in indicator
    # A component value can omit the parent aggregation operator even though
    # the same local sentence binds it explicitly ("평균 자산 ... 가운데
    # 부동산 ..."). Inherit only this noun-bound construction; a generic
    # article-level mention of an average must not affect an unrelated ITEM.
    if not claim_mean and not claim_median and "자산" in indicator:
        context = re.sub(
            r"[^0-9A-Za-z가-힣]", "", _text(claim.get("claim_text"))
        ).lower()
        if "평균자산" in context and "중앙값" not in context and "중위" not in context:
            claim_mean = True
        elif ("중앙값자산" in context or "자산중앙값" in context) and "평균자산" not in context:
            claim_median = True
    item_mean = "평균" in item_name
    item_median = "중앙값" in item_name or "중위" in item_name
    if claim_mean and not claim_median:
        return 1.0 if item_mean else (-1.0 if item_median else 0.0)
    if claim_median and not claim_mean:
        return 1.0 if item_median else (-1.0 if item_mean else 0.0)
    return 0.0


def retain_ranked_components(
    rows: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    target_terms: Sequence[str] = (),
    obj_axis: bool = False,
    claim: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep semantic leaders plus structural target/aggregate anchors."""
    if top_k <= 0:
        return []
    ranked: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        values = [row.get("obj_name", "")] if obj_axis else [row.get("itm_name", "")]
        role = infer_axis_role(row.get("axis_name", "")) if obj_axis else ""
        if claim is None:
            role_targets = tuple(target_terms)
        elif role in {INDUSTRY, COMPANY_SIZE}:
            role_targets = (
                _industry_target_terms(claim, target_terms)
                if role == INDUSTRY
                else tuple(target_terms)
            )
        else:
            role_targets = target_terms if role == "" else ()
        target_match = bool(role_targets and target_terms_match_text(role_targets, values))
        if (
            obj_axis
            and infer_axis_role(row.get("axis_name", "")) == INDUSTRY
            and any(
                industry_label_equivalent(target, row.get("obj_name", ""))
                for target in role_targets
            )
        ):
            target_match = True
        aggregate = obj_axis and _is_aggregate(row)
        row["target_match"] = target_match
        row["is_aggregate"] = aggregate
        # An exact structured target is stronger evidence than embedding
        # proximity and must survive the beam cutoff. Explicit mean/median
        # semantics are independent ITEM evidence and are applied only to
        # ITEM rows, never to OBJ axes.
        statistic_bonus = (
            0.0 if obj_axis or claim is None
            else item_statistic_operator_bonus(claim, row)
        )
        bonus = (
            1.0 if target_match
            else (0.02 if aggregate and not target_terms else 0.0)
        ) + statistic_bonus
        row["rank_score"] = float(row.get("component_score", -1.0)) + bonus
        row["item_statistic_operator_bonus"] = statistic_bonus
        ranked.append(row)
    ranked.sort(key=lambda row: (-float(row["rank_score"]), _text(row.get("component_id"))))

    selected = ranked[:top_k]
    anchors: list[dict[str, Any]] = []
    if not obj_axis and claim is not None and claim_population_requirements(claim):
        required = claim_population_requirements(claim)
        anchors = [
            row for row in ranked
            if _population_traits(row.get("itm_name", "")) & required
        ][:1]
    elif target_terms and (
        not obj_axis
        or infer_axis_role(rows[0].get("axis_name", "")) in {INDUSTRY, COMPANY_SIZE}
    ):
        anchors = [row for row in ranked if row["target_match"]][:1]
    elif obj_axis and claim is not None:
        role = infer_axis_role(rows[0].get("axis_name", ""))
        if role in {POPULATION_ATTRIBUTE, SEX}:
            required = claim_population_requirements(claim)
            anchors = [
                row for row in ranked
                if _population_traits(row.get("obj_name", "")) & required
            ][:1]
        else:
            anchors = [row for row in ranked if row["is_aggregate"]][:1]
    elif obj_axis and top_k > 1:
        anchors = [row for row in ranked if row["is_aggregate"]][:1]
    for anchor in anchors:
        anchor["rank_score"] = float(anchor.get("rank_score", -1.0)) + 1.0
    by_id = {_text(row.get("component_id")): row for row in selected}
    for anchor in anchors:
        key = _text(anchor.get("component_id"))
        if key not in by_id:
            if len(selected) >= top_k:
                selected[-1] = anchor
            else:
                selected.append(anchor)
            by_id[key] = anchor
    result = sorted(
        {(_text(row.get("component_id")) or str(id(row))): row for row in selected}.values(),
        key=lambda row: (-float(row["rank_score"]), _text(row.get("component_id"))),
    )[:top_k]
    for rank, row in enumerate(result, 1):
        row["component_rank"] = rank
    return result


def beam_combine(
    items: Sequence[Mapping[str, Any]],
    objects_by_axis: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    beam_width: int,
) -> list[dict[str, Any]]:
    """Dynamically assemble coordinates; no complete coordinate is persisted."""
    if beam_width <= 0:
        return []
    beam = [
        {"item": dict(item), "objects": {}, "score_sum": float(item["rank_score"]), "parts": 1}
        for item in items
    ]
    beam.sort(key=lambda value: -value["score_sum"])
    beam = beam[:beam_width]
    for axis_order in sorted(objects_by_axis):
        choices = objects_by_axis[axis_order]
        if not choices:
            return []
        expanded: list[dict[str, Any]] = []
        for partial in beam:
            for obj in choices:
                expanded.append({
                    "item": partial["item"],
                    "objects": {**partial["objects"], axis_order: dict(obj)},
                    "score_sum": partial["score_sum"] + float(obj["rank_score"]),
                    "parts": partial["parts"] + 1,
                })
        expanded.sort(
            key=lambda value: (
                -(value["score_sum"] / value["parts"]),
                coordinate_id(value["item"], value["objects"]),
            )
        )
        beam = expanded[:beam_width]
    for candidate in beam:
        candidate["component_score"] = candidate["score_sum"] / candidate["parts"]
    return beam


def mandatory_aggregate_combinations(
    items: Sequence[Mapping[str, Any]],
    objects_by_axis: Mapping[int, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Build all-aggregate coordinates when every axis has one clear total.

    These coordinates express the structure of a targetless claim and must not
    disappear merely because an unrelated detail value has a higher embedding
    score. Multiple aggregate-looking values on one axis are left unresolved.
    """
    selected: dict[int, dict[str, Any]] = {}
    for axis_order, rows in sorted(objects_by_axis.items()):
        by_code = {
            _text(row.get("obj_code")): dict(row)
            for row in rows
            if _is_aggregate(row) and _text(row.get("obj_code"))
        }
        if len(by_code) != 1:
            return []
        value = next(iter(by_code.values()))
        value["rank_score"] = float(value.get("component_score", -1.0)) + 0.02
        selected[axis_order] = value

    combinations = []
    for raw_item in items:
        item = dict(raw_item)
        score_sum = float(item["rank_score"]) + sum(
            float(value["rank_score"]) for value in selected.values()
        )
        parts = 1 + len(selected)
        combinations.append({
            "item": item,
            "objects": {axis: dict(value) for axis, value in selected.items()},
            "score_sum": score_sum,
            "parts": parts,
            "component_score": score_sum / parts,
            "mandatory_aggregate": True,
        })
    return combinations


def mandatory_target_default_combinations(
    items: Sequence[Mapping[str, Any]],
    objects_by_axis: Mapping[int, Sequence[Mapping[str, Any]]],
    target_terms: Sequence[str],
    claim: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build exact-target coordinates with aggregate defaults on other axes.

    Similarity pruning is allowed to rank coordinates, but it must not erase
    an official literal target.  For every axis we therefore retain target
    values when the claim names one and otherwise require one unambiguous
    aggregate value.  Ambiguous axes return no coordinate, which makes the
    downstream decision abstain instead of inventing an OBJ selection.
    """
    if not target_terms:
        return []
    axis_choices: list[tuple[int, list[dict[str, Any]]]] = []
    for axis, rows in sorted(objects_by_axis.items()):
        role = infer_axis_role(rows[0].get("axis_name", "")) if rows else ""
        role_targets = (
            _industry_target_terms(claim, target_terms)
            if role == INDUSTRY else tuple(target_terms)
        )
        exact = [
            dict(row) for row in rows
            if target_terms_match_text(role_targets, [row.get("obj_name", "")])
        ] if role_targets else []
        if role == INDUSTRY and role_targets:
            exact.extend(
                dict(row) for row in rows
                if any(industry_label_equivalent(term, row.get("obj_name", ""))
                       for term in role_targets)
            )
        if exact:
            choices = list({str(row.get("obj_code")): row for row in exact}.values())
        else:
            aggregates = {
                str(row.get("obj_code")): dict(row)
                for row in rows if _is_aggregate(row) and row.get("obj_code")
            }
            if len(aggregates) != 1:
                return []
            choices = list(aggregates.values())
        for choice in choices:
            choice["rank_score"] = float(choice.get("component_score", -1.0)) + 0.5
        axis_choices.append((axis, choices))

    combinations: list[dict[str, Any]] = []
    for raw_item in items:
        item = dict(raw_item)
        for selected in product(*(choices for _, choices in axis_choices)) if axis_choices else [()]:
            objects = {
                axis: dict(obj) for (axis, _), obj in zip(axis_choices, selected)
            }
            candidate = {"item": item, "objects": objects}
            if not candidate_matches_targets(candidate, target_terms, claim):
                continue
            score_sum = float(item["rank_score"]) + sum(
                float(obj["rank_score"]) for obj in objects.values()
            )
            parts = 1 + len(objects)
            combinations.append({
                **candidate,
                "score_sum": score_sum,
                "parts": parts,
                "component_score": score_sum / parts,
                "mandatory_target_default": True,
            })
    return combinations


def coordinate_id(item: Mapping[str, Any], objects: Mapping[int, Mapping[str, Any]]) -> str:
    parts = [_text(item.get("org_id")), _text(item.get("tbl_id")), _text(item.get("itm_id"))]
    parts.extend(f"{axis}:{_text(objects[axis].get('obj_code'))}" for axis in sorted(objects))
    return "|".join(parts)


def coordinate_document(candidate: Mapping[str, Any]) -> str:
    item = candidate["item"]
    fields = [
        f"통계표: {_text(item.get('tbl_name'))}",
        f"항목: {_text(item.get('itm_name'))}",
        f"단위: {_text(item.get('unit'))}",
    ]
    for axis, obj in sorted(candidate["objects"].items()):
        fields.append(
            f"{_text(obj.get('axis_name')) or f'OBJ{axis}'}: {_text(obj.get('obj_name'))}"
        )
    return " | ".join(field for field in fields if not field.endswith(": "))


def _has_role_aware_scope(
    candidate: Mapping[str, Any], claim: Mapping[str, Any]
) -> bool:
    roles = {
        infer_axis_role(obj.get("axis_name", ""))
        for obj in candidate.get("objects", {}).values()
    }
    return bool(
        claim_population_requirements(claim)
        and INDUSTRY in roles
    )


def _objects_with_item_population_semantics(
    candidate: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    objects = list(candidate.get("objects", {}).values())
    item_name = candidate.get("item", {}).get("itm_name", "")
    if _population_traits(item_name):
        objects.append({"axis_name": "특성별", "obj_name": item_name})
    return objects


def candidate_matches_targets(
    candidate: Mapping[str, Any],
    target_terms: Sequence[str],
    claim: Mapping[str, Any] | None = None,
) -> bool:
    if claim is not None and _has_role_aware_scope(candidate, claim):
        return role_aware_coordinate_scope(
            claim,
            _industry_target_terms(claim, target_terms),
            _objects_with_item_population_semantics(candidate),
        )
    if not target_terms:
        return True
    item = candidate["item"]
    selected = [item.get("itm_name", "")]
    selected.extend(obj.get("obj_name", "") for obj in candidate["objects"].values())
    return target_terms_match_text(target_terms, selected)


def select_diverse_candidates(
    candidates: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    per_table_minimum: int = 1,
) -> list[dict[str, Any]]:
    """Reserve one leader per eligible table, then fill by global score."""
    indexed = [(index, dict(candidate)) for index, candidate in enumerate(candidates)]
    indexed.sort(
        key=lambda value: (
            -float(value[1].get("final_rank_score") or 0.0),
            value[0],
        )
    )
    ranked = [candidate for _, candidate in indexed]
    if limit <= 0 or not ranked:
        return []
    if per_table_minimum <= 0:
        return ranked[:limit]
    limit = min(limit, len(ranked))

    first_position: dict[tuple[str, str], int] = {}
    table_ranks: dict[tuple[str, str], int] = {}
    for position, candidate in enumerate(ranked):
        key = table_key(candidate["item"])
        first_position.setdefault(key, position)
        table = candidate.get("table", {})
        try:
            rank = max(1, int(float(table.get("rank") or 999999)))
        except (TypeError, ValueError):
            rank = 999999
        table_ranks[key] = min(rank, table_ranks.get(key, rank))
    # Preserve the best coordinate from every table that can fit in the hard
    # limit.  When there are more tables than slots, upstream table rank decides
    # which tables receive a reserved slot.
    reserved_tables = sorted(
        first_position,
        key=lambda key: (table_ranks[key], first_position[key], key),
    )[:limit]

    selected_by_id: dict[str, dict[str, Any]] = {}
    for key in reserved_tables:
        table_candidates = [row for row in ranked if table_key(row["item"]) == key]
        if table_candidates and len(selected_by_id) < limit:
            candidate = table_candidates[0]
            selected_by_id[str(candidate["coordinate_id"])] = candidate

    for candidate in ranked:
        if len(selected_by_id) >= limit:
            break
        selected_by_id.setdefault(str(candidate["coordinate_id"]), candidate)

    selected_ids = set(selected_by_id)
    selected: list[dict[str, Any]] = []
    for candidate in ranked:
        coordinate = str(candidate["coordinate_id"])
        if coordinate not in selected_ids:
            continue
        selected.append(selected_by_id[coordinate])
        selected_ids.remove(coordinate)
        if len(selected) == limit:
            break

    by_table: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in selected:
        by_table[table_key(candidate["item"])].append(candidate)
    for table_candidates in by_table.values():
        table_candidates.sort(key=lambda candidate: (
            -float(candidate.get("final_rank_score") or 0.0),
            str(candidate.get("coordinate_id") or ""),
        ))
        for coordinate_rank, candidate in enumerate(table_candidates, 1):
            candidate["coordinate_rank_within_table"] = coordinate_rank
    return selected


def search_components_for_claim(
    claim: Mapping[str, Any],
    tables: Sequence[Mapping[str, Any]],
    item_rows: Sequence[Mapping[str, Any]],
    obj_rows: Sequence[Mapping[str, Any]],
    item_embeddings: Any,
    obj_embeddings: Any,
    query_vector: Any,
    *,
    item_top_k: int = 5,
    axis_top_k: int = 5,
    beam_width: int = 50,
    final_top_k: int = 10,
    per_table_minimum: int = 1,
    preserve_table_fallback: bool = False,
    reranker: Any = None,
    trace: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Search lossless components for one claim and return Chroma-compatible rows."""
    component_trace = trace if trace is not None else {}
    component_trace.clear()
    component_trace.update({field: 0 for field in COMPONENT_TRACE_FIELDS})
    table_lookup = {table_key(table): dict(table) for table in tables}
    allowed = set(table_lookup)
    item_rows = [dict(row) for row in item_rows if table_key(row) in allowed]
    obj_rows = [dict(row) for row in obj_rows if table_key(row) in allowed]
    component_trace.update({
        "component_tables_seen": len(table_lookup),
        "component_item_rows": len(item_rows),
        "component_obj_rows": len(obj_rows),
        "component_tables_with_item_rows": len({table_key(row) for row in item_rows}),
    })
    axis_values = [
        {"value": row.get("obj_name", ""), "axis_name": row.get("axis_name", "")}
        for row in obj_rows
    ]
    targets = claim_target_terms(claim, axis_values)
    scored_items = score_component_rows(item_rows, item_embeddings, query_vector)
    scored_objects = score_component_rows(obj_rows, obj_embeddings, query_vector)

    strict_candidates: list[dict[str, Any]] = []
    fallback_candidates: list[dict[str, Any]] = []
    for key, table in table_lookup.items():
        if not regional_table_scope_matches(claim, table.get("tbl_name", "")):
            component_trace["regional_scope_rejected_tables"] += 1
            continue
        compatible_items = []
        incompatible_items = []
        for item in scored_items:
            if table_key(item) != key:
                continue
            state = item_structure_state(claim, item)
            if state["structural_compatible"]:
                compatible_items.append({**item, **state})
            else:
                incompatible_items.append({**item, **state})
        if compatible_items:
            component_trace["compatible_item_tables"] += 1
            component_trace["compatible_item_rows"] += len(compatible_items)
        structural_fallback = not compatible_items and bool(incompatible_items)
        item_pool = incompatible_items if structural_fallback else compatible_items
        ranked_items = retain_ranked_components(
            item_pool, top_k=item_top_k, target_terms=targets, claim=claim
        )
        if not ranked_items:
            continue

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for obj in scored_objects:
            if table_key(obj) != key:
                continue
            try:
                axis_order = int(obj.get("axis_order"))
            except (TypeError, ValueError):
                continue
            if 1 <= axis_order <= MAX_AXIS:
                grouped[axis_order].append(obj)
        ranked_axes = {
            axis: retain_ranked_components(
                rows, top_k=axis_top_k, target_terms=targets, obj_axis=True,
                claim=claim,
            )
            for axis, rows in grouped.items()
        }
        # A KOSIS coordinate must select exactly one value from every official
        # axis.  Never emit a partially assembled coordinate when an axis has
        # no usable embedding row.
        if grouped and any(not ranked_axes[axis] for axis in grouped):
            component_trace["missing_official_axis_tables"] += 1
            continue
        combinations = beam_combine(ranked_items, ranked_axes, beam_width=beam_width)
        mandatory_role = mandatory_role_aware_combinations(
            ranked_items, grouped, claim, targets,
        )
        if mandatory_role:
            by_coordinate = {
                coordinate_id(candidate["item"], candidate["objects"]): candidate
                for candidate in combinations
            }
            for candidate in mandatory_role:
                by_coordinate[coordinate_id(candidate["item"], candidate["objects"])] = candidate
            combinations = list(by_coordinate.values())
        mandatory_target = mandatory_target_default_combinations(
            ranked_items, grouped, targets, claim,
        )
        if mandatory_target:
            by_coordinate = {
                coordinate_id(candidate["item"], candidate["objects"]): candidate
                for candidate in combinations
            }
            for candidate in mandatory_target:
                by_coordinate[coordinate_id(candidate["item"], candidate["objects"])] = candidate
            combinations = list(by_coordinate.values())
        if not targets:
            mandatory = mandatory_aggregate_combinations(ranked_items, grouped)
            by_coordinate = {
                coordinate_id(candidate["item"], candidate["objects"]): candidate
                for candidate in combinations
            }
            for candidate in mandatory:
                by_coordinate[coordinate_id(candidate["item"], candidate["objects"])] = candidate
            combinations = list(by_coordinate.values())
        accepted_for_table = 0
        rejected_for_table: list[dict[str, Any]] = []
        component_trace["beam_candidate_coordinates"] += len(combinations)
        for candidate in combinations:
            hierarchy_ok, hierarchy_state, hierarchy_reason = obj_hierarchy_scope(
                candidate, claim,
            )
            if not hierarchy_ok:
                component_trace["obj_hierarchy_rejected_coordinates"] += 1
                # Keep a complete, structurally assembled coordinate only as
                # a review-only table slot. Population/sex/region role-aware
                # safety remains a hard boundary below.
                if preserve_table_fallback and not _has_role_aware_scope(candidate, claim):
                    reviewed = dict(candidate)
                    reviewed["table"] = table
                    reviewed["coordinate_id"] = coordinate_id(
                        reviewed["item"], reviewed["objects"]
                    )
                    reviewed["document"] = coordinate_document(reviewed)
                    reviewed["claim_target_terms"] = "|".join(targets)
                    reviewed["target_match_state"] = "semantic_fallback"
                    reviewed["obj_hierarchy_state"] = hierarchy_state
                    reviewed["obj_hierarchy_reason"] = hierarchy_reason
                    reviewed["structural_match_state"] = (
                        "hypothesis_fallback" if structural_fallback
                        else "exact_or_unknown"
                    )
                    reviewed["verification_review_required"] = True
                    reviewed["verification_review_reason"] = "|".join(filter(None, (
                        "per_table_coordinate_slot",
                        hierarchy_reason,
                        reviewed["item"].get("structural_filter_reasons", "")
                        if structural_fallback else "",
                    )))
                    reviewed["table_slot_fallback"] = True
                    apply_candidate_scores(reviewed)
                    rejected_for_table.append(reviewed)
                continue
            target_matches = candidate_matches_targets(candidate, targets, claim)
            if not target_matches:
                component_trace["target_rejected_coordinates"] += 1
                # Population and role-aware scope is a safety boundary, not a
                # fuzzy-text preference. Never relax it.
                if _has_role_aware_scope(candidate, claim):
                    continue
            candidate["table"] = table
            candidate["coordinate_id"] = coordinate_id(candidate["item"], candidate["objects"])
            candidate["document"] = coordinate_document(candidate)
            candidate["claim_target_terms"] = "|".join(targets)
            candidate["target_match_state"] = (
                "exact" if target_matches else "semantic_fallback"
            )
            candidate["obj_hierarchy_state"] = hierarchy_state
            candidate["obj_hierarchy_reason"] = hierarchy_reason
            candidate["structural_match_state"] = (
                "hypothesis_fallback" if structural_fallback else "exact_or_unknown"
            )
            candidate["verification_review_required"] = bool(
                not target_matches or structural_fallback
            )
            candidate["verification_review_reason"] = "|".join(filter(None, (
                "target_semantic_fallback" if not target_matches else "",
                candidate["item"].get("structural_filter_reasons", "")
                if structural_fallback else "",
            )))
            apply_candidate_scores(candidate)
            destination = (
                fallback_candidates if candidate["verification_review_required"]
                else strict_candidates
            )
            destination.append(candidate)
            accepted_for_table += 1

        if preserve_table_fallback and not accepted_for_table and rejected_for_table:
            rejected_for_table.sort(
                key=lambda row: (-row["final_rank_score"], row["coordinate_id"])
            )
            fallback_candidates.append(rejected_for_table[0])
            component_trace["per_table_slot_candidates"] += 1
            component_trace["per_table_slot_recovered_tables"] += 1

    strict_candidates.sort(
        key=lambda row: (-row["final_rank_score"], row["coordinate_id"])
    )
    fallback_candidates.sort(
        key=lambda row: (-row["final_rank_score"], row["coordinate_id"])
    )
    all_candidates = list(strict_candidates)
    if len(all_candidates) < final_top_k:
        all_candidates.extend(fallback_candidates)
    component_trace["component_candidates_before_final"] = len(all_candidates)
    all_candidates.sort(key=lambda row: (-row["final_rank_score"], row["coordinate_id"]))
    rerank_pool = select_diverse_candidates(
        all_candidates, max(final_top_k, beam_width),
        per_table_minimum=per_table_minimum,
    )
    if reranker is not None and rerank_pool:
        scores = reranker.score(build_coordinate_query(claim), [row["document"] for row in rerank_pool])
        for row, score in zip(rerank_pool, scores):
            apply_candidate_scores(row, score)
        rerank_pool.sort(key=lambda row: (-row["final_rank_score"], row["coordinate_id"]))
    component_trace["rerank_pool_coordinates"] = len(rerank_pool)
    for global_rank, candidate in enumerate(rerank_pool, 1):
        candidate["global_candidate_rank"] = global_rank
    selected = select_diverse_candidates(
        rerank_pool, final_top_k, per_table_minimum=per_table_minimum,
    )
    component_trace["selected_coordinates"] = len(selected)
    component_trace["dropped_by_final_top_k"] = max(0, len(rerank_pool) - len(selected))
    return [
        build_output_row(claim, candidate, rank, trace=component_trace)
        for rank, candidate in enumerate(selected, 1)
    ]


def build_output_row(
    claim: Mapping[str, Any], candidate: Mapping[str, Any], rank: int,
    *, trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    item = candidate["item"]
    table = candidate["table"]
    row = {field: _text(claim.get(field)) for field in BASE_CLAIM_FIELDS}
    row["period"] = row["period"] or row["measurement_period"]
    row["prd_se"] = row["prd_se"] or row["measurement_prd_se"]
    row.update({
        "org_id": item.get("org_id", table.get("org_id", "")),
        "tbl_id": item.get("tbl_id", table.get("tbl_id", "")),
        "tbl_name": item.get("tbl_name", table.get("tbl_name", "")),
        "category_path": item.get("category_path", ""),
        "coordinate_id": candidate["coordinate_id"],
        "candidate_rank": rank,
        "candidate_status": table.get("candidate_status", ""),
        "candidate_status_code": "",
        "candidate_status_reason": "",
        "candidate_score": table.get("candidate_score", ""),
        "candidate_runner_up_score": table.get("candidate_runner_up_score", ""),
        "table_rank": table.get("rank", ""),
        "stage_a_channel": table.get("stage_a_channel", ""),
        "stage_a_channel_rank": table.get("stage_a_channel_rank", ""),
        "selected_itm_id": item.get("itm_id", ""),
        "selected_itm_name": item.get("itm_name", ""),
        "selected_itm_unit": item.get("unit", ""),
        "mapping_type": item.get("resolved_mapping_type", row.get("mapping_type", "")),
        "resolved_unit_hypothesis": item.get("resolved_unit_hypothesis", ""),
        "hypothesis_evidence": item.get("hypothesis_evidence", ""),
        "retrieval_stage": RETRIEVAL_STAGE,
        "failure_stage": "",
        "dense_score": candidate.get("component_score", ""),
        "item_component_score": item.get("component_score", ""),
        "item_rank_score": item.get("rank_score", ""),
        "item_component_rank": item.get("component_rank", ""),
        "axis_component_scores": json.dumps(
            {
                str(axis): {
                    "component_score": obj.get("component_score", ""),
                    "rank_score": obj.get("rank_score", ""),
                    "component_rank": obj.get("component_rank", ""),
                }
                for axis, obj in sorted(candidate["objects"].items())
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "beam_score_sum": candidate.get("score_sum", ""),
        "beam_parts": candidate.get("parts", ""),
        "beam_score": candidate.get("component_score", ""),
        "reranker_score": candidate.get("reranker_score", ""),
        "table_prior_score": candidate.get("table_prior_score", ""),
        "coordinate_score": candidate.get("coordinate_score", ""),
        "structural_bonus": candidate.get("structural_bonus", ""),
        "fallback_penalty": candidate.get("fallback_penalty", ""),
        "final_rank_score": candidate.get("final_rank_score", ""),
        "global_candidate_rank": candidate.get("global_candidate_rank", ""),
        "coordinate_rank_within_table": candidate.get(
            "coordinate_rank_within_table", ""
        ),
        "coordinate_scope": "table_component_beam",
        "coordinate_prd_se": item.get("prd_se", ""),
        "claim_target_terms": candidate.get("claim_target_terms", ""),
        "period_structural_state": item.get("period_structural_state", ""),
        "unit_structural_state": item.get("unit_structural_state", ""),
        "structural_compatible": bool(item.get("structural_compatible")),
        "target_match_state": candidate.get("target_match_state", ""),
        "obj_hierarchy_state": candidate.get("obj_hierarchy_state", ""),
        "obj_hierarchy_reason": candidate.get("obj_hierarchy_reason", ""),
        "structural_match_state": candidate.get("structural_match_state", ""),
        "verification_review_required": "Y" if (
            _text(claim.get("verification_review_required")).upper() == "Y"
            or candidate.get("verification_review_required")
        ) else "N",
        "verification_review_reason": "|".join(dict.fromkeys(filter(None, (
            _text(claim.get("verification_review_reason")),
            _text(candidate.get("verification_review_reason")),
        )))),
        "mandatory_aggregate": bool(candidate.get("mandatory_aggregate")),
        "mandatory_target_default": bool(
            candidate.get("mandatory_target_default")
        ),
    })
    row.update({field: (trace or {}).get(field, "") for field in COMPONENT_TRACE_FIELDS})
    for level in range(1, MAX_AXIS + 1):
        obj = candidate["objects"].get(level, {})
        row[f"selected_obj_l{level}"] = obj.get("obj_code", "")
        row[f"selected_obj_l{level}_name"] = obj.get("obj_name", "")
        row[f"selected_obj_l{level}_axis_id"] = obj.get("axis_id", "")
        row[f"selected_obj_l{level}_axis_name"] = obj.get("axis_name", "")
    return row


def component_failure_code(trace: Mapping[str, Any] | None) -> str:
    """Return the deepest deterministic component-search failure represented by trace."""
    values = trace or {}
    if not values.get("component_tables_seen") or not values.get("component_item_rows"):
        return "NO_TABLE_COMPONENT_ROWS"
    if not values.get("compatible_item_tables"):
        return "NO_UNIT_OR_PERIOD_COMPATIBLE_ITEM"
    if values.get("missing_official_axis_tables") and not values.get(
        "beam_candidate_coordinates"
    ):
        return "MISSING_OFFICIAL_AXIS"
    if values.get("target_rejected_coordinates") and not values.get(
        "component_candidates_before_final"
    ):
        return "TARGET_LITERAL_NOT_FOUND"
    if values.get("obj_hierarchy_rejected_coordinates") and not values.get(
        "component_candidates_before_final"
    ):
        return "OBJ_HIERARCHY_SCOPE_MISMATCH"
    if not values.get("beam_candidate_coordinates"):
        return "BEAM_EMPTY"
    if values.get("component_candidates_before_final") and not values.get(
        "selected_coordinates"
    ):
        return "DROPPED_BY_FINAL_TOP_K"
    return "NO_COMPONENT_COORDINATE_CANDIDATE"


def terminal_row(
    claim: Mapping[str, Any], trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status_code = component_failure_code(trace)
    row = {field: _text(claim.get(field)) for field in BASE_CLAIM_FIELDS}
    row.update({
        "candidate_rank": 1,
        "candidate_status": "REJECT",
        "candidate_status_code": status_code,
        "candidate_status_reason": COMPONENT_FAILURE_REASONS[status_code],
        "retrieval_stage": RETRIEVAL_STAGE,
        "failure_stage": "component_search",
        "coordinate_scope": "none",
        "selected_itm_id": "",
        "selected_itm_name": "",
        "selected_itm_unit": "",
    })
    row.update({field: (trace or {}).get(field, 0) for field in COMPONENT_TRACE_FIELDS})
    for level in range(1, MAX_AXIS + 1):
        row[f"selected_obj_l{level}"] = ""
        row[f"selected_obj_l{level}_name"] = ""
        row[f"selected_obj_l{level}_axis_id"] = ""
        row[f"selected_obj_l{level}_axis_name"] = ""
    return row


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_component_rows(
    path: str | Path, table_keys: Iterable[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Read only upstream tables through pyarrow predicate pushdown."""
    try:
        import pyarrow.dataset as ds
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("컴포넌트 Parquet 검색에는 pyarrow가 필요합니다") from exc
    keys = sorted({(_text(org), _text(tbl)) for org, tbl in table_keys if _text(tbl)})
    if not keys:
        return []
    expression = None
    for org_id, tbl_id in keys:
        current = ds.field("tbl_id") == tbl_id
        if org_id:
            current = current & (ds.field("org_id") == org_id)
        expression = current if expression is None else expression | current
    return ds.dataset(str(path), format="parquet").to_table(filter=expression).to_pylist()


def load_embedder(model_name: str, device: str | None = None) -> Any:
    from kosis_semantic_search import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(model_name, device=device)


def load_reranker(model_name: str, device: str | None = None) -> Any:
    from kosis_semantic_search import TransformerReranker

    return TransformerReranker(model_name, device=device)


def main() -> None:
    parser = argparse.ArgumentParser(description="BGE-M3 lossless ITEM/OBJ component search")
    parser.add_argument("--claims", required=True)
    parser.add_argument("--table-candidates", required=True)
    parser.add_argument("--items", required=True)
    parser.add_argument("--obj-values", required=True)
    parser.add_argument("--item-embeddings", required=True)
    parser.add_argument("--obj-embeddings", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--device", default=None)
    parser.add_argument("--table-top-k", type=int, default=10)
    parser.add_argument("--item-top-k", type=int, default=5)
    parser.add_argument("--axis-top-k", type=int, default=5)
    parser.add_argument("--beam-width", type=int, default=50)
    parser.add_argument("--final-top-k", type=int, default=10)
    parser.add_argument("--per-table-minimum", type=int, default=1)
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    import numpy as np

    claims = read_csv_rows(args.claims)
    if args.limit:
        claims = claims[: args.limit]
    tables_by_measurement = load_table_candidates(args.table_candidates, args.table_top_k)
    used_keys = {
        table_key(table)
        for claim in claims
        for table in tables_by_measurement.get(measurement_key(claim), [])
    }
    item_rows = read_component_rows(args.items, used_keys)
    obj_rows = read_component_rows(args.obj_values, used_keys)
    item_embeddings = np.load(args.item_embeddings, mmap_mode="r")
    obj_embeddings = np.load(args.obj_embeddings, mmap_mode="r")
    embedder = load_embedder(args.embedding_model, args.device)
    reranker = None if args.no_reranker else load_reranker(args.reranker_model, args.device)

    output: list[dict[str, Any]] = []
    for claim in claims:
        tables = tables_by_measurement.get(measurement_key(claim), [])
        query = build_coordinate_query(claim)
        vector = embedder.encode([query])[0]
        component_trace: dict[str, int] = {}
        rows = search_components_for_claim(
            claim, tables, item_rows, obj_rows, item_embeddings, obj_embeddings, vector,
            item_top_k=args.item_top_k, axis_top_k=args.axis_top_k,
            beam_width=args.beam_width, final_top_k=args.final_top_k,
            per_table_minimum=args.per_table_minimum, reranker=reranker,
            trace=component_trace,
        )
        output.extend(rows or [terminal_row(claim, component_trace)])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in output for key in row))
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output)
    print(json.dumps({"measurements": len(claims), "candidate_rows": len(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
