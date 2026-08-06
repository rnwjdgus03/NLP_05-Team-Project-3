from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_MODEL = "intfloat/multilingual-e5-small"
EMBEDDINGS_FILE = "embeddings.npy"
METADATA_FILE = "metadata.csv"
STATE_FILE = "state.json"

REQUIRED_INPUT_COLUMNS = [
    "mapping_eligible",
    "measurement_indicator",
    "claim_indicator",
    "keywords",
    "measurement_item",
    "metric_domain",
    "claim_text",
]
REQUIRED_METADATA_COLUMNS = [
    "ORG_ID",
    "TBL_ID",
    "STAT_ID",
    "TBL_NM",
    "path",
]

BLANK_VALUES = {"", "-", "nan", "none", "null", "n/a", "na"}
TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z]{2,}")


def clean_text(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return "" if text.lower() in BLANK_VALUES else text


def unique_texts(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def joined(values: Iterable[object], separator: str = ", ") -> str:
    return separator.join(unique_texts(values))


def make_retrieval_query(row: pd.Series, max_claim_chars: int) -> str:
    measurement_indicator = clean_text(row.get("measurement_indicator", ""))
    claim_indicator = clean_text(row.get("claim_indicator", ""))
    keywords = clean_text(row.get("keywords", ""))
    items = joined(
        [
            row.get("measurement_item", ""),
            row.get("claim_industry_or_item", ""),
        ]
    )
    metric_domain = clean_text(row.get("metric_domain", ""))
    region = clean_text(row.get("region", ""))
    population = joined(
        [
            row.get("age_group", ""),
            row.get("gender", ""),
            row.get("population_etc", ""),
        ]
    )
    claim_text = clean_text(row.get("claim_text", ""))
    if max_claim_chars > 0 and len(claim_text) > max_claim_chars:
        claim_text = claim_text[:max_claim_chars].rstrip() + "…"

    fields: list[str] = []
    if measurement_indicator:
        fields.append(f"측정지표: {measurement_indicator}")
    if claim_indicator and claim_indicator != measurement_indicator:
        fields.append(f"대표지표: {claim_indicator}")
    if keywords:
        fields.append(f"통계 검색어: {keywords}")
    if items:
        fields.append(f"세부항목: {items}")
    if metric_domain:
        fields.append(f"분야: {metric_domain}")
    if region:
        fields.append(f"지역: {region}")
    if population:
        fields.append(f"모집단: {population}")
    if claim_text:
        fields.append(f"기사 주장: {claim_text}")

    if not fields:
        return ""
    return "query: " + "\n".join(fields)


def tokenize(value: object) -> set[str]:
    text = clean_text(value).casefold()
    return set(TOKEN_PATTERN.findall(text))


def token_coverage(source: object, candidate: object) -> float:
    source_tokens = tokenize(source)
    if not source_tokens:
        return 0.0
    candidate_tokens = tokenize(candidate)
    if not candidate_tokens:
        return 0.0
    return len(source_tokens & candidate_tokens) / len(source_tokens)


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


def exact_top_k_many(
    embeddings: np.ndarray,
    query_embeddings: np.ndarray,
    indexed_rows: int,
    top_k: int,
    search_batch_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    """여러 검색문을 한 번에 처리하는 청크 기반 exact cosine Top-K."""
    query_count = len(query_embeddings)
    best_scores = np.full((query_count, top_k), -np.inf, dtype=np.float32)
    best_indices = np.full((query_count, top_k), -1, dtype=np.int64)

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    starts = range(0, indexed_rows, search_batch_size)
    iterator = (
        tqdm(
            starts,
            total=(indexed_rows + search_batch_size - 1) // search_batch_size,
            desc="KOSIS 후보 검색",
            unit="chunk",
        )
        if tqdm is not None
        else starts
    )

    for start in iterator:
        end = min(start + search_batch_size, indexed_rows)
        block = np.asarray(embeddings[start:end], dtype=np.float32)
        block_scores = query_embeddings @ block.T
        block_indices = np.arange(start, end, dtype=np.int64)

        keep_in_block = min(top_k, end - start)
        selected = np.argpartition(
            block_scores,
            kth=block_scores.shape[1] - keep_in_block,
            axis=1,
        )[:, -keep_in_block:]
        selected_scores = np.take_along_axis(block_scores, selected, axis=1)
        selected_indices = block_indices[selected]

        merged_scores = np.concatenate([best_scores, selected_scores], axis=1)
        merged_indices = np.concatenate([best_indices, selected_indices], axis=1)
        keep = np.argpartition(
            merged_scores,
            kth=merged_scores.shape[1] - top_k,
            axis=1,
        )[:, -top_k:]
        best_scores = np.take_along_axis(merged_scores, keep, axis=1)
        best_indices = np.take_along_axis(merged_indices, keep, axis=1)

    order = np.argsort(best_scores, axis=1)[:, ::-1]
    return (
        np.take_along_axis(best_indices, order, axis=1),
        np.take_along_axis(best_scores, order, axis=1),
    )


def lexical_sources(row: pd.Series) -> tuple[str, str]:
    keyword_source = joined(
        [
            row.get("measurement_indicator", ""),
            row.get("claim_indicator", ""),
            row.get("keywords", ""),
            row.get("metric_domain", ""),
        ]
    )
    item_source = joined(
        [
            row.get("measurement_item", ""),
            row.get("claim_industry_or_item", ""),
        ]
    )
    return keyword_source, item_source


def rerank_candidates(
    row: pd.Series,
    metadata: pd.DataFrame,
    indices: np.ndarray,
    similarities: np.ndarray,
    vector_weight: float,
    keyword_weight: float,
    item_weight: float,
) -> list[dict]:
    keyword_source, item_source = lexical_sources(row)
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for index, similarity in zip(indices.tolist(), similarities.tolist()):
        if index < 0:
            continue
        candidate = metadata.iloc[index]
        key = (
            clean_text(candidate["ORG_ID"]),
            clean_text(candidate["TBL_ID"]),
        )
        if key in seen:
            continue
        seen.add(key)

        candidate_text = joined(
            [
                candidate.get("TBL_NM", ""),
                candidate.get("path_normalized", ""),
                candidate.get("path", ""),
            ],
            separator=" ",
        )
        keyword_match = token_coverage(keyword_source, candidate_text)
        item_match = token_coverage(item_source, candidate_text)
        final_score = (
            vector_weight * float(similarity)
            + keyword_weight * keyword_match
            + item_weight * item_match
        )
        candidates.append(
            {
                "ORG_ID": clean_text(candidate["ORG_ID"]),
                "TBL_ID": clean_text(candidate["TBL_ID"]),
                "STAT_ID": clean_text(candidate["STAT_ID"]),
                "TBL_NM": clean_text(candidate["TBL_NM"]),
                "path": clean_text(candidate["path"]),
                "vector_similarity": round(float(similarity), 6),
                "keyword_match": round(keyword_match, 6),
                "item_match": round(item_match, 6),
                "score": round(final_score, 6),
            }
        )

    candidates.sort(
        key=lambda item: (item["score"], item["vector_similarity"]),
        reverse=True,
    )
    return candidates


def make_mapping_row_ids(df: pd.DataFrame) -> pd.Series:
    width = max(6, len(str(len(df))))
    return pd.Series(
        [f"MAP{number:0{width}d}" for number in range(1, len(df) + 1)],
        index=df.index,
        dtype=str,
    )


def candidate_columns(candidate_count: int) -> list[str]:
    base = [
        "mapping_row_id",
        "retrieval_query",
        "retrieval_status",
        "retrieval_candidate_pool",
        "candidate_score_margin",
        "candidate_review_priority",
    ]
    fields = [
        "org_id",
        "tbl_id",
        "stat_id",
        "tbl_nm",
        "path",
        "vector_similarity",
        "keyword_match",
        "item_match",
        "score",
    ]
    return base + [
        f"candidate_{rank}_{field}"
        for rank in range(1, candidate_count + 1)
        for field in fields
    ]


def review_priority(
    row: pd.Series,
    candidates: list[dict],
    high_score_threshold: float,
    high_margin_threshold: float,
    medium_score_threshold: float,
    medium_margin_threshold: float,
) -> str:
    if clean_text(row.get("measurement_correct", "")).upper() == "N":
        return "high"
    if not candidates:
        return "high"
    top_score = float(candidates[0]["score"])
    margin = (
        top_score - float(candidates[1]["score"])
        if len(candidates) > 1
        else top_score
    )
    if top_score < high_score_threshold or margin < high_margin_threshold:
        return "high"
    if top_score < medium_score_threshold or margin < medium_margin_threshold:
        return "medium"
    return "low"


def validate_weights(args: argparse.Namespace) -> None:
    weights = [args.vector_weight, args.keyword_weight, args.item_weight]
    if any(weight < 0 for weight in weights):
        raise ValueError("재정렬 가중치는 0 이상이어야 합니다.")
    if not np.isclose(sum(weights), 1.0):
        raise ValueError(
            "--vector-weight, --keyword-weight, --item-weight의 합은 1이어야 합니다."
        )


def run(args: argparse.Namespace) -> None:
    validate_weights(args)
    input_path = Path(args.input).expanduser().resolve()
    db_path = Path(args.db_path).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"입력 CSV를 찾을 수 없습니다: {input_path}")
    if not db_path.is_dir():
        raise FileNotFoundError(f"NumPy DB 폴더를 찾을 수 없습니다: {db_path}")
    if args.candidate_count < 1:
        raise ValueError("--candidate-count는 1 이상이어야 합니다.")
    if args.candidate_pool < args.candidate_count:
        raise ValueError("--candidate-pool은 --candidate-count 이상이어야 합니다.")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit은 1 이상이어야 합니다.")

    state_path = db_path / STATE_FILE
    embeddings_path = db_path / EMBEDDINGS_FILE
    metadata_path = db_path / METADATA_FILE
    for path in [state_path, embeddings_path, metadata_path]:
        if not path.is_file():
            raise FileNotFoundError(f"DB 필수 파일이 없습니다: {path}")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    indexed_rows = int(state.get("next_offset", 0))
    source_rows = int(state.get("source_rows", 0))
    if indexed_rows < 1:
        raise ValueError("DB에 검색 가능한 임베딩이 없습니다.")
    if indexed_rows < source_rows and not args.allow_partial_index:
        raise ValueError(
            f"DB가 아직 전체 구축되지 않았습니다: {indexed_rows:,}/{source_rows:,}. "
            "전체 구축 후 실행하거나 시험 목적이면 --allow-partial-index를 추가하세요."
        )

    df = pd.read_csv(
        input_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"입력 CSV에 필수 컬럼이 없습니다: {missing}\n"
            f"현재 컬럼: {df.columns.tolist()}"
        )
    if args.only_correct and "measurement_correct" not in df.columns:
        raise ValueError("--only-correct 사용에는 measurement_correct 컬럼이 필요합니다.")

    metadata = pd.read_csv(
        metadata_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    missing_metadata = [
        column for column in REQUIRED_METADATA_COLUMNS if column not in metadata.columns
    ]
    if missing_metadata:
        raise ValueError(f"metadata.csv에 필수 컬럼이 없습니다: {missing_metadata}")
    if len(metadata) != source_rows:
        raise ValueError(
            f"metadata.csv 행 수는 {len(metadata):,}, state.json 기준은 "
            f"{source_rows:,}입니다."
        )

    output = df.copy()
    output["mapping_row_id"] = make_mapping_row_ids(output)
    for column in candidate_columns(args.candidate_count):
        if column != "mapping_row_id":
            output[column] = ""

    eligible = output["mapping_eligible"].str.strip().str.upper().eq("Y")
    if args.only_correct:
        eligible &= output["measurement_correct"].str.strip().str.upper().eq("Y")
    target_indices = output.index[eligible].tolist()
    if args.limit is not None:
        target_indices = target_indices[: args.limit]

    output.loc[~eligible, "retrieval_status"] = "skipped_not_eligible"
    if args.only_correct and "measurement_correct" in output.columns:
        incorrect = (
            output["mapping_eligible"].str.strip().str.upper().eq("Y")
            & ~output["measurement_correct"].str.strip().str.upper().eq("Y")
        )
        output.loc[incorrect, "retrieval_status"] = "skipped_measurement_incorrect"
    if args.limit is not None:
        unprocessed_eligible = eligible & ~output.index.isin(target_indices)
        output.loc[unprocessed_eligible, "retrieval_status"] = "skipped_by_limit"

    queries: list[str] = []
    valid_indices: list[int] = []
    for row_index in target_indices:
        query_text = make_retrieval_query(
            output.loc[row_index],
            max_claim_chars=args.max_claim_chars,
        )
        output.at[row_index, "retrieval_query"] = query_text
        if not query_text:
            output.at[row_index, "retrieval_status"] = "empty_query"
            output.at[row_index, "candidate_review_priority"] = "high"
            continue
        queries.append(query_text)
        valid_indices.append(row_index)

    print(f"입력: {len(output):,}행")
    print(f"검색 대상: {len(valid_indices):,}행")
    print(f"DB 검색 범위: {indexed_rows:,}/{source_rows:,}개 통계표")
    if not valid_indices:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"검색할 행이 없어 상태만 저장했습니다: {output_path}")
        return

    saved_model = state.get("model") or DEFAULT_MODEL
    model_name = args.model or saved_model
    if args.model and args.model != saved_model:
        raise ValueError(
            f"DB 모델은 {saved_model!r}, 지정 모델은 {args.model!r}입니다."
        )
    embedder = load_embedder(model_name, args.device)
    query_embeddings = np.asarray(
        embedder.encode(
            queries,
            batch_size=args.encode_batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype=np.float32,
    )

    embeddings = np.load(embeddings_path, mmap_mode="r")
    if embeddings.ndim != 2 or embeddings.shape[0] < indexed_rows:
        raise ValueError(
            f"embeddings.npy 크기가 잘못되었습니다: {embeddings.shape}, "
            f"검색 대상 {indexed_rows:,}행"
        )
    if embeddings.shape[1] != query_embeddings.shape[1]:
        raise ValueError(
            f"DB 임베딩 차원 {embeddings.shape[1]}과 검색 임베딩 차원 "
            f"{query_embeddings.shape[1]}이 다릅니다."
        )

    pool_size = min(args.candidate_pool, indexed_rows)
    pool_indices, pool_scores = exact_top_k_many(
        embeddings=embeddings,
        query_embeddings=query_embeddings,
        indexed_rows=indexed_rows,
        top_k=pool_size,
        search_batch_size=args.search_batch_size,
    )

    long_rows: list[dict] = []
    for query_number, row_index in enumerate(valid_indices):
        candidates = rerank_candidates(
            row=output.loc[row_index],
            metadata=metadata,
            indices=pool_indices[query_number],
            similarities=pool_scores[query_number],
            vector_weight=args.vector_weight,
            keyword_weight=args.keyword_weight,
            item_weight=args.item_weight,
        )[: args.candidate_count]

        output.at[row_index, "retrieval_status"] = (
            "success" if candidates else "no_candidate"
        )
        output.at[row_index, "retrieval_candidate_pool"] = pool_size
        if candidates:
            margin = (
                float(candidates[0]["score"]) - float(candidates[1]["score"])
                if len(candidates) > 1
                else float(candidates[0]["score"])
            )
            output.at[row_index, "candidate_score_margin"] = round(margin, 6)
        output.at[row_index, "candidate_review_priority"] = review_priority(
            row=output.loc[row_index],
            candidates=candidates,
            high_score_threshold=args.high_score_threshold,
            high_margin_threshold=args.high_margin_threshold,
            medium_score_threshold=args.medium_score_threshold,
            medium_margin_threshold=args.medium_margin_threshold,
        )

        for rank, candidate in enumerate(candidates, start=1):
            for source_field, output_field in [
                ("ORG_ID", "org_id"),
                ("TBL_ID", "tbl_id"),
                ("STAT_ID", "stat_id"),
                ("TBL_NM", "tbl_nm"),
                ("path", "path"),
                ("vector_similarity", "vector_similarity"),
                ("keyword_match", "keyword_match"),
                ("item_match", "item_match"),
                ("score", "score"),
            ]:
                output.at[
                    row_index, f"candidate_{rank}_{output_field}"
                ] = candidate[source_field]
            long_rows.append(
                {
                    "mapping_row_id": output.at[row_index, "mapping_row_id"],
                    "claim_measurement_id": clean_text(
                        output.at[row_index, "claim_measurement_id"]
                    )
                    if "claim_measurement_id" in output.columns
                    else "",
                    "candidate_rank": rank,
                    **candidate,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"후보 컬럼 추가 완료: {output_path}")

    if args.long_output:
        long_output_path = Path(args.long_output).expanduser().resolve()
        long_output_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(long_rows).to_csv(
            long_output_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"후보 long 형식 저장: {long_output_path}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "뉴스 측정치 CSV를 KOSIS NumPy DB에서 일괄 검색하고 "
            "Top-N ORG_ID/TBL_ID 후보를 새 컬럼으로 추가합니다."
        )
    )
    parser.add_argument("--input", required=True, help="뉴스 측정치 CSV")
    parser.add_argument("--db-path", required=True, help="kosis_numpy_db 폴더")
    parser.add_argument("--output", required=True, help="후보 컬럼을 붙일 CSV")
    parser.add_argument("--long-output", help="후보별 한 행인 별도 CSV(선택)")
    parser.add_argument("--model", help="생략하면 DB state.json의 모델 사용")
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default="cpu")
    parser.add_argument("--encode-batch-size", type=int, default=32)
    parser.add_argument("--search-batch-size", type=int, default=20000)
    parser.add_argument(
        "--candidate-pool",
        type=int,
        default=20,
        help="벡터 검색 후 재정렬할 후보 수",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=5,
        help="원본에 최종 저장할 후보 수",
    )
    parser.add_argument(
        "--only-correct",
        action="store_true",
        help="mapping_eligible=Y 이면서 measurement_correct=Y인 행만 검색",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="검색 대상 중 앞 N행만 시험 실행",
    )
    parser.add_argument(
        "--allow-partial-index",
        action="store_true",
        help="전체 구축 전의 시험 DB에서도 검색 허용",
    )
    parser.add_argument(
        "--max-claim-chars",
        type=int,
        default=500,
        help="검색문에 넣을 claim_text 최대 글자 수(0이면 제한 없음)",
    )
    parser.add_argument("--vector-weight", type=float, default=0.75)
    parser.add_argument("--keyword-weight", type=float, default=0.20)
    parser.add_argument("--item-weight", type=float, default=0.05)
    parser.add_argument("--high-score-threshold", type=float, default=0.45)
    parser.add_argument("--high-margin-threshold", type=float, default=0.02)
    parser.add_argument("--medium-score-threshold", type=float, default=0.60)
    parser.add_argument("--medium-margin-threshold", type=float, default=0.05)
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\n실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
