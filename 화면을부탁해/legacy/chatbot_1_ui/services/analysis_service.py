"""기사 원문에서 API 응답까지의 전체 분석 흐름을 조합한다."""

from __future__ import annotations

from collections.abc import Callable

from chatbot.schemas import ArticleAnalyzeRequest, ArticleAnalyzeResponse
from chatbot.services.article_pipeline import (
    ArticleMeasurementResult,
    analyze_article_measurements,
)
from chatbot.services.kosis_pipeline import KosisArticleResult, run_kosis_pipeline
from chatbot.services.response_builder import build_article_response


ArticleAnalyzer = Callable[..., ArticleMeasurementResult]
KosisAnalyzer = Callable[..., KosisArticleResult]


def analyze_article_request(
    request: ArticleAnalyzeRequest,
    request_id: str,
    *,
    article_analyzer: ArticleAnalyzer = analyze_article_measurements,
    kosis_analyzer: KosisAnalyzer = run_kosis_pipeline,
) -> ArticleAnalyzeResponse:
    """API 요청 하나를 HCX와 KOSIS 전체 파이프라인으로 처리한다."""
    article_result = article_analyzer(
        request.body,
        title=request.title,
        date=request.date,
        url=request.url,
        article_id=request.article_id,
        splitter=request.splitter,
    )
    kosis_result = kosis_analyzer(
        article_result,
        mode=request.kosis_mode,
    )
    return build_article_response(
        request_id=request_id,
        request=request,
        article_result=article_result,
        kosis_result=kosis_result,
    )


__all__ = ["analyze_article_request"]

