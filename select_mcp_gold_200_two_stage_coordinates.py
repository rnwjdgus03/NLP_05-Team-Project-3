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
    terms = [indicator] if indicator else []
    semantic = clean(claim.get("semantic_type") or claim.get("claim_type")).upper()
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
        return tuple(term for term in raw.split("|") if term)
    return tuple(
        term
        for term in (
            clean(claim.get("destination_country")), clean(claim.get("origin_country")),
            clean(claim.get("region")), clean(claim.get("age_group")), clean(claim.get("gender")),
            clean(claim.get("industry_or_item") or claim.get("measurement_item")),
        )
        if term
    )


def obj_match_score(claim: Mapping[str, str], candidate: Mapping[str, str]) -> tuple[float, bool, bool]:
    targets = obj_target_terms(claim)
    selected = normalized(" ".join(obj_names(candidate)))
    matched = bool(targets) and all(normalized(term) in selected for term in targets)
    aggregate = is_aggregate_candidate(candidate)
    if targets:
        score = 160.0 if matched else 0.0
    else:
        score = 100.0 if aggregate else 0.0
    score += 5.0 / math.log2(rank_value(candidate, "candidate_rank") + 1.0)
    return score, matched, aggregate


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
    # The upstream table/coordinate search already decides which table wins.
    # Keep that decision fixed so ITEM/OBJ decomposition cannot silently turn
    # a correct table into a wrong one.
    candidates = [
        row for row in candidates
        if (clean(row.get("org_id")), clean(row.get("tbl_id"))) == baseline_table
    ]
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
            obj_score, obj_matched, aggregate = obj_match_score(claim, row)
            final_score = item_score + obj_score
            finalists.append(
                (final_score, -rank_value(row, "candidate_rank"), item_rank, item_score,
                 item_matched, obj_score, obj_matched, aggregate, row)
            )
    if not finalists:
        return None
    selected = max(finalists, key=lambda value: value[:2])
    _, _, item_rank, item_score, item_matched, obj_score, obj_matched, aggregate, row = selected
    return {
        **row,
        "candidate_rank": "1",
        "original_candidate_rank": clean(row.get("candidate_rank")),
        "two_stage_item_rank": str(item_rank),
        "two_stage_item_score": str(item_score),
        "two_stage_item_matched_terms": item_matched,
        "two_stage_obj_score": str(obj_score),
        "two_stage_obj_target_terms": "|".join(obj_target_terms(claim)),
        "two_stage_obj_matched": "Y" if obj_matched else "N",
        "two_stage_obj_aggregate": "Y" if aggregate else "N",
        "two_stage_final_score": str(selected[0]),
        "selection_backend": "item_then_obj_v1",
        "two_stage_preserved_org_id": baseline_table[0],
        "two_stage_preserved_tbl_id": baseline_table[1],
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
