#!/usr/bin/env python3
"""Select KOSIS coordinates with separate ITEM and OBJ ranking stages."""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping


AGGREGATE_NAMES = {
    "", "-", "계", "총계", "합계", "전체", "전국", "총액", "총지수", "all", "total",
}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", clean(value).lower())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def row_key(row: Mapping[str, str]) -> str:
    return clean(row.get("gold_id") or row.get("claim_measurement_id") or row.get("claim_id"))


def claim_lookup_keys(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            clean(row.get(name))
            for name in ("gold_id", "claim_measurement_id", "claim_id")
            if clean(row.get(name))
        )
    )


def rank_value(row: Mapping[str, str], field: str, default: int = 999) -> int:
    try:
        return int(float(clean(row.get(field))))
    except ValueError:
        return default


def float_value(row: Mapping[str, str], field: str) -> float:
    try:
        return float(clean(row.get(field)))
    except ValueError:
        return 0.0


def item_intent_terms(claim: Mapping[str, str]) -> tuple[str, ...]:
    text = clean(claim.get("claim_text"))
    indicator = clean(claim.get("item_intent_terms") or claim.get("measurement_indicator") or claim.get("indicator"))
    terms = [indicator] if indicator and indicator != "-" else []
    role = clean(claim.get("measurement_role"))
    value_type = clean(claim.get("value_type"))
    semantic = clean(claim.get("semantic_type") or claim.get("claim_type")).upper()
    if role == "증감값" or value_type == "증감량" or semantic == "ABSOLUTE_CHANGE":
        terms.insert(0, "증감")
    if "RATE" in semantic:
        if re.search(r"전월|전달", text):
            terms.insert(0, "전월비")
        elif re.search(r"전년\s*(?:동월|같은\s*달)|작년\s*같은\s*달", text):
            terms.insert(0, "전년동월비")
        elif re.search(r"전년\s*(?:누계|대비|보다)|작년보다|1년\s*전", text):
            terms.insert(0, "전년동월비")
    return tuple(dict.fromkeys(term for term in terms if term))


def item_match_score(claim: Mapping[str, str], candidate: Mapping[str, str]) -> tuple[float, str]:
    item_name = normalized(candidate.get("selected_itm_name"))
    terms = item_intent_terms(claim)
    matched = [term for term in terms if normalized(term) in item_name or item_name in normalized(term)]
    score = 120.0 if matched else 0.0
    role = clean(claim.get("measurement_role"))
    value_type = clean(claim.get("value_type"))
    semantic = clean(claim.get("semantic_type")).upper()
    if role == "증감값" or value_type == "증감량" or semantic == "ABSOLUTE_CHANGE":
        if "증감" in item_name and "증감률" not in item_name:
            score += 180.0
        elif "증감률" in item_name:
            score -= 120.0
    # A candidate already ranked well by dense/lexical/reranker remains the
    # fallback when the article does not expose an item name explicitly.
    score += 25.0 / math.log2(rank_value(candidate, "table_rank") + 1.0)
    score += 10.0 / math.log2(rank_value(candidate, "candidate_rank") + 1.0)
    if clean(candidate.get("prd_se_match")).lower() in {"true", "y", "1"}:
        score += 5.0
    return score, "|".join(matched)


def obj_names(candidate: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(clean(candidate.get(f"selected_obj_l{level}_name")) for level in range(1, 9))


def is_aggregate_candidate(candidate: Mapping[str, str]) -> bool:
    names = [name for name in obj_names(candidate) if name]
    return not names or all(normalized(name) in {normalized(value) for value in AGGREGATE_NAMES} for name in names)


def obj_target_terms(claim: Mapping[str, str]) -> tuple[str, ...]:
    raw = clean(claim.get("obj_target_terms"))
    if raw:
        return tuple(
            term for term in raw.split("|")
            if term and term != "-" and normalized(term)
        )
    return tuple(
        term
        for term in (
            clean(claim.get("destination_country")), clean(claim.get("origin_country")),
            clean(claim.get("region")), clean(claim.get("age_group")), clean(claim.get("gender")),
            clean(claim.get("industry_or_item") or claim.get("measurement_item")),
        )
        if term and term != "-" and normalized(term)
    )


def obj_term_matches(term: str, selected_name: str) -> bool:
    target = normalized(term)
    selected = normalized(selected_name)
    if not target or not selected:
        return False
    # '정규직'은 '비정규직'의 부분 문자열이지만 서로 다른 KOSIS OBJ다.
    if target == "정규직" and "비정규직" in selected:
        return False
    if target == "비정규직" and selected == "정규직":
        return False
    if target == selected:
        return True
    # 행정구역 접미사와 연령/품목의 설명형 코드명은 부분 일치를 허용한다.
    if selected in {target + "시", target + "도", target + "군", target + "구"}:
        return True
    return len(target) >= 3 and (target in selected or selected in target)


def obj_match_score(
    claim: Mapping[str, str], candidate: Mapping[str, str]
) -> tuple[float, bool, bool, tuple[str, ...]]:
    targets = obj_target_terms(claim)
    selected_names = obj_names(candidate)
    matched_terms = tuple(
        term for term in targets
        if any(obj_term_matches(term, name) for name in selected_names)
    )
    matched = bool(targets) and len(matched_terms) == len(targets)
    aggregate = is_aggregate_candidate(candidate)
    if targets:
        # Partial axis coverage is meaningful when a table separates region,
        # gender and age across several OBJ levels.
        score = 160.0 * len(matched_terms) / len(targets)
    else:
        score = 100.0 if aggregate else 0.0
    score += 5.0 / math.log2(rank_value(candidate, "candidate_rank") + 1.0)
    return score, matched, aggregate, matched_terms


def select_two_stage(
    claim: Mapping[str, str],
    candidates: list[dict[str, str]],
    *,
    item_top_k: int = 3,
) -> dict[str, str] | None:
    if not candidates:
        return None
    baseline = min(candidates, key=lambda row: rank_value(row, "candidate_rank"))
    baseline_table = (clean(baseline.get("org_id")), clean(baseline.get("tbl_id")))
    item_groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for candidate in candidates:
        key = (
            clean(candidate.get("org_id")), clean(candidate.get("tbl_id")),
            clean(candidate.get("selected_itm_id")),
        )
        item_groups[key].append(candidate)

    staged_items = []
    for key, rows in item_groups.items():
        representative = min(rows, key=lambda row: rank_value(row, "candidate_rank"))
        score, matched = item_match_score(claim, representative)
        staged_items.append((score, matched, key, rows))
    staged_items.sort(key=lambda value: (-value[0], value[2]))
    staged_items = staged_items[: max(1, item_top_k)]

    finalists = []
    for item_rank, (item_score, item_matched, key, rows) in enumerate(staged_items, 1):
        for row in rows:
            obj_score, obj_matched, aggregate, obj_matched_terms = obj_match_score(claim, row)
            final_score = item_score + obj_score
            item_exact = bool(item_matched)
            targets = obj_target_terms(claim)
            obj_priority = len(obj_matched_terms) if targets else int(aggregate)
            finalists.append(
                (item_exact, obj_priority, final_score, -rank_value(row, "candidate_rank"),
                 item_rank, item_score, item_matched, obj_score, obj_matched,
                 aggregate, obj_matched_terms, row)
            )
    if not finalists:
        return None
    selected = max(finalists, key=lambda value: value[:4])
    (
        _, _, final_score, _, item_rank, item_score, item_matched, obj_score,
        obj_matched, aggregate, obj_matched_terms, row,
    ) = selected
    return {
        **row,
        "period": clean(claim.get("period")) or clean(row.get("period")),
        "prd_se": clean(claim.get("prd_se")) or clean(row.get("prd_se")),
        "previous_period": clean(claim.get("previous_period")) or clean(row.get("previous_period")),
        "comparison_period": clean(claim.get("comparison_period")) or clean(row.get("comparison_period")),
        "period_extraction_source": clean(claim.get("period_extraction_source")),
        "candidate_rank": "1",
        "original_candidate_rank": clean(row.get("candidate_rank")),
        "two_stage_item_rank": str(item_rank),
        "two_stage_item_score": str(item_score),
        "two_stage_item_matched_terms": item_matched,
        "two_stage_obj_score": str(obj_score),
        "two_stage_obj_target_terms": "|".join(obj_target_terms(claim)),
        "two_stage_obj_matched_terms": "|".join(obj_matched_terms),
        "two_stage_obj_matched": "Y" if obj_matched else "N",
        "two_stage_obj_aggregate": "Y" if aggregate else "N",
        "two_stage_final_score": str(final_score),
        "selection_backend": "item_obj_first_v2",
        "two_stage_baseline_org_id": baseline_table[0],
        "two_stage_baseline_tbl_id": baseline_table[1],
        "two_stage_table_changed": "Y" if (
            clean(row.get("org_id")), clean(row.get("tbl_id"))
        ) != baseline_table else "N",
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--item-top-k", type=int, default=3)
    args = parser.parse_args()

    claim_rows = read_csv(args.claims)
    claims: dict[str, dict[str, str]] = {}
    for claim in claim_rows:
        for key in claim_lookup_keys(claim):
            claims[key] = claim
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(args.candidates):
        grouped[row_key(row)].append(row)

    output = []
    for key, candidates in grouped.items():
        claim = claims.get(key)
        if not claim:
            continue
        selected = select_two_stage(claim, candidates, item_top_k=args.item_top_k)
        if selected:
            output.append(selected)
    write_csv(args.output, output)
    print(f"claims={len(claim_rows)} selected={len(output)} output={args.output}")


if __name__ == "__main__":
    main()
