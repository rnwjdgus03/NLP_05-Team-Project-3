"""Coordinate-level KOSIS metadata retrieval with ChromaDB and BGE models.

This module retrieves ITEM/OBJ coordinate candidates only.  READY decisions
must still be made by official metadata checks and KOSIS API validation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from kosis_semantic_search import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANKER_MODEL,
    SentenceTransformerEmbedder,
    TransformerReranker,
    file_sha256,
    reciprocal_rank_fusion,
)


COORDINATE_SCHEMA_VERSION = 2
DEFAULT_COLLECTION_NAME = "kosis_coordinate_bge_m3_v1"
QUERY_FIELDS = (
    ("claim_text", "문장"),
    ("measurement_indicator", "지표"),
    ("indicator", "지표"),
    ("measurement_item", "항목"),
    ("industry_or_item", "대상"),
    ("metric_domain", "도메인"),
    ("value_type", "값유형"),
    ("semantic_type", "의미유형"),
    ("measurement_role", "역할"),
    ("unit", "단위"),
    ("canonical_unit", "표준단위"),
    ("unit_dimension", "단위차원"),
    ("measurement_period", "기간"),
    ("period", "기간"),
    ("measurement_prd_se", "주기"),
    ("prd_se", "주기"),
    ("region", "지역"),
    ("age_group", "연령"),
    ("gender", "성별"),
    ("origin_country", "출발국"),
    ("destination_country", "도착국"),
)


def _first(row: Mapping[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", str(value or "")).lower()


def _join_nonempty(parts: Iterable[Any], sep: str = " > ") -> str:
    return sep.join(_clean(part) for part in parts if _clean(part))


def _axis_order(row: Mapping[str, Any]) -> int | None:
    raw = _first(row, "OBJ_ID_SN", "obj_id_sn", "axis_order", "obj_level")
    try:
        order = int(float(raw))
        return order if 1 <= order <= 8 else None
    except (TypeError, ValueError):
        return None


def _stable_id(parts: Sequence[Any]) -> str:
    payload = "\x1f".join(_clean(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def infer_mapping_type(row: Mapping[str, Any]) -> str:
    raw = _first(row, "mapping_type", "semantic_type", "value_type").lower()
    if raw in {"rate", "rate_change", "rate_from_level", "증감률"}:
        return "rate"
    if raw in {"difference", "absolute_change", "difference_from_level", "증감량"}:
        return "difference"
    return raw or "level"


def build_coordinate_query(row: Mapping[str, Any]) -> str:
    seen: set[tuple[str, str]] = set()
    parts: list[str] = []
    for key, label in QUERY_FIELDS:
        value = _clean(row.get(key, ""))
        if not value or value == "-":
            continue
        marker = (label, value)
        if marker in seen:
            continue
        seen.add(marker)
        parts.append(f"{label}: {value}")
    return " | ".join(parts)


def normalize_meta_rows(meta_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for source in meta_rows or []:
        row = dict(source)
        rows.append(
            {
                "org_id": _first(row, "org_id", "ORG_ID"),
                "tbl_id": _first(row, "tbl_id", "TBL_ID"),
                "tbl_name": _first(row, "tbl_name", "TBL_NM"),
                "category_path": _first(row, "category_path", "path"),
                "itm_id": _first(row, "ITM_ID", "itm_id", "code_id", "code"),
                "itm_name": _first(row, "ITM_NM", "itm_nm", "code_name", "name"),
                "obj_id": _first(row, "OBJ_ID", "obj_id", "axis_id"),
                "obj_name": _first(row, "OBJ_NM", "obj_nm", "axis_name"),
                "unit": _first(row, "unit", "UNIT", "UNIT_NM", "unit_name"),
                "unit_dimension": _first(row, "unit_dimension"),
                "prd_se": _first(row, "prd_se", "PRD_SE"),
                "unit_id": _first(row, "unit_id", "UNIT_ID"),
                "parent_code_id": _first(row, "parent_code_id", "PARENT_CODE_ID"),
                "is_item": _first(row, "is_item", "IS_ITEM"),
                "axis_order": str(_axis_order(row) or ""),
            }
        )
    return rows


def build_coordinate_documents(meta_rows: Iterable[Mapping[str, Any]], *, max_documents: int = 0) -> list[dict[str, Any]]:
    """Build one document per org_id + tbl_id + itm_id + OBJ path."""
    rows = normalize_meta_rows(meta_rows)
    by_table: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["org_id"], row["tbl_id"])
        table = by_table.setdefault(
            key,
            {
                "org_id": row["org_id"],
                "tbl_id": row["tbl_id"],
                "tbl_name": row["tbl_name"],
                "category_path": row["category_path"],
                "unit": row["unit"],
                "unit_dimension": row["unit_dimension"],
                "prd_se": row["prd_se"],
                "items": {},
                "axes": defaultdict(list),
            },
        )
        if (row["obj_id"].upper() == "ITEM" or row.get("is_item", "").upper() == "Y") and row["itm_id"]:
            table["items"][row["itm_id"]] = {"id": row["itm_id"], "name": row["itm_name"], "unit": row["unit"]}
            if row["unit"] and not table["unit"]:
                table["unit"] = row["unit"]
        elif row["axis_order"] and row["itm_id"]:
            table["axes"][int(row["axis_order"])].append(row)

    documents = []
    for table in by_table.values():
        axis_values = [table["axes"][order] for order in sorted(table["axes"])]
        if not table["items"] or not axis_values:
            continue
        for itm_id, item in sorted(table["items"].items()):
            itm_name = item.get("name", "")
            unit = item.get("unit") or table["unit"]
            paths = [[]]
            for values in axis_values:
                paths = [path + [value] for path in paths for value in values]
            for path in paths:
                metadata: dict[str, Any] = {
                    "org_id": table["org_id"],
                    "tbl_id": table["tbl_id"],
                    "tbl_name": table["tbl_name"],
                    "category_path": table["category_path"],
                    "itm_id": itm_id,
                    "itm_name": itm_name,
                    "itm_key": _compact(f"{itm_id} {itm_name}"),
                    "unit": unit,
                    "unit_dimension": table["unit_dimension"],
                    "prd_se": table["prd_se"],
                    "mapping_type": "level",
                }
                text_parts = [
                    f"통계표명: {table['tbl_name']}",
                    f"통계표ID: {table['tbl_id']}",
                    f"통계분류경로: {table['category_path']}",
                    f"측정항목명: {itm_name}",
                    f"측정항목ID: {itm_id}",
                    f"행열좌표항목: {itm_name}",
                ]
                id_parts = [table["org_id"], table["tbl_id"], itm_id]
                obj_names = []
                axis_names = []
                obj_codes = []
                axis_pairs = []
                for value in path:
                    level = int(value["axis_order"])
                    axis_name = value["obj_name"]
                    code = value["itm_id"]
                    name = value["itm_name"]
                    metadata[f"obj_l{level}_axis_id"] = value["obj_id"]
                    metadata[f"obj_l{level}_axis_name"] = axis_name
                    metadata[f"obj_l{level}"] = code
                    metadata[f"obj_l{level}_name"] = name
                    metadata[f"obj_l{level}_key"] = _compact(f"{code} {name}")
                    obj_names.append(name)
                    axis_names.append(axis_name)
                    obj_codes.append(code)
                    axis_pairs.append(f"{axis_name}={name}")
                    id_parts.extend([level, value["obj_id"], code])
                    text_parts.extend([
                        f"분류축{level}명: {axis_name}",
                        f"분류축{level}코드: {value['obj_id']}",
                        f"분류값{level}명: {name}",
                        f"분류값{level}코드: {code}",
                        f"행열좌표{level}: {axis_name}={name}",
                    ])
                metadata["axis_path"] = _join_nonempty(axis_names)
                metadata["obj_path"] = _join_nonempty(obj_names)
                metadata["obj_codes"] = " > ".join(obj_codes)
                metadata["coordinate_label"] = _join_nonempty([table["tbl_name"], itm_name, *axis_pairs], sep=" | ")
                metadata["coordinate_id"] = _stable_id(id_parts)
                text_parts.extend(
                    [
                        f"분류축경로: {metadata['axis_path']}",
                        f"분류값경로: {metadata['obj_path']}",
                        f"좌표라벨: {metadata['coordinate_label']}",
                        f"단위명: {unit}",
                        f"단위차원: {table['unit_dimension']}",
                        f"수록주기: {table['prd_se']}",
                    ]
                )
                metadata["coordinate_text"] = " | ".join(part for part in text_parts if part.split(":", 1)[-1].strip())
                documents.append(
                    {
                        "coordinate_id": metadata["coordinate_id"],
                        "document": " | ".join(part for part in text_parts if part.split(":", 1)[-1].strip()),
                        "metadata": metadata,
                    }
                )
                if max_documents and len(documents) >= max_documents:
                    return documents
    return documents


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _metadata_filter(row: Mapping[str, Any], *, tbl_ids: set[str], claim: Mapping[str, Any]) -> bool:
    if tbl_ids and str(row.get("tbl_id", "")) not in tbl_ids:
        return False
    claim_prd = _first(claim, "measurement_prd_se", "prd_se")
    if claim_prd and row.get("prd_se") and str(row["prd_se"]) != claim_prd:
        return False
    claim_unit_dim = _first(claim, "unit_dimension")
    if claim_unit_dim and row.get("unit_dimension") and str(row["unit_dimension"]) != claim_unit_dim:
        return False
    claim_mapping = infer_mapping_type(claim)
    row_mapping = str(row.get("mapping_type", "") or "level")
    if claim_mapping in {"rate", "difference"} and row_mapping not in {"level", claim_mapping}:
        return False
    return True


def lexical_coordinate_search(
    documents: Sequence[Mapping[str, Any]], query: str, *, top_k: int = 50,
    tbl_ids: set[str] | None = None, claim: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", query.lower()))
    hits = []
    for doc in documents:
        metadata = doc["metadata"]
        if claim is not None and not _metadata_filter(metadata, tbl_ids=tbl_ids or set(), claim=claim):
            continue
        text = str(doc["document"]).lower()
        doc_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", text))
        overlap = len(tokens & doc_tokens)
        contains = sum(1 for token in tokens if len(token) >= 2 and token in text)
        score = overlap + contains
        if score > 0:
            hits.append({"coordinate_id": doc["coordinate_id"], "rank": 0, "score": float(score), "document": doc["document"], "metadata": metadata})
    hits.sort(key=lambda row: row["score"], reverse=True)
    for rank, hit in enumerate(hits[:top_k], 1):
        hit["rank"] = rank
    return hits[:top_k]


@dataclass
class CoordinateSearchRuntime:
    persist_dir: Path
    collection_name: str = DEFAULT_COLLECTION_NAME
    embedder: Any | None = None
    reranker: Any | None = None
    reranker_model: str = DEFAULT_RERANKER_MODEL
    device: str | None = None
    use_reranker: bool = True

    def __post_init__(self) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("ChromaDB 좌표 검색에는 chromadb가 필요합니다.") from exc
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_collection(self.collection_name)
        self.embedder = self.embedder or SentenceTransformerEmbedder(device=self.device)

    def dense_search(self, query: str, *, top_k: int = 50, tbl_ids: set[str] | None = None,
                     claim: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if tbl_ids:
            where["tbl_id"] = {"$in": sorted(tbl_ids)}
        if claim:
            prd_se = _first(claim, "measurement_prd_se", "prd_se")
            unit_dimension = _first(claim, "unit_dimension")
            if prd_se:
                where["prd_se"] = prd_se
            if unit_dimension:
                where["unit_dimension"] = unit_dimension
        vector = self.embedder.encode([query])[0].tolist()
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for rank, coordinate_id in enumerate(ids, 1):
            metadata = dict(metas[rank - 1] or {})
            if claim and not _metadata_filter(metadata, tbl_ids=tbl_ids or set(), claim=claim):
                continue
            hits.append(
                {
                    "coordinate_id": coordinate_id,
                    "rank": rank,
                    "score": 1.0 - float(distances[rank - 1] or 0.0),
                    "document": docs[rank - 1],
                    "metadata": metadata,
                }
            )
        return hits

    def rerank(self, query: str, hits: Sequence[Mapping[str, Any]], *, top_k: int = 20) -> list[dict[str, Any]]:
        rows = [dict(hit) for hit in hits[:top_k]]
        if not rows or not self.use_reranker:
            return rows
        if self.reranker is None:
            self.reranker = TransformerReranker(self.reranker_model, device=self.device)
        scores = self.reranker.score(query, [row["document"] for row in rows])
        for row, score in zip(rows, scores):
            row["reranker_score"] = float(score)
        return sorted(rows, key=lambda row: row.get("reranker_score", 0.0), reverse=True)


def fuse_coordinate_hits(dense_hits: Sequence[Mapping[str, Any]],
                         lexical_hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source_name, hits in (("dense", dense_hits), ("lexical", lexical_hits)):
        for hit in hits:
            coordinate_id = str(hit["coordinate_id"])
            row = merged.setdefault(coordinate_id, dict(hit))
            row[f"{source_name}_rank"] = int(hit["rank"])
            row[f"{source_name}_score"] = float(hit.get("score", 0.0))
            row["document"] = hit.get("document", row.get("document", ""))
            row["metadata"] = hit.get("metadata", row.get("metadata", {}))
    for row in merged.values():
        row["fusion_score"] = reciprocal_rank_fusion(row.get("lexical_rank"), row.get("dense_rank"))
    return sorted(merged.values(), key=lambda row: row["fusion_score"], reverse=True)


def coordinate_hits_to_candidates(hits: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    item_candidates: dict[str, dict[str, Any]] = {}
    obj_candidates: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for rank, hit in enumerate(hits, 1):
        metadata = hit.get("metadata", {})
        score = float(hit.get("reranker_score", hit.get("fusion_score", 0.0)))
        itm_id = str(metadata.get("itm_id", "")).strip()
        if itm_id and (itm_id not in item_candidates or score > float(item_candidates[itm_id]["semantic_score"])):
            item_candidates[itm_id] = {
                "code": itm_id,
                "name": metadata.get("itm_name", ""),
                "semantic_score": score,
                "coordinate_rank": rank,
                "coordinate_id": hit.get("coordinate_id", ""),
            }
        for level in range(1, 9):
            code = str(metadata.get(f"obj_l{level}", "")).strip()
            if not code:
                continue
            existing = obj_candidates[level].get(code)
            if existing is None or score > float(existing["semantic_score"]):
                obj_candidates[level][code] = {
                    "code": code,
                    "name": metadata.get(f"obj_l{level}_name", ""),
                    "semantic_score": score,
                    "coordinate_rank": rank,
                    "coordinate_id": hit.get("coordinate_id", ""),
                }
    items = sorted(item_candidates.values(), key=lambda row: row["semantic_score"], reverse=True)
    objs = {
        level: sorted(values.values(), key=lambda row: row["semantic_score"], reverse=True)
        for level, values in obj_candidates.items()
    }
    return items, objs


def build_chroma_coordinate_index(
    meta_index: str | Path,
    persist_dir: str | Path,
    *,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 64,
    max_documents: int = 0,
    device: str | None = None,
    embedder: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("ChromaDB 인덱스 생성에는 chromadb가 필요합니다.") from exc
    meta_index = Path(meta_index)
    persist_dir = Path(persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = persist_dir / "manifest.json"
    source_hash = file_sha256(meta_index)
    rows = _read_csv(meta_index)
    documents = build_coordinate_documents(rows, max_documents=max_documents)
    if not documents:
        raise ValueError("ChromaDB에 저장할 KOSIS 좌표 document가 없습니다.")
    if not force and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing.get("schema_version") == COORDINATE_SCHEMA_VERSION
            and existing.get("embedding_model") == embedding_model
            and existing.get("source_meta_sha256") == source_hash
            and existing.get("document_count") == len(documents)
            and existing.get("max_documents") == max_documents
            and existing.get("collection_name") == collection_name
        ):
            return existing

    client = chromadb.PersistentClient(path=str(persist_dir))
    if force:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
    collection = client.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    embedder = embedder or SentenceTransformerEmbedder(embedding_model, device=device)
    first = embedder.encode([documents[0]["document"]], batch_size=1)
    dimension = int(len(first[0]))

    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        embeddings = embedder.encode([row["document"] for row in batch], batch_size=batch_size)
        collection.upsert(
            ids=[row["coordinate_id"] for row in batch],
            documents=[row["document"] for row in batch],
            metadatas=[row["metadata"] for row in batch],
            embeddings=[list(map(float, vector)) for vector in embeddings],
        )

    manifest = {
        "schema_version": COORDINATE_SCHEMA_VERSION,
        "embedding_model": embedding_model,
        "embedding_dimension": dimension,
        "normalized_embeddings": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_meta_file": str(meta_index),
        "source_meta_sha256": source_hash,
        "document_count": len(documents),
        "max_documents": max_documents,
        "collection_name": collection_name,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def search_coordinate_candidates(
    *, runtime: CoordinateSearchRuntime, fallback_documents: Sequence[Mapping[str, Any]],
    claim: Mapping[str, Any], table_candidates: Sequence[Mapping[str, Any]], dense_top_k: int = 50,
    lexical_top_k: int = 50, rerank_top_k: int = 20, validation_top_k: int = 10,
) -> list[dict[str, Any]]:
    query = build_coordinate_query(claim)
    tbl_ids = {str(row.get("tbl_id", "")).strip() for row in table_candidates if str(row.get("tbl_id", "")).strip()}
    dense = runtime.dense_search(query, top_k=dense_top_k, tbl_ids=tbl_ids, claim=claim)
    lexical = lexical_coordinate_search(fallback_documents, query, top_k=lexical_top_k, tbl_ids=tbl_ids, claim=claim)
    fused = fuse_coordinate_hits(dense, lexical)
    return runtime.rerank(query, fused, top_k=rerank_top_k)[:validation_top_k]
