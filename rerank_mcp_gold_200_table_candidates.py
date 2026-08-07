#!/usr/bin/env python3
"""Lexical-first BGE reranking for KOSIS table candidates.

Retrieval is intentionally gold-free.  Lexical candidates form the primary
pool because the KOSIS table catalog is dominated by short, near-duplicate
titles where dense retrieval alone performed poorly.  Chroma/BGE dense hits
are retained as an auditable secondary signal, and a BGE cross-encoder reranks
the lexical pool.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Mapping

from kosis_semantic_search import DEFAULT_RERANKER_MODEL, TransformerReranker, build_table_document
from search_mcp_gold_200_chroma_bge import build_gold_free_table_query


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def claim_key(row: Mapping[str, str]) -> str:
    return str(row.get("gold_id") or row.get("claim_id") or "").strip()


def table_key(row: Mapping[str, str]) -> tuple[str, str]:
    return str(row.get("org_id", "")).strip(), str(row.get("tbl_id", "")).strip()


def rank_score(rank: int | None) -> float:
    return 0.0 if not rank else 1.0 / math.log2(rank + 1.0)


def normalized_reranker_scores(scores: Iterable[float]) -> list[tuple[float, float]]:
    """Convert sigmoid probabilities to query-local normalized logits."""

    logits = []
    for score in scores:
        probability = min(max(float(score), 1e-6), 1.0 - 1e-6)
        logits.append(math.log(probability / (1.0 - probability)))
    if not logits:
        return []
    low, high = min(logits), max(logits)
    normalized = (
        [0.5] * len(logits)
        if high - low < 1e-12
        else [(value - low) / (high - low) for value in logits]
    )
    return list(zip(logits, normalized))


def candidate_document(row: Mapping[str, str]) -> str:
    existing = str(row.get("candidate_document", "") or "").strip()
    return existing or build_table_document(row)


def _rank(row: Mapping[str, str]) -> int:
    try:
        return int(float(str(row.get("candidate_rank", "") or "0")))
    except ValueError:
        return 0


def _float(row: Mapping[str, str], key: str) -> float:
    try:
        return float(str(row.get(key, "") or "0"))
    except ValueError:
        return 0.0


def merge_candidate_pool(
    lexical_rows: Iterable[dict[str, str]],
    dense_rows: Iterable[dict[str, str]],
    *,
    lexical_top_k: int,
    dense_top_k: int,
) -> dict[str, list[dict[str, object]]]:
    merged: dict[str, dict[tuple[str, str], dict[str, object]]] = defaultdict(dict)
    for source, rows, limit in (
        ("lexical", lexical_rows, lexical_top_k),
        ("dense", dense_rows, dense_top_k),
    ):
        for row in rows:
            query = claim_key(row)
            key = table_key(row)
            rank = _rank(row)
            if not query or not all(key) or rank <= 0 or rank > limit:
                continue
            current = merged[query].setdefault(
                key,
                {
                    **row,
                    "lexical_rank": None,
                    "dense_rank": None,
                    "lexical_score": 0.0,
                    "semantic_score": 0.0,
                },
            )
            # Prefer the richer non-empty values when the same table is found
            # by both retrievers.
            for field, value in row.items():
                if value and not current.get(field):
                    current[field] = value
            if source == "lexical":
                current["lexical_rank"] = rank
                current["lexical_score"] = _float(row, "candidate_score")
                current["candidate_hits"] = row.get("candidate_hits", "")
            else:
                current["dense_rank"] = rank
                current["semantic_score"] = _float(row, "semantic_score")
                if row.get("candidate_document"):
                    current["candidate_document"] = row["candidate_document"]
    return {query: list(rows.values()) for query, rows in merged.items()}


def rerank_claim_candidates(
    claim: dict[str, str],
    candidates: list[dict[str, object]],
    score_documents: Callable[[str, list[str]], list[float]],
    *,
    final_top_k: int,
) -> list[dict[str, object]]:
    query = build_gold_free_table_query(claim)
    documents = [candidate_document(row) for row in candidates]
    scores = score_documents(query, documents) if documents else []
    if len(scores) != len(candidates):
        raise ValueError("reranker returned a different number of scores")

    calibrated = normalized_reranker_scores(scores)
    for row, document, reranker_score, (reranker_logit, reranker_normalized) in zip(
        candidates, documents, scores, calibrated
    ):
        lexical_rank = row.get("lexical_rank")
        dense_rank = row.get("dense_rank")
        # Lexical candidates are the guarded primary pool. Dense-only tables
        # remain in the audit output only when fewer lexical candidates exist.
        lexical_guard = 1 if lexical_rank else 0
        fusion = (
            0.20 * reranker_normalized
            + 0.75 * rank_score(int(lexical_rank) if lexical_rank else None)
            + 0.05 * rank_score(int(dense_rank) if dense_rank else None)
        )
        row.update(
            {
                "query_text": query,
                "candidate_document": document,
                "reranker_score": float(reranker_score),
                "reranker_logit": reranker_logit,
                "reranker_normalized": reranker_normalized,
                "fusion_score": fusion,
                "lexical_guard": lexical_guard,
            }
        )

    ranked = sorted(
        candidates,
        key=lambda row: (
            -int(row["lexical_guard"]),
            -float(row["fusion_score"]),
            int(row.get("lexical_rank") or 10**9),
            str(row.get("tbl_id", "")),
        ),
    )[:final_top_k]
    output = []
    for rank, row in enumerate(ranked, 1):
        output.append(
            {
                "gold_id": claim.get("gold_id", ""),
                "claim_id": claim.get("claim_id", ""),
                "article_id": claim.get("article_id", ""),
                "title": claim.get("title", ""),
                "claim_text": claim.get("claim_text", ""),
                "claim_type": claim.get("claim_type", ""),
                "claim_value": claim.get("claim_value", ""),
                "claim_unit": claim.get("claim_unit", ""),
                "input_quality_status": claim.get("input_quality_status", ""),
                "input_quality_reason": claim.get("input_quality_reason", ""),
                "candidate_rank": rank,
                "org_id": row.get("org_id", ""),
                "tbl_id": row.get("tbl_id", ""),
                "tbl_name": row.get("tbl_name", ""),
                "stat_id": row.get("stat_id", ""),
                "category_path": row.get("category_path", ""),
                "lexical_rank": row.get("lexical_rank") or "",
                "dense_rank": row.get("dense_rank") or "",
                "lexical_score": row.get("lexical_score", 0.0),
                "semantic_score": row.get("semantic_score", 0.0),
                "reranker_score": row.get("reranker_score", 0.0),
                "reranker_logit": row.get("reranker_logit", 0.0),
                "reranker_normalized": row.get("reranker_normalized", 0.0),
                "fusion_score": row.get("fusion_score", 0.0),
                "candidate_hits": row.get("candidate_hits", ""),
                "query_text": row.get("query_text", ""),
                "candidate_document": row.get("candidate_document", ""),
                "retrieval_backend": "lexical-first+bge-reranker+chroma-audit",
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--lexical-candidates", type=Path, required=True)
    parser.add_argument("--dense-candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--dense-top-k", type=int, default=20)
    parser.add_argument("--final-top-k", type=int, default=20)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    claims = read_csv(args.claims)
    forbidden = (
        {
            field
            for field in claims[0]
            if field.lower().startswith("gold_") and field.lower() != "gold_id"
        }
        if claims
        else set()
    )
    if forbidden:
        raise SystemExit("retrieval input contains forbidden gold fields: " + ", ".join(sorted(forbidden)))
    pools = merge_candidate_pool(
        read_csv(args.lexical_candidates),
        read_csv(args.dense_candidates),
        lexical_top_k=args.lexical_top_k,
        dense_top_k=args.dense_top_k,
    )
    reranker = TransformerReranker(
        args.reranker_model,
        device=args.device,
        batch_size=args.batch_size,
    )
    rows: list[dict[str, object]] = []
    for index, claim in enumerate(claims, 1):
        rows.extend(
            rerank_claim_candidates(
                claim,
                pools.get(claim_key(claim), []),
                reranker.score,
                final_top_k=args.final_top_k,
            )
        )
        if index % 10 == 0:
            print(f"reranked_claims={index}/{len(claims)}", flush=True)
    write_csv(args.output, rows)
    print(f"claims={len(claims)} candidates={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
