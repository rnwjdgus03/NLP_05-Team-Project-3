"""measurement 결과를 기존 KOSIS 파이프라인에 연결한다.

기존 KOSIS 코드는 재현성을 위해 CSV 계약과 CLI 단계를 사용한다.
이 모듈은 그 계약을 보존하면서 챗봇의 요청·응답 dict와 연결하는
서비스 어댑터다.
"""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Literal, TypedDict

from chatbot.services.article_pipeline import ArticleMeasurementResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TABLE_INDEX = PROJECT_ROOT / "kosis_table_summary.csv"
DEFAULT_SEMANTIC_INDEX = PROJECT_ROOT / "data" / "indexes" / "kosis_bge_m3"
PIPELINE_SCRIPT = PROJECT_ROOT / "run_kosis_measurement_pipeline.py"

KosisMode = Literal["table", "metadata", "verify"]
RetrievalMode = Literal["auto", "lexical", "hybrid"]
CommandRunner = Callable[..., object]


class KosisMeasurementResult(TypedDict):
    claim_id: str
    claim_measurement_id: str
    status: str
    status_code: str
    status_reason: str
    stage: str
    measurement: dict[str, str]
    rejection: dict[str, str] | None
    enrichment: dict[str, str] | None
    candidates: list[dict[str, str]]
    mapping: dict[str, str] | None
    verification: dict[str, str] | None
    final_status: str
    mapping_status: str


class KosisArticleResult(TypedDict):
    article_id: str
    mode: KosisMode
    retrieval_mode: RetrievalMode
    measurement_count: int
    eligible_count: int
    enrich_count: int
    rejected_count: int
    candidate_count: int
    mapping_count: int
    verified_count: int
    review_count: int
    not_kosis_count: int
    results: list[KosisMeasurementResult]


class KosisPipelineError(RuntimeError):
    """KOSIS 서비스 파이프라인을 완료하지 못했을 때 발생한다."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _measurement_key(row: Mapping[str, object]) -> str:
    measurement_id = _text(row.get("claim_measurement_id"))
    if measurement_id and measurement_id != "-":
        return f"measurement:{measurement_id}"
    claim_id = _text(row.get("claim_id"))
    return f"claim:{claim_id}" if claim_id else ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    materialized = [dict(row) for row in rows]
    fields = list(dict.fromkeys(key for row in materialized for key in row))
    if not fields:
        fields = ["claim_id", "claim_measurement_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)


def _group_rows(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = _measurement_key(row)
        if key:
            grouped[key].append(row)
    return grouped


def _rank(row: Mapping[str, object]) -> int:
    try:
        return int(_text(row.get("candidate_rank")) or 999)
    except ValueError:
        return 999


def _choose_mapping(rows: list[dict[str, str]]) -> dict[str, str] | None:
    if not rows:
        return None
    ready = [
        row
        for row in rows
        if _text(row.get("final_status")) == "READY"
        or _text(row.get("mapping_status")) == "READY"
    ]
    return min(ready or rows, key=_rank)


def merge_kosis_results(
    measurements: Iterable[Mapping[str, object]],
    *,
    rejected: Iterable[dict[str, str]] = (),
    enrichments: Iterable[dict[str, str]] = (),
    candidates: Iterable[dict[str, str]] = (),
    mappings: Iterable[dict[str, str]] = (),
    verified: Iterable[dict[str, str]] = (),
) -> list[KosisMeasurementResult]:
    """KOSIS 단계별 행을 measurement 단위의 하나의 결과로 병합한다."""
    rejected_by_key = _group_rows(rejected)
    enrichments_by_key = _group_rows(enrichments)
    candidates_by_key = _group_rows(candidates)
    mappings_by_key = _group_rows(mappings)
    verified_by_key = _group_rows(verified)
    results: list[KosisMeasurementResult] = []

    for source in measurements:
        measurement = {str(key): _text(value) for key, value in source.items()}
        key = _measurement_key(measurement)
        rejection = (rejected_by_key.get(key) or [None])[0]
        enrichment = (enrichments_by_key.get(key) or [None])[0]
        candidate_rows = sorted(candidates_by_key.get(key, []), key=_rank)
        mapping = _choose_mapping(mappings_by_key.get(key, []))
        verification = (verified_by_key.get(key) or [None])[0]
        final_status = _text(
            (verification or {}).get("final_status")
            or (mapping or {}).get("final_status")
        )
        mapping_status = _text(
            (verification or {}).get("mapping_status")
            or (mapping or {}).get("mapping_status")
        )

        if verification:
            status = _text(verification.get("verdict")) or final_status or "판단불가"
            status_code = (
                _text(verification.get("verdict_code"))
                or final_status
                or "COMPARISON_FAILED"
            )
            status_reason = _text(verification.get("verdict_reason")) or "검증 사유 없음"
            stage = "verification"
        elif mapping:
            status = final_status or mapping_status or "REVIEW"
            status_code = final_status or mapping_status or "REVIEW"
            status_reason = (
                _text(mapping.get("review_reason"))
                or _text(mapping.get("not_kosis_reason"))
                or _text(mapping.get("mapping_reason"))
                or "매핑 확정 필요"
            )
            stage = "mapping"
        elif candidate_rows:
            top = candidate_rows[0]
            status = _text(top.get("candidate_status")) or "TABLE_ONLY"
            status_code = _text(top.get("candidate_status_code")) or status
            status_reason = _text(top.get("candidate_status_reason")) or "통계표 후보"
            stage = "candidate"
        elif enrichment:
            status = "보강 필요"
            status_code = _text(enrichment.get("mapping_exclusion_code")) or "ENRICH"
            status_reason = (
                _text(enrichment.get("mapping_exclusion_reason"))
                or _text(enrichment.get("enrichment_actions"))
                or "추가 정보 보강 필요"
            )
            final_status = "REVIEW"
            stage = "enrich"
        elif rejection:
            status = "검증대상 아님"
            status_code = _text(rejection.get("mapping_exclusion_code")) or "KOSIS_INELIGIBLE"
            status_reason = _text(rejection.get("mapping_exclusion_reason")) or "KOSIS 검증 대상 아님"
            final_status = "NOT_KOSIS"
            stage = "gate"
        else:
            status = "판단불가"
            status_code = "NO_KOSIS_RESULT"
            status_reason = "KOSIS 통계표 후보를 찾지 못했습니다."
            stage = "candidate"

        results.append(
            {
                "claim_id": _text(measurement.get("claim_id")),
                "claim_measurement_id": _text(
                    measurement.get("claim_measurement_id")
                ),
                "status": status,
                "status_code": status_code,
                "status_reason": status_reason,
                "stage": stage,
                "measurement": measurement,
                "rejection": rejection,
                "enrichment": enrichment,
                "candidates": candidate_rows,
                "mapping": mapping,
                "verification": verification,
                "final_status": final_status,
                "mapping_status": mapping_status,
            }
        )
    return results


def _pipeline_paths(input_path: Path, out_dir: Path) -> dict[str, Path]:
    stem = input_path.stem
    return {
        "ready": out_dir / f"{stem}_kosis_ready.csv",
        "enrich": out_dir / f"{stem}_kosis_enrich.csv",
        "rejected": out_dir / f"{stem}_kosis_rejected.csv",
        "table_candidates": out_dir / f"{stem}_kosis_table_candidates.csv",
        "final_candidates": out_dir / f"{stem}_kosis_candidates_with_meta.csv",
        "mappings": out_dir / f"{stem}_kosis_validated_mappings.csv",
        "verified": out_dir / f"{stem}_kosis_verified.csv",
    }


def _run_in_directory(
    article_result: ArticleMeasurementResult,
    *,
    mode: KosisMode,
    retrieval_mode: RetrievalMode,
    table_index: Path,
    semantic_index: Path,
    request_dir: Path,
    top_tables: int,
    top_rank_for_meta: int,
    min_score: int,
    delay: float,
    no_reranker: bool,
    command_runner: CommandRunner,
) -> KosisArticleResult:
    input_path = request_dir / "article_measurements.csv"
    out_dir = request_dir / "kosis"
    measurement_rows = [dict(row) for row in article_result.get("measurements") or []]
    _write_csv(input_path, measurement_rows)

    command = [
        sys.executable,
        str(PIPELINE_SCRIPT),
        "--input",
        str(input_path),
        "--table-index",
        str(table_index),
        "--out-dir",
        str(out_dir),
        "--retrieval-mode",
        retrieval_mode,
        "--semantic-index",
        str(semantic_index),
        "--top-tables",
        str(top_tables),
        "--top-rank-for-meta",
        str(top_rank_for_meta),
        "--min-score",
        str(min_score),
        "--delay",
        str(delay),
    ]
    if no_reranker:
        command.append("--no-reranker")
    if mode == "table":
        command.append("--skip-meta")
    elif mode == "verify":
        command.append("--verify")

    try:
        command_runner(
            command,
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = _text(error.stderr) or _text(error.stdout) or str(error)
        raise KosisPipelineError(f"KOSIS 파이프라인 실패: {detail}") from error
    except Exception as error:
        raise KosisPipelineError(
            f"KOSIS 파이프라인 실행 실패: {type(error).__name__}: {error}"
        ) from error

    paths = _pipeline_paths(input_path, out_dir)
    ready = _read_csv(paths["ready"])
    enrichments = _read_csv(paths["enrich"])
    rejected = _read_csv(paths["rejected"])
    candidates_path = (
        paths["table_candidates"] if mode == "table" else paths["final_candidates"]
    )
    candidates = _read_csv(candidates_path)
    mappings = _read_csv(paths["mappings"]) if mode == "verify" else []
    verified = _read_csv(paths["verified"]) if mode == "verify" else []
    merged = merge_kosis_results(
        measurement_rows,
        rejected=rejected,
        enrichments=enrichments,
        candidates=candidates,
        mappings=mappings,
        verified=verified,
    )
    mapping_count = sum(
        result.get("final_status") == "READY"
        or result.get("mapping_status") == "READY"
        for result in merged
    )
    verified_count = sum(
        result.get("status_code") in {"MATCH", "VALUE_MISMATCH"}
        for result in merged
    )
    review_count = sum(result.get("final_status") == "REVIEW" for result in merged)
    not_kosis_count = sum(
        result.get("final_status") == "NOT_KOSIS" for result in merged
    )
    return {
        "article_id": _text(article_result.get("article_id")),
        "mode": mode,
        "retrieval_mode": retrieval_mode,
        "measurement_count": len(measurement_rows),
        "eligible_count": len(ready),
        "enrich_count": len(enrichments),
        "rejected_count": len(rejected),
        "candidate_count": len(candidates),
        "mapping_count": mapping_count,
        "verified_count": verified_count,
        "review_count": review_count,
        "not_kosis_count": not_kosis_count,
        "results": merged,
    }


def run_kosis_pipeline(
    article_result: ArticleMeasurementResult,
    *,
    mode: KosisMode = "metadata",
    retrieval_mode: RetrievalMode = "auto",
    table_index: str | Path = DEFAULT_TABLE_INDEX,
    semantic_index: str | Path = DEFAULT_SEMANTIC_INDEX,
    artifact_dir: str | Path | None = None,
    top_tables: int = 2,
    top_rank_for_meta: int = 2,
    min_score: int = 10,
    delay: float = 0.12,
    no_reranker: bool = False,
    command_runner: CommandRunner = subprocess.run,
) -> KosisArticleResult:
    """measurement를 KOSIS 게이트·검색·검증 파이프라인에 전달한다.

    ``table``은 오프라인 lexical 통계표 검색까지, ``metadata``는
    KOSIS 메타 API 조회까지, ``verify``는 실제값 비교까지 실행한다.
    """
    if mode not in {"table", "metadata", "verify"}:
        raise KosisPipelineError(f"지원하지 않는 KOSIS mode입니다: {mode}")
    if retrieval_mode not in {"auto", "lexical", "hybrid"}:
        raise KosisPipelineError(
            f"지원하지 않는 retrieval mode입니다: {retrieval_mode}"
        )
    if top_tables < 1 or top_rank_for_meta < 1:
        raise KosisPipelineError("KOSIS 후보 수는 1 이상이어야 합니다.")
    if min_score < 0 or delay < 0:
        raise KosisPipelineError("min_score와 delay는 0 이상이어야 합니다.")

    measurement_rows = article_result.get("measurements") or []
    if not measurement_rows:
        return {
            "article_id": _text(article_result.get("article_id")),
            "mode": mode,
            "retrieval_mode": retrieval_mode,
            "measurement_count": 0,
            "eligible_count": 0,
            "enrich_count": 0,
            "rejected_count": 0,
            "candidate_count": 0,
            "mapping_count": 0,
            "verified_count": 0,
            "review_count": 0,
            "not_kosis_count": 0,
            "results": [],
        }

    resolved_table_index = Path(table_index).expanduser().resolve()
    if not resolved_table_index.is_file():
        raise KosisPipelineError(
            f"KOSIS 통계표 인덱스가 없습니다: {resolved_table_index}"
        )
    resolved_semantic_index = Path(semantic_index).expanduser().resolve()

    if artifact_dir is not None:
        request_dir = Path(artifact_dir).expanduser().resolve()
        request_dir.mkdir(parents=True, exist_ok=True)
        return _run_in_directory(
            article_result,
            mode=mode,
            retrieval_mode=retrieval_mode,
            table_index=resolved_table_index,
            semantic_index=resolved_semantic_index,
            request_dir=request_dir,
            top_tables=top_tables,
            top_rank_for_meta=top_rank_for_meta,
            min_score=min_score,
            delay=delay,
            no_reranker=no_reranker,
            command_runner=command_runner,
        )

    with tempfile.TemporaryDirectory(prefix="news-chatbot-kosis-") as temp_dir:
        return _run_in_directory(
            article_result,
            mode=mode,
            retrieval_mode=retrieval_mode,
            table_index=resolved_table_index,
            semantic_index=resolved_semantic_index,
            request_dir=Path(temp_dir),
            top_tables=top_tables,
            top_rank_for_meta=top_rank_for_meta,
            min_score=min_score,
            delay=delay,
            no_reranker=no_reranker,
            command_runner=command_runner,
        )


__all__ = [
    "DEFAULT_TABLE_INDEX",
    "DEFAULT_SEMANTIC_INDEX",
    "KosisArticleResult",
    "KosisMeasurementResult",
    "KosisMode",
    "KosisPipelineError",
    "RetrievalMode",
    "merge_kosis_results",
    "run_kosis_pipeline",
]
