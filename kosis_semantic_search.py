"""Dense retrieval and cross-encoder reranking for KOSIS table search.

The semantic layer only proposes table candidates.  Measurement eligibility,
ITEM/OBJ compatibility, period checks, and READY/REVIEW/REJECT decisions stay
in ``kosis_match_claims_to_index.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_EMBEDDING_REVISION = "5617a9f"
DEFAULT_RERANKER_REVISION = "953dc6f"
INDEX_FORMAT_VERSION = 2
DOCUMENT_SCHEMA_VERSION = 1
SURVEY_NAME_HINTS = (
    "경제활동인구조사", "지역별고용조사", "인구동향조사", "인구동향통계",
    "인구동향", "기업특성별무역통계", "기업특성별 무역통계", "무역통계",
    "광업제조업조사", "서비스업동향조사", "소비자물가조사", "가계동향조사",
    "농림어업조사", "사회조사", "전국사업체조사", "인구주택총조사",
    "장래인구추계", "국제수지",
)

_SURVEY_PHRASE = re.compile(
    r"[‘'\"“]?(?P<name>[가-힣A-Za-z0-9· ]{2,40}?(?:수급\s*)?(?:실태\s*)?조사)[’'\"”]?"
)


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


def survey_hints_from_claim(claim):
    explicit = [
        str(claim.get(key, "") or "").strip()
        for key in ("survey_name", "statistics_name", "stat_name", "source_survey")
    ]
    text = " ".join(
        str(claim.get(key, "") or "")
        for key in ("title", "claim_text", "context_before", "context_after")
    )
    compact = re.sub(r"\s+", "", text)
    found = []
    for value in explicit:
        if value and value != "-":
            found.extend(part.strip() for part in value.split("|") if part.strip())
    for name in SURVEY_NAME_HINTS:
        if re.sub(r"\s+", "", name) in compact:
            found.append(name)
    for match in _SURVEY_PHRASE.finditer(text):
        name = re.sub(r"\s+", "", match.group("name")).strip()
        if 3 <= len(name) <= 30:
            found.append(name)
    return tuple(dict.fromkeys(found))


def target_axes_from_claim(claim):
    terms = []
    for key in (
        "obj_target_terms", "target_axes", "destination_country", "origin_country",
        "region", "age_group", "gender", "industry_or_item", "measurement_item",
    ):
        raw = str(claim.get(key, "") or "").strip()
        if not raw or raw == "-":
            continue
        terms.extend(part.strip() for part in re.split(r"[|,]", raw) if part.strip())
    return tuple(dict.fromkeys(terms))


def table_target_axes_from_claim(claim):
    """Return only grounded axes useful for table-level retrieval.

    ``obj_target_terms`` is intentionally excluded here.  It is produced for
    coordinate selection and can contain narrative words such as "record" or
    "increase" that pull a table embedding away from the requested statistic.
    """
    terms = []
    for key in (
        "destination_country", "origin_country", "region", "age_group",
        "gender", "industry_or_item", "measurement_item",
    ):
        raw = str(claim.get(key, "") or "").strip()
        if not raw or raw == "-":
            continue
        terms.extend(part.strip() for part in re.split(r"[|,]", raw) if part.strip())
    return tuple(dict.fromkeys(terms))


def _positive_scope_hints(claim):
    focused = "".join(
        str(claim.get(key, "") or "")
        for key in ("indicator", "industry_or_item", "claim_text", "keywords")
    ).replace(" ", "")
    hints = []
    if any(token in focused for token in ("수출", "수입", "무역수지")):
        hints.append("대한민국 무역통계 품목별 수출액 수입액")
    if "산업기술인력" in focused:
        hints.append("산업기술인력수급실태조사 산업별 현재인원")
    if any(token in focused for token in ("신기술도입", "기술도입", "혁신도입")):
        hints.append("기업규모별 기술 도입 현황 비율")
        if any(token in focused for token in ("로봇", "인공지능", "AI", "4차산업")):
            hints.append(
                "기업활동조사 기업규모별 4차 산업혁명 관련 기술 개발 활용 도입 비율"
            )
    return tuple(hints)


def build_table_search_queries(claim):
    """Build short positive-only BGE-M3 queries and keep distinct views.

    Table documents contain only a table name and category path, so values,
    dates, units, and exclusion prose are retrieval noise.  Multiple focused
    views recover generic tables whose concrete item lives in ITEM/OBJ metadata.
    """
    indicator = str(claim.get("indicator", "") or "").strip()
    targets = "; ".join(table_target_axes_from_claim(claim))
    surveys = "; ".join(survey_hints_from_claim(claim))
    queries = []

    metric_parts = [indicator, targets]
    metric = " ".join(part for part in metric_parts if part and part != "-")
    if metric:
        queries.append(f"통계표: {metric}")

    path_text = surveys
    if path_text:
        queries.append(f"분류경로: {path_text} | 통계표: {indicator}")

    queries.extend(
        f"통계표: {hint} | 분류경로: {hint}"
        for hint in _positive_scope_hints(claim)
    )
    if not queries:
        fallback = str(claim.get("claim_text", "") or "").strip()[:220]
        if fallback:
            queries.append(f"통계표: {fallback}")
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def build_claim_query(claim):
    scope_hints = list(_positive_scope_hints(claim))
    fields = [
        ("조사명", "; ".join(survey_hints_from_claim(claim))),
        ("지표", claim.get("indicator", "")),
        ("대상", claim.get("industry_or_item", "")),
        ("대상축", "; ".join(table_target_axes_from_claim(claim))),
        ("의미", claim.get("semantic_type", "")),
        ("단위", claim.get("unit", "")),
        ("단위차원", claim.get("unit_dimension", "")),
        ("대상유형", claim.get("entity_type", "")),
        ("주기", claim.get("prd_se", "")),
        ("검색범위", "; ".join(scope_hints)),
        ("문장", str(claim.get("claim_text", "") or "")[:320]),
    ]
    return " | ".join(
        f"{label}: {str(value).strip()}"
        for label, value in fields
        if str(value or "").strip() not in {"", "-"}
    )


def build_early_claim_query(claim, neighbor_limit=500):
    """Build a semantic query before measurement-level structuring.

    The claim sentence remains the primary signal. Title and neighboring
    sentences provide disambiguating context, but article date is deliberately
    excluded so retrieval cannot turn publication time into a measurement
    period.
    """

    def cleaned(key, limit):
        value = str(claim.get(key, "") or "").strip()
        if value in {"", "-"}:
            return ""
        return value[:limit]

    shared_context = re.sub(
        r"(?mi)^\[publication_date\][^\n]*(?:\n|$)",
        "",
        cleaned("article_context", 1200),
    ).strip()
    fields = [
        ("claim", cleaned("claim_text", 1200)),
        ("title", cleaned("title", 300)),
        ("major_targets", cleaned("major_target_hints", 400)),
        ("shared_article_context", shared_context[:1000]),
        ("claim_local_context", cleaned("local_context", 1400)),
        ("related_article_context", cleaned("antecedent_context", 900)),
        ("previous_context", cleaned("prev_sentence", neighbor_limit)),
        ("next_context", cleaned("next_sentence", neighbor_limit)),
    ]
    return " | ".join(f"{label}: {value}" for label, value in fields if value)


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


def _atomic_write_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def inspect_embedding_matrix(matrix, *, expected_rows=None, chunk_rows=2048):
    """Scan an embedding matrix without materializing the full file in RAM."""
    np = _require_numpy()
    if matrix.ndim != 2:
        raise ValueError(f"embedding matrix must be 2-D, got {matrix.shape}")
    if expected_rows is not None and matrix.shape[0] != expected_rows:
        raise ValueError(
            f"embedding row mismatch: expected={expected_rows}, actual={matrix.shape[0]}"
        )
    zero_vectors = 0
    nonfinite_vectors = 0
    min_norm = float("inf")
    max_norm = 0.0
    for start in range(0, matrix.shape[0], chunk_rows):
        block = np.asarray(matrix[start : start + chunk_rows], dtype="float32")
        finite_rows = np.isfinite(block).all(axis=1)
        nonfinite_vectors += int((~finite_rows).sum())
        safe = np.where(np.isfinite(block), block, 0.0)
        norms = np.linalg.norm(safe, axis=1)
        zero_vectors += int((norms <= 1e-8).sum())
        if len(norms):
            min_norm = min(min_norm, float(norms.min()))
            max_norm = max(max_norm, float(norms.max()))
    return {
        "row_count": int(matrix.shape[0]),
        "dimension": int(matrix.shape[1]),
        "zero_vector_count": zero_vectors,
        "nonfinite_vector_count": nonfinite_vectors,
        "min_norm": 0.0 if min_norm == float("inf") else min_norm,
        "max_norm": max_norm,
    }


def require_complete_embedding_matrix(matrix, *, expected_rows):
    stats = inspect_embedding_matrix(matrix, expected_rows=expected_rows)
    if stats["zero_vector_count"] or stats["nonfinite_vector_count"]:
        raise ValueError(
            "incomplete/corrupt semantic index: "
            f"zero_vectors={stats['zero_vector_count']}, "
            f"nonfinite_vectors={stats['nonfinite_vector_count']}, "
            f"rows={stats['row_count']}"
        )
    return stats


class SentenceTransformerEmbedder:
    def __init__(
        self, model_name=DEFAULT_EMBEDDING_MODEL, device=None,
        revision=DEFAULT_EMBEDDING_REVISION,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "임베딩 모델을 사용하려면 requirements-ml.txt를 설치하세요."
            ) from exc
        self.model_name = model_name
        self.revision = revision
        self.model = SentenceTransformer(model_name, device=device, revision=revision)
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
        revision=DEFAULT_RERANKER_REVISION,
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
        self.revision = revision
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name, revision=revision
        )
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
        if self.manifest.get("status") != "complete":
            raise ValueError("완료되지 않은 KOSIS 임베딩 인덱스입니다.")
        if self.manifest.get("document_schema_version") != DOCUMENT_SCHEMA_VERSION:
            raise ValueError("KOSIS 임베딩 문서 스키마 버전이 일치하지 않습니다.")
        if file_sha256(tables_path) != self.manifest.get("tables_sha256"):
            raise ValueError("tables.csv와 임베딩 manifest의 해시가 일치하지 않습니다.")
        expected_embeddings_hash = self.manifest.get("embeddings_sha256")
        if expected_embeddings_hash and file_sha256(embeddings_path) != expected_embeddings_hash:
            raise ValueError("embeddings.npy와 임베딩 manifest의 해시가 일치하지 않습니다.")
        with tables_path.open(encoding="utf-8-sig", newline="") as handle:
            self.tables = [normalize_table_row(row) for row in csv.DictReader(handle)]
        self.embeddings = np.load(embeddings_path, mmap_mode="r")
        if len(self.tables) != self.embeddings.shape[0]:
            raise ValueError("tables.csv와 embeddings.npy의 행 수가 다릅니다.")
        if self.manifest.get("completed_rows") != len(self.tables):
            raise ValueError("manifest가 전체 임베딩 완료를 증명하지 못합니다.")
        require_complete_embedding_matrix(self.embeddings, expected_rows=len(self.tables))
        self._torch = None
        self._accelerated_embeddings = None
        self.search_backend = "numpy-cpu"
        if device and str(device).startswith("cuda"):
            self._enable_cuda_search(device)
        self.embedder = embedder or SentenceTransformerEmbedder(
            self.manifest["embedding_model"], device=device,
            revision=self.manifest.get(
                "embedding_revision", DEFAULT_EMBEDDING_REVISION
            ),
        )

    def _enable_cuda_search(self, device):
        """Keep the table matrix on GPU so every claim does not scan it on CPU."""
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("CUDA semantic search requires torch") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA semantic search was requested but CUDA is unavailable")
        try:
            matrix = torch.from_numpy(self.embeddings).to(
                device=device, dtype=torch.float32
            )
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError("failed to preload semantic embeddings on CUDA") from exc
        self._torch = torch
        self._accelerated_embeddings = matrix
        self.search_backend = "torch-cuda"
        memory_mib = matrix.numel() * matrix.element_size() / (1024 * 1024)
        print(
            f"semantic_vector_backend=torch-cuda rows={matrix.shape[0]} "
            f"dimension={matrix.shape[1]} memory_mib={memory_mib:.1f}",
            flush=True,
        )

    def _accelerated_scores(self, query_vector, raw_top_k):
        torch = self._torch
        query = torch.as_tensor(
            query_vector,
            dtype=self._accelerated_embeddings.dtype,
            device=self._accelerated_embeddings.device,
        )
        with torch.inference_mode():
            scores = self._accelerated_embeddings @ query
            values, indices = torch.topk(
                scores, k=raw_top_k, largest=True, sorted=True
            )
        return indices.cpu().tolist(), values.float().cpu().tolist()

    def search(self, query, top_k=50):
        np = _require_numpy()
        if not self.tables or top_k <= 0:
            return []
        query_vector = np.asarray(self.embedder.encode([query]), dtype="float32")[0]
        norm = float(np.linalg.norm(query_vector))
        if norm == 0:
            return []
        query_vector = query_vector / norm
        row_count = len(self.tables)
        top_k = min(top_k, row_count)
        raw_top_k = min(row_count, max(top_k * 2, top_k + 50))
        if self._accelerated_embeddings is not None:
            indices, ordered_scores = self._accelerated_scores(query_vector, raw_top_k)
            scores_by_index = dict(zip(indices, ordered_scores))
            score_for = scores_by_index.__getitem__
        else:
            scores = np.asarray(self.embeddings @ query_vector, dtype="float32")
            if raw_top_k == len(scores):
                indices = np.argsort(-scores).tolist()
            else:
                indices = np.argpartition(scores, -raw_top_k)[-raw_top_k:]
                indices = indices[np.argsort(-scores[indices])].tolist()
            score_for = lambda index: float(scores[index])
        # Identical table documents are common across archived table versions.
        # Collapse them before they consume the semantic Top-K budget.
        representatives = {}
        for index in indices:
            row = self.tables[index]
            family = build_table_document(row)
            archived = bool(re.search(r"_(?:19|20)\d{2}$", row["tbl_id"]))
            priority = (archived, row["tbl_id"])
            current = representatives.get(family)
            if current is None or priority < current[0]:
                representatives[family] = (priority, index)
        selected = sorted(
            (entry[1] for entry in representatives.values()),
            key=lambda index: (-score_for(index), self.tables[index]["tbl_id"]),
        )[:top_k]
        hits = []
        for rank, index in enumerate(selected, 1):
            row = self.tables[index]
            hits.append(
                SemanticHit(
                    org_id=row["org_id"],
                    tbl_id=row["tbl_id"],
                    score=score_for(index),
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
        reranker_batch_size=8,
    ):
        self.index = SemanticTableIndex(index_dir, embedder=embedder, device=device)
        self.reranker_model = reranker_model
        self.use_reranker = use_reranker
        self.device = device
        self._reranker = reranker
        self.reranker_batch_size = reranker_batch_size

    def search(self, query, top_k):
        return self.index.search(query, top_k=top_k)

    def search_many(self, queries, top_k):
        """Search each semantic view and merge by reciprocal-rank evidence."""
        merged = {}
        for query_index, query in enumerate(dict.fromkeys(queries)):
            for hit in self.search(query, top_k=top_k):
                entry = merged.setdefault(
                    hit.key,
                    {"hit": hit, "rrf": 0.0, "best_rank": hit.rank, "views": []},
                )
                entry["rrf"] += 1.0 / (60 + hit.rank)
                entry["best_rank"] = min(entry["best_rank"], hit.rank)
                entry["views"].append(query_index)
                if hit.score > entry["hit"].score:
                    entry["hit"] = hit
        ordered = sorted(
            merged.values(),
            key=lambda item: (-item["rrf"], item["best_rank"], -item["hit"].score),
        )[:top_k]
        return [
            SemanticHit(
                org_id=item["hit"].org_id,
                tbl_id=item["hit"].tbl_id,
                score=item["hit"].score,
                rank=rank,
            )
            for rank, item in enumerate(ordered, 1)
        ]

    def rerank(self, query, table_rows):
        if not table_rows:
            return []
        if not self.use_reranker:
            return [None] * len(table_rows)
        if self._reranker is None:
            self._reranker = TransformerReranker(
                self.reranker_model,
                device=self.device,
                batch_size=self.reranker_batch_size,
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
    embedding_revision=DEFAULT_EMBEDDING_REVISION,
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
            and existing.get("status") == "complete"
            and existing.get("document_schema_version") == DOCUMENT_SCHEMA_VERSION
            and existing.get("embedding_model") == embedding_model
            and existing.get("embedding_revision") == embedding_revision
            and existing.get("source_sha256") == source_hash
            and existing.get("table_count") == len(tables)
            and existing.get("completed_rows") == len(tables)
            and existing.get("tables_sha256") == file_sha256(tables_path)
        )
        if reusable:
            try:
                matrix = np.load(embeddings_path, mmap_mode="r")
                require_complete_embedding_matrix(matrix, expected_rows=len(tables))
            except (OSError, ValueError) as exc:
                print(f"index=invalid reason={exc}; rebuilding", flush=True)
            else:
                print(f"index=reused tables={len(tables)} path={out_dir}", flush=True)
                return existing

    # A partial rebuild must never remain discoverable as a complete index.
    manifest_path.unlink(missing_ok=True)
    with tables_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["org_id", "tbl_id", "tbl_name", "stat_id", "category_path"],
        )
        writer.writeheader()
        writer.writerows(tables)
    tables_hash = file_sha256(tables_path)

    embedder = embedder or SentenceTransformerEmbedder(
        embedding_model, device=device, revision=embedding_revision
    )
    documents = [build_table_document(row) for row in tables]
    start_row = 0
    matrix = None
    if not force and progress_path.exists() and embeddings_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        resumable = (
            progress.get("format_version") == INDEX_FORMAT_VERSION
            and progress.get("document_schema_version") == DOCUMENT_SCHEMA_VERSION
            and progress.get("embedding_model") == embedding_model
            and progress.get("embedding_revision") == embedding_revision
            and progress.get("source_sha256") == source_hash
            and progress.get("table_count") == len(tables)
            and progress.get("tables_sha256") == tables_hash
        )
        if resumable:
            matrix = np.load(embeddings_path, mmap_mode="r+")
            start_row = min(int(progress.get("completed_rows", 0)), len(documents))
            prefix_valid = (
                matrix.ndim == 2
                and matrix.shape[0] == len(tables)
                and matrix.shape[1] == int(progress.get("dimension", 0))
            )
            if prefix_valid and start_row:
                prefix_stats = inspect_embedding_matrix(
                    matrix[:start_row], expected_rows=start_row
                )
                prefix_valid = not (
                    prefix_stats["zero_vector_count"]
                    or prefix_stats["nonfinite_vector_count"]
                )
            if prefix_valid:
                print(f"index=resume completed={start_row}/{len(documents)}", flush=True)
            else:
                print("index=invalid-progress; rebuilding", flush=True)
                matrix = None
                start_row = 0

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
        _atomic_write_json(
            progress_path,
            {
                    "format_version": INDEX_FORMAT_VERSION,
                    "document_schema_version": DOCUMENT_SCHEMA_VERSION,
                    "embedding_model": embedding_model,
                    "embedding_revision": embedding_revision,
                    "source_sha256": source_hash,
                    "tables_sha256": tables_hash,
                    "table_count": len(tables),
                    "dimension": int(first.shape[1]),
                    "completed_rows": start_row,
            },
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
            _atomic_write_json(
                progress_path,
                {
                        "format_version": INDEX_FORMAT_VERSION,
                        "document_schema_version": DOCUMENT_SCHEMA_VERSION,
                        "embedding_model": embedding_model,
                        "embedding_revision": embedding_revision,
                        "source_sha256": source_hash,
                        "tables_sha256": tables_hash,
                        "table_count": len(tables),
                        "dimension": int(matrix.shape[1]),
                        "completed_rows": end,
                },
            )
            print(f"embedded={end}/{len(documents)}", flush=True)
            next_report = end + report_every
    matrix.flush()
    integrity = require_complete_embedding_matrix(matrix, expected_rows=len(tables))

    embeddings_hash = file_sha256(embeddings_path)
    manifest = {
        "format_version": INDEX_FORMAT_VERSION,
        "document_schema_version": DOCUMENT_SCHEMA_VERSION,
        "status": "complete",
        "embedding_model": embedding_model,
        "embedding_revision": embedding_revision,
        "table_count": len(tables),
        "completed_rows": len(tables),
        "dimension": int(matrix.shape[1]),
        "source_file": table_index.name,
        "source_sha256": source_hash,
        "tables_sha256": tables_hash,
        "embeddings_sha256": embeddings_hash,
        "integrity": integrity,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(manifest_path, manifest)
    progress_path.unlink(missing_ok=True)
    return manifest
