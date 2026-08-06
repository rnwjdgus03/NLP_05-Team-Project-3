import pytest

from chatbot.services.article_pipeline import (
    ArticleClaimClassificationError,
    ArticleMeasurementExtractionError,
    ArticlePreprocessingError,
    analyze_article_measurements,
    classify_article_claims,
    detect_article_claims,
    extract_article_measurements,
    preprocess_article,
)


def test_preprocess_article_converts_raw_text_to_claim_records():
    result = preprocess_article(
        """
        <p>통계청이 고용 동향을 발표했다.</p>
        <p>취업자는 10만명 증가했다. 고용률도 1.2% 올랐다.</p>
        무단 전재 및 재배포 금지
        """,
        title="8월 고용지표 발표",
        date="2026-08-04",
        url="https://example.com/employment",
        article_id="NEWS-001",
        splitter="regex",
    )

    assert result["article_id"] == "NEWS-001"
    assert result["splitter"] == "regex"
    assert result["sentence_count"] == 3
    assert [row["claim_id"] for row in result["sentences"]] == [
        "NEWS-001-C001",
        "NEWS-001-C002",
        "NEWS-001-C003",
    ]
    assert result["sentences"][2]["prev_sentence"] == "취업자는 10만명 증가했다."
    assert (
        result["sentences"][2]["prev_prev_sentence"]
        == "통계청이 고용 동향을 발표했다."
    )
    assert all(row["title"] == "8월 고용지표 발표" for row in result["sentences"])
    assert all("무단 전재" not in row["claim_text"] for row in result["sentences"])
    assert (
        result["sentences"][0]["next_sentence"]
        == result["sentences"][1]["claim_text"]
    )


@pytest.mark.parametrize("body", ["", "   ", None])
def test_preprocess_article_rejects_blank_body(body):
    with pytest.raises(ArticlePreprocessingError, match="비어"):
        preprocess_article(body, splitter="regex")


def test_preprocess_article_rejects_body_removed_as_noise():
    with pytest.raises(ArticlePreprocessingError, match="정제한 후"):
        preprocess_article("무단 전재 및 재배포 금지", splitter="regex")


def test_preprocess_article_generates_default_id_when_id_is_blank():
    result = preprocess_article(
        "소비자물가는 2.3% 상승했다.",
        article_id="",
        splitter="regex",
    )

    assert result["article_id"] == "A0001"
    assert result["sentences"][0]["claim_id"] == "A0001-C001"


def test_classify_article_claims_preserves_context_and_filters_true_claims():
    preprocessed = preprocess_article(
        "통계청이 발표했다. 소비자물가는 2.3% 상승했다.",
        date="2026-08-04",
        splitter="regex",
    )
    calls = []

    def fake_classifier(**kwargs):
        calls.append(kwargs)
        is_claim = "2.3%" in kwargs["text"]
        return {
            "is_claim": is_claim,
            "reason": "통계 수치 주장" if is_claim else "발표 문맥",
            "confidence": "high",
        }

    result = classify_article_claims(
        preprocessed,
        classifier=fake_classifier,
        sleep_seconds=0,
    )

    assert result["sentence_count"] == 2
    assert result["claim_count"] == 1
    assert result["claims"][0]["claim_text"] == "소비자물가는 2.3% 상승했다."
    assert result["claims"][0]["is_claim"] == "True"
    assert result["sentences"][0]["is_claim"] == "False"
    assert calls[1]["prev"] == "통계청이 발표했다."
    assert calls[1]["prev_prev"] == "-"
    assert calls[1]["date"] == "2026-08-04"


def test_detect_article_claims_runs_preprocessing_and_classification():
    def fake_classifier(**kwargs):
        return {
            "is_claim": "%" in kwargs["text"],
            "reason": "test",
            "confidence": "medium",
        }

    result = detect_article_claims(
        "인구 동향을 발표했다. 출생률은 0.8% 하락했다.",
        article_id="NEWS-002",
        splitter="regex",
        classifier=fake_classifier,
        sleep_seconds=0,
    )

    assert result["article_id"] == "NEWS-002"
    assert result["claim_count"] == 1
    assert result["claims"][0]["claim_id"] == "NEWS-002-C002"


def test_classify_article_claims_wraps_classifier_error_with_claim_id():
    preprocessed = preprocess_article("소비자물가는 2.3% 올랐다.", splitter="regex")

    def broken_classifier(**kwargs):
        raise TimeoutError("API timeout")

    with pytest.raises(
        ArticleClaimClassificationError,
        match="A0001-C001 주장 판별 실패",
    ):
        classify_article_claims(
            preprocessed,
            classifier=broken_classifier,
            sleep_seconds=0,
        )


def test_extract_article_measurements_only_processes_true_claims():
    classified = detect_article_claims(
        "통계청이 발표했다. 소비자물가는 2.3% 상승했다.",
        splitter="regex",
        sleep_seconds=0,
        classifier=lambda **kwargs: {
            "is_claim": "%" in kwargs["text"],
            "reason": "test",
            "confidence": "high",
        },
    )
    calls = []

    def fake_extractor(**kwargs):
        calls.append(kwargs)
        return {
            "claim_domain_scope": "국내공식통계",
            "is_recurring_series": "Y",
            "indicator": "소비자물가",
            "measurements": [
                {
                    "measurement_text": "2.3%",
                    "measurement_usage": "KOSIS_VALUE",
                    "measurement_indicator": "소비자물가 증감률",
                    "measurement_item": "전체",
                    "measurement_period": "2026",
                    "measurement_prd_se": "Y",
                    "measurement_role": "증감률",
                    "value": "2.3",
                    "unit": "%",
                    "value_type": "RATE",
                    "direction": "증가",
                    "change_base": "전년",
                }
            ],
        }

    result = extract_article_measurements(
        classified,
        extractor=fake_extractor,
        sleep_seconds=0,
    )

    assert len(calls) == 1
    assert calls[0]["claim"]["claim_id"] == "A0001-C002"
    assert calls[0]["claim"]["context_version"].startswith("claim-context-v2.0")
    assert calls[0]["claim"]["article_context"]
    assert calls[0]["claim"]["local_context"]
    assert calls[0]["claim"]["context_sentence_ids"]
    assert result["claim_count"] == 1
    assert result["measurement_count"] == 1
    assert result["measurement_row_count"] == 1
    assert result["measurements"][0]["claim_measurement_id"] == "A0001-C002-m1"
    assert result["measurements"][0]["value"] == "2.3"
    assert result["measurements"][0]["unit"] == "%"


def test_analyze_article_measurements_runs_all_hcx_stages():
    classifier_calls = []
    extractor_calls = []

    def fake_classifier(**kwargs):
        classifier_calls.append(kwargs)
        return {
            "is_claim": "10만명" in kwargs["text"],
            "reason": "test",
            "confidence": "high",
        }

    def fake_extractor(**kwargs):
        extractor_calls.append(kwargs)
        return {
            "claim_domain_scope": "국내공식통계",
            "is_recurring_series": "Y",
            "measurements": [
                {
                    "measurement_text": "10만명",
                    "measurement_usage": "KOSIS_VALUE",
                    "measurement_indicator": "취업자 증감",
                    "measurement_period": "2026",
                    "measurement_prd_se": "Y",
                    "measurement_role": "증감량",
                    "value": "100000",
                    "unit": "명",
                }
            ],
        }

    result = analyze_article_measurements(
        "고용 동향을 발표했다. 취업자는 10만명 증가했다.",
        article_id="NEWS-003",
        splitter="regex",
        claim_sleep_seconds=0,
        extraction_sleep_seconds=0,
        classifier=fake_classifier,
        extractor=fake_extractor,
    )

    assert len(classifier_calls) == 2
    assert len(extractor_calls) == 1
    assert result["article_id"] == "NEWS-003"
    assert result["claim_count"] == 1
    assert result["measurement_count"] == 1
    assert result["measurements"][0]["claim_id"] == "NEWS-003-C002"


def test_extract_article_measurements_returns_empty_when_no_claims():
    classified = detect_article_claims(
        "통계청이 발표했다.",
        splitter="regex",
        sleep_seconds=0,
        classifier=lambda **kwargs: {
            "is_claim": False,
            "reason": "주장 아님",
            "confidence": "high",
        },
    )

    result = extract_article_measurements(classified, sleep_seconds=0)

    assert result["claim_count"] == 0
    assert result["measurement_count"] == 0
    assert result["measurement_row_count"] == 0
    assert result["measurements"] == []


def test_extract_article_measurements_wraps_extractor_error_with_claim_id():
    classified = detect_article_claims(
        "소비자물가는 2.3% 올랐다.",
        splitter="regex",
        sleep_seconds=0,
        classifier=lambda **kwargs: {
            "is_claim": True,
            "reason": "test",
            "confidence": "high",
        },
    )

    def broken_extractor(**kwargs):
        raise TimeoutError("API timeout")

    with pytest.raises(
        ArticleMeasurementExtractionError,
        match="A0001-C001 measurement 추출 실패",
    ):
        extract_article_measurements(
            classified,
            extractor=broken_extractor,
            sleep_seconds=0,
        )
