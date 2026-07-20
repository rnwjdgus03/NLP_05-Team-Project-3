"""Dense retrieval and cross-encoder reranking for KOSIS table search.

The semantic layer only proposes table candidates.  Measurement eligibility,
ITEM/OBJ compatibility, period checks, and READY/REVIEW/REJECT decisions stay
in ``kosis_match_claims_to_index.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
INDEX_FORMAT_VERSION = 1


def table_key(row):
    return str(row.get("org_id", "")), str(row.get("tbl_id", ""))


def normalize_table_row(row):
    return {
        "org_id": row.get("org_id") or row.get("ORG_ID") or "",
        "tbl_id": row.get("tbl_id") or row.get("TBL_ID") or "",
        "tbl_name": row.get("tbl_name") or row.get("TBL_NM") or "",
        "stat_id": row.get("stat_id") or row.get("STAT_ID") or "",
        "category_path": row.get("category_path") or row.get("path") or "",
    }


def build_table_document(row):
    row = normalize_table_row(row)
    parts = [
        f"통계표: {row['tbl_name']}",
        f"분류경로: {row['category_path']}",
    ]
    if row["stat_id"]:
        parts.append(f"통계 ID: {row['stat_id']}")
    return " | ".join(part for part in parts if part.split(":", 1)[-1].strip())


def build_claim_query(claim):
    focused = " ".join(
        str(claim.get(key, "") or "")
        for key in ("indicator", "industry_or_item", "claim_text")
    )
    compact_focused = "".join(focused.split())
    scope_hints = []
    if any(token in compact_focused for token in ("수출", "수입", "무역수지")):
        scope_hints.extend(
            [
                "대한민국 전체 품목별 수출입 공식통계",
                "개별 기업 설문, 기업혁신조사, 전망지수 제외",
            ]
        )
    if any(token in compact_focused for token in ("국제선여객", "LCC", "대형항공사")):
        scope_hints.extend(
            [
                "항공사 또는 국제선 여객 운송 실적",
                "지역 간 전체 교통 통행량 제외",
            ]
        )
    if "정비사" in compact_focused:
        scope_hints.extend(
            [
                "항공 정비사 재직 인원",
                "부족 인원과 부족률 제외",
            ]
        )
    fields = [
        ("지표", claim.get("indicator", "")),
        ("대상", claim.get("industry_or_item", "")),
        ("의미", claim.get("semantic_type", "")),
        ("단위", claim.get("unit", "")),
        ("단위차원", claim.get("unit_dimension", "")),
        ("대상유형", claim.get("entity_type", "")),
        ("기간", claim.get("period", "")),
        ("주기", claim.get("prd_se", "")),
        ("검색범위", "; ".join(scope_hints)),
        ("문장", claim.get("claim_text", "")),
    ]
    return " | ".join(
        f"{label}: {str(value).strip()}"
        for label, value in fields
        if str(value or "").strip() not in {"", "-"}
    )


def reciprocal_rank_fusion(lexical_rank, semantic_rank, rank_constant=60):
    score = 0.0
    if lexical_rank:
        score += 1.0 / (rank_constant + lexical_rank)
    if semantic_rank:
        score += 1.0 / (rank_constant + semantic_rank)
    return score


def normalized_rrf_score(lexical_rank, semantic_rank, rank_constant=60):
    maximum = 2.0 / (rank_constant + 1)
    return min(
        1.0,
        reciprocal_rank_fusion(lexical_rank, semantic_rank, rank_constant) / maximum,
    )


def _require_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "임베딩 검색에는 numpy가 필요합니다. requirements-ml.txt를 설치하세요."
        ) from exc
    return np


class SentenceTransformerEmbedder:
    def __init__(self, model_name=DEFAULT_EMBEDDING_MODEL, device=None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "임베딩 모델을 사용하려면 requirements-ml.txt를 설치하세요."
            ) from exc
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)
        if device and str(device).startswith("cuda"):
            self.model.half()

    def encode(self, texts, batch_size=16, show_progress_bar=False):
        return self.model.encode(
            list(texts),
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=show_progress_bar,
        )


class TransformerReranker:
    def __init__(
        self,
        model_name=DEFAULT_RERANKER_MODEL,
        device=None,
        batch_size=8,
        max_length=512,
    ):
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "리랭커를 사용하려면 requirements-ml.txt를 설치하세요."
            ) from exc
        self.torch = torch
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        if str(self.device).startswith("cuda"):
            self.model.half()
        self.model.eval()

    def score(self, query, documents):
        scores = []
        pairs = [[query, document] for document in documents]
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with self.torch.no_grad():
                logits = self.model(**encoded, return_dict=True).logits.view(-1).float()
                batch_scores = self.torch.sigmoid(logits).cpu().tolist()
            scores.extend(float(score) for score in batch_scores)
        return scores


@dataclass
class SemanticHit:
    org_id: str
    tbl_id: str
    score: float
    rank: int

    @property
    def key(self):
        return self.org_id, self.tbl_id


class SemanticTableIndex:
    def __init__(self, index_dir, embedder=None, device=None):
        np = _require_numpy()
        self.index_dir = Path(index_dir)
        manifest_path = self.index_dir / "manifest.json"
        tables_path = self.index_dir / "tables.csv"
        embeddings_path = self.index_dir / "embeddings.npy"
        missing = [
            str(path)
            for path in (manifest_path, tables_path, embeddings_path)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError("임베딩 인덱스 파일이 없습니다: " + ", ".join(missing))

        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("format_version") != INDEX_FORMAT_VERSION:
            raise ValueError("지원하지 않는 KOSIS 임베딩 인덱스 버전입니다.")
        with tables_path.open(encoding="utf-8-sig", newline="") as handle:
            self.tables = [normalize_table_row(row) for row in csv.DictReader(handle)]
        self.embeddings = np.load(embeddings_path, mmap_mode="r")
        if len(self.tables) != self.embeddings.shape[0]:
            raise ValueError("tables.csv와 embeddings.npy의 행 수가 다릅니다.")
        self.embedder = embedder or SentenceTransformerEmbedder(
            self.manifest["embedding_model"], device=device
        )

    def search(self, query, top_k=50):
        np = _require_numpy()
        if not self.tables or top_k <= 0:
            return []
        query_vector = np.asarray(self.embedder.encode([query]), dtype="float32")[0]
        norm = float(np.linalg.norm(query_vector))
        if norm == 0:
            return []
        query_vector = query_vector / norm
        scores = np.asarray(self.embeddings @ query_vector, dtype="float32")
        top_k = min(top_k, len(scores))
        if top_k == len(scores):
            indices = np.argsort(-scores)
        else:
            indices = np.argpartition(scores, -top_k)[-top_k:]
            indices = indices[np.argsort(-scores[indices])]
        hits = []
        for rank, index in enumerate(indices.tolist(), 1):
            row = self.tables[index]
            hits.append(
                SemanticHit(
                    org_id=row["org_id"],
                    tbl_id=row["tbl_id"],
                    score=float(scores[index]),
                    rank=rank,
                )
            )
        return hits


class SemanticSearchRuntime:
    def __init__(
        self,
        index_dir,
        reranker_model=DEFAULT_RERANKER_MODEL,
        use_reranker=True,
        device=None,
        embedder=None,
        reranker=None,
    ):
        self.index = SemanticTableIndex(index_dir, embedder=embedder, device=device)
        self.reranker_model = reranker_model
        self.use_reranker = use_reranker
        self.device = device
        self._reranker = reranker

    def search(self, query, top_k):
        return self.index.search(query, top_k=top_k)

    def rerank(self, query, table_rows):
        if not table_rows:
            return []
        if not self.use_reranker:
            return [None] * len(table_rows)
        if self._reranker is None:
            self._reranker = TransformerReranker(
                self.reranker_model,
                device=self.device,
            )
        return self._reranker.score(
            query,
            [build_table_document(row) for row in table_rows],
        )


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_semantic_index(
    table_index,
    out_dir,
    embedding_model=DEFAULT_EMBEDDING_MODEL,
    batch_size=16,
    device=None,
    embedder=None,
    force=False,
):
    np = _require_numpy()
    table_index = Path(table_index)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with table_index.open(encoding="utf-8-sig", newline="") as handle:
        tables = [normalize_table_row(row) for row in csv.DictReader(handle)]
    tables = [row for row in tables if all(table_key(row))]
    if not tables:
        raise ValueError("임베딩할 KOSIS 통계표가 없습니다.")

    source_hash = file_sha256(table_index)
    manifest_path = out_dir / "manifest.json"
    embeddings_path = out_dir / "embeddings.npy"
    tables_path = out_dir / "tables.csv"
    progress_path = out_dir / "progress.json"
    if not force and manifest_path.exists() and embeddings_path.exists() and tables_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        reusable = (
            existing.get("format_version") == INDEX_FORMAT_VERSION
            and existing.get("embedding_model") == embedding_model
            and existing.get("source_sha256") == source_hash
            and existing.get("table_count") == len(tables)
        )
        if reusable:
            print(f"index=reused tables={len(tables)} path={out_dir}", flush=True)
            return existing

    with tables_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["org_id", "tbl_id", "tbl_name", "stat_id", "category_path"],
        )
        writer.writeheader()
        writer.writerows(tables)

    embedder = embedder or SentenceTransformerEmbedder(embedding_model, device=device)
    documents = [build_table_document(row) for row in tables]
    start_row = 0
    matrix = None
    if not force and progress_path.exists() and embeddings_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        resumable = (
            progress.get("format_version") == INDEX_FORMAT_VERSION
            and progress.get("embedding_model") == embedding_model
            and progress.get("source_sha256") == source_hash
            and progress.get("table_count") == len(tables)
        )
        if resumable:
            matrix = np.load(embeddings_path, mmap_mode="r+")
            if matrix.shape[0] != len(tables):
                raise ValueError("재개할 임베딩 행렬 크기가 현재 통계표와 다릅니다.")
            start_row = min(int(progress.get("completed_rows", 0)), len(documents))
            print(f"index=resume completed={start_row}/{len(documents)}", flush=True)

    if matrix is None:
        first_end = min(batch_size, len(documents))
        first = np.asarray(
            embedder.encode(documents[:first_end], batch_size=batch_size), dtype="float32"
        )
        if first.ndim != 2:
            raise ValueError("임베딩 모델 출력은 2차원 배열이어야 합니다.")
        matrix = np.lib.format.open_memmap(
            embeddings_path,
            mode="w+",
            dtype="float32",
            shape=(len(documents), first.shape[1]),
        )
        matrix[:first_end] = first
        matrix.flush()
        start_row = first_end
        progress_path.write_text(
            json.dumps(
                {
                    "format_version": INDEX_FORMAT_VERSION,
                    "embedding_model": embedding_model,
                    "source_sha256": source_hash,
                    "table_count": len(tables),
                    "dimension": int(first.shape[1]),
                    "completed_rows": start_row,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"embedded={start_row}/{len(documents)}", flush=True)

    report_every = max(batch_size, 1000)
    next_report = start_row + report_every
    for start in range(start_row, len(documents), batch_size):
        end = min(start + batch_size, len(documents))
        matrix[start:end] = np.asarray(
            embedder.encode(documents[start:end], batch_size=batch_size),
            dtype="float32",
        )
        if end >= next_report or end == len(documents):
            matrix.flush()
            progress_path.write_text(
                json.dumps(
                    {
                        "format_version": INDEX_FORMAT_VERSION,
                        "embedding_model": embedding_model,
                        "source_sha256": source_hash,
                        "table_count": len(tables),
                        "dimension": int(matrix.shape[1]),
                        "completed_rows": end,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"embedded={end}/{len(documents)}", flush=True)
            next_report = end + report_every
    matrix.flush()

    manifest = {
        "format_version": INDEX_FORMAT_VERSION,
        "embedding_model": embedding_model,
        "table_count": len(tables),
        "dimension": int(matrix.shape[1]),
        "source_file": table_index.name,
        "source_sha256": source_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    progress_path.unlink(missing_ok=True)
    return manifest
