#!/usr/bin/env python3
"""Hybrid KOSIS table retrieval ending at a PostgreSQL-ready Top-3 handoff."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from kosis_semantic_search import (
    SemanticSearchRuntime,
    build_table_document,
    normalize_table_row,
)


TOKEN_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+)?|[A-Za-z]+|[가-힣]+")
RRF_K = 60
HANDOFF_SCHEMA_VERSION = "kosis-table-handoff-v1"
RETRIEVAL_AUDIT_SCHEMA_VERSION = "kosis-retrieval-audit-v1"
LEXICAL_CONTEXT_LIMIT = 240
SEMANTIC_CONTEXT_LIMIT = 320


def _text(value: Any) -> str:
    return str(value or "").strip()


def table_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return _text(row.get("org_id")), _text(row.get("tbl_id"))


def lexical_tokens(value: Any) -> tuple[str, ...]:
    """Tokenize Korean without a runtime morphology dependency.

    Full words preserve precision while Korean character bigrams recover common
    spacing and compound-word variations.  Numeric and Latin tokens remain exact.
    """
    normalized = _text(value).lower().replace("ㆍ", " ").replace("·", " ")
    output: list[str] = []
    for token in TOKEN_PATTERN.findall(normalized):
        output.append(f"w:{token}")
        if re.fullmatch(r"[가-힣]+", token) and len(token) >= 2:
            output.extend(
                f"g:{token[index:index + 2]}"
                for index in range(max(1, len(token) - 1))
            )
    return tuple(output)


def _clean_query_value(value: Any, *, limit: int | None = None) -> str:
    if isinstance(value, Mapping):
        value = " ".join(_text(item) for item in value.values() if _text(item))
    elif isinstance(value, (set, frozenset)):
        value = " ".join(sorted(_text(item) for item in value if _text(item)))
    elif isinstance(value, (list, tuple)):
        value = " ".join(_text(item) for item in value if _text(item))
    cleaned = re.sub(r"\s+", " ", _text(value)).strip()
    if cleaned in {"", "-"}:
        return ""
    return cleaned if limit is None else cleaned[:limit].rstrip()


def _first_query_value(claim: Mapping[str, Any], *fields: str) -> str:
    for field in fields:
        value = _clean_query_value(claim.get(field))
        if value:
            return value
    return ""


def _query_compact(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean_query_value(value)).lower()


def measurement_context_conflict(claim: Mapping[str, Any]) -> bool:
    """Detect when article-level labels would override a precise measurement.

    HCX emits both a claim-level indicator/domain and a measurement-level
    indicator.  In multi-metric sentences these can legitimately differ (for
    example, a labour-market article citing a birth count).  The precise
    measurement must drive table retrieval in that case.
    """
    measurement = _query_compact(claim.get("measurement_indicator"))
    if not measurement:
        return False
    claim_indicator = _query_compact(claim.get("claim_indicator"))
    if (
        claim_indicator
        and measurement != claim_indicator
        and measurement not in claim_indicator
        and claim_indicator not in measurement
    ):
        return True

    domain = _query_compact(claim.get("metric_domain"))
    if not domain:
        return False
    domain_markers = {
        "고용": ("고용", "취업", "실업", "근로", "임금", "종사자"),
        "인구": ("인구", "출생", "사망", "가구", "혼인", "이혼", "전입", "전출"),
        "무역": ("무역", "수출", "수입", "통관"),
        "물가": ("물가", "가격", "소비자", "생산자", "수입물가", "수출물가"),
        "농업": ("농업", "농가", "쌀", "벼", "재배", "경지", "농산물"),
    }
    markers = domain_markers.get(domain)
    if not markers:
        return False
    target = measurement + _query_compact(claim.get("measurement_item"))
    return not any(_query_compact(marker) in target for marker in markers)


def measurement_focused_retrieval_claim(claim: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a retrieval-only view with conflicting article labels removed."""
    if not measurement_context_conflict(claim):
        return claim
    focused = dict(claim)
    # Persist the decision.  ``retrieve_without_reranker`` passes this focused
    # view into the query builders; recomputing the conflict after replacing
    # claim_indicator/metric_domain would otherwise turn focus mode back off
    # and silently reintroduce the article title and prose.
    focused["_measurement_focused_retrieval"] = True
    focused["metric_domain"] = ""
    measurement_indicator = _clean_query_value(claim.get("measurement_indicator"))
    if measurement_indicator:
        focused["claim_indicator"] = measurement_indicator
        focused["indicator"] = measurement_indicator
    # These are article/claim-level context fields, not properties of the
    # individual measurement.  Coordinate fields (item, region, age, gender,
    # period and unit) remain available.
    for field in ("keywords", "title", "claim_text", "prev_sentence", "next_sentence"):
        focused[field] = ""
    return focused


def is_measurement_focused_retrieval(claim: Mapping[str, Any]) -> bool:
    return bool(claim.get("_measurement_focused_retrieval")) or measurement_context_conflict(claim)


def lexical_query_document(claim: Mapping[str, Any]) -> str:
    """Build a conservatively weighted BM25 query from structured claim fields.

    Indicator and domain are repeated once; every other field contributes at
    most once. The bounded claim sentence recovers details for partially
    structured inputs, while complete indicator/domain inputs leave prose to
    BGE-M3 and the reranker.
    """
    indicator = _first_query_value(claim, "measurement_indicator", "indicator")
    domain = _first_query_value(claim, "metric_domain")
    focused = is_measurement_focused_retrieval(claim)
    weighted = (
        [indicator, indicator, indicator, indicator]
        if focused else [indicator, indicator, domain, domain]
    )
    weighted.extend(
        _first_query_value(claim, *fields)
        for fields in (
            ("industry_or_item",),
            ("measurement_item",),
            ("survey_name", "source_survey"),
            ("statistics_name", "stat_name"),
            (() if focused else ("keywords",)),
            (() if focused else ("title",)),
            ("claim_domain_scope",),
            ("unit",),
            ("prd_se",),
            ("region",),
        )
    )
    # Free prose contributes many unrelated one-off BM25 terms. When both core
    # fields are available, the dense and reranker stages retain that context
    # while BM25 stays a precise structured-field retriever. Prose remains a
    # lexical fallback for partially structured inputs.
    if not focused and not (indicator and domain):
        weighted.append(_clean_query_value(
            claim.get("claim_text"), limit=LEXICAL_CONTEXT_LIMIT,
        ))
    return " ".join(value for value in weighted if value)


def semantic_query_document(claim: Mapping[str, Any]) -> str:
    """Build a general BGE query without validation-set-specific expansions."""
    focused = is_measurement_focused_retrieval(claim)
    fields = (
        ("통계영역", "" if focused else _first_query_value(claim, "metric_domain")),
        ("지표", _first_query_value(claim, "measurement_indicator", "indicator")),
        ("대상", _first_query_value(claim, "industry_or_item")),
        ("측정항목", _first_query_value(claim, "measurement_item")),
        ("조사명", _first_query_value(claim, "survey_name", "source_survey")),
        ("통계명", _first_query_value(claim, "statistics_name", "stat_name")),
        ("핵심어", "" if focused else _first_query_value(claim, "keywords")),
        ("기사제목", "" if focused else _first_query_value(claim, "title")),
        ("통계범위", _first_query_value(claim, "claim_domain_scope")),
        ("단위", _first_query_value(claim, "unit")),
        ("주기", _first_query_value(claim, "prd_se")),
        ("지역", _first_query_value(claim, "region")),
        ("문장", "" if focused else _clean_query_value(
            claim.get("claim_text"), limit=SEMANTIC_CONTEXT_LIMIT,
        )),
    )
    return " | ".join(
        f"{label}: {value}" for label, value in fields if value
    )


@dataclass(frozen=True)
class LexicalHit:
    org_id: str
    tbl_id: str
    score: float
    rank: int

    @property
    def key(self) -> tuple[str, str]:
        return self.org_id, self.tbl_id


class BM25TableIndex:
    """Small in-process BM25 index for the 107k-table KOSIS catalogue."""

    def __init__(self, table_rows: Sequence[Mapping[str, Any]], *, k1: float = 1.5,
                 b: float = 0.75) -> None:
        self.tables = [normalize_table_row(row) for row in table_rows]
        self.k1 = float(k1)
        self.b = float(b)
        self.lengths: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, row in enumerate(self.tables):
            counts = Counter(lexical_tokens(build_table_document(row)))
            self.lengths.append(sum(counts.values()))
            for token, frequency in counts.items():
                self.postings[token].append((index, frequency))
        self.average_length = (
            sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        )

    def search(self, query: str, top_k: int = 50) -> list[LexicalHit]:
        if top_k <= 0 or not self.tables:
            return []
        query_counts = Counter(lexical_tokens(query))
        scores: dict[int, float] = defaultdict(float)
        document_count = len(self.tables)
        average_length = max(self.average_length, 1.0)
        for token, query_frequency in query_counts.items():
            posting = self.postings.get(token, ())
            if not posting:
                continue
            document_frequency = len(posting)
            idf = math.log(1.0 + (document_count - document_frequency + 0.5)
                           / (document_frequency + 0.5))
            query_weight = 1.0 + math.log(query_frequency)
            for document_index, term_frequency in posting:
                length_ratio = self.lengths[document_index] / average_length
                denominator = term_frequency + self.k1 * (
                    1.0 - self.b + self.b * length_ratio
                )
                scores[document_index] += (
                    idf * query_weight * term_frequency * (self.k1 + 1.0) / denominator
                )
        ordered = sorted(
            scores.items(),
            key=lambda item: (-item[1], table_key(self.tables[item[0]])),
        )[: min(top_k, len(scores))]
        return [
            LexicalHit(
                org_id=self.tables[index]["org_id"],
                tbl_id=self.tables[index]["tbl_id"],
                score=float(score),
                rank=rank,
            )
            for rank, (index, score) in enumerate(ordered, 1)
        ]


def reciprocal_rank(rank: int | None, *, rrf_k: int = RRF_K) -> float:
    return 0.0 if rank is None else 1.0 / (rrf_k + rank)


def fuse_hits(
    lexical_hits: Sequence[Any],
    dense_hits: Sequence[Any],
    table_lookup: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    rrf_k: int = RRF_K,
) -> list[dict[str, Any]]:
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for backend, hits in (("lexical", lexical_hits), ("dense", dense_hits)):
        for hit in hits:
            key = hit.key
            if key not in table_lookup:
                continue
            item = evidence.setdefault(key, {
                "table": dict(table_lookup[key]),
                "lexical_rank": None,
                "lexical_score": None,
                "dense_rank": None,
                "dense_score": None,
            })
            item[f"{backend}_rank"] = int(hit.rank)
            item[f"{backend}_score"] = float(hit.score)
    fused = []
    for key, item in evidence.items():
        item["rrf_score"] = (
            reciprocal_rank(item["lexical_rank"], rrf_k=rrf_k)
            + reciprocal_rank(item["dense_rank"], rrf_k=rrf_k)
        )
        item["org_id"], item["tbl_id"] = key
        fused.append(item)
    return sorted(
        fused,
        key=lambda item: (
            -item["rrf_score"],
            item["lexical_rank"] or 10**9,
            item["dense_rank"] or 10**9,
            item["org_id"],
            item["tbl_id"],
        ),
    )


def rerank_top3(
    query: str,
    fused: Sequence[Mapping[str, Any]],
    rerank_scores: Sequence[float | None],
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    if len(fused) != len(rerank_scores):
        raise ValueError("reranker score count does not match fused candidates")
    ranked = []
    for source, score in zip(fused, rerank_scores):
        row = dict(source)
        numeric_score = None if score is None else float(score)
        if numeric_score is not None and not math.isfinite(numeric_score):
            raise ValueError(f"reranker returned a non-finite score: {numeric_score}")
        row["reranker_score"] = numeric_score
        ranked.append(row)
    ranked.sort(key=lambda row: (
        -(row["reranker_score"] if row["reranker_score"] is not None else -math.inf),
        -row["rrf_score"],
        row["org_id"],
        row["tbl_id"],
    ))
    selected = []
    seen: set[tuple[str, str]] = set()
    for row in ranked:
        key = row["org_id"], row["tbl_id"]
        if key in seen:
            continue
        seen.add(key)
        output = {**row, "rank": len(selected) + 1}
        selected.append(output)
        if len(selected) == top_k:
            break
    return selected


def diverse_rerank_pool(
    fused: Sequence[Mapping[str, Any]],
    lexical_hits: Sequence[LexicalHit],
    dense_hits: Sequence[Any],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Preserve strong candidates from both retrieval modalities for reranking."""
    if top_k <= 0:
        return []
    by_key = {
        (str(row["org_id"]), str(row["tbl_id"])): dict(row)
        for row in fused
    }
    quota = min(5, max(1, top_k // 4))
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def append_key(key: tuple[str, str]) -> None:
        row = by_key.get(key)
        if row is not None and key not in seen and len(selected) < top_k:
            seen.add(key)
            selected.append(row)

    for hit in lexical_hits[:quota]:
        append_key((str(hit.org_id), str(hit.tbl_id)))
    for hit in dense_hits[:quota]:
        append_key((str(hit.org_id), str(hit.tbl_id)))
    for row in fused:
        append_key((str(row["org_id"]), str(row["tbl_id"])))
    return selected


def exact_domain_scope_filter(
    candidates: Sequence[Mapping[str, Any]],
    claim: Mapping[str, Any],
    *,
    minimum_candidates: int,
) -> list[dict[str, Any]]:
    """Use an exact domain scope only when it preserves the requested depth."""
    domain = re.sub(
        r"[^0-9A-Za-z가-힣]", "",
        _first_query_value(claim, "metric_domain"),
    ).lower()
    rows = [dict(row) for row in candidates]
    if not domain:
        return rows
    # KOSIS category names and news-domain labels are not a shared ontology.
    # For example, employment claims live under ``경제활동인구조사`` and do not
    # literally contain ``고용``.  Alias-aware matching preserves the intended
    # domain gate without deleting the official table before reranking.
    aliases = {
        "고용": ("고용", "경제활동인구", "취업", "실업", "노동"),
        "산업활동": (
            "산업활동", "전산업생산", "광업제조업동향", "생산지수",
            "서비스업동향", "서비스업생산", "소매판매",
        ),
        "물가": ("물가", "소비자물가", "가격"),
        "인구": ("인구", "주민등록", "인구동향"),
        "무역": ("무역", "수출", "수입", "교역"),
    }
    domain_terms = tuple(
        re.sub(r"[^0-9A-Za-z가-힣]", "", value).lower()
        for value in aliases.get(domain, (domain,))
    )
    matched = []
    for row in rows:
        table = row.get("table") or {}
        table_scope = re.sub(
            r"[^0-9A-Za-z가-힣]", "",
            f"{_text(table.get('tbl_name'))} {_text(table.get('category_path'))}",
        ).lower()
        if any(term and term in table_scope for term in domain_terms):
            matched.append(row)
    return matched if len(matched) >= minimum_candidates else rows


class HybridTop3Retriever:
    def __init__(
        self,
        table_rows: Sequence[Mapping[str, Any]],
        semantic_runtime: Any,
        *,
        lexical_index: BM25TableIndex | None = None,
        lexical_top_k: int = 50,
        dense_top_k: int = 50,
        rerank_top_k: int = 50,
        final_top_k: int = 3,
    ) -> None:
        self.tables = [normalize_table_row(row) for row in table_rows]
        self.table_lookup = {table_key(row): row for row in self.tables}
        self.lexical_index = lexical_index or BM25TableIndex(self.tables)
        self.semantic_runtime = semantic_runtime
        self.lexical_top_k = lexical_top_k
        self.dense_top_k = dense_top_k
        self.rerank_top_k = rerank_top_k
        self.final_top_k = final_top_k
        if min(lexical_top_k, dense_top_k, rerank_top_k, final_top_k) <= 0:
            raise ValueError("all Top-K values must be positive")
        if final_top_k > 3:
            raise ValueError("final_top_k must not exceed the MCP Top-3 contract")
        if final_top_k > rerank_top_k:
            raise ValueError("final_top_k must not exceed rerank_top_k")

    def _retrieve_reranked(
        self, claim: Mapping[str, Any], *, top_k: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if top_k > 50:
            raise ValueError("reranked table pool must not exceed 50 candidates")
        if top_k > self.rerank_top_k:
            raise ValueError("top_k must not exceed configured rerank_top_k")
        lexical_query = lexical_query_document(claim)
        reranker_query = semantic_query_document(claim)
        if not lexical_query and not reranker_query:
            return [], {
                "bm25": [], "bge": [], "rrf": [], "rrf_reranker": [],
            }
        lexical_hits = self.lexical_index.search(lexical_query, self.lexical_top_k)
        dense_hits = self.semantic_runtime.search(
            reranker_query, top_k=self.dense_top_k,
        )
        fused = fuse_hits(lexical_hits, dense_hits, self.table_lookup)
        rerank_pool = diverse_rerank_pool(
            fused,
            lexical_hits,
            dense_hits,
            top_k=min(self.rerank_top_k, len(fused)),
        )
        rerank_pool = exact_domain_scope_filter(
            rerank_pool,
            claim,
            minimum_candidates=top_k,
        )
        scores = self.semantic_runtime.rerank(
            reranker_query,
            [row["table"] for row in rerank_pool],
        )
        final = rerank_top3(
            reranker_query, rerank_pool, scores, top_k=top_k,
        )
        trace = {
            "bm25": [
                {
                    "org_id": hit.org_id, "tbl_id": hit.tbl_id,
                    "rank": hit.rank, "score": hit.score,
                }
                for hit in lexical_hits
            ],
            "bge": [
                {
                    "org_id": hit.org_id, "tbl_id": hit.tbl_id,
                    "rank": hit.rank, "score": hit.score,
                }
                for hit in dense_hits
            ],
            "rrf": [
                {
                    "org_id": row["org_id"], "tbl_id": row["tbl_id"],
                    "rank": rank, "score": row["rrf_score"],
                }
                for rank, row in enumerate(rerank_pool, 1)
            ],
            "rrf_reranker": [
                {
                    "org_id": row["org_id"], "tbl_id": row["tbl_id"],
                    "rank": row["rank"], "score": row["reranker_score"],
                }
                for row in final
            ],
        }
        return final, trace

    def retrieve_reranked_pool_with_trace(
        self, claim: Mapping[str, Any], *, top_k: int = 50,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """Return an auditable table pool for downstream coordinate search.

        This is deliberately separate from the externally established Top-3
        handoff.  It uses the same BM25, BGE-M3, RRF, domain-scope, and
        reranker path while allowing coordinate generation to inspect up to 50
        reranked tables.
        """
        return self._retrieve_reranked(claim, top_k=top_k)

    def retrieve_reranked_pool(
        self, claim: Mapping[str, Any], *, top_k: int = 50,
    ) -> list[dict[str, Any]]:
        candidates, _trace = self.retrieve_reranked_pool_with_trace(
            claim, top_k=top_k,
        )
        return candidates

    def retrieve_with_trace(
        self, claim: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        return self._retrieve_reranked(claim, top_k=self.final_top_k)

    def retrieve(self, claim: Mapping[str, Any]) -> list[dict[str, Any]]:
        candidates, _trace = self.retrieve_with_trace(claim)
        return candidates


def build_retrieval_audit(
    claim: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    hydrated_candidates: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(hydrated_candidates if hydrated_candidates is not None else candidates)
    return {
        "schema_version": RETRIEVAL_AUDIT_SCHEMA_VERSION,
        "pipeline_stage": "hybrid-table-retrieval",
        "claim_measurement_id": _text(
            claim.get("claim_measurement_id") or claim.get("claim_id")
        ),
        "query": {
            key: _text(claim.get(key))
            for key in (
                "claim_text", "indicator", "industry_or_item", "period",
                "prd_se", "value", "unit", "region",
            )
            if _text(claim.get(key))
        },
        "table_candidates": rows,
        "retrieval": {
            "lexical_backend": "bm25-korean-bigram-v1",
            "embedding_model": "BAAI/bge-m3",
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "top_k": len(rows),
        },
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--semantic-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--dense-top-k", type=int, default=50)
    parser.add_argument("--rerank-top-k", type=int, default=50)
    parser.add_argument("--final-top-k", type=int, default=3)
    parser.add_argument(
        "--trace-output", type=Path,
        help="optional JSONL containing BM25/BGE/RRF/reranker ablations",
    )
    args = parser.parse_args()
    if min(args.lexical_top_k, args.dense_top_k, args.rerank_top_k,
           args.final_top_k) <= 0:
        parser.error("all Top-K values must be positive")

    tables = read_csv(args.semantic_index / "tables.csv")
    runtime = SemanticSearchRuntime(
        args.semantic_index,
        device=args.device,
        reranker_batch_size=32,
    )
    retriever = HybridTop3Retriever(
        tables,
        runtime,
        lexical_top_k=args.lexical_top_k,
        dense_top_k=args.dense_top_k,
        rerank_top_k=args.rerank_top_k,
        final_top_k=args.final_top_k,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.trace_output:
        args.trace_output.parent.mkdir(parents=True, exist_ok=True)
    trace_context = (
        args.trace_output.open("w", encoding="utf-8")
        if args.trace_output else nullcontext(None)
    )
    with args.output.open("w", encoding="utf-8") as handle, trace_context as trace_handle:
        for claim in read_csv(args.claims):
            candidates, trace = retriever.retrieve_with_trace(claim)
            handle.write(json.dumps(build_retrieval_audit(claim, candidates), ensure_ascii=False))
            handle.write("\n")
            if trace_handle is not None:
                query_id = _text(
                    claim.get("claim_measurement_id") or claim.get("claim_id")
                )
                for ablation, rows in trace.items():
                    trace_handle.write(json.dumps({
                        "claim_measurement_id": query_id,
                        "ablation": ablation,
                        "depth_limit": {
                            "bm25": args.lexical_top_k,
                            "bge": args.dense_top_k,
                            "rrf": args.rerank_top_k,
                            "rrf_reranker": args.final_top_k,
                        }[ablation],
                        "table_candidates": rows,
                    }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
