#!/usr/bin/env python3
"""Build a persistent ChromaDB index for official KOSIS ITEM/OBJ coordinates."""

from __future__ import annotations

import argparse

from kosis_chroma_coordinate_search import (
    DEFAULT_COLLECTION_NAME,
    build_chroma_coordinate_index,
)
from kosis_semantic_search import DEFAULT_EMBEDDING_MODEL


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta-index", required=True)
    parser.add_argument("--persist-dir", default="data/indexes/kosis_chroma_coordinates")
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-documents", type=int, default=0, help="Limit coordinate documents for quick experiments; 0 means all")
    parser.add_argument("--device", default=None, help="예: cuda, cpu. 기본은 모델 자동 선택")
    parser.add_argument("--force", action="store_true", help="기존 Chroma collection을 재생성")
    args = parser.parse_args()

    manifest = build_chroma_coordinate_index(
        args.meta_index,
        args.persist_dir,
        collection_name=args.collection_name,
        embedding_model=args.embedding_model,
        batch_size=args.batch_size,
        max_documents=args.max_documents,
        device=args.device,
        force=args.force,
    )
    print(
        f"saved={args.persist_dir} collection={manifest['collection_name']} "
        f"documents={manifest['document_count']} "
        f"dimension={manifest['embedding_dimension']} "
        f"model={manifest['embedding_model']}"
    )


if __name__ == "__main__":
    main()
