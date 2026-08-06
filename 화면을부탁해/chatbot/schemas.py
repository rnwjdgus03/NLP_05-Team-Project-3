"""FastAPI와 챗봇 서비스가 공유하는 요청·응답 계약."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


KosisMode = Literal["table", "metadata", "verify"]
RetrievalMode = Literal["auto", "lexical", "hybrid"]
AnalysisStage = Literal["gate", "enrich", "candidate", "mapping", "verification"]
ProcessingStatus = Literal["completed", "partial"]


class ArticleAnalyzeRequest(BaseModel):
    """기사 원문 분석 API 요청."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=200_000)
    title: str = Field(default="", max_length=500)
    date: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=2_000)
    article_id: str = Field(default="A0001", max_length=200)
    splitter: Literal["auto", "kss", "regex"] = "auto"
    kosis_mode: KosisMode = "metadata"
    retrieval_mode: RetrievalMode = "auto"
    contextual: bool = True

    @field_validator("body")
    @classmethod
    def body_must_contain_visible_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("기사 원문이 비어 있습니다.")
        return value


class ArticleURLAnalyzeRequest(BaseModel):
    """기사 URL을 서버에서 수집한 뒤 분석하는 API 요청."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=2_000)
    article_id: str = Field(default="A0001", max_length=200)
    splitter: Literal["auto", "kss", "regex"] = "auto"
    kosis_mode: KosisMode = "metadata"
    retrieval_mode: RetrievalMode = "auto"
    contextual: bool = True


class SentenceAnalysis(BaseModel):
    """문장별 통계 주장 판별 결과."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    claim_text: str
    prev_sentence: str = ""
    prev_prev_sentence: str = ""
    next_sentence: str = ""
    is_claim: bool
    reason: str = ""
    confidence: str = ""


class KosisCandidate(BaseModel):
    """measurement에 대한 KOSIS 통계표 후보."""

    model_config = ConfigDict(extra="ignore")

    rank: int = Field(ge=1)
    score: float | None = None
    status: str = ""
    status_code: str = ""
    status_reason: str = ""
    org_id: str = ""
    tbl_id: str = ""
    tbl_name: str = ""
    category_path: str = ""


class MeasurementAnalysis(BaseModel):
    """하나의 measurement와 KOSIS 판정 결과."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    claim_measurement_id: str
    claim_text: str = ""
    measurement_text: str = ""
    measurement_usage: str = ""
    measurement_role: str = ""
    indicator: str = ""
    item: str = ""
    period: str = ""
    prd_se: str = ""
    value: str = ""
    unit: str = ""
    stage: AnalysisStage
    status: str
    status_code: str
    status_reason: str
    final_status: str = ""
    mapping_status: str = ""
    verdict_stage: str = ""
    review_reason: str = ""
    not_kosis_reason: str = ""
    enrichment_actions: str = ""
    scope_gate_code: str = ""
    scope_gate_reason: str = ""
    candidates: list[KosisCandidate] = Field(default_factory=list)
    kosis_actual_value: str = ""
    kosis_unit: str = ""
    kosis_period_used: str = ""
    needs_review: bool = False


class AnalysisSummary(BaseModel):
    """기사 분석 단계별 건수."""

    sentence_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    measurement_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    enrich_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    mapping_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    review_count: int = Field(default=0, ge=0)
    not_kosis_count: int = Field(default=0, ge=0)


class ArticleAnalyzeResponse(BaseModel):
    """기사 원문 분석 API의 최종 응답."""

    request_id: str
    processing_status: ProcessingStatus = "completed"
    article_id: str
    title: str = ""
    date: str = ""
    url: str = ""
    kosis_mode: KosisMode
    retrieval_mode: RetrievalMode = "auto"
    summary: AnalysisSummary
    sentences: list[SentenceAnalysis] = Field(default_factory=list)
    measurements: list[MeasurementAnalysis] = Field(default_factory=list)


class APIError(BaseModel):
    """API 오류 응답에 공통으로 사용할 정보."""

    code: str
    message: str
    stage: str = ""
    claim_id: str = ""


class ErrorResponse(BaseModel):
    request_id: str
    error: APIError


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "news-factcheck-chatbot"


__all__ = [
    "APIError",
    "AnalysisStage",
    "AnalysisSummary",
    "ArticleAnalyzeRequest",
    "ArticleAnalyzeResponse",
    "ArticleURLAnalyzeRequest",
    "ErrorResponse",
    "HealthResponse",
    "KosisCandidate",
    "KosisMode",
    "MeasurementAnalysis",
    "ProcessingStatus",
    "RetrievalMode",
    "SentenceAnalysis",
]
