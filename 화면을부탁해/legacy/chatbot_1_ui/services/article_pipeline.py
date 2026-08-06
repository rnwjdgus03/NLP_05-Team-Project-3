"""기사 원문을 기존 HCX 분석 파이프라인에 연결한다.

이 모듈은 CSV 파일 없이 챗봇에서 받은 기사 원문 문자열 하나를
``전처리 -> 주장 판별 -> measurement 추출`` 순서로 처리하는
챗봇용 어댑터다.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Literal, TypedDict

from dotenv import load_dotenv

from extract_hcx import extract_claim as extract_hcx_claim
from extract_hcx import to_rows as hcx_result_to_rows
from is_claim_filter_hcx import PROMPT_VERSION as IS_CLAIM_PROMPT_VERSION
from is_claim_filter_hcx import call_hcx as call_is_claim_hcx
from preprocess_news import get_sentence_splitter, preprocess_articles


SplitterName = Literal["auto", "kss", "regex"]
ExtractionEffort = Literal["none", "low", "medium"]


class ArticleSentence(TypedDict):
    claim_id: str
    article_id: str
    title: str
    date: str
    url: str
    claim_text: str
    prev_sentence: str
    prev_prev_sentence: str


class ArticlePreprocessResult(TypedDict):
    article_id: str
    splitter: str
    sentence_count: int
    sentences: list[ArticleSentence]


class ClassifiedArticleSentence(ArticleSentence):
    is_claim: str
    is_claim_reason: str
    is_claim_confidence: str
    is_claim_method: str
    extraction_model: str
    prompt_version: str
    extracted_at: str


class ArticleClaimResult(TypedDict):
    article_id: str
    splitter: str
    sentence_count: int
    claim_count: int
    sentences: list[ClassifiedArticleSentence]
    claims: list[ClassifiedArticleSentence]


class ArticleMeasurementResult(ArticleClaimResult):
    measurement_count: int
    measurement_row_count: int
    measurements: list[dict[str, str]]


class ArticlePreprocessingError(ValueError):
    """기사 입력을 문장 레코드로 변환할 수 없을 때 발생한다."""


class ArticleClaimClassificationError(RuntimeError):
    """HCX 주장 판별을 완료하지 못했을 때 발생한다."""


class ArticleMeasurementExtractionError(RuntimeError):
    """HCX measurement 추출을 완료하지 못했을 때 발생한다."""


ClaimClassifier = Callable[..., Mapping[str, object]]
MeasurementExtractor = Callable[..., Mapping[str, object]]


def _text(value: object) -> str:
    return str(value or "").strip()


def preprocess_article(
    body: str,
    *,
    title: str = "",
    date: str = "",
    url: str = "",
    article_id: str = "A0001",
    splitter: SplitterName = "auto",
    min_chars: int = 2,
) -> ArticlePreprocessResult:
    """기사 원문 하나를 정제하고 문장별 claim 레코드로 변환한다.

    ``article_id``를 비우면 기존 전처리기가 ``A0001``을 생성한다.
    ``splitter='auto'``는 KSS가 설치되어 있으면 KSS, 아니면 내장 정규식
    분리기를 사용한다.
    """
    normalized_body = _text(body)
    if not normalized_body:
        raise ArticlePreprocessingError("기사 원문이 비어 있습니다.")
    if min_chars < 1:
        raise ArticlePreprocessingError("min_chars는 1 이상이어야 합니다.")

    try:
        split_sentences, splitter_used = get_sentence_splitter(splitter)
    except (RuntimeError, ValueError) as error:
        raise ArticlePreprocessingError(str(error)) from error

    article = {
        "article_id": _text(article_id),
        "title": _text(title),
        "date": _text(date),
        "url": _text(url),
        "body": normalized_body,
    }
    columns = {
        "article_id": "article_id",
        "title": "title",
        "date": "date",
        "url": "url",
        "body": "body",
    }
    rows, empty_articles = preprocess_articles(
        [article],
        columns,
        split_sentences,
        min_chars=min_chars,
    )
    if empty_articles or not rows:
        raise ArticlePreprocessingError(
            "기사를 정제한 후 분석할 본문이 남지 않았습니다."
        )

    return {
        "article_id": rows[0]["article_id"],
        "splitter": splitter_used,
        "sentence_count": len(rows),
        "sentences": rows,
    }


def _normalize_is_claim(value: object) -> str:
    if value is True or str(value or "").strip().lower() == "true":
        return "True"
    return "False"


def classify_article_claims(
    preprocessed: ArticlePreprocessResult,
    *,
    api_key: str | None = None,
    model: str = "HCX-007",
    sleep_seconds: float = 0.5,
    classifier: ClaimClassifier | None = None,
) -> ArticleClaimResult:
    """전처리된 모든 문장을 HCX로 판별하고 통계 주장만 분리한다.

    운영 코드는 기본 HCX 판별기를 사용한다. 테스트나 다른 모델을
    붙일 때는 ``classifier``를 주입할 수 있다. 주입한 판별기를 사용하면
    API 키는 필수가 아니다.
    """
    if sleep_seconds < 0:
        raise ArticleClaimClassificationError(
            "sleep_seconds는 0 이상이어야 합니다."
        )

    active_classifier = classifier
    resolved_key = _text(api_key)
    if active_classifier is None:
        load_dotenv()
        resolved_key = resolved_key or _text(os.getenv("CLOVA_API_KEY"))
        if not resolved_key:
            raise ArticleClaimClassificationError(
                ".env에 CLOVA_API_KEY를 설정하세요."
            )
        active_classifier = call_is_claim_hcx

    classified: list[ClassifiedArticleSentence] = []
    source_sentences = preprocessed.get("sentences") or []
    for index, sentence in enumerate(source_sentences):
        claim_id = _text(sentence.get("claim_id")) or f"sentence-{index + 1}"
        try:
            decision = active_classifier(
                api_key=resolved_key,
                model=model,
                text=_text(sentence.get("claim_text")),
                prev=_text(sentence.get("prev_sentence")) or "-",
                prev_prev=_text(sentence.get("prev_prev_sentence")) or "-",
                date=_text(sentence.get("date")) or "-",
            )
            if not isinstance(decision, Mapping):
                raise TypeError("판별기 결과가 mapping이 아닙니다.")
        except Exception as error:
            raise ArticleClaimClassificationError(
                f"{claim_id} 주장 판별 실패: {type(error).__name__}: {error}"
            ) from error

        row: ClassifiedArticleSentence = {
            **sentence,
            "is_claim": _normalize_is_claim(decision.get("is_claim")),
            "is_claim_reason": _text(decision.get("reason")) or "-",
            "is_claim_confidence": _text(decision.get("confidence")) or "-",
            "is_claim_method": "hcx",
            "extraction_model": model,
            "prompt_version": IS_CLAIM_PROMPT_VERSION,
            "extracted_at": time.strftime("%Y-%m-%d"),
        }
        classified.append(row)
        if sleep_seconds and index + 1 < len(source_sentences):
            time.sleep(sleep_seconds)

    claims = [row for row in classified if row["is_claim"] == "True"]
    return {
        "article_id": _text(preprocessed.get("article_id")),
        "splitter": _text(preprocessed.get("splitter")),
        "sentence_count": len(classified),
        "claim_count": len(claims),
        "sentences": classified,
        "claims": claims,
    }


def detect_article_claims(
    body: str,
    *,
    title: str = "",
    date: str = "",
    url: str = "",
    article_id: str = "A0001",
    splitter: SplitterName = "auto",
    min_chars: int = 2,
    api_key: str | None = None,
    model: str = "HCX-007",
    sleep_seconds: float = 0.5,
    classifier: ClaimClassifier | None = None,
) -> ArticleClaimResult:
    """기사 원문 전처리부터 통계 주장 판별까지 한 번에 실행한다."""
    preprocessed = preprocess_article(
        body,
        title=title,
        date=date,
        url=url,
        article_id=article_id,
        splitter=splitter,
        min_chars=min_chars,
    )
    return classify_article_claims(
        preprocessed,
        api_key=api_key,
        model=model,
        sleep_seconds=sleep_seconds,
        classifier=classifier,
    )


def extract_article_measurements(
    classified: ArticleClaimResult,
    *,
    api_key: str | None = None,
    model: str = "HCX-007",
    effort: ExtractionEffort = "none",
    sleep_seconds: float = 1.0,
    extractor: MeasurementExtractor | None = None,
) -> ArticleMeasurementResult:
    """``is_claim=True`` 문장에서 measurement를 추출한다.

    각 measurement는 기존 ``extract_hcx.to_rows`` 계약에 맞춰 별도 행이
    된다. 수치가 없는 주장은 하나의 placeholder 행으로 보존되며,
    ``measurement_count``에는 실제 ID가 생성된 measurement만 포함한다.
    """
    if effort not in {"none", "low", "medium"}:
        raise ArticleMeasurementExtractionError(
            f"지원하지 않는 effort입니다: {effort}"
        )
    if sleep_seconds < 0:
        raise ArticleMeasurementExtractionError(
            "sleep_seconds는 0 이상이어야 합니다."
        )

    source_claims = [
        claim
        for claim in (classified.get("claims") or [])
        if _normalize_is_claim(claim.get("is_claim")) == "True"
    ]
    active_extractor = extractor
    resolved_key = _text(api_key)
    if source_claims and active_extractor is None:
        load_dotenv()
        resolved_key = resolved_key or _text(os.getenv("CLOVA_API_KEY"))
        if not resolved_key:
            raise ArticleMeasurementExtractionError(
                ".env에 CLOVA_API_KEY를 설정하세요."
            )
        active_extractor = extract_hcx_claim

    measurement_rows: list[dict[str, str]] = []
    for index, claim in enumerate(source_claims):
        claim_id = _text(claim.get("claim_id")) or f"claim-{index + 1}"
        try:
            if active_extractor is None:
                raise RuntimeError("measurement extractor가 없습니다.")
            extraction = active_extractor(
                api_key=resolved_key,
                model=model,
                claim=claim,
                effort=effort,
            )
            if not isinstance(extraction, Mapping):
                raise TypeError("추출기 결과가 mapping이 아닙니다.")
            rows = hcx_result_to_rows(claim, dict(extraction), model)
        except Exception as error:
            raise ArticleMeasurementExtractionError(
                f"{claim_id} measurement 추출 실패: "
                f"{type(error).__name__}: {error}"
            ) from error

        measurement_rows.extend(rows)
        if sleep_seconds and index + 1 < len(source_claims):
            time.sleep(sleep_seconds)

    measurement_count = sum(
        _text(row.get("claim_measurement_id")) not in {"", "-"}
        for row in measurement_rows
    )
    return {
        **classified,
        "claim_count": len(source_claims),
        "measurement_count": measurement_count,
        "measurement_row_count": len(measurement_rows),
        "measurements": measurement_rows,
    }


def analyze_article_measurements(
    body: str,
    *,
    title: str = "",
    date: str = "",
    url: str = "",
    article_id: str = "A0001",
    splitter: SplitterName = "auto",
    min_chars: int = 2,
    api_key: str | None = None,
    model: str = "HCX-007",
    effort: ExtractionEffort = "none",
    claim_sleep_seconds: float = 0.5,
    extraction_sleep_seconds: float = 1.0,
    classifier: ClaimClassifier | None = None,
    extractor: MeasurementExtractor | None = None,
) -> ArticleMeasurementResult:
    """기사 원문에서 통계 주장과 measurement를 한 번에 추출한다."""
    classified = detect_article_claims(
        body,
        title=title,
        date=date,
        url=url,
        article_id=article_id,
        splitter=splitter,
        min_chars=min_chars,
        api_key=api_key,
        model=model,
        sleep_seconds=claim_sleep_seconds,
        classifier=classifier,
    )
    return extract_article_measurements(
        classified,
        api_key=api_key,
        model=model,
        effort=effort,
        sleep_seconds=extraction_sleep_seconds,
        extractor=extractor,
    )


__all__ = [
    "ArticleClaimClassificationError",
    "ArticleClaimResult",
    "ArticleMeasurementExtractionError",
    "ArticleMeasurementResult",
    "ArticlePreprocessingError",
    "ArticlePreprocessResult",
    "ArticleSentence",
    "ClassifiedArticleSentence",
    "ClaimClassifier",
    "ExtractionEffort",
    "MeasurementExtractor",
    "SplitterName",
    "analyze_article_measurements",
    "classify_article_claims",
    "detect_article_claims",
    "extract_article_measurements",
    "preprocess_article",
]
