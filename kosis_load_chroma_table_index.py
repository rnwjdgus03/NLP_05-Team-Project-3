#!/usr/bin/env python3
"""Load an existing BGE KOSIS table index into persistent ChromaDB.

The dense vectors are reused verbatim, so loading does not recompute BGE
embeddings. Re-running is safe because rows are upserted by stable table ID.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from kosis_semantic_search import INDEX_FORMAT_VERSION, build_table_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Load KOSIS BGE table vectors into ChromaDB")
    parser.add_argument("--semantic-index", default="data/indexes/kosis_bge_m3")
    parser.add_argument("--persist-dir", default="data/indexes/kosis_table_chroma")
    parser.add_argument("--collection", default="kosis_table")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    import chromadb

    source_dir = Path(args.semantic_index)
    source_manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("format_version") != INDEX_FORMAT_VERSION:
        raise SystemExit("지원하지 않는 BGE 표 인덱스 버전입니다.")

    with (source_dir / "tables.csv").open(encoding="utf-8-sig", newline="") as handle:
        tables = list(csv.DictReader(handle))
    embeddings = np.load(source_dir / "embeddings.npy", mmap_mode="r")
    if len(tables) != embeddings.shape[0]:
        raise SystemExit("tables.csv와 embeddings.npy의 행 수가 다릅니다.")

    persist_dir = Path(args.persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    if args.reset:
        try:
            client.delete_collection(args.collection)
        except Exception:
            pass
    collection = client.get_or_create_collection(
        name=args.collection,
        metadata={"hnsw:space": "cosine"},
    )

    for start in range(0, len(tables), args.batch_size):
        stop = min(start + args.batch_size, len(tables))
        batch = tables[start:stop]
        ids = [f"{row['org_id']}::{row['tbl_id']}" for row in batch]
        documents = [build_table_document(row) for row in batch]
        metadatas = [
            {
                "org_id": row.get("org_id", ""),
                "tbl_id": row.get("tbl_id", ""),
                "tbl_name": row.get("tbl_name", ""),
                "stat_id": row.get("stat_id", ""),
                "category_path": row.get("category_path", ""),
            }
            for row in batch
        ]
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=np.asarray(embeddings[start:stop], dtype="float32").tolist(),
        )
        print(f"loaded={stop}/{len(tables)}", flush=True)

    manifest = {
        "format_version": 1,
        "collection": args.collection,
        "embedding_model": source_manifest["embedding_model"],
        "embedding_dimension": int(embeddings.shape[1]),
        "document_count": len(tables),
        "source_semantic_index": str(source_dir),
        "source_sha256": source_manifest.get("source_sha256", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (persist_dir / "chroma_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"collection={args.collection} count={collection.count()} persist_dir={persist_dir}",
        flush=True,
    )


if __name__ == "__main__":
    main()
