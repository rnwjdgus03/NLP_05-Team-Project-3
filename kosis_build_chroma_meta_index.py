#!/usr/bin/env python3
"""KOSIS 메타 CSV → ChromaDB 영속 좌표 인덱스 생성.

좌표 구성/문서화/메타데이터는 kosis_meta_coordinates.py 가 담당하고(순수 로직),
이 스크립트는 임베딩 계산과 Chroma 적재만 맡는다.

embedding 은 BGE-M3 로 **미리 계산해서 직접 저장**한다. Chroma 의 기본 임베딩 함수를
쓰지 않으므로 모델과 차원이 manifest 로 고정된다.

사용법(Colab GPU 권장):
  python kosis_build_chroma_meta_index.py \
    --meta-index 05_hcx_measurements_kosis_meta_index.csv \
    --persist-dir data/indexes/kosis_meta_chroma \
    --collection kosis_meta_coordinates \
    --embedding-model BAAI/bge-m3 \
    --device cuda
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from kosis_meta_coordinates import (
    SCHEMA_VERSION,
    build_coordinates,
    coordinate_document,
    coordinate_metadata,
    read_csv_rows,
)
from kosis_semantic_search import DEFAULT_EMBEDDING_MODEL, file_sha256

MANIFEST_NAME = "chroma_manifest.json"


def load_prd_se_by_table(path: str | None) -> dict[tuple[str, str], str]:
    """통계표별 수록주기(prd_se) 힌트. 후보 CSV 등에서 (org_id, tbl_id) → prd_se 를 읽는다."""
    if not path:
        return {}
    mapping: dict[tuple[str, str], str] = {}
    for row in read_csv_rows(path):
        org = str(row.get("org_id") or "").strip()
        tbl = str(row.get("tbl_id") or "").strip()
        prd = str(row.get("prd_se") or row.get("PRD_SE") or "").strip()
        if org and tbl and prd:
            mapping.setdefault((org, tbl), prd)
    return mapping


def build_documents(meta_rows, *, axis_value_limit, max_coordinates_per_table,
                    prd_se_by_table=None):
    coordinates = build_coordinates(
        meta_rows,
        axis_value_limit=axis_value_limit,
        max_coordinates_per_table=max_coordinates_per_table,
        prd_se_by_table=prd_se_by_table,
    )
    ids, documents, metadatas = [], [], []
    seen = set()
    for coordinate in coordinates:
        cid = coordinate["coordinate_id"]
        if cid in seen:   # 같은 좌표는 한 번만 (재생성 시 결정적)
            continue
        seen.add(cid)
        ids.append(cid)
        documents.append(coordinate_document(coordinate))
        metadatas.append(coordinate_metadata(coordinate))
    return ids, documents, metadatas


def embedding_fingerprint(ids, vectors, decimals: int = 6) -> tuple[str, str]:
    """임베딩의 지문 두 개. (원본, 반올림)

    두 지문을 함께 남기는 이유:
      원본만 다르고 반올림이 같다  → 부동소수점 오차. 좌표 자체는 동일하다.
      둘 다 다르다                 → 입력이나 모델이 실제로 바뀌었다.
    이 구분이 없으면 '재빌드했는데 결과가 달라졌다'의 원인을 짚을 수 없다(실측).
    """
    raw = hashlib.sha256()
    rounded = hashlib.sha256()
    for key, vector in sorted(zip(ids, vectors), key=lambda pair: pair[0]):
        raw.update(key.encode("utf-8"))
        rounded.update(key.encode("utf-8"))
        array = np.asarray(vector, dtype=np.float32)
        raw.update(array.tobytes())
        rounded.update(np.round(array, decimals).tobytes())
    return raw.hexdigest()[:32], rounded.hexdigest()[:32]


def write_manifest(persist_dir: Path, payload: dict) -> Path:
    path = persist_dir / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a persistent ChromaDB index of KOSIS coordinates")
    parser.add_argument("--meta-index", required=True)
    parser.add_argument("--persist-dir", default="data/indexes/kosis_meta_chroma")
    parser.add_argument("--collection", default="kosis_meta_coordinates")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--torch-threads",
        type=int,
        default=0,
        help="CPU 추론 스레드 수. 0이면 PyTorch 기본값",
    )
    parser.add_argument("--axis-value-limit", type=int, default=40)
    parser.add_argument("--max-coordinates-per-table", type=int, default=4000)
    parser.add_argument("--prd-se-source", default=None,
                        help="(org_id, tbl_id) → prd_se 힌트를 가진 CSV (예: table_candidates)")
    parser.add_argument("--reset", action="store_true", help="같은 이름의 collection 을 지우고 다시 만든다")
    args = parser.parse_args()

    if args.torch_threads > 0:
        import torch

        torch.set_num_threads(min(args.torch_threads, os.cpu_count() or args.torch_threads))
        print(f"torch_threads={torch.get_num_threads()}", flush=True)

    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise SystemExit("chromadb 가 필요합니다: pip install chromadb") from exc
    from kosis_semantic_search import SentenceTransformerEmbedder

    meta_rows = read_csv_rows(args.meta_index)
    ids, documents, metadatas = build_documents(
        meta_rows,
        axis_value_limit=args.axis_value_limit,
        max_coordinates_per_table=args.max_coordinates_per_table,
        prd_se_by_table=load_prd_se_by_table(args.prd_se_source),
    )
    if not ids:
        raise SystemExit("좌표 문서가 0개입니다. --meta-index 를 확인하세요.")
    print(f"meta_rows={len(meta_rows)} coordinates={len(ids)}")

    embedder = SentenceTransformerEmbedder(args.embedding_model, device=args.device)
    vectors = embedder.encode(documents, batch_size=args.batch_size, show_progress_bar=True)
    dimension = int(vectors.shape[1])

    persist_dir = Path(args.persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    if args.reset:
        try:
            client.delete_collection(args.collection)
        except Exception:
            pass
    else:
        try:
            existing = client.get_collection(args.collection)
        except Exception:
            existing = None
        if existing is not None and existing.count():
            raise SystemExit(
                f"collection={args.collection} 에 기존 문서 {existing.count()}개가 있습니다. "
                "재현 가능한 재생성을 위해 --reset 을 사용하세요."
            )
    collection = client.get_or_create_collection(
        name=args.collection, metadata={"hnsw:space": "cosine"}
    )
    for start in range(0, len(ids), 1000):
        stop = start + 1000
        collection.upsert(
            ids=ids[start:stop],
            documents=documents[start:stop],
            metadatas=metadatas[start:stop],
            embeddings=[v.tolist() for v in vectors[start:stop]],
        )

    raw_fp, rounded_fp = embedding_fingerprint(ids, vectors)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "embedding_model": args.embedding_model,
        "embedding_dimension": dimension,
        "normalized": True,   # SentenceTransformerEmbedder 가 normalize_embeddings=True
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_meta_file": str(args.meta_index),
        "source_meta_sha256": file_sha256(args.meta_index),
        # 2026-08-02: 같은 입력으로 재빌드했는데 골드 recall 이 ±1건 흔들렸다.
        # source_meta_sha256 과 document_count 는 양쪽 다 같아서 원인을 못 짚었다.
        # 임베딩 자체를 지문으로 남겨 '인덱스가 정말 같은가'를 사후 확인 가능하게 한다.
        "embedding_fingerprint": raw_fp,
        "embedding_fingerprint_rounded": rounded_fp,
        "document_count": len(ids),
        "collection": args.collection,
        "axis_value_limit": args.axis_value_limit,
        "max_coordinates_per_table": args.max_coordinates_per_table,
    }
    path = write_manifest(persist_dir, manifest)
    print(f"saved collection={args.collection} documents={len(ids)} dim={dimension}")
    print(f"manifest={path}")


if __name__ == "__main__":
    main()
