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
