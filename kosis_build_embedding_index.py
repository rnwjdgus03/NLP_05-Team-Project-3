#!/usr/bin/env python3
"""Build a reusable BGE-M3 dense index for KOSIS table summaries."""

from __future__ import annotations

import argparse

from kosis_semantic_search import DEFAULT_EMBEDDING_MODEL, build_semantic_index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-index", required=True)
    parser.add_argument("--out-dir", default="data/indexes/kosis_bge_m3")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default=None, help="예: cuda, cpu. 기본은 모델 자동 선택")
    parser.add_argument("--force", action="store_true", help="기존 완료·체크포인트를 무시하고 재생성")
    args = parser.parse_args()

    manifest = build_semantic_index(
        args.table_index,
        args.out_dir,
        embedding_model=args.embedding_model,
        batch_size=args.batch_size,
        device=args.device,
        force=args.force,
    )
    print(
        f"saved={args.out_dir} tables={manifest['table_count']} "
        f"dimension={manifest['dimension']} model={manifest['embedding_model']}"
    )


if __name__ == "__main__":
    main()
