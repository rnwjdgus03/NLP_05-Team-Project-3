#!/usr/bin/env python3
"""Apply gold-free KOSIS schema compatibility to a reranked table pool.

Semantic retrieval answers whether a table is related to the claim.  This
stage answers the different, structured question: does the table expose the
requested period and OBJ scope without adding an unrequested population or
adjustment?  It only reorders an upstream candidate pool and never invents a
table or coordinate.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Mapping

from kosis_meta_coordinates import is_aggregate_name, normalize_periodicity, periodicity_satisfied
from kosis_sqlite_metadata import clean
from kosis_sqlite_resolver import MetadataStore, lookup_keys
from select_mcp_gold_200_two_stage_coordinates import obj_target_terms, obj_term_matches


STRONG_SCOPES = (
    ("계절조정", ("계절조정",)),
    ("이민자", ("이민자", "외국인", "귀화")),
    ("귀화", ("귀화", "이민자")),
    ("구직기간1주", ("구직기간1주", "1주기준", "1주 기준")),
    ("시계열보정전", ("시계열보정전", "보정전", "보정 전")),
)

SPECIALIZED_AXES = (
    ("교육정도", ("교육", "학력")),
    ("연령", ("연령", "세")),
    ("행정구역", ("지역", "시도", "시군구")),
    ("국적", ("국가", "국적", "출발국", "도착국")),
    ("가구형태", ("가구",)),
    ("점유형태", ("점유",)),
    ("거처종류", ("거처", "주거")),
)

GEOGRAPHIC_TABLE_MARKERS = (
    "시군구", "시도/", "시도별", "9개도", "39개시", "행정구역별",
)
PARENTHETICAL = re.compile(r"\([^)]*\)")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(row: Mapping[str, object], field: str) -> float:
    try:
        return float(clean(row.get(field)))
    except ValueError:
        return 0.0


def rank(row: Mapping[str, object]) -> int:
    try:
        return int(float(clean(row.get("candidate_rank"))))
    except ValueError:
        return 999


def compact(*values: object) -> str:
    return "".join(clean(value).replace(" ", "").lower() for value in values if clean(value))


def title_core(value: object) -> str:
    text = PARENTHETICAL.sub("", clean(value))
    return compact(text).lstrip("·-/")


def indicator_terms(claim: Mapping[str, str]) -> tuple[str, ...]:
    values = (
        claim.get("measurement_indicator"), claim.get("indicator"),
        claim.get("item_intent_terms"),
    )
    terms: list[str] = []
    for value in values:
        for term in clean(value).split("|"):
            normalized = compact(term)
            if len(normalized) >= 2 and normalized not in terms:
                terms.append(normalized)
    return tuple(terms)


def table_structure_score(
    claim: Mapping[str, str], candidate: Mapping[str, str], store: MetadataStore
) -> tuple[float, list[str]]:
    org_id, tbl_id = clean(candidate.get("org_id")), clean(candidate.get("tbl_id"))
    table = store.table(org_id, tbl_id) or {}
    table_name = clean(table.get("tbl_name") or candidate.get("tbl_name"))
    category = clean(table.get("category_path") or candidate.get("category_path"))
    axes = store.axes(org_id, tbl_id)
    claim_text = compact(
        claim.get("claim_text"), claim.get("measurement_indicator"),
        claim.get("measurement_item"), claim.get("obj_target_terms"),
    )
    table_text = compact(table_name, category)
    score = 0.0
    reasons: list[str] = []

    core = title_core(table_name)
    indicators = indicator_terms(claim)
    if any(core.startswith(term) for term in indicators):
        score += 0.6
        reasons.append("INDICATOR_LEADING_TABLE")

    region_target = clean(claim.get("region"))
    geographic_table = any(
        compact(marker) in compact(table_name) for marker in GEOGRAPHIC_TABLE_MARKERS
    )
    geographic_aggregate = geographic_table and any(
        is_aggregate_name(value.get("obj_name"))
        for axis in axes for value in axis.get("values", [])
    )
    if region_target in {"", "-", "N/A", "전국", "계", "전체"} and geographic_table:
        if geographic_aggregate:
            score += 0.1
            reasons.append("GEOGRAPHIC_TABLE_HAS_AGGREGATE")
        else:
            score -= 0.8
            reasons.append("UNREQUESTED_GEOGRAPHIC_GRANULARITY")

    for marker, allowed_claim_terms in STRONG_SCOPES:
        if compact(marker) in table_text and not any(compact(term) in claim_text for term in allowed_claim_terms):
            score -= 1.2
            reasons.append(f"UNREQUESTED_SCOPE:{marker}")

    wanted_prd = normalize_periodicity(
        clean(claim.get("measurement_prd_se") or claim.get("prd_se"))
    )
    available_prd = store.periodicities(org_id, tbl_id)
    if wanted_prd and available_prd:
        if periodicity_satisfied(wanted_prd, available_prd):
            score += 0.25
            reasons.append("PERIOD_SUPPORTED")
        else:
            score -= 1.0
            reasons.append("PERIOD_UNSUPPORTED")
    if "연도별" in table_name:
        if wanted_prd == "Y":
            score += 0.2
            reasons.append("ANNUAL_TABLE_MATCH")
        elif wanted_prd:
            score -= 1.0
            reasons.append("ANNUAL_TABLE_MISMATCH")
    if "월별" in table_name:
        if wanted_prd == "M":
            score += 0.2
            reasons.append("MONTHLY_TABLE_MATCH")
        elif wanted_prd:
            score -= 1.0
            reasons.append("MONTHLY_TABLE_MISMATCH")

    targets = obj_target_terms(claim)
    if targets:
        names = [clean(value.get("obj_name")) for axis in axes for value in axis.get("values", [])]
        matched = [target for target in targets if any(obj_term_matches(target, name) for name in names)]
        coverage = len(matched) / len(targets)
        if coverage == 1.0:
            score += 1.0
            reasons.append("ALL_OBJ_TARGETS_SUPPORTED")
        elif coverage > 0:
            score += 0.4 * coverage
            reasons.append("PARTIAL_OBJ_TARGETS_SUPPORTED")
        else:
            score -= 1.0
            reasons.append("OBJ_TARGETS_UNSUPPORTED")
    else:
        if "총괄" in table_name:
            score += 0.15
            reasons.append("UNSCOPED_TOTAL_TABLE")
        for marker, allowed_claim_terms in SPECIALIZED_AXES:
            if marker == "행정구역" and geographic_aggregate:
                continue
            if marker in table_name and not any(compact(term) in claim_text for term in allowed_claim_terms):
                score -= 0.15
                reasons.append(f"UNREQUESTED_AXIS:{marker}")

    return score, reasons


def apply_policy(
    claims: list[dict[str, str]], candidates: list[dict[str, str]],
    store: MetadataStore, *, weight: float,
) -> list[dict[str, object]]:
    claim_map: dict[str, dict[str, str]] = {}
    for claim in claims:
        for key in lookup_keys(claim):
            claim_map[key] = claim
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for row in candidates:
        key = clean(row.get("gold_id") or row.get("claim_measurement_id") or row.get("claim_id"))
        if not key:
            continue
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)

    output: list[dict[str, object]] = []
    for key in order:
        claim = claim_map.get(key, grouped[key][0])
        rescored = []
        for row in grouped[key]:
            structural_score, reasons = table_structure_score(claim, row, store)
            upstream_score = number(row, "metadata_fusion_score")
            if not upstream_score:
                upstream_score = number(row, "fusion_score")
            final_score = upstream_score + weight * structural_score
            rescored.append({
                **row,
                "pre_structural_candidate_rank": rank(row),
                "structural_table_score": structural_score,
                "structural_table_reasons": "|".join(reasons),
                "structural_weight": weight,
                "structural_fusion_score": final_score,
            })
        rescored.sort(key=lambda row: (
            -float(row["structural_fusion_score"]),
            int(row["pre_structural_candidate_rank"]),
            clean(row.get("tbl_id")),
        ))
        for index, row in enumerate(rescored, 1):
            row["candidate_rank"] = index
            row["retrieval_backend"] = clean(row.get("retrieval_backend")) + "+sqlite-structural-policy"
            output.append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weight", type=float, default=0.25)
    args = parser.parse_args()
    if args.weight < 0:
        parser.error("--weight must be non-negative")
    store = MetadataStore(args.metadata_db)
    try:
        output = apply_policy(
            read_csv(args.claims), read_csv(args.candidates), store, weight=args.weight
        )
    finally:
        store.close()
    write_csv(args.output, output)
    print(f"rows={len(output)} weight={args.weight:g} output={args.output}")


if __name__ == "__main__":
    main()
