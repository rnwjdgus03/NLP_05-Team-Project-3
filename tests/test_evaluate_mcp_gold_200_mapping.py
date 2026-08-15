from evaluate_mcp_gold_200_mapping import (
    build_key_maps,
    coordinate_recall_metrics,
    evaluate_mapping,
    retrieval_metrics,
    rows_for_gold,
)


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


def test_retrieval_metrics_prefers_table_rank_over_coordinate_rank():
    gold = [{"gold_id": "G1", "gold_org_id": "101", "gold_tbl_id": "RIGHT"}]
    candidates = [{
        "gold_id": "G1", "org_id": "101", "tbl_id": "RIGHT",
        "candidate_rank": "9", "table_rank": "2",
    }]
    metrics, _ = retrieval_metrics(gold, candidates, (1, 2, 10))
    by_k = {row["top_k"]: row for row in metrics}
    assert by_k[1]["hits"] == 0
    assert by_k[2]["hits"] == 1


def test_measurement_id_wins_when_claim_has_multiple_predictions():
    gold = [{
        "gold_id": "G1", "claim_id": "C1", "claim_measurement_id": "C1-m2",
        "gold_org_id": "101", "gold_tbl_id": "RIGHT", "gold_itm_id": "I2",
        "gold_prd_se": "M", "gold_period": "202501",
    }]
    mapped = [
        {
            "claim_id": "C1", "claim_measurement_id": "C1-m1",
            "org_id": "101", "tbl_id": "WRONG", "selected_itm_id": "I1",
            "prd_se": "M", "period": "202501",
        },
        {
            "claim_id": "C1", "claim_measurement_id": "C1-m2",
            "org_id": "101", "tbl_id": "RIGHT", "selected_itm_id": "I2",
            "prd_se": "M", "period": "202501",
        },
    ]

    evaluated, metrics, failures = evaluate_mapping(gold, mapped)

    assert evaluated[0]["matched_by"] == "claim_measurement_id"
    assert evaluated[0]["pred_tbl_id"] == "RIGHT"
    assert evaluated[0]["full_mapping_correct"] == "Y"
    assert not failures


def test_unspecified_previous_period_does_not_penalize_context_preservation():
    gold = [{
        "gold_id": "G1", "claim_measurement_id": "C1-m1",
        "gold_org_id": "101", "gold_tbl_id": "T", "gold_itm_id": "I",
        "gold_prd_se": "M", "gold_period": "202501", "gold_previous_period": "N/A",
    }]
    mapped = [{
        "claim_measurement_id": "C1-m1", "org_id": "101", "tbl_id": "T",
        "selected_itm_id": "I", "coordinate_prd_se": "M", "period": "202501",
        "previous_period": "202401",
    }]
    evaluated, _, _ = evaluate_mapping(gold, mapped)
    assert evaluated[0]["previous_period_correct"] == "Y"
    assert evaluated[0]["period_group_correct"] == "Y"


def test_selected_periodicity_wins_over_table_capability_set():
    gold = [{
        "gold_id": "G1", "gold_org_id": "101", "gold_tbl_id": "T",
        "gold_itm_id": "I", "gold_prd_se": "M", "gold_period": "202501",
    }]
    mapped = [{
        "gold_id": "G1", "org_id": "101", "tbl_id": "T", "selected_itm_id": "I",
        "prd_se": "M", "coordinate_prd_se": "M|Q|Y", "period": "202501",
    }]
    evaluated, _, _ = evaluate_mapping(gold, mapped)
    assert evaluated[0]["pred_prd_se"] == "M"
    assert evaluated[0]["prd_se_correct"] == "Y"


def test_input_fixture_matches_gold_by_measurement_id_when_gold_id_is_absent():
    gold = {"gold_id": "G1", "claim_id": "C1", "claim_measurement_id": "C1-m2"}
    fixture = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m2",
        "input_quality_status": "READY",
    }]
    rows, matched_by, _ = rows_for_gold(gold, build_key_maps(fixture))
    assert matched_by == "claim_measurement_id"
    assert rows[0]["input_quality_status"] == "READY"


def test_coordinate_recall_scores_all_gold_specified_axes():
    gold = [{
        "gold_id": "G1", "gold_org_id": "101", "gold_tbl_id": "T",
        "gold_itm_id": "I", "gold_obj_l1": "R", "gold_obj_l2": "F",
        "gold_obj_l3": "AGE",
    }]
    candidates = [
        {"gold_id": "G1", "org_id": "101", "tbl_id": "T",
         "selected_itm_id": "I", "selected_obj_l1": "R",
         "selected_obj_l2": "F", "selected_obj_l3": "WRONG", "candidate_rank": "1"},
        {"gold_id": "G1", "org_id": "101", "tbl_id": "T",
         "selected_itm_id": "I", "selected_obj_l1": "R",
         "selected_obj_l2": "F", "selected_obj_l3": "AGE", "candidate_rank": "3"},
    ]
    rows = {row["top_k"]: row for row in coordinate_recall_metrics(gold, candidates, (1, 3))}
    assert rows[1]["coordinate_recall"] == 0.0
    assert rows[3]["coordinate_recall"] == 1.0
