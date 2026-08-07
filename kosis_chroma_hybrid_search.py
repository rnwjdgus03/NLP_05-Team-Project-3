#!/usr/bin/env python3
"""ChromaDB dense + lexical 하이브리드 좌표 검색 → BGE reranker → API 검증 입력 생성.

파이프라인 위치: 1차 READY 이후, kosis_validate_mapping_candidates.py 이전.

순서(요청 사양 그대로):
  1) 상류 통계표 검색으로 얻은 TBL_ID Top-K 로 후보 범위를 제한
  2) Chroma metadata hard filter (tbl_id / prd_se / unit_dimension) 를 **검색 전에** 적용
  3) BGE-M3 dense Top-N
  4) lexical Top-N (동일 필터 통과 좌표 대상)
  5) dense + lexical 후보 합치기 → coordinate_id 중복 제거
  6) RRF 로 1차 결합 (기존 kosis_semantic_search.reciprocal_rank_fusion 재사용)
  7) BGE reranker 로 Top-R 재정렬
  8) 최종 Top-F 만 API 검증 단계로 전달

중요: 임베딩/리랭커 점수는 후보 생성·순위에만 쓴다. READY 는 여기서 정하지 않는다.
출력은 kosis_validate_mapping_candidates.py 의 입력 스키마와 호환된다.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from kosis_meta_coordinates import (
    MAX_AXIS,
    build_chroma_where,
    build_coordinate_query,
    build_coordinates,
    claim_target_terms,
    claim_prd_se,
    coordinate_document,
    coordinate_metadata,
    metadata_is_aggregate,
    passes_hard_filter,
    prd_se_compatible,
    read_csv_rows,
    target_terms_match_text,
)
from kosis_match_claims_to_index import item_mapping_type
from kosis_semantic_search import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANKER_MODEL,
    reciprocal_rank_fusion,
)

RETRIEVAL_STAGE = "chroma_hybrid_v1"


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def measurement_key(row: Mapping[str, Any]) -> str:
    return _text(row.get("claim_measurement_id") or row.get("claim_id"))


def load_table_candidates(path: str, top_k: int) -> dict[str, list[dict]]:
    """measurement 별 상류 통계표 Top-K (rank 오름차순)."""
    by_measurement: dict[str, list[dict]] = defaultdict(list)
    for row in read_csv_rows(path):
        key = measurement_key(row)
        if not key:
            continue
        try:
            rank = int(float(_text(row.get("candidate_rank")) or "999"))
        except ValueError:
            rank = 999
        by_measurement[key].append({
            "rank": rank,
            "org_id": _text(row.get("org_id")),
            "tbl_id": _text(row.get("tbl_id")),
            "tbl_name": _text(row.get("tbl_name")),
            "candidate_status": _text(row.get("candidate_status")),
            "candidate_score": _text(row.get("candidate_score")),
            "candidate_runner_up_score": _text(row.get("candidate_runner_up_score")),
        })
    return {
        key: sorted(rows, key=lambda r: r["rank"])[:top_k]
        for key, rows in by_measurement.items()
    }


# --------------------------------------------------------------------------
# lexical
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def lexical_score(query: str, document: str) -> float:
    """가벼운 토큰 겹침 점수(기존 프로젝트 lexical 후보 생성과 같은 사상)."""
    query_tokens = set(_TOKEN_RE.findall(query.lower()))
    document_tokens = set(_TOKEN_RE.findall(document.lower()))
    if not query_tokens or not document_tokens:
        return 0.0
    overlap = query_tokens & document_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(document_tokens) + 0.5 * len(overlap) / len(query_tokens)


def lexical_search(query: str, pool: Sequence[Mapping[str, Any]], top_k: int) -> list[dict]:
    scored = []
    for entry in pool:
        score = lexical_score(query, entry["document"])
        if score > 0:
            scored.append({**entry, "lexical_score": score})
    scored.sort(key=lambda e: -e["lexical_score"])
    return scored[:top_k]


# --------------------------------------------------------------------------
# fusion
# --------------------------------------------------------------------------

def fuse_candidates(dense: Sequence[Mapping[str, Any]],
                    lexical: Sequence[Mapping[str, Any]]) -> list[dict]:
    """coordinate_id 로 중복 제거하고 RRF 로 결합한다."""
    dense_rank = {c["coordinate_id"]: i + 1 for i, c in enumerate(dense)}
    lexical_rank = {c["coordinate_id"]: i + 1 for i, c in enumerate(lexical)}
    merged: dict[str, dict] = {}
    for entry in list(dense) + list(lexical):
        cid = entry["coordinate_id"]
        current = merged.setdefault(cid, dict(entry))
        for key in ("dense_score", "lexical_score"):
            if entry.get(key) is not None and current.get(key) is None:
                current[key] = entry[key]
    fused = []
    for cid, entry in merged.items():
        entry["dense_rank"] = dense_rank.get(cid)
        entry["lexical_rank"] = lexical_rank.get(cid)
        entry["fusion_score"] = reciprocal_rank_fusion(
            entry["lexical_rank"], entry["dense_rank"]
        )
        fused.append(entry)
    fused.sort(key=lambda e: -e["fusion_score"])
    return fused


# --------------------------------------------------------------------------
# 출력 스키마 (validate 입력 호환)
# --------------------------------------------------------------------------

BASE_CLAIM_FIELDS = (
    "gold_id", "claim_id", "claim_measurement_id", "article_id", "title",
    "claim_text", "date", "indicator",
    "measurement_indicator", "metric_domain", "industry_or_item", "measurement_item",
    "value", "unit", "raw_unit", "canonical_unit", "unit_dimension", "semantic_type",
    "entity_type", "value_type", "measurement_role", "measurement_usage",
    "period", "measurement_period", "prd_se", "measurement_prd_se", "previous_period",
    "change_base", "comparison_period", "mapping_type",
    "region", "age_group", "gender", "origin_country", "destination_country",
    "input_quality_status", "input_quality_reason",
)


def resolve_mapping_type(claim: Mapping[str, Any], meta: Mapping[str, Any]) -> tuple[str, str]:
    """이 항목으로 주장 값을 만들 수 있는 방식과, 못 만든다면 그 이유.

    2026-08-02: mapping_type 은 주장에서 오는 값이 아니라 **항목을 고를 때 계산**되는 값이다.
    A 경로(kosis_match_claims_to_index)는 item_mapping_type 으로 이걸 채우는데
    C 경로는 Chroma 메타에서 항목만 가져오고 계산을 하지 않았다.
    그 결과 validate 가 빈 값을 'direct' 로 메워서,
    '증감률 주장 vs 수준값 항목'(예: % vs 천달러)을 단위 불일치로 막았다.
    실측: 잠근 125건 중 UNIT_MISMATCH 46건 전부 mapping_type 이 비어 있었고
          그중 30건이 증감률 주장이었다.

    주의: KOSIS 단위를 모르면 여기서도 빈 값이 나온다. 그건 정상이다 —
          단위를 확인할 수 없는 좌표를 자동 확정하면 안 된다.
    """
    claim_mapping_type = _text(claim.get("mapping_type"))
    if claim_mapping_type:
        return claim_mapping_type, ""
    try:
        return item_mapping_type(claim, _text(meta.get("unit")), _text(meta.get("itm_name")))
    except Exception as exc:
        return "", f"MAPPING_TYPE_ERROR: {type(exc).__name__}"


def mapping_compatibility_priority(
    claim: Mapping[str, Any], candidate: Mapping[str, Any]
) -> tuple[int, str, str]:
    """Rank structurally compatible ITEMs before neural similarity."""

    meta = candidate.get("metadata") or candidate
    mapping_type, reason = resolve_mapping_type(claim, meta)
    if mapping_type == "direct":
        priority = 0
    elif mapping_type in {"rate_from_level", "difference_from_level"}:
        priority = 1
    else:
        priority = 2
    return priority, mapping_type, reason


def build_output_row(claim: Mapping[str, Any], table: Mapping[str, Any],
                     candidate: Mapping[str, Any], rank: int) -> dict:
    meta = candidate["metadata"]
    row: dict[str, Any] = {field: _text(claim.get(field)) for field in BASE_CLAIM_FIELDS}
    row["period"] = row["period"] or row["measurement_period"]
    row["prd_se"] = row["prd_se"] or row["measurement_prd_se"]
    mapping_type = _text(candidate.get("resolved_mapping_type"))
    unit_reason = _text(candidate.get("mapping_compatibility_reason"))
    if not mapping_type and not unit_reason:
        mapping_type, unit_reason = resolve_mapping_type(claim, meta)
    row["mapping_type"] = mapping_type
    row["unit_compatibility_reason"] = unit_reason
    row.update({
        "org_id": meta.get("org_id", table.get("org_id", "")),
        "tbl_id": meta.get("tbl_id", table.get("tbl_id", "")),
        "tbl_name": meta.get("tbl_name", table.get("tbl_name", "")),
        "category_path": meta.get("category_path", ""),
        "coordinate_id": candidate["coordinate_id"],
        "candidate_rank": rank,
        # 상류 표 후보의 판정을 그대로 전달(하류 게이트가 참조)
        "candidate_status": table.get("candidate_status", ""),
        "candidate_score": table.get("candidate_score", ""),
        "candidate_runner_up_score": table.get("candidate_runner_up_score", ""),
        "table_rank": table.get("rank", ""),
        "selected_itm_id": meta.get("itm_id", ""),
        "selected_itm_name": meta.get("itm_name", ""),
        "selected_itm_unit": meta.get("unit", ""),
        "retrieval_stage": RETRIEVAL_STAGE,
        "dense_rank": candidate.get("dense_rank", ""),
        "dense_score": candidate.get("dense_score", ""),
        "lexical_rank": candidate.get("lexical_rank", ""),
        "lexical_score": candidate.get("lexical_score", ""),
        "fusion_score": candidate.get("fusion_score", ""),
        "reranker_score": candidate.get("reranker_score", ""),
        "final_rank_score": candidate.get("final_rank_score", ""),
        # 주기가 안 맞아 강등된 후보인지 (배제하지 않고 기록만 한다)
        "prd_se_match": candidate.get("prd_se_match", ""),
        "coordinate_prd_se": meta.get("prd_se", ""),
        "claim_target_terms": candidate.get("claim_target_terms", ""),
        "obj_target_match": candidate.get("obj_target_match", ""),
    })
    for level in range(1, MAX_AXIS + 1):
        row[f"selected_obj_l{level}"] = meta.get(f"obj_l{level}", "")
        row[f"selected_obj_l{level}_name"] = meta.get(f"obj_l{level}_name", "")
        row[f"selected_obj_l{level}_axis_id"] = meta.get(f"obj_l{level}_axis_id", "")
    return row


# --------------------------------------------------------------------------
# 검색 백엔드
# --------------------------------------------------------------------------

class ChromaCoordinateSearcher:
    """Chroma 영속 인덱스 기반 dense 검색 (metadata filter 를 검색 전에 적용)."""

    def __init__(self, persist_dir: str, collection: str,
                 embedding_model: str = DEFAULT_EMBEDDING_MODEL, device: str | None = None):
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise RuntimeError("chromadb 가 필요합니다: pip install chromadb") from exc
        from kosis_semantic_search import SentenceTransformerEmbedder

        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_collection(collection)
        self.embedder = SentenceTransformerEmbedder(embedding_model, device=device)
        manifest_path = Path(persist_dir) / "chroma_manifest.json"
        self.manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                         if manifest_path.exists() else {})
        expected = self.manifest.get("embedding_model")
        if expected and expected != embedding_model:
            raise ValueError(
                f"인덱스 임베딩 모델({expected})과 요청 모델({embedding_model})이 다릅니다."
            )
        self.expected_dimension = int(self.manifest.get("embedding_dimension") or 0)

    def search(self, query: str, where: Mapping[str, Any] | None, top_k: int) -> list[dict]:
        vector = self.embedder.encode([query])[0].tolist()
        if self.expected_dimension and len(vector) != self.expected_dimension:
            raise ValueError(
                f"인덱스 차원({self.expected_dimension})과 query 차원({len(vector)})이 다릅니다."
            )
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for cid, document, metadata, distance in zip(ids, documents, metadatas, distances):
            hits.append({
                "coordinate_id": cid,
                "document": document,
                "metadata": dict(metadata or {}),
                "dense_score": 1.0 - float(distance),   # cosine distance → 유사도
                "lexical_score": None,
            })
        return hits

    def pool_for_tables(self, tbl_ids: Sequence[str], limit: int = 4000) -> list[dict]:
        """lexical 검색용 후보 풀.

        ``limit`` 은 전체 한도가 아니라 표별 한도다. Top-5를 한 번에 ``$in`` 조회한 뒤
        4,000개만 자르면 저장 순서상 앞 표가 풀을 독점할 수 있기 때문이다.
        """
        ids = [t for t in dict.fromkeys(tbl_ids) if t]
        if not ids:
            return []
        pool, seen = [], set()
        for tbl_id in ids:
            result = self.collection.get(
                where={"tbl_id": tbl_id},
                include=["documents", "metadatas"],
                limit=limit,
            )
            for cid, document, metadata in zip(result.get("ids") or [],
                                               result.get("documents") or [],
                                               result.get("metadatas") or []):
                if cid in seen:
                    continue
                seen.add(cid)
                pool.append({
                    "coordinate_id": cid,
                    "document": document,
                    "metadata": dict(metadata or {}),
                    "dense_score": None,
                    "lexical_score": None,
                })
        return pool


class InMemoryCoordinateSearcher:
    """meta CSV 만으로 동작하는 fallback (dense 없음, 테스트·GPU 없는 환경용)."""

    def __init__(self, meta_rows: Iterable[Mapping[str, Any]], **kwargs):
        self.entries = []
        for coordinate in build_coordinates(meta_rows, **kwargs):
            self.entries.append({
                "coordinate_id": coordinate["coordinate_id"],
                "document": coordinate_document(coordinate),
                "metadata": coordinate_metadata(coordinate),
                "dense_score": None,
                "lexical_score": None,
            })
        self.manifest = {"embedding_model": None, "note": "in-memory lexical only"}

    def search(self, query: str, where: Mapping[str, Any] | None, top_k: int) -> list[dict]:
        return []   # dense 없음

    def pool_for_tables(self, tbl_ids: Sequence[str], limit: int = 4000) -> list[dict]:
        ids = {t for t in tbl_ids if t}
        if not ids:
            return self.entries[:limit]
        by_table = defaultdict(list)
        for entry in self.entries:
            tbl_id = _text(entry["metadata"].get("tbl_id"))
            if tbl_id in ids and len(by_table[tbl_id]) < limit:
                by_table[tbl_id].append(entry)
        return [entry for tbl_id in dict.fromkeys(tbl_ids)
                for entry in by_table.get(tbl_id, [])]


def search_measurement(claim: Mapping[str, Any], tables: Sequence[Mapping[str, Any]],
                       searcher, *, dense_top_k: int, lexical_top_k: int,
                       rerank_top_k: int, final_top_k: int, reranker=None,
                       lexical_pool_per_table: int = 4000) -> tuple[list[dict], dict]:
    """한 measurement 의 좌표 후보를 dense+lexical+rerank 로 뽑는다."""
    query = build_coordinate_query(claim)
    tbl_ids = [t["tbl_id"] for t in tables]
    where = build_chroma_where(claim, tbl_ids)

    started = time.perf_counter()
    dense = searcher.search(query, where, dense_top_k)
    pool = [entry for entry in searcher.pool_for_tables(
                tbl_ids, limit=lexical_pool_per_table)
            if passes_hard_filter(claim, entry["metadata"], tbl_ids)]
    lexical = lexical_search(query, pool, lexical_top_k)
    search_seconds = time.perf_counter() - started

    # 값만 넘기면 '실업률'(경제활동별), '1월'(통계분류)처럼 문장과 우연히
    # 겹친 지표·시점도 target 으로 보인다. 축 의미를 함께 넘겨
    # 국가·지역·산업·품목·인구집단 축만 대상 신호로 쓴다.
    axis_values = [
        {
            "name": entry["metadata"].get(f"obj_l{level}_name", ""),
            "axis_name": entry["metadata"].get(f"obj_l{level}_axis_name", ""),
        }
        for entry in pool for level in range(1, MAX_AXIS + 1)
    ]
    target_terms = claim_target_terms(claim, axis_values)

    def target_match(candidate: Mapping[str, Any]) -> bool:
        metadata = candidate.get("metadata") or {}
        selected_values = [metadata.get(f"obj_l{level}_name", "")
                           for level in range(1, MAX_AXIS + 1)]
        return target_terms_match_text(target_terms, selected_values) if target_terms else False

    fused = fuse_candidates(dense, lexical)
    if target_terms:
        # exact OBJ 언급은 dense/lexical Top-K 밖이어도 reranker가 볼 수 있어야 한다.
        # 그렇지 않으면 '축에 값이 있는데 후보 절단 때문에 못 찾음'과
        # '축에 값이 없음'을 구분할 수 없다.
        seen = {candidate["coordinate_id"] for candidate in fused}
        for entry in pool:
            if entry["coordinate_id"] in seen or not target_match(entry):
                continue
            fused.append({**entry, "dense_rank": None, "lexical_rank": None,
                          "fusion_score": 0.0})
            seen.add(entry["coordinate_id"])
        fused.sort(key=lambda candidate: (
            0 if target_match(candidate) else 1,
            -float(candidate.get("fusion_score") or 0.0),
        ))
    # A wider table pool can flood the global Top-K with many OBJ coordinates
    # and remove the one ITEM that matches the structured comparison base.
    # Add one target/aggregate representative per compatible table/ITEM before
    # the reranker cutoff so 전년동월비 cannot disappear behind 전월비 rows.
    seen = {candidate["coordinate_id"] for candidate in fused}
    structural: dict[tuple[str, str, bool, bool], dict] = {}
    for entry in pool:
        priority, mapping_type, reason = mapping_compatibility_priority(claim, entry)
        if priority >= 2:
            continue
        metadata = entry.get("metadata") or {}
        target_matched = target_match(entry)
        aggregate = metadata_is_aggregate(metadata)
        if target_terms and not target_matched:
            continue
        if not target_terms and not aggregate:
            continue
        key = (
            _text(metadata.get("tbl_id")),
            _text(metadata.get("itm_id")),
            target_matched,
            aggregate,
        )
        structural.setdefault(
            key,
            {
                **entry,
                "dense_rank": None,
                "lexical_rank": None,
                "fusion_score": 0.0,
                "mapping_priority": priority,
                "resolved_mapping_type": mapping_type,
                "mapping_compatibility_reason": reason,
            },
        )
    for entry in structural.values():
        if entry["coordinate_id"] not in seen:
            fused.append(entry)
            seen.add(entry["coordinate_id"])

    for candidate in fused:
        priority, mapping_type, reason = mapping_compatibility_priority(claim, candidate)
        candidate["mapping_priority"] = priority
        candidate["resolved_mapping_type"] = mapping_type
        candidate["mapping_compatibility_reason"] = reason
    fused.sort(key=lambda candidate: (
        candidate["mapping_priority"],
        0 if (not target_terms or target_match(candidate)) else 1,
        0 if (target_terms or metadata_is_aggregate(candidate.get("metadata") or {})) else 1,
        -float(candidate.get("fusion_score") or 0.0),
    ))
    fused = fused[:rerank_top_k]
    rerank_seconds = 0.0
    if reranker is not None and fused:
        started = time.perf_counter()
        scores = reranker.score(query, [c["document"] for c in fused])
        rerank_seconds = time.perf_counter() - started
        for candidate, score in zip(fused, scores):
            candidate["reranker_score"] = float(score)
            candidate["final_rank_score"] = float(score)
    else:
        for candidate in fused:
            candidate["final_rank_score"] = candidate.get("fusion_score", 0.0)

    # 주기 불일치는 '배제'가 아니라 '강등'이다. 점수 스케일(리랭커 로짓은 음수 가능)에
    # 흔들리지 않도록 곱셈 감점 대신 정렬 키의 1순위로만 쓴다.
    wanted_prd_se = claim_prd_se(claim)
    for candidate in fused:
        candidate["prd_se_match"] = prd_se_compatible(
            wanted_prd_se, (candidate.get("metadata") or {}).get("prd_se", ""))

    # 주장이 세부 대상을 말하지 않으면 좌표도 집계여야 한다.
    # 이 규칙은 2026-07-31 부터 READY 확정 게이트에만 있었고 순위에는 없었다.
    # 그래서 세부 분류가 1위로 올라온 뒤에야 탈락했다.
    #
    # 실측(잠근 125건, 대상 미특정 46건): 같은 축에 집계 코드가 있는데도
    #   C(리랭커)는 32건에서 세부를 골랐고, A(빌드 순서 유지)는 8건뿐이었다.
    #   리랭커가 build_coordinates 의 집계 우선 정렬을 의미 유사도로 덮어쓴다.
    #   '계'보다 세부 분류 이름이 주장 문장과 더 비슷해 보이기 때문이다.
    #
    # prd_se 와 마찬가지로 점수를 곱해 깎지 않는다(리랭커 로짓은 음수가 될 수 있다).
    # 정렬 키로만 쓰고, 주기 일치를 앞에 둔다 — 기간 불일치가 더 강한 제약이다.
    prefer_aggregate = not target_terms
    for candidate in fused:
        metadata = candidate.get("metadata") or {}
        candidate["obj_aggregate"] = metadata_is_aggregate(metadata)
        candidate["obj_target_match"] = target_match(candidate)
        candidate["claim_target_terms"] = "|".join(target_terms)
    fused.sort(key=lambda c: (
        0 if c["prd_se_match"] else 1,
        c.get("mapping_priority", 2),
        0 if (not target_terms or c["obj_target_match"]) else 1,
        0 if (not prefer_aggregate or c["obj_aggregate"]) else 1,
        -c["final_rank_score"],
    ))

    stats = {
        "query": query,
        "dense_count": len(dense),
        "lexical_count": len(lexical),
        "fused_count": len(fused),
        "structural_shortlist_count": len(structural),
        "mapping_incompatible_demoted": sum(
            1 for candidate in fused if candidate.get("mapping_priority", 2) >= 2
        ),
        "prd_se_demoted": sum(1 for c in fused if not c["prd_se_match"]),
        "prefer_aggregate": prefer_aggregate,
        "claim_target_terms": "|".join(target_terms),
        "target_matched_candidates": sum(1 for c in fused if c["obj_target_match"]),
        "aggregate_promoted": (sum(1 for c in fused if not c["obj_aggregate"])
                               if prefer_aggregate else 0),
        "search_seconds": search_seconds,
        "rerank_seconds": rerank_seconds,
    }
    return fused[:final_top_k], stats


def main() -> None:
    parser = argparse.ArgumentParser(description="ChromaDB hybrid coordinate search for KOSIS mapping")
    parser.add_argument("--claims", required=True, help="1차 READY measurement CSV")
    parser.add_argument("--table-candidates", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--persist-dir", default="data/indexes/kosis_meta_chroma")
    parser.add_argument("--collection", default="kosis_meta_coordinates")
    parser.add_argument("--meta-index", default=None,
                        help="Chroma 없이 lexical 만으로 돌릴 때 사용할 메타 CSV")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--device", default=None)
    parser.add_argument("--table-top-k", type=int, default=5)
    parser.add_argument("--dense-top-k", type=int, default=50)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--lexical-pool-per-table", type=int, default=4000)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--final-top-k", type=int, default=10)
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stats-output", default=None)
    args = parser.parse_args()

    claims = read_csv_rows(args.claims)
    if args.limit:
        claims = claims[:args.limit]
    tables_by_measurement = load_table_candidates(args.table_candidates, args.table_top_k)

    if args.meta_index:
        searcher = InMemoryCoordinateSearcher(read_csv_rows(args.meta_index))
        print("retrieval=lexical_only (in-memory fallback, dense 없음)")
    else:
        searcher = ChromaCoordinateSearcher(
            args.persist_dir, args.collection,
            embedding_model=args.embedding_model, device=args.device,
        )
        print(f"retrieval=chroma_hybrid manifest={searcher.manifest.get('embedding_model')}")
        # 어느 인덱스로 뽑은 후보인지 남긴다. 같은 입력으로 재빌드해도 임베딩이
        # 미세하게 달라져 recall 이 ±1건 흔들린 적이 있다(2026-08-02 실측).
        # A/B 비교를 할 때 이 지문이 같은지부터 확인해야 한다.
        print(f"index_fingerprint={searcher.manifest.get('embedding_fingerprint', '(없음)')}"
              f" rounded={searcher.manifest.get('embedding_fingerprint_rounded', '(없음)')}")

    reranker = None
    if not args.no_reranker and not args.meta_index:
        from kosis_semantic_search import TransformerReranker
        reranker = TransformerReranker(args.reranker_model, device=args.device)

    out_rows, stats_rows = [], []
    total_search = total_rerank = 0.0
    for claim in claims:
        key = measurement_key(claim)
        tables = tables_by_measurement.get(key, [])
        if not tables:
            continue
        by_table = {t["tbl_id"]: t for t in tables}
        candidates, stats = search_measurement(
            claim, tables, searcher,
            dense_top_k=args.dense_top_k, lexical_top_k=args.lexical_top_k,
            rerank_top_k=args.rerank_top_k, final_top_k=args.final_top_k,
            reranker=reranker, lexical_pool_per_table=args.lexical_pool_per_table,
        )
        for rank, candidate in enumerate(candidates, start=1):
            table = by_table.get(_text(candidate["metadata"].get("tbl_id")), tables[0])
            out_rows.append(build_output_row(claim, table, candidate, rank))
        total_search += stats["search_seconds"]
        total_rerank += stats["rerank_seconds"]
        stats_rows.append({"claim_measurement_id": key, **{
            k: v for k, v in stats.items() if k != "query"}})

    if not out_rows:
        raise SystemExit("생성된 후보가 없습니다. --table-candidates 와 claim ID 를 확인하세요.")

    fields = list(dict.fromkeys(key for row in out_rows for key in row))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    measurements = len({row["claim_measurement_id"] for row in out_rows})
    print(f"measurements={measurements} candidate_rows={len(out_rows)} → {args.output}")
    print(f"avg_search_seconds={total_search / max(len(stats_rows), 1):.4f} "
          f"avg_rerank_seconds={total_rerank / max(len(stats_rows), 1):.4f}")
    if args.stats_output and stats_rows:
        with open(args.stats_output, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(stats_rows[0]))
            writer.writeheader()
            writer.writerows(stats_rows)
        print(f"stats={args.stats_output}")


if __name__ == "__main__":
    main()
