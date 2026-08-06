from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ["ORG_ID", "TBL_ID", "TBL_NM", "STAT_ID", "path"]
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
STATE_FILE = "state.json"
EMBEDDINGS_FILE = "embeddings.npy"
METADATA_FILE = "metadata.csv"

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
            f"필수 컬럼이 없습니다: {missing}\n현재 컬럼: {df.columns.tolist()}"
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

    df["record_id"] = df["ORG_ID"] + "::" + df["TBL_ID"]
    duplicated = df["record_id"].duplicated(keep=False)
    if duplicated.any():
        examples = df.loc[duplicated, "record_id"].head(5).tolist()
        raise ValueError(f"ORG_ID::TBL_ID 중복이 있습니다. 예: {examples}")

    df["path_normalized"] = df["path"].map(normalize_path)
    df["document"] = [
        make_document(name, path)
        for name, path in zip(df["TBL_NM"], df["path_normalized"])
    ]
    return df


def load_embedder(model_name: str, device: str | None):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers가 설치되지 않았습니다. "
            "`python -m pip install -r requirements.txt`를 먼저 실행하세요."
        ) from exc

    kwargs = {"device": device} if device else {}
    return SentenceTransformer(model_name, **kwargs)


def batch_starts(start: int, end: int, size: int) -> Iterator[int]:
    current = start
    while current < end:
        yield current
        current += size


def atomic_write_json(path: Path, data: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def load_state(index_path: Path) -> dict:
    state_path = index_path / STATE_FILE
    if not state_path.is_file():
        raise FileNotFoundError(
            f"인덱스 상태 파일이 없습니다: {state_path}\n"
            "`build` 명령을 먼저 실행하세요."
        )
    return json.loads(state_path.read_text(encoding="utf-8"))


def reset_index(index_path: Path) -> None:
    for name in [STATE_FILE, EMBEDDINGS_FILE, METADATA_FILE]:
        target = index_path / name
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)


def build(args: argparse.Namespace) -> None:
    input_path = Path(args.input).expanduser().resolve()
    index_path = Path(args.db_path).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")
    if args.batch_size < 1 or args.encode_batch_size < 1:
        raise ValueError("배치 크기는 1 이상이어야 합니다.")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit은 1 이상이어야 합니다.")

    index_path.mkdir(parents=True, exist_ok=True)
    if args.reset:
        reset_index(index_path)

    state_path = index_path / STATE_FILE
    embeddings_path = index_path / EMBEDDINGS_FILE
    metadata_path = index_path / METADATA_FILE

    print(f"입력 읽는 중: {input_path}")
    df = load_source(input_path)
    fingerprint = file_fingerprint(input_path)
    target_end = len(df) if args.limit is None else min(len(df), args.limit)

    if state_path.exists():
        state = load_state(index_path)
        if state.get("source_sha256") != fingerprint:
            raise ValueError(
                "기존 인덱스와 입력 CSV가 다릅니다. "
                "새 --db-path를 쓰거나 --reset으로 다시 만드세요."
            )
        if state.get("model") != args.model:
            raise ValueError(
                f"기존 모델은 {state.get('model')!r}, 현재 모델은 {args.model!r}입니다. "
                "같은 모델을 쓰거나 새 --db-path를 지정하세요."
            )
        if int(state.get("source_rows", -1)) != len(df):
            raise ValueError("기존 인덱스와 입력 CSV 행 수가 다릅니다.")
        start = int(state.get("next_offset", 0))
        if not embeddings_path.is_file() or not metadata_path.is_file():
            raise FileNotFoundError(
                "진행 기록은 있지만 embeddings.npy 또는 metadata.csv가 없습니다. "
                "새 --db-path를 쓰거나 --reset으로 다시 만드세요."
            )
    else:
        start = 0
        metadata_columns = [
            "record_id",
            "ORG_ID",
            "TBL_ID",
            "STAT_ID",
            "TBL_NM",
            "path",
            "path_normalized",
        ]
        temp_metadata = metadata_path.with_suffix(".csv.tmp")
        df[metadata_columns].to_csv(
            temp_metadata,
            index=False,
            encoding="utf-8-sig",
        )
        temp_metadata.replace(metadata_path)
        state = {
            "format": "kosis-numpy-exact-v1",
            "input": str(input_path),
            "source_sha256": fingerprint,
            "model": args.model,
            "source_rows": len(df),
            "embedding_dim": None,
            "next_offset": 0,
            "complete": False,
        }
        atomic_write_json(state_path, state)

    if start >= target_end:
        print(f"추가 처리할 행이 없습니다. 현재 임베딩: {start:,}/{len(df):,}")
        print(f"인덱스 경로: {index_path}")
        return

    embedder = load_embedder(args.model, args.device)
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    starts = list(batch_starts(start, target_end, args.batch_size))
    iterator = (
        tqdm(starts, desc="NumPy 인덱스 구축", unit="batch")
        if tqdm is not None
        else starts
    )
    embeddings_memmap = None

    for batch_number, batch_start in enumerate(iterator, start=1):
        batch_end = min(batch_start + args.batch_size, target_end)
        documents = df.iloc[batch_start:batch_end]["document"].tolist()
        batch_embeddings = np.asarray(
            embedder.encode(
                documents,
                batch_size=args.encode_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        )
        if batch_embeddings.ndim != 2 or len(batch_embeddings) != len(documents):
            raise ValueError(
                "임베딩 결과 크기가 예상과 다릅니다: "
                f"{batch_embeddings.shape}, 문서 {len(documents)}개"
            )

        embedding_dim = int(batch_embeddings.shape[1])
        saved_dim = state.get("embedding_dim")
        if saved_dim is not None and int(saved_dim) != embedding_dim:
            raise ValueError(
                f"기존 임베딩 차원은 {saved_dim}, 현재 결과는 {embedding_dim}입니다."
            )

        if embeddings_memmap is None:
            if embeddings_path.exists():
                embeddings_memmap = np.load(embeddings_path, mmap_mode="r+")
                expected_shape = (len(df), embedding_dim)
                if embeddings_memmap.shape != expected_shape:
                    raise ValueError(
                        f"기존 embeddings.npy 크기는 {embeddings_memmap.shape}, "
                        f"예상 크기는 {expected_shape}입니다."
                    )
            else:
                embeddings_memmap = np.lib.format.open_memmap(
                    embeddings_path,
                    mode="w+",
                    dtype=np.float32,
                    shape=(len(df), embedding_dim),
                )

        embeddings_memmap[batch_start:batch_end] = batch_embeddings
        embeddings_memmap.flush()

        state["embedding_dim"] = embedding_dim
        state["next_offset"] = batch_end
        state["complete"] = batch_end == len(df)
        atomic_write_json(state_path, state)

        if tqdm is not None:
            iterator.set_postfix(indexed=f"{batch_end:,}/{len(df):,}")
        elif batch_number == 1 or batch_end == target_end or batch_number % 10 == 0:
            print(f"진행: {batch_end:,}/{len(df):,}")

    del embeddings_memmap
    print(f"\n완료: {state['next_offset']:,}/{len(df):,}개 임베딩")
    print(f"인덱스 경로: {index_path}")
    if state["next_offset"] < len(df):
        print("시험 구축 상태입니다. 같은 명령에서 --limit을 빼면 이어서 전체 구축합니다.")


def exact_top_k(
    embeddings: np.ndarray,
    query_embedding: np.ndarray,
    indexed_rows: int,
    top_k: int,
    search_batch_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    """메모리맵을 청크로 읽어 정확한 코사인 Top-K를 반환한다."""
    best_scores = np.empty(0, dtype=np.float32)
    best_indices = np.empty(0, dtype=np.int64)

    for start in range(0, indexed_rows, search_batch_size):
        end = min(start + search_batch_size, indexed_rows)
        block = np.asarray(embeddings[start:end], dtype=np.float32)
        scores = block @ query_embedding
        indices = np.arange(start, end, dtype=np.int64)

        all_scores = np.concatenate([best_scores, scores])
        all_indices = np.concatenate([best_indices, indices])
        keep = min(top_k, len(all_scores))
        selected = np.argpartition(all_scores, -keep)[-keep:]
        best_scores = all_scores[selected]
        best_indices = all_indices[selected]

    order = np.argsort(best_scores)[::-1]
    return best_indices[order], best_scores[order]


def query(args: argparse.Namespace) -> None:
    index_path = Path(args.db_path).expanduser().resolve()
    if not index_path.is_dir():
        raise FileNotFoundError(f"NumPy 인덱스 경로를 찾을 수 없습니다: {index_path}")
    if args.top_k < 1 or args.search_batch_size < 1:
        raise ValueError("--top-k와 --search-batch-size는 1 이상이어야 합니다.")

    state = load_state(index_path)
    embeddings_path = index_path / EMBEDDINGS_FILE
    metadata_path = index_path / METADATA_FILE
    if not embeddings_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("embeddings.npy 또는 metadata.csv가 없습니다.")

    indexed_rows = int(state.get("next_offset", 0))
    if indexed_rows < 1:
        raise ValueError("검색할 임베딩이 없습니다. build를 먼저 실행하세요.")

    saved_model = state.get("model") or DEFAULT_MODEL
    model_name = args.model or saved_model
    if args.model and args.model != saved_model:
        raise ValueError(
            f"인덱스 모델은 {saved_model!r}인데 --model은 {args.model!r}입니다."
        )

    query_text = make_query_text(
        query=args.query,
        indicator=args.indicator,
        keyword=args.keyword,
        region=args.region,
        population=args.population,
    )
    embedder = load_embedder(model_name, args.device)
    query_embedding = np.asarray(
        embedder.encode(
            [query_text],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0],
        dtype=np.float32,
    )

    embeddings = np.load(embeddings_path, mmap_mode="r")
    if embeddings.ndim != 2 or embeddings.shape[0] < indexed_rows:
        raise ValueError(
            f"embeddings.npy 크기가 잘못되었습니다: {embeddings.shape}, "
            f"검색 대상 {indexed_rows:,}행"
        )
    if embeddings.shape[1] != query_embedding.shape[0]:
        raise ValueError(
            f"인덱스 차원 {embeddings.shape[1]}과 검색 벡터 차원 "
            f"{query_embedding.shape[0]}이 다릅니다."
        )

    top_k = min(args.top_k, indexed_rows)
    indices, scores = exact_top_k(
        embeddings=embeddings,
        query_embedding=query_embedding,
        indexed_rows=indexed_rows,
        top_k=top_k,
        search_batch_size=args.search_batch_size,
    )
    metadata = pd.read_csv(
        metadata_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    if len(metadata) != int(state["source_rows"]):
        raise ValueError(
            f"metadata.csv는 {len(metadata):,}행, 예상은 "
            f"{int(state['source_rows']):,}행입니다."
        )

    result = metadata.iloc[indices].copy().reset_index(drop=True)
    result.insert(0, "similarity", np.round(scores.astype(float), 6))
    result.insert(0, "rank", np.arange(1, len(result) + 1))

    display_columns = ["rank", "similarity", "ORG_ID", "TBL_ID", "TBL_NM", "path"]
    print(result[display_columns].to_string(index=False))
    print(f"\n검색 대상: {indexed_rows:,}개 | 방식: NumPy exact cosine")

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"후보 저장: {output_path}")


def preview(args: argparse.Namespace) -> None:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")
    if args.rows < 1:
        raise ValueError("--rows는 1 이상이어야 합니다.")

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


def info(args: argparse.Namespace) -> None:
    index_path = Path(args.db_path).expanduser().resolve()
    state = load_state(index_path)
    indexed = int(state.get("next_offset", 0))
    total = int(state.get("source_rows", 0))
    print(f"인덱스 경로: {index_path}")
    print(f"모델: {state.get('model')}")
    print(f"임베딩 차원: {state.get('embedding_dim')}")
    print(f"구축 상태: {indexed:,}/{total:,}")
    print(f"전체 완료: {'Y' if state.get('complete') else 'N'}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KOSIS 통계표 CSV로 NumPy 정확 검색 인덱스를 구축합니다."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="NumPy 인덱스 구축/이어받기")
    build_parser.add_argument("--input", required=True, help="KOSIS CSV 경로")
    build_parser.add_argument("--db-path", default="./kosis_numpy_db")
    build_parser.add_argument("--model", default=DEFAULT_MODEL)
    build_parser.add_argument("--device", choices=["cpu", "cuda", "mps"])
    build_parser.add_argument("--batch-size", type=int, default=256)
    build_parser.add_argument("--encode-batch-size", type=int, default=64)
    build_parser.add_argument(
        "--limit",
        type=int,
        help="앞 N행까지만 시험 구축합니다. 생략하면 같은 인덱스에 이어서 전체 구축합니다.",
    )
    build_parser.add_argument(
        "--reset",
        action="store_true",
        help="해당 인덱스의 상태·임베딩·메타데이터를 지우고 처음부터 만듭니다.",
    )
    build_parser.set_defaults(func=build)

    query_parser = subparsers.add_parser("query", help="Top-K 후보 정확 검색")
    query_parser.add_argument("--db-path", default="./kosis_numpy_db")
    query_parser.add_argument("--model")
    query_parser.add_argument("--device", choices=["cpu", "cuda", "mps"])
    query_parser.add_argument("--query", help="기사 주장 문장")
    query_parser.add_argument("--indicator", help="추출된 지표명")
    query_parser.add_argument("--keyword", help="KOSIS 검색 키워드")
    query_parser.add_argument("--region", help="지역")
    query_parser.add_argument("--population", help="모집단")
    query_parser.add_argument("--top-k", type=int, default=20)
    query_parser.add_argument(
        "--search-batch-size",
        type=int,
        default=20000,
        help="검색 시 한 번에 읽을 벡터 수",
    )
    query_parser.add_argument("--output", help="후보 CSV 저장 경로")
    query_parser.set_defaults(func=query)

    preview_parser = subparsers.add_parser(
        "preview", help="정규화·임베딩 문서 미리보기"
    )
    preview_parser.add_argument("--input", required=True)
    preview_parser.add_argument("--rows", type=int, default=10)
    preview_parser.add_argument("--output")
    preview_parser.set_defaults(func=preview)

    info_parser = subparsers.add_parser("info", help="인덱스 구축 상태 확인")
    info_parser.add_argument("--db-path", default="./kosis_numpy_db")
    info_parser.set_defaults(func=info)
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
