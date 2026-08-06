"""기사 원문 사실검증 FastAPI 애플리케이션."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from chatbot.schemas import (
    APIError,
    ArticleAnalyzeRequest,
    ArticleAnalyzeResponse,
    ArticleURLAnalyzeRequest,
    ErrorResponse,
    HealthResponse,
)
from chatbot.services.analysis_service import analyze_article_request
from chatbot.services.article_pipeline import (
    ArticleClaimClassificationError,
    ArticleMeasurementExtractionError,
    ArticlePreprocessingError,
)
from chatbot.services.kosis_pipeline import KosisPipelineError
from chatbot.services.article_scraper import (
    ArticleExtractionError,
    ArticleFetchError,
    InvalidArticleURLError,
    ScrapedArticle,
    fetch_article,
)


logger = logging.getLogger(__name__)
AnalysisService = Callable[[ArticleAnalyzeRequest, str], ArticleAnalyzeResponse]
ArticleFetcher = Callable[[str], ScrapedArticle]
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    stage: str,
) -> JSONResponse:
    payload = ErrorResponse(
        request_id=request_id,
        error=APIError(code=code, message=message, stage=stage),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def create_app(
    analysis_service: AnalysisService | None = None,
    article_fetcher: ArticleFetcher | None = None,
) -> FastAPI:
    active_service = analysis_service or analyze_article_request
    active_fetcher = article_fetcher or fetch_article
    application = FastAPI(
        title="News Fact-check Chatbot API",
        version="0.1.0",
        description="기사 원문의 수치 주장을 추출하고 KOSIS와 대조합니다.",
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request
        first = error.errors()[0] if error.errors() else {}
        message = str(first.get("msg") or "입력값 검증에 실패했습니다.")
        return _error_response(
            request_id=str(uuid4()),
            status_code=422,
            code="INVALID_REQUEST",
            message=message,
            stage="request",
        )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @application.get("/", include_in_schema=False)
    def chatbot_home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.post(
        "/api/articles/analyze",
        response_model=ArticleAnalyzeResponse,
        responses={
            422: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    def analyze(request: ArticleAnalyzeRequest):
        request_id = str(uuid4())
        try:
            return active_service(request, request_id)
        except ArticlePreprocessingError as error:
            return _error_response(
                request_id=request_id,
                status_code=422,
                code="ARTICLE_PREPROCESSING_FAILED",
                message=str(error),
                stage="preprocessing",
            )
        except ArticleClaimClassificationError as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="CLAIM_CLASSIFICATION_FAILED",
                message=str(error),
                stage="claim_classification",
            )
        except ArticleMeasurementExtractionError as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="MEASUREMENT_EXTRACTION_FAILED",
                message=str(error),
                stage="measurement_extraction",
            )
        except KosisPipelineError as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="KOSIS_PIPELINE_FAILED",
                message=str(error),
                stage="kosis",
            )
        except Exception:
            logger.exception("Unexpected article analysis error request_id=%s", request_id)
            return _error_response(
                request_id=request_id,
                status_code=500,
                code="INTERNAL_ERROR",
                message="기사 분석 중 내부 오류가 발생했습니다.",
                stage="internal",
            )

    @application.post(
        "/api/articles/analyze-url",
        response_model=ArticleAnalyzeResponse,
        responses={
            422: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    def analyze_url(request: ArticleURLAnalyzeRequest):
        request_id = str(uuid4())
        try:
            article = active_fetcher(request.url)
            analysis_request = ArticleAnalyzeRequest(
                body=article.body,
                title=article.title,
                date=article.date,
                url=article.url,
                article_id=request.article_id,
                splitter=request.splitter,
                kosis_mode=request.kosis_mode,
            )
            return active_service(analysis_request, request_id)
        except InvalidArticleURLError as error:
            return _error_response(
                request_id=request_id,
                status_code=422,
                code="INVALID_ARTICLE_URL",
                message=str(error),
                stage="article_fetch",
            )
        except (ArticleFetchError, ArticleExtractionError) as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="ARTICLE_FETCH_FAILED",
                message=str(error),
                stage="article_fetch",
            )
        except ArticlePreprocessingError as error:
            return _error_response(
                request_id=request_id,
                status_code=422,
                code="ARTICLE_PREPROCESSING_FAILED",
                message=str(error),
                stage="preprocessing",
            )
        except ArticleClaimClassificationError as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="CLAIM_CLASSIFICATION_FAILED",
                message=str(error),
                stage="claim_classification",
            )
        except ArticleMeasurementExtractionError as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="MEASUREMENT_EXTRACTION_FAILED",
                message=str(error),
                stage="measurement_extraction",
            )
        except KosisPipelineError as error:
            return _error_response(
                request_id=request_id,
                status_code=502,
                code="KOSIS_PIPELINE_FAILED",
                message=str(error),
                stage="kosis",
            )
        except Exception:
            logger.exception("Unexpected URL analysis error request_id=%s", request_id)
            return _error_response(
                request_id=request_id,
                status_code=500,
                code="INTERNAL_ERROR",
                message="기사 분석 중 내부 오류가 발생했습니다.",
                stage="internal",
            )

    return application


app = create_app()


__all__ = ["app", "create_app"]
