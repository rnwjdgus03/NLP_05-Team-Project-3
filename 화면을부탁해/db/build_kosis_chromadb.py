from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = ["ORG_ID", "TBL_ID", "TBL_NM", "STAT_ID", "path"]
DEFAULT_COLLECTION = "kosis_tables"
DEFAULT_MODEL = "intfloat/multilingual-e5-small"

DROP_PATH_PARTS = {
    "국내통계",
    "주제별 통계",
    "기관별 통계",
    "통계표",
}

# 경로의 한 단계 전체가 연도/기간일 때만 제거한다.
# 예: "2010년~", "1970~2009년", "2008년 이후", "2006"
YEAR_ONLY_PATTERNS = [
    re.compile(r"^(?:19|20)\d{2}년?$"),
    re.compile(r"^(?:19|20)\d{2}년?\s*(?:이후|이전|부터|까지)$"),
    re.compile(r"^(?:19|20)\d{2}년?\s*[~-]\s*$"),
    re.compile(r"^(?:19|20)\d{2}년?\s*[~-]\s*(?:19|20)\d{2}년?$"),
]


def normalize_path(value: object) -> str:
    """KOSIS 분류 경로를 검색용 텍스트로 정규화한다."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return ""

    parts = re.split(r"\s*(?:>|/|→|│|\|)\s*", text)
    normalized_parts: list[str] = []

    for part in parts:
        part = re.sub(r"\s+", " ", part).strip(" -–—·ㆍ:;")
        if not part or part in DROP_PATH_PARTS:
            continue
        if any(pattern.fullmatch(part) for pattern in YEAR_ONLY_PATTERNS):
            continue
        if part not in normalized_parts:
            normalized_parts.append(part)

    return " ".join(normalized_parts)


def make_document(table_name: str, normalized_path: str) -> str:
    """E5 계열 모델용 passage 문서를 만든다."""
    fields = [f"통계표명: {table_name.strip()}"]
    if normalized_path:
        fields.append(f"분류경로: {normalized_path}")
    return "passage: " + "\n".join(fields)


def make_query_text(
    query: str | None,
    indicator: str | None,
    keyword: str | None,
    region: str | None,
    population: str | None,
) -> str:
    fields: list[str] = []
    if indicator:
        fields.append(f"지표: {indicator.strip()}")
    if keyword:
        fields.append(f"통계 검색어: {keyword.strip()}")
    if region:
        fields.append(f"지역: {region.strip()}")
    if population:
        fields.append(f"모집단: {population.strip()}")
    if query:
        fields.append(f"기사 주장: {query.strip()}")
    if not fields:
        raise ValueError("검색어 또는 지표명 중 하나 이상을 입력해야 합니다.")
    return "query: " + "\n".join(fields)


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_source(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        input_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"필수 컬럼이 없습니다: {missing}\n"
            f"현재 컬럼: {df.columns.tolist()}"
        )

    df = df[REQUIRED_COLUMNS].copy()
    blank_counts = (df == "").sum()
    if int(blank_counts.sum()) > 0:
        details = ", ".join(
            f"{column}={int(count)}"
            for column, count in blank_counts.items()
            if count
        )
        raise ValueError(f"빈 값이 있습니다: {details}")

    record_ids = df["ORG_ID"] + "::" + df["TBL_ID"]
    duplicated = record_ids.duplicated(keep=False)
    if duplicated.any():
        examples = record_ids[duplicated].head(5).tolist()
        raise ValueError(f"ORG_ID::TBL_ID 중복이 있습니다. 예: {examples}")

    df["path_normalized"] = df["path"].map(normalize_path)
    df["document"] = [
        make_document(name, path)
        for name, path in zip(df["TBL_NM"], df["path_normalized"])
    ]
    df["record_id"] = record_ids
    return df


def load_embedder(model_name: str, device: str | None):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers가 설치되지 않았습니다. "
            "`pip install -r requirements.txt`를 먼저 실행하세요."
        ) from exc

    kwargs = {"device": device} if device else {}
    return SentenceTransformer(model_name, **kwargs)


def load_chroma():
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError(
            "chromadb가 설치되지 않았습니다. "
            "`pip install -r requirements.txt`를 먼저 실행하세요."
        ) from exc
    return chromadb


def build(args: argparse.Namespace) -> None:
    try:
        from tqdm import tqdm
    except ImportError as exc:
        raise RuntimeError(
            "tqdm이 설치되지 않았습니다. "
            "`pip install -r requirements.txt`를 먼저 실행하세요."
        ) from exc

    input_path = Path(args.input).expanduser().resolve()
    db_path = Path(args.db_path).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")
    if args.batch_size < 1:
        raise ValueError("--batch-size는 1 이상이어야 합니다.")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit은 1 이상이어야 합니다.")

    chromadb = load_chroma()
    db_path.mkdir(parents=True, exist_ok=True)
    progress_path = db_path / f".{args.collection}.progress.json"

    client = chromadb.PersistentClient(path=str(db_path))
    if args.reset:
        try:
            client.delete_collection(args.collection)
        except Exception:
            pass
        progress_path.unlink(missing_ok=True)

    collection_metadata = {
        "description": "KOSIS 통계표 후보 검색 인덱스",
        "embedding_model": args.model,
    }
    collection = client.get_or_create_collection(
        name=args.collection,
        metadata=collection_metadata,
        configuration={"hnsw": {"space": "cosine"}},
    )
    saved_model = (collection.metadata or {}).get("embedding_model")
    if saved_model and saved_model != args.model:
        raise ValueError(
            f"기존 컬렉션 모델은 {saved_model!r}, 현재 모델은 {args.model!r}입니다. "
            "같은 모델을 사용하거나 새 컬렉션 이름을 지정하세요."
        )

    fingerprint = file_fingerprint(input_path)
    start = 0
    if progress_path.exists():
        state = json.loads(progress_path.read_text(encoding="utf-8"))
        if state.get("source_sha256") != fingerprint:
            raise ValueError(
                "기존 진행 기록과 입력 파일이 다릅니다. "
                "새 컬렉션을 사용하거나 --reset으로 다시 만드세요."
            )
        if state.get("model") != args.model:
            raise ValueError(
                "기존 진행 기록과 임베딩 모델이 다릅니다. "
                "새 컬렉션을 사용하거나 --reset으로 다시 만드세요."
            )
        start = int(state.get("next_offset", 0))

    print(f"입력 읽는 중: {input_path}")
    df = load_source(input_path)
    target_end = len(df) if args.limit is None else min(len(df), args.limit)
    if start >= target_end:
        print(
            f"추가 처리할 행이 없습니다. "
            f"컬렉션 레코드 수: {collection.count():,}"
        )
        return

    embedder = load_embedder(args.model, args.device)
    selected = df.iloc[start:target_end]

    progress = tqdm(
        range(0, len(selected), args.batch_size),
        total=(len(selected) + args.batch_size - 1) // args.batch_size,
        desc="ChromaDB 구축",
        unit="batch",
    )
    for relative_start in progress:
        batch_df = selected.iloc[
            relative_start : relative_start + args.batch_size
        ]
        documents = batch_df["document"].tolist()
        embeddings = embedder.encode(
            documents,
            batch_size=args.encode_batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        metadatas = [
            {
                "org_id": row.ORG_ID,
                "tbl_id": row.TBL_ID,
                "stat_id": row.STAT_ID,
                "tbl_nm": row.TBL_NM,
                "path_raw": row.path,
                "path_normalized": row.path_normalized,
            }
            for row in batch_df.itertuples(index=False)
        ]
        collection.upsert(
            ids=batch_df["record_id"].tolist(),
            embeddings=embeddings.tolist(),
            documents=documents,
            metadatas=metadatas,
        )

        next_offset = start + relative_start + len(batch_df)
        progress_path.write_text(
            json.dumps(
                {
                    "input": str(input_path),
                    "source_sha256": fingerprint,
                    "model": args.model,
                    "collection": args.collection,
                    "next_offset": next_offset,
                    "source_rows": len(df),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        progress.set_postfix(
            indexed=f"{next_offset:,}/{len(df):,}",
            stored=f"{collection.count():,}",
        )

    print(f"\n완료: {collection.count():,}개 레코드")
    print(f"DB 경로: {db_path}")
    print(f"컬렉션: {args.collection}")


def query(args: argparse.Namespace) -> None:
    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"ChromaDB 경로를 찾을 수 없습니다: {db_path}")
    if args.top_k < 1:
        raise ValueError("--top-k는 1 이상이어야 합니다.")

    chromadb = load_chroma()
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_collection(name=args.collection)
    saved_model = (collection.metadata or {}).get("embedding_model")
    model_name = args.model or saved_model or DEFAULT_MODEL
    if saved_model and args.model and saved_model != args.model:
        raise ValueError(
            f"컬렉션 모델은 {saved_model!r}인데 --model은 {args.model!r}입니다."
        )

    query_text = make_query_text(
        query=args.query,
        indicator=args.indicator,
        keyword=args.keyword,
        region=args.region,
        population=args.population,
    )
    embedder = load_embedder(model_name, args.device)
    query_embedding = embedder.encode(
        [query_text],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )[0]

    result = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=args.top_k,
        include=["metadatas", "documents", "distances"],
    )
    rows: list[dict] = []
    ids = result["ids"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    for rank, (record_id, metadata, distance) in enumerate(
        zip(ids, metadatas, distances),
        start=1,
    ):
        rows.append(
            {
                "rank": rank,
                "similarity": round(1.0 - float(distance), 6),
                "record_id": record_id,
                **metadata,
            }
        )

    output_df = pd.DataFrame(rows)
    display_columns = [
        "rank",
        "similarity",
        "ORG_ID",
        "TBL_ID",
        "TBL_NM",
        "path",
    ]
    terminal_df = output_df.rename(
        columns={
            "org_id": "ORG_ID",
            "tbl_id": "TBL_ID",
            "tbl_nm": "TBL_NM",
            "path_raw": "path",
        }
    )
    print(terminal_df[display_columns].to_string(index=False))

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        terminal_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n후보 저장: {output_path}")


def preview(args: argparse.Namespace) -> None:
    input_path = Path(args.input).expanduser().resolve()
    df = load_source(input_path)
    preview_df = df[
        [
            "ORG_ID",
            "TBL_ID",
            "TBL_NM",
            "STAT_ID",
            "path",
            "path_normalized",
            "document",
        ]
    ].head(args.rows)
    print(preview_df.to_string(index=False))

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        preview_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n미리보기 저장: {output_path}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KOSIS 통계표 CSV로 ChromaDB 후보 검색 인덱스를 구축합니다."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="ChromaDB 구축/이어받기")
    build_parser.add_argument("--input", required=True, help="KOSIS CSV 경로")
    build_parser.add_argument("--db-path", default="./kosis_chroma_db")
    build_parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    build_parser.add_argument("--model", default=DEFAULT_MODEL)
    build_parser.add_argument("--device", choices=["cpu", "cuda", "mps"])
    build_parser.add_argument("--batch-size", type=int, default=256)
    build_parser.add_argument("--encode-batch-size", type=int, default=64)
    build_parser.add_argument(
        "--limit",
        type=int,
        help="원본의 앞 N행까지만 구축합니다. 시험 실행 후 생략하면 이어서 전체 구축합니다.",
    )
    build_parser.add_argument(
        "--reset",
        action="store_true",
        help="동일 이름 컬렉션과 진행 기록을 삭제하고 처음부터 다시 만듭니다.",
    )
    build_parser.set_defaults(func=build)

    query_parser = subparsers.add_parser("query", help="Top-K 후보 검색")
    query_parser.add_argument("--db-path", default="./kosis_chroma_db")
    query_parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    query_parser.add_argument("--model")
    query_parser.add_argument("--device", choices=["cpu", "cuda", "mps"])
    query_parser.add_argument("--query", help="기사 주장 문장")
    query_parser.add_argument("--indicator", help="추출된 지표명")
    query_parser.add_argument("--keyword", help="KOSIS 검색 키워드")
    query_parser.add_argument("--region", help="지역")
    query_parser.add_argument("--population", help="모집단")
    query_parser.add_argument("--top-k", type=int, default=20)
    query_parser.add_argument("--output", help="후보 CSV 저장 경로")
    query_parser.set_defaults(func=query)

    preview_parser = subparsers.add_parser(
        "preview", help="정규화·임베딩 문서 미리보기"
    )
    preview_parser.add_argument("--input", required=True)
    preview_parser.add_argument("--rows", type=int, default=10)
    preview_parser.add_argument("--output")
    preview_parser.set_defaults(func=preview)
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("\n중단되었습니다. 다음 실행에서 마지막 완료 배치부터 이어받습니다.")
        return 130
    except Exception as exc:
        print(f"\n실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
