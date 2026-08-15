from evaluate_locked_blind_mcp import evaluate


def test_evaluate_reports_retrieval_coordinate_and_period_separately() -> None:
    evidence = [
        {
            "claim_measurement_id": "A-m1",
            "article_id": "A",
            "gold_tbl_id": "T-GOLD",
            "gold_itm_id": "I1",
            "gold_obj_l1": "O1",
            "gold_period": "202501",
            "table_gold_eligible": True,
            "coordinate_gold_eligible": True,
            "period_gold_eligible": True,
        }
    ]
    candidates = [
        {"claim_measurement_id": "A-m1", "tbl_id": "T-WRONG", "candidate_rank": "1"},
        {"claim_measurement_id": "A-m1", "tbl_id": "T-GOLD", "candidate_rank": "2"},
    ]
    selected = [
        {
            "claim_measurement_id": "A-m1",
            "tbl_id": "T-GOLD",
            "selected_itm_id": "I1",
            "selected_obj_l1": "O1",
        }
    ]
    claims = [{"claim_measurement_id": "A-m1", "period": "202501"}]

    result = evaluate(evidence, candidates, selected, claims)

    assert result["metrics"]["table_recall_at_1"]["rate"] == 0.0
    assert result["metrics"]["table_recall_at_5"]["rate"] == 1.0
    assert result["metrics"]["selected_table_exact"]["rate"] == 1.0
    assert result["metrics"]["selected_coordinate_exact"]["rate"] == 1.0
    assert result["metrics"]["period_extraction_exact"]["rate"] == 1.0


def test_equivalent_verified_table_counts_for_retrieval():
    evidence = [{
        "claim_measurement_id": "A-m1",
        "gold_tbl_id": "CANONICAL",
        "acceptable_tbl_ids": ["ALTERNATE"],
        "table_gold_eligible": True,
    }]
    result = evaluate(
        evidence,
        [{"claim_measurement_id": "A-m1", "tbl_id": "ALTERNATE", "candidate_rank": "1"}],
        [],
        [{"claim_measurement_id": "A-m1"}],
    )
    assert result["metrics"]["table_recall_at_1"]["rate"] == 1.0
