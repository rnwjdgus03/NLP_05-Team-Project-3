import pytest
from pydantic import ValidationError

from chatbot.schemas import (
    AnalysisSummary,
    ArticleAnalyzeRequest,
    ArticleAnalyzeResponse,
    MeasurementAnalysis,
    SentenceAnalysis,
)


def test_article_analyze_request_strips_metadata_and_sets_defaults():
    request = ArticleAnalyzeRequest(
        body="  소비자물가는 2.3% 상승했다.  ",
        title="  물가 기사  ",
    )

    assert request.body == "소비자물가는 2.3% 상승했다."
    assert request.title == "물가 기사"
    assert request.article_id == "A0001"
    assert request.splitter == "auto"
    assert request.kosis_mode == "metadata"
    assert request.retrieval_mode == "auto"
    assert request.contextual is True


@pytest.mark.parametrize("body", ["", "   ", "\n\t"])
def test_article_analyze_request_rejects_blank_body(body):
    with pytest.raises(ValidationError):
        ArticleAnalyzeRequest(body=body)


def test_article_analyze_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ArticleAnalyzeRequest(body="기사 본문", unknown_option=True)


def test_article_analyze_response_serializes_stable_public_contract():
    response = ArticleAnalyzeResponse(
        request_id="req-001",
        article_id="A0001",
        title="물가 기사",
        date="2026-08-04",
        kosis_mode="verify",
        summary=AnalysisSummary(
            sentence_count=2,
            claim_count=1,
            measurement_count=1,
            eligible_count=1,
            rejected_count=0,
            candidate_count=2,
            mapping_count=1,
            verified_count=1,
        ),
        sentences=[
            SentenceAnalysis(
                claim_id="A0001-C002",
                claim_text="소비자물가는 2.3% 상승했다.",
                is_claim=True,
                reason="통계 주장",
                confidence="high",
            )
        ],
        measurements=[
            MeasurementAnalysis(
                claim_id="A0001-C002",
                claim_measurement_id="A0001-C002-m1",
                claim_text="소비자물가는 2.3% 상승했다.",
                measurement_text="2.3%",
                value="2.3",
                unit="%",
                stage="verification",
                status="일치",
                status_code="MATCH",
                status_reason="차이율=0.2%",
                final_status="READY",
                mapping_status="READY",
                kosis_actual_value="2.295",
                kosis_unit="%",
                kosis_period_used="2026",
            )
        ],
    )

    payload = response.model_dump(mode="json")

    assert payload["processing_status"] == "completed"
    assert payload["summary"]["verified_count"] == 1
    assert payload["measurements"][0]["status_code"] == "MATCH"
    assert payload["measurements"][0]["final_status"] == "READY"
    assert payload["measurements"][0]["candidates"] == []
