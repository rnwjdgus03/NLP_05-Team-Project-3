from evaluate_mcp_gold_200_regression import evaluate, normalize_label


def test_normalize_label_accepts_english_and_korean_verdicts():
    assert normalize_label("SUPPORTS") == "SUPPORTS"
    assert normalize_label("MATCH") == "SUPPORTS"
    assert normalize_label("일치") == "SUPPORTS"
    assert normalize_label("REFUTES") == "REFUTES"
    assert normalize_label("MISMATCH") == "REFUTES"
    assert normalize_label("불일치") == "REFUTES"
    assert normalize_label("판정보류") == ""


def test_evaluate_scores_strict_and_decided_accuracy():
    gold = [
        {"gold_id": "G1", "claim_id": "C1", "gold_label": "SUPPORTS"},
        {"gold_id": "G2", "claim_id": "C2", "gold_label": "REFUTES"},
        {"gold_id": "G3", "claim_id": "C3", "gold_label": "REFUTES"},
    ]
    predictions = [
        {"gold_id": "G1", "predicted_label": "SUPPORTS"},
        {"claim_id": "C2", "predicted_label": "SUPPORTS"},
    ]

    result = evaluate(gold, predictions)

    assert result["summary"]["gold_rows"] == 3
    assert result["summary"]["covered_labels"] == 2
    assert result["summary"]["correct"] == 1
    assert result["summary"]["strict_accuracy"] == 0.333333
    assert result["summary"]["decided_accuracy"] == 0.5
    assert result["summary"]["error_counts"] == {
        "correct": 1,
        "label_mismatch": 1,
        "uncovered": 1,
    }


def test_evaluate_checks_coordinate_fields_when_predictions_include_them():
    gold = [
        {
            "gold_id": "G1",
            "claim_id": "C1",
            "gold_label": "SUPPORTS",
            "gold_org_id": "101",
            "gold_tbl_id": "T1",
            "gold_obj_l1": "A",
            "gold_obj_l2": "B",
            "gold_itm_id": "I1",
            "gold_prd_se": "M",
            "gold_period": "202401",
            "gold_actual_value": "10.5",
        }
    ]
    predictions = [
        {
            "claim_id": "C1",
            "verdict": "일치",
            "org_id": "101",
            "tbl_id": "T1",
            "obj_l1": "A",
            "obj_l2": "B",
            "itm_id": "I1",
            "prd_se": "M",
            "period": "202401",
            "actual_value": "10.50",
        }
    ]

    result = evaluate(gold, predictions)
    row = result["evaluated"][0]

    assert row["correct"] == "Y"
    assert row["coordinate_full_exact"] == "Y"
    assert result["summary"]["coordinate_full_exact"] == 1
    assert row["actual_abs_error"] == "0.00"
