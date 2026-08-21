#!/usr/bin/env python3
"""Stage A: build a reranked table-pool JSONL without model co-residency."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from kosis_coordinate_low_memory import (
    JsonlCheckpoint,
    TABLE_POOL_SCHEMA,
    TABLE_RETRIEVAL_SCHEMA,
    assert_resume_compatible,
    claim_fingerprint,
    prepare_unique_claims,
    search_eligible_claims,
    require_schema,
)
from kosis_hybrid_top3 import (
    BM25TableIndex,
    diverse_rerank_pool,
    exact_domain_scope_filter,
    fuse_hits,
    lexical_query_document,
    read_csv,
    rerank_top3,
    semantic_query_document,
    table_key,
)
from kosis_component_search import normalize_prd_se
from kosis_postgres_store import PostgresKosisMetadataStore
from kosis_semantic_search import (
    SemanticSearchRuntime,
    TransformerReranker,
    build_table_document,
)
from kosis_match_claims_to_index import (
    normalized_claim_row,
    table_structural_signals,
)


def apply_general_table_guards(
    candidates: list[dict[str, Any]], claim: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply frozen v16 table guards without claim-ID or gold-set overrides."""
    normalized = normalized_claim_row(claim)
    kept: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for candidate in candidates:
        score, signals = table_structural_signals(candidate["table"], normalized)
        hard_guards = [signal for signal in signals if signal.startswith("guard:")]
        if score <= -(10**8) or hard_guards:
            reason = hard_guards[0] if hard_guards else "guard:structural-mismatch"
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        enriched = dict(candidate)
        enriched["v16_structural_score"] = score
        enriched["v16_structural_signals"] = signals
        kept.append(enriched)
    return kept, rejected


ORG_PATTERN = re.compile(
    r"([0-9A-Za-z가-힣·]{2,30}(?:부|청|원|공사|공단|협회|은행|연구원))"
)


def compact(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


_FAMILY_NOISE = re.compile(
    r"\((?:[^)]{0,24})?(?:(?:19|20)\d{2}|\uae30\uc900|\uac1c\ud3b8|\uac1c\uc815|\uc7a0\uc815|\ud655\uc815)(?:[^)]{0,24})?\)"
)


def table_family_identity(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return a stable organization/survey/table-family identity.

    Publication years and revision annotations do not create a new family, but
    semantic qualifiers such as country/item/sex remain in the normalized name.
    This keeps genuinely different official tables separate while allowing
    annual revisions of the same table to support one another.
    """
    table = candidate.get("table") or {}
    org_id = str(table.get("org_id") or candidate.get("org_id") or "").strip()
    survey = str(
        table.get("stat_id")
        or table.get("survey_name")
        or table.get("stat_name")
        or ""
    ).strip()
    if not survey:
        category = str(table.get("category_path") or "")
        survey = re.split(r"[>/|]", category, maxsplit=1)[0].strip()
    name = _FAMILY_NOISE.sub(" ", str(table.get("tbl_name") or ""))
    name = re.sub(r"(?:19|20)\d{2}(?:\s*=\s*100(?:\.0)?)?", " ", name)
    name = re.sub(r"\b(?:v|ver)\.?\s*\d+(?:\.\d+)*\b", " ", name, flags=re.I)
    family = compact(name) or compact(table.get("tbl_id"))
    return compact(org_id), compact(survey), family


def apply_family_rerank(
    candidates: list[dict[str, Any]], *, table_pool_top_k: int,
) -> list[dict[str, Any]]:
    """Rerank by official survey family and reserve one leader per family."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        groups[table_family_identity(row)].append(row)

    enriched: list[dict[str, Any]] = []
    for family_key, members in groups.items():
        best = max(float(row.get("metadata_rerank_score") or 0.0) for row in members)
        lexical_dense = any(
            row.get("lexical_rank") not in (None, "")
            and row.get("dense_rank") not in (None, "")
            for row in members
        )
        support_bonus = min(0.12, 0.03 * max(0, len(members) - 1))
        if lexical_dense:
            support_bonus += 0.04
        key_text = "|".join(family_key)
        for raw in members:
            row = dict(raw)
            member_score = float(row.get("metadata_rerank_score") or 0.0)
            row["table_family_key"] = key_text
            row["table_family_size"] = len(members)
            row["table_family_best_member_score"] = best
            row["table_family_support_bonus"] = support_bonus
            row["table_family_score"] = 0.85 * member_score + 0.15 * best + support_bonus
            row["table_family_signals"] = [
                f"family_members:{len(members)}",
                "family_lexical_dense" if lexical_dense else "family_single_channel",
            ]
            enriched.append(row)

    enriched.sort(key=lambda row: (
        -float(row["table_family_score"]),
        -float(row.get("metadata_rerank_score") or 0.0),
        -float(row.get("rrf_score") or 0.0),
        str(row.get("org_id") or ""), str(row.get("tbl_id") or ""),
    ))
    leaders: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for row in enriched:
        key = str(row["table_family_key"])
        if key not in seen_families:
            leaders.append(row)
            seen_families.add(key)
        if len(leaders) >= table_pool_top_k:
            break
    selected_ids = {id(row) for row in leaders}
    selected = list(leaders)
    if len(selected) < table_pool_top_k:
        for row in enriched:
            if id(row) in selected_ids:
                continue
            selected.append(row)
            if len(selected) >= table_pool_top_k:
                break
    return [
        {**row, "rank": rank, "table_family_rank": rank}
        for rank, row in enumerate(selected, 1)
    ]


def survey_family_rerank_pool(
    fused: list[dict[str, Any]],
    lexical_hits: list[Any],
    dense_hits: list[Any],
    *,
    top_k: int,
    reserved_slots: int,
    survey_group_limit: int = 0,
) -> list[dict[str, Any]]:
    """Reserve long-tail survey/family leaders before the table reranker.

    The legacy pool mostly follows global RRF order.  This policy keeps that
    behavior for unreserved slots while round-robining family leaders across
    official organization/survey groups.  It therefore exposes semantically
    plausible long-tail tables to the reranker without changing their scores.
    """
    baseline = diverse_rerank_pool(
        fused, lexical_hits, dense_hits, top_k=min(top_k, len(fused)),
    )
    if reserved_slots <= 0 or not fused:
        return baseline
    limit = min(top_k, len(fused))
    reserved_limit = min(max(0, reserved_slots), limit)

    family_leaders: dict[tuple[str, str, str], dict[str, Any]] = {}
    family_positions: dict[tuple[str, str, str], int] = {}
    for position, row in enumerate(fused):
        key = table_family_identity(row)
        family_leaders.setdefault(key, dict(row))
        family_positions.setdefault(key, position)

    by_survey: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for key, row in family_leaders.items():
        by_survey[key[:2]].append((family_positions[key], row))
    for rows in by_survey.values():
        rows.sort(key=lambda value: (value[0], table_key(value[1])))

    survey_order = sorted(
        by_survey,
        key=lambda key: (by_survey[key][0][0], key),
    )
    if survey_group_limit > 0:
        survey_order = survey_order[:survey_group_limit]
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    round_index = 0
    while len(selected) < reserved_limit:
        progressed = False
        for survey in survey_order:
            rows = by_survey[survey]
            if round_index >= len(rows):
                continue
            row = rows[round_index][1]
            key = table_key(row)
            if key not in seen:
                selected.append(row)
                seen.add(key)
                progressed = True
                if len(selected) >= reserved_limit:
                    break
        if not progressed:
            break
        round_index += 1

    for row in [*baseline, *fused]:
        if len(selected) >= limit:
            break
        key = table_key(row)
        if key in seen:
            continue
        selected.append(dict(row))
        seen.add(key)
    return selected


def claim_metadata_values(claim: Mapping[str, Any], *fields: str) -> list[str]:
    values = []
    for field in fields:
        value = str(claim.get(field) or "").strip()
        if value and value != "-":
            values.append(value)
    return values


def item_table_recall_terms(
    claim: Mapping[str, Any], *, structured_priority: bool = True,
) -> list[str]:
    """Build a small, structured ITEM-name query set for PostgreSQL recall."""
    raw_values = claim_metadata_values(
        claim, "measurement_indicator", "indicator", "measurement_item",
        "industry_or_item", "obj_target_terms", "claim_industry_or_item", "keywords",
    )
    generic = {
        "지표", "수치", "값", "통계", "증감", "증가", "감소", "증감률",
        "전월비", "전년비", "전년동월비", "월", "분기", "연간",
    }
    terms: list[str] = []

    def append(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip(" -_/|,;()")
        normalized = compact(value)
        if len(normalized) < 2 or normalized in {compact(item) for item in generic}:
            return
        if value not in terms:
            terms.append(value)

    for raw in raw_values:
        cleaned = re.sub(r"\([^)]*\)", " ", raw)
        for phrase in re.split(r"[,;|/]", cleaned):
            append(phrase)
            reduced = re.sub(
                r"(?:전년동월비|전년비|전월비|증감률|증가율|감소율)$", "", phrase,
            ).strip()
            append(reduced)
            for token in re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", phrase):
                append(token)
                if token.endswith("수") and len(token) >= 3:
                    append(token[:-1])
    compact_source = compact(" ".join(raw_values))
    if "수출" in compact_source:
        append("수출액")
    if "수입" in compact_source:
        append("수입액")
    if any(marker in compact_source for marker in ("인력", "근로자", "종사자")):
        append("현재인원")
        append("인원")
    aliases = {
        "명목임금": ("임금총액", "전체임금총액"),
        "월평균명목임금": ("임금총액", "월평균임금"),
        "1인가구수": ("1인가구",),
        "영아급사증후군": ("영아급사증후군",),
        "영아돌연사증후군": ("영아 돌연사 증후군", "영아급사증후군"),
        "음식서비스": ("음식서비스",),
        "비임금근로자": ("비임금근로자",),
        "60세이상": ("60세이상",),
    }
    for source, replacements in aliases.items():
        if compact(source) in compact_source:
            for replacement in replacements:
                append(replacement)

    metric_suffixes = (
        "증감률", "증가율", "감소율", "실업률", "고용률", "비율", "금액",
        "수출액", "수입액", "판매액", "거래액", "생산액", "소득", "가격",
        "지수", "인원", "인구", "건수", "수", "액", "률", "율", "량",
    )
    original_order = {value: index for index, value in enumerate(terms)}
    derived_level_aliases = {"수출액", "수입액", "현재인원", "인원"}
    exact_aliases = {
        "1인가구", "영아 돌연사 증후군", "영아급사증후군",
        "비임금근로자", "60세이상",
        "임금총액", "전체임금총액", "음식서비스",
    }

    def priority(value: str) -> tuple[int, int]:
        normalized = compact(value)
        metric = any(normalized.endswith(compact(suffix)) for suffix in metric_suffixes)
        return (-3 if structured_priority and value in exact_aliases else
                -1 if value in derived_level_aliases else
                0 if metric and " " not in value else 1 if " " not in value else 2,
                original_order[value])

    return sorted(terms, key=priority)[:16]


def merge_item_table_recall(
    fused: list[dict[str, Any]],
    item_hits: list[Mapping[str, Any]],
    lookup: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge a third table-recall channel into the Stage A RRF pool."""
    by_key = {table_key(row): dict(row) for row in fused}
    for hit in item_hits:
        key = (str(hit.get("org_id") or ""), str(hit.get("tbl_id") or ""))
        if key not in lookup:
            continue
        row = by_key.setdefault(key, {
            "table": dict(lookup[key]),
            "org_id": key[0], "tbl_id": key[1],
            "lexical_rank": None, "lexical_score": None,
            "dense_rank": None, "dense_score": None,
            "rrf_score": 0.0,
        })
        rank = int(hit.get("rank") or 10**9)
        row["item_recall_rank"] = rank
        row["item_recall_term_order"] = int(hit.get("first_term_order") or 10**9)
        row["item_recall_term_rank"] = int(hit.get("term_rank") or 10**9)
        row["item_recall_score"] = float(hit.get("score") or 0.0)
        row["item_recall_term_count"] = int(hit.get("matched_term_count") or 1)
        row["item_recall_term_orders"] = list(hit.get("matched_term_orders") or [])
        row["item_recall_names"] = list(hit.get("matched_item_names") or [])
        row["component_recall_sources"] = list(
            hit.get("matched_component_sources") or []
        )
        row["rrf_score"] = float(row.get("rrf_score") or 0.0) + 1.0 / (60 + rank)
    return sorted(by_key.values(), key=lambda row: (
        -float(row.get("rrf_score") or 0.0),
        int(row.get("item_recall_rank") or 10**9),
        str(row.get("org_id") or ""), str(row.get("tbl_id") or ""),
    ))


def explicit_table_name_recall(
    claim: Mapping[str, Any], tables: list[Mapping[str, Any]], *, limit: int = 5,
) -> list[dict[str, Any]]:
    """Recall official tables whose full name is explicitly cited by the claim.

    This channel uses only prediction-time article fields and the public KOSIS
    catalogue.  It does not infer a table from a validation label.  Exact table
    citations are rare but authoritative, so they must not be lost behind many
    sibling tables from the same survey family.
    """
    evidence = compact(" ".join(
        str(claim.get(field) or "")
        for field in (
            "title", "claim_text", "prev_sentence", "next_sentence",
            "statistics_name", "stat_name", "keywords",
        )
    ))
    if not evidence:
        return []
    matches: list[dict[str, Any]] = []
    for table in tables:
        table_name = str(table.get("tbl_name") or "").strip()
        normalized = compact(table_name)
        if len(normalized) < 5 or normalized not in evidence:
            continue
        matches.append({
            "org_id": str(table.get("org_id") or ""),
            "tbl_id": str(table.get("tbl_id") or ""),
            "table_name": table_name,
            "match_length": len(normalized),
        })
    matches.sort(key=lambda row: (
        -int(row["match_length"]), row["org_id"], row["tbl_id"],
    ))
    return matches[: max(0, int(limit))]


def merge_explicit_table_recall(
    fused: list[dict[str, Any]],
    hits: list[Mapping[str, Any]],
    lookup: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge exact cited-table evidence into the normal Stage-A pool."""
    by_key = {table_key(row): dict(row) for row in fused}
    for rank, hit in enumerate(hits, 1):
        key = (str(hit.get("org_id") or ""), str(hit.get("tbl_id") or ""))
        if key not in lookup:
            continue
        row = by_key.setdefault(key, {
            "table": dict(lookup[key]),
            "org_id": key[0], "tbl_id": key[1],
            "lexical_rank": None, "lexical_score": None,
            "dense_rank": None, "dense_score": None,
            "rrf_score": 0.0,
        })
        row["explicit_table_name_rank"] = rank
        row["explicit_table_name"] = str(hit.get("table_name") or "")
        row["explicit_table_name_match"] = True
        row["rrf_score"] = float(row.get("rrf_score") or 0.0) + 1.0 / (60 + rank)
    return sorted(by_key.values(), key=lambda row: (
        int(row.get("explicit_table_name_rank") or 10**9),
        -float(row.get("rrf_score") or 0.0),
        str(row.get("org_id") or ""), str(row.get("tbl_id") or ""),
    ))


def strong_structured_recall(row: Mapping[str, Any]) -> bool:
    """Return true only for component evidence strong enough to reserve a slot.

    A single literal on only one component axis is useful as retrieval evidence,
    but it is too broad to evict a strong lexical/dense candidate.  Reserved
    slots are therefore limited to either multiple matched terms or evidence
    spanning both ITEM and OBJ components.
    """
    term_count = int(row.get("item_recall_term_count") or 1)
    source_count = len(set(row.get("component_recall_sources") or []))
    return term_count >= 2 or source_count >= 2


def reserve_item_recall_slots(
    pool: list[dict[str, Any]], fused: list[dict[str, Any]],
    item_hits: list[Mapping[str, Any]], *, top_k: int, slots: int,
) -> list[dict[str, Any]]:
    """Guarantee bounded ITEM-matched tables reach the cross-encoder."""
    if slots <= 0 or top_k <= 0:
        return pool[:top_k]
    by_key = {table_key(row): row for row in fused}
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hit in item_hits[:slots]:
        key = (str(hit.get("org_id") or ""), str(hit.get("tbl_id") or ""))
        if key in by_key and key not in seen:
            selected.append(dict(by_key[key]))
            seen.add(key)
    for row in [*pool, *fused]:
        key = table_key(row)
        if key in seen:
            continue
        selected.append(dict(row))
        seen.add(key)
        if len(selected) >= top_k:
            break
    return selected[:top_k]


def metadata_table_score(
    candidate: Mapping[str, Any], claim: Mapping[str, Any],
) -> tuple[float, list[str]]:
    """Soft evidence from survey, publisher and statistical classification."""
    table = candidate.get("table") or {}
    table_name = str(table.get("tbl_name") or "")
    category = str(table.get("category_path") or "")
    org_name = str(candidate.get("postgres_org_name") or table.get("org_name") or "")
    survey_name = str(table.get("survey_name") or table.get("stat_name") or "")
    search_document = str(table.get("search_document") or "")
    table_text = compact(f"{table_name} {survey_name} {org_name} {category} {search_document}")
    score = 0.0
    signals: list[str] = []

    survey_values = claim_metadata_values(
        claim, "survey_name", "source_survey", "statistics_name", "stat_name",
    )
    for value in survey_values:
        token = compact(value)
        if token and token in table_text:
            score += 0.20
            signals.append(f"survey:{value}")
            break

    claim_stat_ids = set(claim_metadata_values(claim, "stat_id", "statistics_id"))
    table_stat_id = str(table.get("stat_id") or "").strip()
    if table_stat_id and table_stat_id in claim_stat_ids:
        score += 0.20
        signals.append(f"survey_id:{table_stat_id}")

    source_values = claim_metadata_values(
        claim, "source_organization", "source_org", "publisher", "organization_name",
    )
    source_values.extend(ORG_PATTERN.findall(str(claim.get("claim_text") or "")))
    compact_org = compact(org_name)
    if compact_org and any(
        compact(value) and (
            compact(value) in compact_org or compact_org in compact(value)
        )
        for value in source_values
    ):
        score += 0.10
        signals.append(f"organization:{org_name}")
    claim_org_ids = set(claim_metadata_values(claim, "source_org_id", "org_id"))
    table_org_id = str(table.get("org_id") or candidate.get("org_id") or "").strip()
    if table_org_id and table_org_id in claim_org_ids:
        score += 0.10
        signals.append(f"organization_id:{table_org_id}")

    indicator_values = claim_metadata_values(
        claim, "measurement_indicator", "indicator", "industry_or_item",
        "measurement_item",
    )
    if any(compact(value) and compact(value) in table_text for value in indicator_values):
        score += 0.08
        signals.append("indicator_or_item")

    domain = compact(claim.get("metric_domain"))
    if domain:
        if domain in table_text:
            score += 0.08
            signals.append("classification_domain")
        elif category:
            score -= 0.05
            signals.append("classification_domain_absent")

    category_terms = set(re.findall(
        r"[A-Za-z0-9]+|[가-힣]{2,}",
        " ".join(survey_values + indicator_values + claim_metadata_values(claim, "metric_domain")),
    ))
    category_compact = compact(category)
    overlap = sum(compact(term) in category_compact for term in category_terms if compact(term))
    if overlap:
        bonus = min(0.15, 0.03 * overlap)
        score += bonus
        signals.append(f"classification_overlap:{overlap}")

    # A structured OBJ dimension should help select the matching table axis,
    # not only the later coordinate. This separates otherwise near-identical
    # tables such as 거래주체별/거래규모별/행정구역별 without any table-ID rule.
    axis_requirements = (
        (
            "region",
            claim_metadata_values(claim, "region"),
            ("행정구역", "지역별", "시도별", "시군구별", "권역별", "도시별"),
        ),
        (
            "age",
            claim_metadata_values(claim, "age_group"),
            ("연령별", "연령대별", "나이별", "경영주연령"),
        ),
        (
            "gender",
            claim_metadata_values(claim, "gender"),
            ("성별", "남녀별"),
        ),
    )
    readable_table_text = f"{table_name} {category} {search_document}"
    for role, values, markers in axis_requirements:
        has_requirement = any(
            str(value).strip() not in {"", "-"} for value in values
        )
        if has_requirement and any(marker in readable_table_text for marker in markers):
            score += 0.18
            signals.append(f"obj_axis:{role}")
    return score, signals


def period_within_metadata_range(
    period: Any, prd_se: Any, range_text: Any,
) -> bool | None:
    """Return whether a requested month/year is inside an official range.

    KOSIS stores ranges as human-readable strings such as
    ``M:2017.01~2026.06`` and ``Y:2023~2025``.  Only formats that can be
    interpreted without guessing are enforced. Quarterly and irregular
    formats remain unknown and therefore are never rejected here.
    """
    requested_type = normalize_prd_se(prd_se)
    requested_digits = re.sub(r"\D", "", str(period or ""))
    text = str(range_text or "").strip()
    if requested_type == "M" and len(requested_digits) >= 6:
        endpoints = re.findall(r"(\d{4})[.\-/](\d{1,2})", text)
        if len(endpoints) < 2:
            return None
        requested_value = int(requested_digits[:6])
        start = int(endpoints[0][0]) * 100 + int(endpoints[0][1])
        end = int(endpoints[-1][0]) * 100 + int(endpoints[-1][1])
        return start <= requested_value <= end
    if requested_type == "Y" and len(requested_digits) >= 4:
        years = [int(value) for value in re.findall(r"(?<!\d)(\d{4})(?!\d)", text)]
        if len(years) < 2:
            return None
        return years[0] <= int(requested_digits[:4]) <= years[-1]
    return None


def apply_pre_rerank_metadata(
    candidates: list[dict[str, Any]], claim: Mapping[str, Any], store: Any,
    *, minimum_candidates: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reject known period mismatches before cross-encoder reranking."""
    metadata_rows = store.table_rerank_metadata(candidates)
    metadata = {
        (row["org_id"], row["tbl_id"]): row for row in metadata_rows
    }
    requested = normalize_prd_se(
        claim.get("measurement_prd_se") or claim.get("prd_se")
    )
    exact: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    counts = {
        "period_exact": 0, "period_unknown": 0, "period_mismatch_rejected": 0,
        "period_range_exact": 0, "period_range_unknown": 0,
        "period_range_mismatch_rejected": 0,
        "metadata_complete": 0, "metadata_incomplete": 0,
    }
    for candidate in candidates:
        key = (str(candidate.get("org_id") or ""), str(candidate.get("tbl_id") or ""))
        row = metadata.get(key, {})
        periods = {normalize_prd_se(value) for value in row.get("periodicities", [])}
        periods.discard("")
        if requested and periods and requested not in periods:
            counts["period_mismatch_rejected"] += 1
            continue
        requested_period = str(
            claim.get("measurement_period") or claim.get("period") or ""
        ).strip()
        matching_ranges = [
            str(value.get("range_text") or "").strip()
            for value in row.get("period_ranges") or []
            if normalize_prd_se(value.get("prd_se")) == requested
            and str(value.get("range_text") or "").strip()
        ]
        range_states = [
            period_within_metadata_range(requested_period, requested, value)
            for value in matching_ranges
        ]
        known_range_states = [state for state in range_states if state is not None]
        if requested_period and known_range_states and not any(known_range_states):
            counts["period_range_mismatch_rejected"] += 1
            continue
        enriched = dict(candidate)
        table = dict(enriched.get("table") or {})
        if row.get("tbl_name"):
            table["tbl_name"] = row["tbl_name"]
        if row.get("category_path"):
            table["category_path"] = row["category_path"]
        if row.get("search_document"):
            table["search_document"] = row["search_document"]
        enriched["table"] = table
        enriched["postgres_periodicities"] = sorted(periods)
        enriched["postgres_period_ranges"] = list(row.get("period_ranges") or [])
        enriched["postgres_metadata_complete"] = bool(row.get("metadata_complete"))
        metadata_score, metadata_signals = metadata_table_score(enriched, claim)
        enriched["metadata_score"] = metadata_score
        enriched["metadata_signals"] = metadata_signals
        completeness = "metadata_complete" if row.get("metadata_complete") else "metadata_incomplete"
        counts[completeness] += 1
        if requested and requested in periods:
            enriched["pre_rerank_period_state"] = "exact"
            counts["period_exact"] += 1
            if known_range_states and any(known_range_states):
                enriched["pre_rerank_period_range_state"] = "exact"
                counts["period_range_exact"] += 1
            else:
                enriched["pre_rerank_period_range_state"] = "unknown"
                counts["period_range_unknown"] += 1
            exact.append(enriched)
        else:
            enriched["pre_rerank_period_state"] = "unknown"
            enriched["metadata_score"] -= 0.20
            enriched["metadata_signals"] = [*metadata_signals, "period_unknown_penalty"]
            counts["period_unknown"] += 1
            unknown.append(enriched)
    # Exact-period tables always lead. Unknown metadata only backfills depth;
    # a known mismatching table never reaches the reranker.
    kept = exact if len(exact) >= minimum_candidates else [*exact, *unknown]
    return kept, counts


def retrieve_without_reranker(
    claim: Mapping[str, Any], tables: list[dict[str, Any]], lexical_index: Any,
    semantic_runtime: Any, *, lexical_top_k: int, dense_top_k: int,
    rerank_top_k: int, table_pool_top_k: int, postgres_store: Any,
    rerank_family_slots: int = 0,
    rerank_survey_groups: int = 0,
    item_recall_top_k: int = 50,
    item_rerank_slots: int = 10,
    item_recall_policy: str = "balanced",
) -> dict[str, Any]:
    lexical_query = lexical_query_document(claim)
    semantic_query = semantic_query_document(claim)
    lookup = {table_key(row): row for row in tables}
    lexical_hits = lexical_index.search(lexical_query, lexical_top_k)
    dense_hits = semantic_runtime.search(semantic_query, top_k=dense_top_k)
    fused = fuse_hits(lexical_hits, dense_hits, lookup)
    explicit_hits = explicit_table_name_recall(claim, tables)
    fused = merge_explicit_table_recall(fused, explicit_hits, lookup)
    semantic_pool = survey_family_rerank_pool(
        fused, lexical_hits, dense_hits,
        top_k=min(rerank_top_k, len(fused)),
        reserved_slots=rerank_family_slots,
        survey_group_limit=rerank_survey_groups,
    )
    semantic_keys = {table_key(row) for row in semantic_pool}
    item_terms = item_table_recall_terms(
        claim, structured_priority=item_recall_policy == "balanced",
    )
    item_hits = (
        postgres_store.item_table_recall(
            item_terms, limit=item_recall_top_k,
            prd_se=normalize_prd_se(
                claim.get("measurement_prd_se") or claim.get("prd_se")
            ),
            balanced_terms=item_recall_policy == "balanced",
        )
        if item_recall_top_k > 0 and hasattr(postgres_store, "item_table_recall")
        else []
    )
    fused = merge_item_table_recall(fused, item_hits, lookup)
    # Dual-channel pool: exact component hits receive bounded reserved slots,
    # while the remaining slots come from the untouched semantic pool.  This
    # prevents a broad component term from evicting previously strong BGE
    # candidates before the cross-encoder sees them.
    pool = semantic_pool
    pool = reserve_item_recall_slots(
        pool, fused, item_hits,
        top_k=min(rerank_top_k, len(fused)), slots=item_rerank_slots,
    )
    # An exact official table citation is stronger than a semantic sibling.
    # Reserve it before metadata guards; period/scope guards still apply.
    explicit_rows = [
        row for row in fused if row.get("explicit_table_name_match")
    ]
    if explicit_rows:
        pool = reserve_item_recall_slots(
            pool, fused, explicit_rows,
            top_k=min(rerank_top_k, len(fused)), slots=min(3, len(explicit_rows)),
        )
    pool = [
        {**row, "semantic_baseline": table_key(row) in semantic_keys}
        for row in pool
    ]
    pool = exact_domain_scope_filter(
        pool, claim, minimum_candidates=table_pool_top_k,
    )
    pool, structural_rejections = apply_general_table_guards(pool, claim)
    pool, metadata_filter_counts = apply_pre_rerank_metadata(
        pool, claim, postgres_store, minimum_candidates=table_pool_top_k,
    )
    return {
        "schema_version": TABLE_RETRIEVAL_SCHEMA,
        "claim_measurement_id": claim["claim_measurement_id"],
        "claim_fingerprint": claim_fingerprint(claim),
        "claim": dict(claim),
        "reranker_query": semantic_query,
        "structural_rejection_counts": structural_rejections,
        "metadata_filter_counts": metadata_filter_counts,
        "rerank_family_slots": rerank_family_slots,
        "rerank_survey_groups": rerank_survey_groups,
        "item_recall_terms": item_terms,
        "item_recall_hit_count": len(item_hits),
        "item_rerank_slots": item_rerank_slots,
        "item_recall_policy": item_recall_policy,
        "explicit_table_name_hits": explicit_hits,
        "candidates": pool,
    }


def rerank_table_record(
    record: Mapping[str, Any], reranker: Any, *, table_pool_top_k: int,
) -> dict[str, Any]:
    require_schema(record, TABLE_RETRIEVAL_SCHEMA)
    candidates = list(record.get("candidates") or [])
    scores = reranker.score(
        record.get("reranker_query", ""),
        [build_table_document(row["table"]) for row in candidates],
    )
    ranked = []
    for candidate, score in zip(candidates, scores):
        row = dict(candidate)
        row["reranker_score"] = float(score)
        row["metadata_rerank_score"] = float(score) + float(row.get("metadata_score") or 0.0)
        if row.get("explicit_table_name_match"):
            row["metadata_rerank_score"] += 1.0
        ranked.append(row)
    item_recall_policy = str(record.get("item_recall_policy") or "balanced")
    family_ranked = apply_family_rerank(ranked, table_pool_top_k=table_pool_top_k)
    baseline_ranked = apply_family_rerank(
        [row for row in ranked if row.get("semantic_baseline")],
        table_pool_top_k=table_pool_top_k,
    )
    # Reserve a bounded tail for official literal ITEM/OBJ matches. This
    # prevents the semantic cross-encoder from erasing an exact component hit.
    structured_rows = [
        row for row in ranked if row.get("item_recall_rank") is not None
    ]
    explicit = sorted(
        [row for row in ranked if row.get("explicit_table_name_match")],
        key=lambda row: int(row.get("explicit_table_name_rank") or 10**9),
    )
    if item_recall_policy == "legacy":
        structured = sorted(structured_rows, key=lambda row: (
            int(row.get("item_recall_rank") or 10**9),
            -float(row.get("metadata_rerank_score") or 0.0),
        ))
        reserve = min(4, table_pool_top_k, len(structured))
        selected = list(family_ranked[:max(0, table_pool_top_k - reserve)])
    else:
        structured = sorted(
            [row for row in structured_rows if strong_structured_recall(row)],
            key=lambda row: (
            -int(row.get("item_recall_term_count") or 1),
            -len(row.get("component_recall_sources") or []),
            int(row.get("item_recall_term_order") or 10**9),
            int(row.get("item_recall_term_rank") or 10**9),
            -float(row.get("metadata_rerank_score") or 0.0),
            ),
        )
        reserve = min(5, table_pool_top_k, len(structured))
        selected = list(baseline_ranked[:max(0, table_pool_top_k - reserve)])
    if explicit:
        explicit_keys = {table_key(row) for row in explicit}
        selected = [*explicit, *(row for row in selected if table_key(row) not in explicit_keys)]
        selected = selected[:table_pool_top_k]
    seen = {table_key(row) for row in selected}
    for row in structured:
        if len(selected) >= table_pool_top_k:
            break
        if table_key(row) in seen:
            continue
        selected.append(row)
        seen.add(table_key(row))
    for row in family_ranked:
        if len(selected) >= table_pool_top_k:
            break
        if table_key(row) in seen:
            continue
        selected.append(row)
        seen.add(table_key(row))
    ranked = [
        {**row, "rank": rank, "table_family_rank": rank}
        for rank, row in enumerate(selected, 1)
    ]
    return {
        "schema_version": TABLE_POOL_SCHEMA,
        "claim_measurement_id": record["claim_measurement_id"],
        "claim_fingerprint": record["claim_fingerprint"],
        "claim": dict(record["claim"]),
        "item_recall_terms": list(record.get("item_recall_terms") or []),
        "item_recall_hit_count": int(record.get("item_recall_hit_count") or 0),
        "item_rerank_slots": int(record.get("item_rerank_slots") or 0),
        "item_recall_policy": item_recall_policy,
        "table_candidates": ranked,
    }


def run_retrieve(args: argparse.Namespace) -> None:
    claims = search_eligible_claims(prepare_unique_claims(read_csv(args.claims)))
    claims = [row for row in claims if row[0] >= args.start_row]
    if args.limit:
        claims = claims[:args.limit]
    output = JsonlCheckpoint(args.retrieval_output)
    current_records = [{
        "claim_measurement_id": claim["claim_measurement_id"],
        "claim_fingerprint": claim_fingerprint(claim),
    } for _number, claim in claims]
    assert_resume_compatible(current_records, output.records)
    pending = [(number, claim) for number, claim in claims
               if claim["claim_measurement_id"] not in output.completed_ids]
    print(f"[stage_a1] pending={len(pending)} completed={len(output.completed_ids)}", flush=True)
    if not pending:
        return
    tables = read_csv(args.semantic_index / "tables.csv")
    lexical_index = BM25TableIndex(tables)
    runtime = SemanticSearchRuntime(
        args.semantic_index, device=args.device, use_reranker=False,
    )
    with PostgresKosisMetadataStore(args.postgres_dsn) as store:
        with store.metadata_read_guard():
            for index, (row_number, claim) in enumerate(pending, 1):
                started = time.perf_counter()
                packet = retrieve_without_reranker(
                    claim, tables, lexical_index, runtime,
                    lexical_top_k=args.lexical_top_k, dense_top_k=args.dense_top_k,
                    rerank_top_k=args.table_rerank_top_k,
                    table_pool_top_k=args.table_pool_top_k,
                    rerank_family_slots=args.rerank_family_slots,
                    rerank_survey_groups=args.rerank_survey_groups,
                    item_recall_top_k=args.item_recall_top_k,
                    item_rerank_slots=args.item_rerank_slots,
                    item_recall_policy=args.item_recall_policy,
                    postgres_store=store,
                )
                output.append(packet)
                print(
                    f"[stage_a1] {index}/{len(pending)} row={row_number} "
                    f"claim={claim['claim_measurement_id']} candidates={len(packet['candidates'])} "
                    f"elapsed={time.perf_counter() - started:.1f}s", flush=True,
                )


def run_rerank(args: argparse.Namespace) -> None:
    source = JsonlCheckpoint(args.retrieval_output)
    output = JsonlCheckpoint(args.output)
    assert_resume_compatible(source.records, output.records)
    pending = [row for row in source.records
               if row["claim_measurement_id"] not in output.completed_ids]
    print(f"[stage_a2] pending={len(pending)} completed={len(output.completed_ids)}", flush=True)
    if not pending:
        return
    reranker = TransformerReranker(
        device=args.device, batch_size=args.reranker_batch_size,
    )
    for index, record in enumerate(pending, 1):
        started = time.perf_counter()
        packet = rerank_table_record(
            record, reranker, table_pool_top_k=args.table_pool_top_k,
        )
        output.append(packet)
        print(
            f"[stage_a2] {index}/{len(pending)} claim={packet['claim_measurement_id']} "
            f"tables={len(packet['table_candidates'])} "
            f"elapsed={time.perf_counter() - started:.1f}s", flush=True,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--semantic-index", required=True, type=Path)
    parser.add_argument("--postgres-dsn", default=os.environ.get("KOSIS_POSTGRES_DSN"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--retrieval-output", type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--dense-top-k", type=int, default=50)
    parser.add_argument("--table-rerank-top-k", type=int, default=50)
    parser.add_argument("--table-pool-top-k", type=int, default=50)
    parser.add_argument("--rerank-family-slots", type=int, default=0)
    parser.add_argument("--rerank-survey-groups", type=int, default=0)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--item-recall-top-k", type=int, default=50)
    parser.add_argument("--item-rerank-slots", type=int, default=10)
    parser.add_argument(
        "--item-recall-policy", choices=("legacy", "balanced"),
        default="balanced",
    )
    parser.add_argument("--start-row", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--worker-phase", choices=("retrieve", "rerank"))
    args = parser.parse_args()
    if args.retrieval_output is None:
        args.retrieval_output = args.output.with_name(args.output.stem + ".retrieval.jsonl")
    if args.table_pool_top_k > args.table_rerank_top_k:
        parser.error("--table-pool-top-k cannot exceed --table-rerank-top-k")
    if args.start_row <= 0:
        parser.error("--start-row must be positive")
    if args.item_recall_top_k < 0 or args.item_rerank_slots < 0:
        parser.error("ITEM recall limits must be non-negative")
    if args.item_rerank_slots > args.table_rerank_top_k:
        parser.error("--item-rerank-slots cannot exceed --table-rerank-top-k")
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or KOSIS_POSTGRES_DSN is required")
    return args


def main() -> None:
    args = parse_args()
    if args.worker_phase == "retrieve":
        run_retrieve(args)
        return
    if args.worker_phase == "rerank":
        run_rerank(args)
        return
    base = [
        sys.executable, str(Path(__file__).resolve()),
        "--claims", str(args.claims), "--semantic-index", str(args.semantic_index),
        "--postgres-dsn", str(args.postgres_dsn),
        "--output", str(args.output), "--retrieval-output", str(args.retrieval_output),
        "--lexical-top-k", str(args.lexical_top_k),
        "--dense-top-k", str(args.dense_top_k),
        "--table-rerank-top-k", str(args.table_rerank_top_k),
        "--table-pool-top-k", str(args.table_pool_top_k),
        "--rerank-family-slots", str(args.rerank_family_slots),
        "--rerank-survey-groups", str(args.rerank_survey_groups),
        "--item-recall-top-k", str(args.item_recall_top_k),
        "--item-rerank-slots", str(args.item_rerank_slots),
        "--item-recall-policy", args.item_recall_policy,
        "--reranker-batch-size", str(args.reranker_batch_size),
        "--start-row", str(args.start_row), "--limit", str(args.limit),
    ]
    if args.device:
        base.extend(("--device", args.device))
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    for phase in ("retrieve", "rerank"):
        print(f"[stage_a] starting child phase={phase}", flush=True)
        subprocess.run(base + ["--worker-phase", phase], check=True, env=environment)
        print(f"[stage_a] child phase={phase} exited; model memory released", flush=True)


if __name__ == "__main__":
    main()
