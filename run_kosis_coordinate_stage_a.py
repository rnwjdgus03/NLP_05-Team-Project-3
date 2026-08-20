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
    return score, signals


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
        enriched["postgres_metadata_complete"] = bool(row.get("metadata_complete"))
        metadata_score, metadata_signals = metadata_table_score(enriched, claim)
        enriched["metadata_score"] = metadata_score
        enriched["metadata_signals"] = metadata_signals
        completeness = "metadata_complete" if row.get("metadata_complete") else "metadata_incomplete"
        counts[completeness] += 1
        if requested and requested in periods:
            enriched["pre_rerank_period_state"] = "exact"
            counts["period_exact"] += 1
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
) -> dict[str, Any]:
    lexical_query = lexical_query_document(claim)
    semantic_query = semantic_query_document(claim)
    lookup = {table_key(row): row for row in tables}
    lexical_hits = lexical_index.search(lexical_query, lexical_top_k)
    dense_hits = semantic_runtime.search(semantic_query, top_k=dense_top_k)
    fused = fuse_hits(lexical_hits, dense_hits, lookup)
    pool = survey_family_rerank_pool(
        fused, lexical_hits, dense_hits,
        top_k=min(rerank_top_k, len(fused)),
        reserved_slots=rerank_family_slots,
        survey_group_limit=rerank_survey_groups,
    )
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
        ranked.append(row)
    ranked = apply_family_rerank(ranked, table_pool_top_k=table_pool_top_k)
    return {
        "schema_version": TABLE_POOL_SCHEMA,
        "claim_measurement_id": record["claim_measurement_id"],
        "claim_fingerprint": record["claim_fingerprint"],
        "claim": dict(record["claim"]),
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
