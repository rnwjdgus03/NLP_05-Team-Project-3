from extract_hcx import extract_numeric_candidates, normalize_hcx_measurements, normalize_number


def test_plain_and_single_magnitude_numbers():
    assert normalize_number("1.8") == "1.8"
    assert normalize_number("2만867") == "20867"
    assert normalize_number("31.2만") == "312000"
    assert normalize_number("6838억") == "683800000000"


def test_mixed_korean_section_notation():
    assert normalize_number("5천121만7천221") == "51217221"
    assert normalize_number("1천24만4천550") == "10244550"
    assert normalize_number("1억2345만6789") == "123456789"
    assert normalize_number("1조7240억") == "1724000000000"
    assert normalize_number("3억5천만") == "350000000"


def test_invalid_unit_order_is_not_silently_reinterpreted():
    assert normalize_number("1만2억") == "1만2억"
    assert normalize_number("1백2천") == "1백2천"


def test_article_candidate_repairs_incorrect_model_value():
    text = "2024년 주민등록 전체 인구는 5천121만7천221명이다."
    candidates = extract_numeric_candidates(text)
    assert [(row["value"], row["unit"]) for row in candidates] == [("51217221", "명")]

    result = {
        "measurements": [{
            "measurement_text": "5천121만7천221명",
            "measurement_usage": "KOSIS_VALUE",
            "measurement_role": "현재값",
            "value": "1222221",
            "unit": "명",
        }]
    }
    normalized = normalize_hcx_measurements(result, candidates, text)
    assert normalized["measurements"][0]["value"] == "51217221"
    assert normalized["measurements"][0]["measurement_text"] == "5천121만7천221명"


def test_equal_values_at_different_spans_are_not_deduplicated():
    text = "1월은 10명, 2월은 10명, 3월은 12명이다."
    candidates = extract_numeric_candidates(text)

    assert [(row["value"], row["unit"]) for row in candidates] == [
        ("10", "명"),
        ("10", "명"),
        ("12", "명"),
    ]
    assert candidates[0]["start"] != candidates[1]["start"]
    assert candidates[0]["end"] != candidates[1]["end"]


def test_equal_values_with_different_periods_survive_hcx_normalization():
    text = "1월은 10명, 2월은 10명, 3월은 12명이다."
    candidates = extract_numeric_candidates(text)
    result = {
        "measurements": [
            {
                "measurement_text": "10명",
                "measurement_usage": "KOSIS_VALUE",
                "measurement_role": "현재값",
                "measurement_period": "202501",
                "measurement_item": "-",
                "value": "10",
                "unit": "명",
            },
            {
                "measurement_text": "10명",
                "measurement_usage": "KOSIS_VALUE",
                "measurement_role": "현재값",
                "measurement_period": "202502",
                "measurement_item": "-",
                "value": "10",
                "unit": "명",
            },
            {
                "measurement_text": "12명",
                "measurement_usage": "KOSIS_VALUE",
                "measurement_role": "현재값",
                "measurement_period": "202503",
                "measurement_item": "-",
                "value": "12",
                "unit": "명",
            },
        ]
    }

    normalized = normalize_hcx_measurements(result, candidates, text)
    assert [row["measurement_period"] for row in normalized["measurements"]] == [
        "202501",
        "202502",
        "202503",
    ]


def test_equal_values_keep_occurrence_specific_usage():
    text = "정책 목표는 10명이며, 실제 가입자는 10명이다."
    candidates = [
        {
            "measurement_text": "10명", "value": "10", "unit": "명",
            "measurement_usage": "POLICY_VALUE", "measurement_role": "목표값",
            "value_approximate": "N", "start": 6, "end": 9,
        },
        {
            "measurement_text": "10명", "value": "10", "unit": "명",
            "measurement_usage": "KOSIS_VALUE", "measurement_role": "현재값",
            "value_approximate": "N", "start": 20, "end": 23,
        },
    ]
    result = {
        "measurements": [
            {
                "measurement_text": "10명",
                "measurement_usage": "POLICY_VALUE",
                "measurement_role": "목표값",
                "measurement_period": "2025",
                "measurement_item": "목표 인원",
                "value": "10",
                "unit": "명",
            },
            {
                "measurement_text": "10명",
                "measurement_usage": "KOSIS_VALUE",
                "measurement_role": "현재값",
                "measurement_period": "2025",
                "measurement_item": "가입자",
                "value": "10",
                "unit": "명",
            },
        ]
    }
    normalized = normalize_hcx_measurements(result, candidates, text)
    assert [row["measurement_usage"] for row in normalized["measurements"]] == [
        "POLICY_VALUE", "KOSIS_VALUE",
    ]
