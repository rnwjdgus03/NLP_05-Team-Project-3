from evaluate_mcp_gold_200_mapping import evaluate_mapping, retrieval_metrics


def test_retrieval_metrics_score_table_recall_at_k():
    gold = [
        {"gold_id": "G1", "claim_id": "C1", "gold_org_id": "101", "gold_tbl_id": "T1"},
        {"gold_id": "G2", "claim_id": "C2", "gold_org_id": "101", "gold_tbl_id": "T2"},
        {"gold_id": "G3", "claim_id": "C3", "gold_org_id": "101", "gold_tbl_id": "T3"},
    ]
    candidates = [
        {"gold_id": "G1", "org_id": "101", "tbl_id": "T1", "candidate_rank": "1"},
        {"claim_id": "C2", "org_id": "101", "tbl_id": "TX", "candidate_rank": "1"},
        {"claim_id": "C2", "org_id": "101", "tbl_id": "T2", "candidate_rank": "3"},
    ]

    metrics, misses = retrieval_metrics(gold, candidates, (1, 3))

    by_k = {row["top_k"]: row for row in metrics}
    assert by_k[1]["hits"] == 1
    assert by_k[1]["table_recall"] == 0.333333
    assert by_k[3]["hits"] == 2
    assert by_k[3]["table_recall"] == 0.666667
    assert [row["gold_id"] for row in misses] == ["G3"]


def test_evaluate_mapping_scores_full_coordinate_match():
    gold = [
        {
            "gold_id": "G1",
            "claim_id": "C1",
            "gold_org_id": "101",
            "gold_tbl_id": "T1",
            "gold_obj_l1": "A",
            "gold_obj_l2": "B",
            "gold_itm_id": "I1",
            "gold_prd_se": "M",
            "gold_period": "202401",
            "gold_previous_period": "202301",
        },
        {
            "gold_id": "G2",
            "claim_id": "C2",
            "gold_org_id": "101",
            "gold_tbl_id": "T2",
            "gold_obj_l1": "A",
            "gold_obj_l2": "",
            "gold_itm_id": "I2",
            "gold_prd_se": "Y",
            "gold_period": "2024",
            "gold_previous_period": "",
        },
    ]
    mapped = [
        {
            "claim_id": "C1",
            "org_id": "101",
            "tbl_id": "T1",
            "obj_l1": "A",
            "obj_l2": "B",
            "itm_id": "I1",
            "prd_se": "M",
            "period": "202401",
            "previous_period": "202301",
        },
        {
            "claim_id": "C2",
            "org_id": "101",
            "tbl_id": "WRONG",
            "obj_l1": "A",
            "itm_id": "I2",
            "prd_se": "Y",
            "period": "2024",
        },
    ]

    evaluated, metrics, failures = evaluate_mapping(gold, mapped)

    by_metric = {row["metric"]: row for row in metrics}
    assert by_metric["mapping_coverage"]["rate"] == 1.0
    assert by_metric["table_accuracy"]["rate"] == 0.5
    assert by_metric["item_accuracy"]["rate"] == 1.0
    assert by_metric["period_accuracy"]["rate"] == 1.0
    assert by_metric["full_mapping_accuracy"]["rate"] == 0.5
    assert evaluated[0]["full_mapping_correct"] == "Y"
    assert [row["gold_id"] for row in failures] == ["G2"]
