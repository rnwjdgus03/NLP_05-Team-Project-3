from chatbot.schemas import ArticleAnalyzeRequest
from chatbot.services.response_builder import build_article_response


def test_build_article_response_flattens_internal_pipeline_rows():
    request = ArticleAnalyzeRequest(
        body="소비자물가는 2.3% 상승했다.",
        title="물가 기사",
        date="2026-08-04",
        kosis_mode="verify",
    )
    measurement = {
        "claim_id": "A0001-C001",
        "claim_measurement_id": "A0001-C001-m1",
        "claim_text": request.body,
        "measurement_text": "2.3%",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_indicator": "소비자물가 증감률",
        "measurement_period": "2026",
        "measurement_prd_se": "Y",
        "value": "2.3",
        "unit": "%",
        "needs_review": "N",
    }
    article_result = {
        "article_id": "A0001",
        "splitter": "regex",
        "sentence_count": 1,
        "claim_count": 1,
        "sentences": [
            {
                "claim_id": "A0001-C001",
                "article_id": "A0001",
                "title": request.title,
                "date": request.date,
                "url": "",
                "claim_text": request.body,
                "prev_sentence": "",
                "prev_prev_sentence": "",
                "is_claim": "True",
                "is_claim_reason": "통계 주장",
                "is_claim_confidence": "high",
                "is_claim_method": "hcx",
                "extraction_model": "HCX-007",
                "prompt_version": "test",
                "extracted_at": "2026-08-04",
            }
        ],
        "claims": [],
        "measurement_count": 1,
        "measurement_row_count": 1,
        "measurements": [measurement],
    }
    kosis_result = {
        "article_id": "A0001",
        "mode": "verify",
        "measurement_count": 1,
        "eligible_count": 1,
        "enrich_count": 0,
        "rejected_count": 0,
        "candidate_count": 1,
        "mapping_count": 1,
        "verified_count": 1,
        "review_count": 0,
        "not_kosis_count": 0,
        "retrieval_mode": "auto",
        "results": [
            {
                "claim_id": "A0001-C001",
                "claim_measurement_id": "A0001-C001-m1",
                "status": "일치",
                "status_code": "MATCH",
                "status_reason": "차이율=0.2%",
                "stage": "verification",
                "final_status": "READY",
                "mapping_status": "READY",
                "measurement": measurement,
                "rejection": None,
                "candidates": [
                    {
                        "candidate_rank": "1",
                        "candidate_score": "24",
                        "candidate_status": "READY",
                        "candidate_status_code": "READY",
                        "candidate_status_reason": "통계표 확정",
                        "org_id": "101",
                        "tbl_id": "DT_TEST",
                        "tbl_name": "소비자물가지수",
                    }
                ],
                "mapping": {"mapping_status": "READY"},
                "verification": {
                    "verdict": "일치",
                    "final_status": "READY",
                    "mapping_status": "READY",
                    "kosis_actual_value": "2.295",
                    "kosis_unit": "%",
                    "kosis_period_used": "2026",
                },
            }
        ],
    }

    response = build_article_response(
        request_id="req-001",
        request=request,
        article_result=article_result,
        kosis_result=kosis_result,
    )

    assert response.summary.verified_count == 1
    assert response.retrieval_mode == "auto"
    assert response.sentences[0].is_claim is True
    assert response.measurements[0].status_code == "MATCH"
    assert response.measurements[0].final_status == "READY"
    assert response.measurements[0].mapping_status == "READY"
    assert response.measurements[0].needs_review is False
    assert response.measurements[0].candidates[0].tbl_id == "DT_TEST"
    assert response.measurements[0].kosis_actual_value == "2.295"
