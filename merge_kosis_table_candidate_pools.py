#!/usr/bin/env python3
"""Union dense/reranked and structured KOSIS table candidate pools.

The vector pool handles paraphrases.  The SQLite/PostgreSQL catalog pool
recovers official tables through survey names, periods and visible axes.  This
module only builds a candidate union; ITEM/OBJ selection remains downstream.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Mapping

from kosis_sqlite_metadata import clean
from kosis_sqlite_resolver import lookup_keys


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
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def integer(value: object, default: int = 999) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return default


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(clean(value))
    except ValueError:
        return default


def claim_key(row: Mapping[str, object]) -> str:
    return clean(row.get("gold_id") or row.get("claim_measurement_id") or row.get("claim_id"))


def vector_score(row: Mapping[str, object], rank: int, pool_size: int) -> float:
    for field in ("metadata_fusion_score", "structural_fusion_score", "fusion_score"):
        score = number(row.get(field), -1.0)
        if 0.0 <= score <= 1.5:
            return min(score, 1.0)
    return max(0.0, 1.0 - (rank - 1) / max(1, pool_size))


def catalog_score(row: Mapping[str, object], rank: int, pool_size: int) -> float:
    boost = max(0.0, number(row.get("catalog_exact_boost")))
    rank_component = max(0.0, 1.0 - (rank - 1) / max(1, pool_size - 1))
    # Catalog-only retrieval must be able to enter the pool, but a weak lexical
    # hit must not erase a strong dense result.
    return min(1.0, 0.40 + boost / 20.0 + 0.25 * rank_component)


def candidate_base(claim: Mapping[str, str]) -> dict[str, object]:
    return {
        **claim,
        "claim_id": clean(claim.get("claim_id")),
        "claim_measurement_id": clean(claim.get("claim_measurement_id")),
        "indicator": clean(claim.get("indicator") or claim.get("measurement_indicator")),
        "industry_or_item": clean(claim.get("industry_or_item") or claim.get("measurement_item")),
        "period": clean(claim.get("period") or claim.get("measurement_period")),
        "prd_se": clean(claim.get("measurement_prd_se") or claim.get("prd_se")),
    }


def merge_pools(
    claims: list[dict[str, str]],
    vector_rows: list[dict[str, str]],
    catalog_rows: list[dict[str, str]],
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    aliases: dict[str, str] = {}
    claim_by_key: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for claim in claims:
        canonical = claim_key(claim)
        if not canonical:
            continue
        order.append(canonical)
        claim_by_key[canonical] = claim
        for key in lookup_keys(claim):
            aliases[key] = canonical

    grouped_vector: dict[str, list[dict[str, str]]] = defaultdict(list)
    grouped_catalog: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row, grouped in ((row, grouped_vector) for row in vector_rows):
        canonical = aliases.get(claim_key(row))
        if canonical:
            grouped[canonical].append(row)
    for row, grouped in ((row, grouped_catalog) for row in catalog_rows):
        canonical = aliases.get(claim_key(row))
        if canonical:
            grouped[canonical].append(row)

    output: list[dict[str, object]] = []
    for key in order:
        vectors = sorted(grouped_vector[key], key=lambda row: integer(row.get("candidate_rank")))
        catalogs = sorted(grouped_catalog[key], key=lambda row: integer(row.get("candidate_rank")))
        merged: dict[tuple[str, str], dict[str, object]] = {}
        for source, rows in (("vector", vectors), ("catalog", catalogs)):
            for fallback_rank, row in enumerate(rows, 1):
                table_key = (clean(row.get("org_id")), clean(row.get("tbl_id")))
                if not all(table_key):
                    continue
                rank = integer(row.get("candidate_rank"), fallback_rank)
                entry = merged.setdefault(table_key, {
                    **candidate_base(claim_by_key[key]),
                    "org_id": table_key[0], "tbl_id": table_key[1],
                })
                if source == "vector":
                    # Preserve rich reranker fields when both backends agree.
                    entry.update(row)
                    entry["vector_rank"] = rank
                    entry["vector_pool_score"] = vector_score(row, rank, max(1, len(vectors)))
                else:
                    for field, value in row.items():
                        if field not in entry or not clean(entry.get(field)):
                            entry[field] = value
                    entry["catalog_rank"] = rank
                    entry["catalog_pool_score"] = catalog_score(row, rank, max(1, len(catalogs)))

        rescored: list[dict[str, object]] = []
        for entry in merged.values():
            dense = number(entry.get("vector_pool_score"))
            catalog = number(entry.get("catalog_pool_score"))
            agreement = 0.05 if dense and catalog else 0.0
            hybrid = min(1.05, max(dense, catalog) + agreement)
            entry.update({
                "pre_hybrid_candidate_rank": entry.get("candidate_rank", ""),
                "hybrid_table_score": hybrid,
                "hybrid_agreement": "Y" if agreement else "N",
                "fusion_score": hybrid,
                "retrieval_backend": "bge-reranker+structured-catalog-union-v1",
            })
            rescored.append(entry)
        rescored.sort(key=lambda row: (
            -number(row.get("hybrid_table_score")),
            integer(row.get("catalog_rank")), integer(row.get("vector_rank")),
            clean(row.get("tbl_id")),
        ))
        for rank, row in enumerate(rescored[:limit], 1):
            row["candidate_rank"] = rank
            output.append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--vector-candidates", type=Path, required=True)
    parser.add_argument("--catalog-candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=50)
    args = parser.parse_args()
    rows = merge_pools(
        read_csv(args.claims), read_csv(args.vector_candidates),
        read_csv(args.catalog_candidates), limit=args.top_k,
    )
    write_csv(args.output, rows)
    print(f"claims={len(read_csv(args.claims))} candidates={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
