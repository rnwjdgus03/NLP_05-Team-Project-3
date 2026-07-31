from evaluate_context_window_ablation import candidate_key, score


def test_candidate_key_normalizes_measurement_fields():
    row = {
        "article_id": "A0006",
        "measurement_indicator": "반도체 수출액",
        "measurement_item": "반도체",
        "value": "1,000.0",
        "unit": "억원",
        "measurement_period": "2025-01",
        "measurement_prd_se": "M",
        "measurement_role": "증감값",
    }

    assert candidate_key(row) == "A0006|수출:반도체|1000|억원|202501|M|증감량"


def test_score_uses_missing_prediction_as_negative():
    gold = [
        {
            "candidate_id": "CG1",
            "candidate_key": "positive",
            "gold_ready_draft": "Y",
            "human_override": "",
        },
        {
            "candidate_id": "CG2",
            "candidate_key": "negative",
            "gold_ready_draft": "N",
            "human_override": "",
        },
    ]

    result = score(gold, {"positive": "Y"})

    assert result["tp"] == 1
    assert result["tn"] == 1
    assert result["f1"] == 1.0


def test_score_prefers_locked_gold_ready_column():
    gold = [
        {
            "candidate_id": "CG1",
            "candidate_key": "locked",
            "gold_ready": "Y",
            "gold_ready_draft": "N",
            "human_override": "",
        }
    ]

    result = score(gold, {"locked": "Y"})

    assert result["tp"] == 1
