"""내부 분석 dict를 사용자용 API 응답으로 변환한다."""

from __future__ import annotations

from collections.abc import Mapping

from chatbot.schemas import (
    AnalysisSummary,
    ArticleAnalyzeRequest,
    ArticleAnalyzeResponse,
    KosisCandidate,
    MeasurementAnalysis,
    SentenceAnalysis,
)
from chatbot.services.article_pipeline import ArticleMeasurementResult
from chatbot.services.kosis_pipeline import KosisArticleResult


def _text(value: object) -> str:
    return str(value or "").strip()


def _truthy(value: object) -> bool:
    return value is True or _text(value).lower() in {"true", "y", "yes", "1"}


def _number(value: object) -> float | None:
    try:
        text = _text(value)
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(_text(value))
        return parsed if parsed >= 1 else default
    except ValueError:
        return default


def _candidate(row: Mapping[str, object], fallback_rank: int) -> KosisCandidate:
    return KosisCandidate(
        rank=_positive_int(row.get("candidate_rank"), fallback_rank),
        score=_number(row.get("candidate_score")),
        status=_text(row.get("candidate_status")),
        status_code=_text(row.get("candidate_status_code")),
        status_reason=_text(row.get("candidate_status_reason")),
        org_id=_text(row.get("org_id")),
        tbl_id=_text(row.get("tbl_id")),
        tbl_name=_text(row.get("tbl_name")),
        category_path=_text(row.get("category_path")),
    )


def build_article_response(
    *,
    request_id: str,
    request: ArticleAnalyzeRequest,
    article_result: ArticleMeasurementResult,
    kosis_result: KosisArticleResult,
) -> ArticleAnalyzeResponse:
    """문장·measurement·KOSIS 결과를 공개 API 계약으로 축약한다."""
    sentences = [
        SentenceAnalysis(
            claim_id=_text(row.get("claim_id")),
            claim_text=_text(row.get("claim_text")),
            prev_sentence=_text(row.get("prev_sentence")),
            prev_prev_sentence=_text(row.get("prev_prev_sentence")),
            next_sentence=_text(row.get("next_sentence")),
            is_claim=_truthy(row.get("is_claim")),
            reason=_text(row.get("is_claim_reason")),
            confidence=_text(row.get("is_claim_confidence")),
        )
        for row in article_result.get("sentences") or []
    ]

    measurements: list[MeasurementAnalysis] = []
    for result in kosis_result.get("results") or []:
        source = result.get("measurement") or {}
        verification = result.get("verification") or {}
        mapping = result.get("mapping") or {}
        enrichment = result.get("enrichment") or {}
        rejection = result.get("rejection") or {}
        details = verification or mapping or enrichment or rejection
        candidates = [
            _candidate(row, index)
            for index, row in enumerate(result.get("candidates") or [], 1)
        ]
        status = _text(result.get("status"))
        status_code = _text(result.get("status_code"))
        final_status = _text(result.get("final_status"))
        mapping_status = _text(result.get("mapping_status"))
        needs_review = (
            final_status != "NOT_KOSIS"
            and (
                final_status == "REVIEW"
                or result.get("stage") == "enrich"
                or _truthy(source.get("needs_review"))
                or status_code not in {"MATCH", "VALUE_MISMATCH"}
                or status not in {"일치", "불일치"}
            )
        )
        measurements.append(
            MeasurementAnalysis(
                claim_id=_text(result.get("claim_id")),
                claim_measurement_id=_text(result.get("claim_measurement_id")),
                claim_text=_text(source.get("claim_text")),
                measurement_text=_text(source.get("measurement_text")),
                measurement_usage=_text(source.get("measurement_usage")),
                measurement_role=_text(source.get("measurement_role")),
                indicator=_text(source.get("measurement_indicator"))
                or _text(source.get("indicator")),
                item=_text(source.get("measurement_item"))
                or _text(source.get("industry_or_item")),
                period=_text(source.get("measurement_period"))
                or _text(source.get("period")),
                prd_se=_text(source.get("measurement_prd_se"))
                or _text(source.get("prd_se")),
                value=_text(source.get("value")),
                unit=_text(source.get("unit")),
                stage=result["stage"],
                status=status,
                status_code=status_code,
                status_reason=_text(result.get("status_reason")),
                final_status=final_status,
                mapping_status=mapping_status,
                verdict_stage=_text(verification.get("verdict_stage")),
                review_reason=_text(details.get("review_reason")),
                not_kosis_reason=_text(details.get("not_kosis_reason")),
                enrichment_actions=_text(enrichment.get("enrichment_actions")),
                scope_gate_code=_text(details.get("scope_gate_code")),
                scope_gate_reason=_text(details.get("scope_gate_reason")),
                candidates=candidates,
                kosis_actual_value=_text(verification.get("kosis_actual_value")),
                kosis_unit=_text(verification.get("kosis_unit")),
                kosis_period_used=_text(verification.get("kosis_period_used")),
                needs_review=needs_review,
            )
        )

    summary = AnalysisSummary(
        sentence_count=int(article_result.get("sentence_count") or 0),
        claim_count=int(article_result.get("claim_count") or 0),
        measurement_count=int(article_result.get("measurement_count") or 0),
        eligible_count=int(kosis_result.get("eligible_count") or 0),
        enrich_count=int(kosis_result.get("enrich_count") or 0),
        rejected_count=int(kosis_result.get("rejected_count") or 0),
        candidate_count=int(kosis_result.get("candidate_count") or 0),
        mapping_count=int(kosis_result.get("mapping_count") or 0),
        verified_count=int(kosis_result.get("verified_count") or 0),
        review_count=int(kosis_result.get("review_count") or 0),
        not_kosis_count=int(kosis_result.get("not_kosis_count") or 0),
    )
    return ArticleAnalyzeResponse(
        request_id=request_id,
        article_id=_text(article_result.get("article_id")) or request.article_id,
        title=request.title,
        date=request.date,
        url=request.url,
        kosis_mode=request.kosis_mode,
        retrieval_mode=request.retrieval_mode,
        summary=summary,
        sentences=sentences,
        measurements=measurements,
    )


__all__ = ["build_article_response"]
