#!/usr/bin/env python3
"""Retrieve KOSIS table hints before HCX measurement structuring.

This path intentionally does not require ``mapping_eligible=Y``. It reads
claim-level rows, searches the semantic table index with article context, and
writes both auditable Top-K candidates and a compact context file for
``extract_hcx.py --retrieval-context``.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from kosis_semantic_search import (
    DEFAULT_RERANKER_MODEL,
    SemanticSearchRuntime,
    build_early_claim_query,
)


CANDIDATE_FIELDS = [
    "claim_id",
    "candidate_rank",
    "dense_rank",
    "org_id",
    "tbl_id",
    "tbl_name",
    "stat_id",
    "category_path",
    "semantic_score",
    "reranker_score",
    "meta_items_units",
]

CONTEXT_FIELDS = [
    "claim_id",
    "retrieval_context",
    "early_candidate_count",
    "early_context_count",
    "early_embedding_model",
    "early_reranker_model",
]


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_true_claim(row):
    if "is_claim" not in row:
        return True
    return str(row.get("is_claim", "")).strip().lower() in {"true", "y", "yes", "1"}


def table_key(row):
    return str(row.get("org_id", "")), str(row.get("tbl_id", ""))


def load_meta_hints(path, per_table_limit=8):
    hints = defaultdict(list)
    if not path:
        return hints
    meta_path = Path(path)
    if not meta_path.exists():
        raise FileNotFoundError(f"meta index not found: {meta_path}")
    seen = defaultdict(set)
    for row in read_csv(meta_path):
        key = table_key(row)
        if not all(key):
            continue
        name = str(row.get("code_name") or row.get("ITM_NM") or "").strip()
        unit = str(row.get("unit_name") or row.get("UNIT_NM") or "").strip()
        is_item = str(row.get("is_item", "")).strip().upper()
        if not name or is_item not in {"Y", "TRUE", "1"}:
            continue
        label = f"{name} [{unit}]" if unit else name
        if label in seen[key] or len(hints[key]) >= per_table_limit:
            continue
        seen[key].add(label)
        hints[key].append(label)
    return hints


def rerank_hits(runtime, query, hits, rerank_top_k):
    table_by_key = {
        (row["org_id"], row["tbl_id"]): row
        for row in runtime.index.tables
    }
    entries = []
    for hit in hits:
        row = table_by_key.get(hit.key)
        if row:
            entries.append({"hit": hit, "table": row, "reranker_score": None})

    count = min(max(rerank_top_k, 0), len(entries))
    if count:
        scores = runtime.rerank(query, [item["table"] for item in entries[:count]])
        for item, score in zip(entries[:count], scores):
            item["reranker_score"] = score

    if any(item["reranker_score"] is not None for item in entries):
        entries.sort(
            key=lambda item: (
                item["reranker_score"] is None,
                -(item["reranker_score"] or 0.0),
                -item["hit"].score,
            )
        )
    return entries


def candidate_rows(claim_id, entries, meta_hints):
    rows = []
    for rank, item in enumerate(entries, 1):
        hit = item["hit"]
        table = item["table"]
        rows.append(
            {
                "claim_id": claim_id,
                "candidate_rank": rank,
                "dense_rank": hit.rank,
                "org_id": hit.org_id,
                "tbl_id": hit.tbl_id,
                "tbl_name": table.get("tbl_name", ""),
                "stat_id": table.get("stat_id", ""),
                "category_path": table.get("category_path", ""),
                "semantic_score": f"{hit.score:.8f}",
                "reranker_score": (
                    f"{item['reranker_score']:.8f}"
                    if item["reranker_score"] is not None
                    else ""
                ),
                "meta_items_units": " | ".join(meta_hints.get(hit.key, [])),
            }
        )
    return rows


def context_payload(rows, context_top_k):
    candidates = []
    for row in rows[:context_top_k]:
        candidate = {
            "rank": int(row["candidate_rank"]),
            "org_id": row["org_id"],
            "tbl_id": row["tbl_id"],
            "table_name": row["tbl_name"],
            "category": row["category_path"],
        }
        if row.get("meta_items_units"):
            candidate["items_and_units"] = row["meta_items_units"].split(" | ")
        candidates.append(candidate)
    return json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))


def load_resumable_outputs(candidate_path, context_path, overwrite):
    if overwrite:
        return [], [], set()
    candidates = read_csv(candidate_path) if candidate_path.exists() else []
    contexts = read_csv(context_path) if context_path.exists() else []
    candidate_ids = {row.get("claim_id", "") for row in candidates}
    context_ids = {row.get("claim_id", "") for row in contexts}
    done = (candidate_ids & context_ids) - {""}
    return (
        [row for row in candidates if row.get("claim_id") in done],
        [row for row in contexts if row.get("claim_id") in done],
        done,
    )


def write_rows(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def enrich_reused_candidates(
    source_path,
    candidate_path,
    context_path,
    meta_hints,
    context_top_k,
):
    candidates = read_csv(source_path)
    existing_contexts = {
        row.get("claim_id", ""): row
        for row in (read_csv(context_path) if context_path.exists() else [])
    }
    grouped = defaultdict(list)
    claim_order = []
    for row in candidates:
        claim_id = row.get("claim_id", "")
        if claim_id not in grouped:
            claim_order.append(claim_id)
        row["meta_items_units"] = " | ".join(
            meta_hints.get(table_key(row), [])
        )
        grouped[claim_id].append(row)

    contexts = []
    for claim_id in claim_order:
        rows = sorted(
            grouped[claim_id],
            key=lambda row: int(row.get("candidate_rank") or 10**9),
        )
        previous = existing_contexts.get(claim_id, {})
        contexts.append(
            {
                "claim_id": claim_id,
                "retrieval_context": context_payload(rows, context_top_k),
                "early_candidate_count": len(rows),
                "early_context_count": min(len(rows), context_top_k),
                "early_embedding_model": previous.get("early_embedding_model", ""),
                "early_reranker_model": previous.get("early_reranker_model", ""),
            }
        )
    write_rows(candidate_path, candidates, CANDIDATE_FIELDS)
    write_rows(context_path, contexts, CONTEXT_FIELDS)
    return len(contexts), len(candidates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--output-candidates", required=True)
    parser.add_argument("--output-context", required=True)
    parser.add_argument(
        "--reuse-candidates",
        default="",
        help="enrich an existing candidate CSV with --meta-index without rerunning BGE",
    )
    parser.add_argument("--semantic-index", default="data/indexes/kosis_bge_m3")
    parser.add_argument("--semantic-top-k", type=int, default=20)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--context-top-k", type=int, default=5)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--meta-index", default="")
    parser.add_argument("--device", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.semantic_top_k <= 0:
        raise SystemExit("--semantic-top-k must be positive")
    if not 0 < args.context_top_k <= args.semantic_top_k:
        raise SystemExit("--context-top-k must be between 1 and --semantic-top-k")
    if args.checkpoint_every <= 0:
        raise SystemExit("--checkpoint-every must be positive")

    candidate_path = Path(args.output_candidates)
    context_path = Path(args.output_context)
    meta_hints = load_meta_hints(args.meta_index)
    if args.reuse_candidates:
        claim_count, candidate_count = enrich_reused_candidates(
            Path(args.reuse_candidates),
            candidate_path,
            context_path,
            meta_hints,
            args.context_top_k,
        )
        print(
            f"enriched_claims={claim_count} candidates={candidate_count} "
            f"context={context_path}"
        )
        return
    if not args.input:
        raise SystemExit("--input is required unless --reuse-candidates is used")

    claims = [row for row in read_csv(args.input) if is_true_claim(row)]
    candidates, contexts, done = load_resumable_outputs(
        candidate_path, context_path, args.overwrite
    )
    if done:
        print(f"resume={len(done)} completed claims")

    runtime = SemanticSearchRuntime(
        args.semantic_index,
        reranker_model=args.reranker_model,
        use_reranker=not args.no_reranker,
        device=args.device or None,
    )
    embedding_model = runtime.index.manifest.get("embedding_model", "")
    reranker_model = "" if args.no_reranker else args.reranker_model

    processed = 0
    for claim in claims:
        claim_id = str(claim.get("claim_id", "")).strip()
        if not claim_id or claim_id in done:
            continue
        if args.limit and processed >= args.limit:
            break

        query = build_early_claim_query(claim)
        if not query:
            print(f"[{claim_id}] skipped: empty query")
            continue
        hits = runtime.search(query, top_k=args.semantic_top_k)
        entries = rerank_hits(runtime, query, hits, args.rerank_top_k)
        rows = candidate_rows(claim_id, entries, meta_hints)
        candidates.extend(rows)
        contexts.append(
            {
                "claim_id": claim_id,
                "retrieval_context": context_payload(rows, args.context_top_k),
                "early_candidate_count": len(rows),
                "early_context_count": min(len(rows), args.context_top_k),
                "early_embedding_model": embedding_model,
                "early_reranker_model": reranker_model,
            }
        )
        done.add(claim_id)
        processed += 1
        if processed % args.checkpoint_every == 0:
            write_rows(candidate_path, candidates, CANDIDATE_FIELDS)
            write_rows(context_path, contexts, CONTEXT_FIELDS)
        print(f"[{claim_id}] candidates={len(rows)} context={min(len(rows), args.context_top_k)}")

    write_rows(candidate_path, candidates, CANDIDATE_FIELDS)
    write_rows(context_path, contexts, CONTEXT_FIELDS)
    print(
        f"completed={len(done)} new={processed} "
        f"candidates={candidate_path} context={context_path}"
    )


if __name__ == "__main__":
    main()
