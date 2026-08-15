#!/usr/bin/env python3
"""Rerank retrieved KOSIS tables with official ITEM/OBJ metadata.

Vector/lexical retrieval still supplies the table Top-N pool.  This script
enriches only that small pool from SQLite and lets a cross encoder compare the
claim with the table's actual supported ITEMs and axes.  SQLite remains the
source of exact codes; the reranker only decides the table order.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Callable, Mapping

from kosis_meta_coordinates import claim_axis_value_mentions
from kosis_semantic_search import DEFAULT_RERANKER_MODEL, TransformerReranker
from kosis_sqlite_metadata import clean
from kosis_sqlite_resolver import MetadataStore, aggregate_value, item_candidates, lookup_keys
from rerank_mcp_gold_200_table_candidates import normalized_reranker_scores
from search_mcp_gold_200_chroma_bge import build_gold_free_table_query


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


def rank_value(row: Mapping[str, object]) -> int:
    try:
        return int(float(clean(row.get("candidate_rank"))))
    except ValueError:
        return 999


def rank_score(rank: int) -> float:
    return 0.0 if rank <= 0 or rank >= 999 else 1.0 / math.log2(rank + 1.0)


def metadata_document(
    claim: Mapping[str, str], candidate: Mapping[str, str], store: MetadataStore
) -> str:
    org_id, tbl_id = clean(candidate.get("org_id")), clean(candidate.get("tbl_id"))
    table = store.table(org_id, tbl_id) or {}
    items = store.items(org_id, tbl_id)
    axes = store.axes(org_id, tbl_id)
    periodicities = sorted(store.periodicities(org_id, tbl_id))
    ranked_items = item_candidates(claim, candidate, items, top_k=12) if items else []
    item_text = "; ".join(
        f"{clean(item.get('itm_name'))} [{clean(item.get('unit_name'))}]"
        for item, _, _, _ in ranked_items
    )
    axis_parts = []
    for axis in axes:
        axis_name = clean(axis.get("axis_name"))
        values = [dict(value) for value in axis.get("values", [])]
        mentioned = claim_axis_value_mentions(
            claim,
            axis_name,
            ({"name": value.get("obj_name"), "axis_name": axis_name} for value in values),
        )
        aggregate = aggregate_value(values)
        supported = list(mentioned)
        if aggregate:
            aggregate_name = clean(aggregate.get("obj_name"))
            if aggregate_name and aggregate_name not in supported:
                supported.append(aggregate_name)
        axis_parts.append(
            f"{axis_name}" + (f" (관련값: {', '.join(supported[:8])})" if supported else "")
        )
    original = clean(candidate.get("candidate_document"))
    parts = [
        f"통계표: {clean(table.get('tbl_name') or candidate.get('tbl_name'))}",
        f"분류경로: {clean(table.get('category_path') or candidate.get('category_path'))}",
        f"공식 항목: {item_text}",
        f"공식 분류축: {'; '.join(axis_parts)}",
        f"수록주기: {', '.join(periodicities)}" if periodicities else "수록주기: 미확인",
    ]
    if original:
        parts.append(f"기존 검색 문서: {original}")
    return " | ".join(part for part in parts if not part.endswith(": "))


def rerank_group(
    claim: dict[str, str],
    candidates: list[dict[str, str]],
    store: MetadataStore,
    score_documents: Callable[[str, list[str]], list[float]],
    *,
    metadata_weight: float,
) -> list[dict[str, object]]:
    ordered = sorted(candidates, key=rank_value)
    query = build_gold_free_table_query(claim)
    documents = [metadata_document(claim, row, store) for row in ordered]
    scores = score_documents(query, documents)
    if len(scores) != len(ordered):
        raise ValueError("reranker returned a different number of scores")
    calibrated = normalized_reranker_scores(scores)
    enriched = []
    for row, document, score, (logit, normalized_score) in zip(
        ordered, documents, scores, calibrated
    ):
        upstream_rank = rank_value(row)
        fusion = metadata_weight * normalized_score + (1.0 - metadata_weight) * rank_score(upstream_rank)
        enriched.append({
            **row,
            "upstream_candidate_rank": upstream_rank,
            "metadata_query_text": query,
            "metadata_candidate_document": document,
            "metadata_reranker_score": score,
            "metadata_reranker_logit": logit,
            "metadata_reranker_normalized": normalized_score,
            "metadata_fusion_score": fusion,
            "metadata_weight": metadata_weight,
        })
    enriched.sort(key=lambda row: (
        -float(row["metadata_fusion_score"]),
        int(row["upstream_candidate_rank"]),
        clean(row.get("tbl_id")),
    ))
    for index, row in enumerate(enriched, 1):
        row["candidate_rank"] = index
        row["retrieval_backend"] = clean(row.get("retrieval_backend")) + "+sqlite-metadata-reranker"
    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--table-candidates", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--metadata-weight", type=float, default=0.65)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not 0.0 <= args.metadata_weight <= 1.0:
        parser.error("--metadata-weight must be between 0 and 1")

    claims: dict[str, dict[str, str]] = {}
    for claim in read_csv(args.claims):
        for key in lookup_keys(claim):
            claims[key] = claim
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(args.table_candidates):
        key = clean(row.get("gold_id") or row.get("claim_measurement_id") or row.get("claim_id"))
        if key and rank_value(row) <= args.top_k:
            grouped[key].append(row)

    reranker = TransformerReranker(args.model, device=args.device, batch_size=args.batch_size)
    store = MetadataStore(args.metadata_db)
    output: list[dict[str, object]] = []
    try:
        groups = list(grouped.items())
        if args.limit > 0:
            groups = groups[: args.limit]
        for index, (key, candidates) in enumerate(groups, 1):
            claim = claims.get(key)
            if not claim:
                continue
            output.extend(rerank_group(
                claim, candidates, store, reranker.score,
                metadata_weight=args.metadata_weight,
            ))
            if index % 10 == 0:
                print(f"metadata_reranked={index}/{len(groups)}", flush=True)
    finally:
        store.close()
    write_csv(args.output, output)
    print(json.dumps({"claims": len(groups), "candidate_rows": len(output), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
