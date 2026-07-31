from evaluate_chroma_hybrid_mapping import (
    GOLD_REQUIRED,
    api_valid_measurements,
    best_status_by_measurement,
    evaluate,
    ranked_by_measurement,
    recall_at_k,
    ready_coordinate_precision,
)

KEYS = {"M1", "M2"}

CANDIDATES = [
    {"claim_measurement_id": "M1", "candidate_rank": "1", "tbl_id": "T_WRONG",
     "selected_itm_id": "I9", "selected_obj_l1": "9"},
    {"claim_measurement_id": "M1", "candidate_rank": "2", "tbl_id": "T_GOLD",
     "selected_itm_id": "I1", "selected_obj_l1": "1"},
    {"claim_measurement_id": "M2", "candidate_rank": "1", "tbl_id": "T_GOLD2",
     "selected_itm_id": "I2", "selected_obj_l1": "2"},
]

GOLD = {
    "M1": {"claim_measurement_id": "M1", "gold_tbl_id": "T_GOLD",
           "gold_itm_id": "I1", "gold_obj_l1": "1"},
    "M2": {"claim_measurement_id": "M2", "gold_tbl_id": "T_GOLD2",
           "gold_itm_id": "I2", "gold_obj_l1": "2"},
}


def test_ranked_by_measurement_sorts_by_rank():
    ranked = ranked_by_measurement(CANDIDATES, KEYS)
    assert [row["tbl_id"] for row in ranked["M1"]] == ["T_WRONG", "T_GOLD"]


def test_recall_at_k_counts_rank_position():
    ranked = ranked_by_measurement(CANDIDATES, KEYS)
    gold_tbl = {k: v["gold_tbl_id"] for k, v in GOLD.items()}
    result = recall_at_k(ranked, gold_tbl, "tbl_id")
    assert result["recall@1"] == 0.5   # M2만 1위 정답
    assert result["recall@3"] == 1.0
    assert result["labeled"] == 2


def test_recall_reports_gold_required_when_no_gold():
    ranked = ranked_by_measurement(CANDIDATES, KEYS)
    result = recall_at_k(ranked, {"M1": "", "M2": ""}, "tbl_id")
    assert result["recall@1"] == GOLD_REQUIRED
    assert result["labeled"] == 0


def test_best_status_prefers_ready_then_provisional():
    validated = [
        {"claim_measurement_id": "M1", "mapping_status": "MAPPING_FAILED"},
        {"claim_measurement_id": "M1", "mapping_status": "PROVISIONAL"},
        {"claim_measurement_id": "M2", "mapping_status": "NEEDS_CONFIRMATION"},
        {"claim_measurement_id": "M2", "mapping_status": "READY"},
    ]
    best = best_status_by_measurement(validated, KEYS)
    assert best["M1"] == "PROVISIONAL"
    assert best["M2"] == "READY"


def test_api_valid_requires_response_code_valid():
    validated = [
        {"claim_measurement_id": "M1", "response_code_valid": "False"},
        {"claim_measurement_id": "M2", "response_code_valid": "True"},
    ]
    assert api_valid_measurements(validated, KEYS) == {"M2"}


def test_evaluate_reports_missing_gold_and_status_counts():
    validated = [
        {"claim_measurement_id": "M1", "mapping_status": "PROVISIONAL",
         "response_code_valid": "True", "attempted_combination_count": "3"},
        {"claim_measurement_id": "M2", "candidate_rank": "1",
         "mapping_status": "READY", "tbl_id": "T_GOLD2",
         "selected_itm_id": "I2", "selected_obj_l1": "2",
         "response_code_valid": "True", "attempted_combination_count": "2"},
    ]
    verified = [{"claim_measurement_id": "M2", "verdict": "일치", "verdict_code": "MATCH"}]
    result = evaluate("C", KEYS, CANDIDATES, validated, verified, GOLD, [])
    assert result["measurements"] == 2
    assert result["mapping_status"]["READY"] == 1
    assert result["mapping_status"]["PROVISIONAL"] == 1
    assert result["api_valid_measurements"] == 2
    assert result["kosis_api_calls"] == 5
    assert result["verdict_reached"] == 1
    assert result["missing_gold"] == []
    assert result["ready_precision"] == 1.0
    assert result["ready_coordinate_evaluation"]["correct"] == 1


def test_ready_coordinate_precision_excludes_provisional_and_requires_exact_codes():
    validated = [
        {"claim_measurement_id": "M1", "candidate_rank": "1",
         "mapping_status": "PROVISIONAL", "tbl_id": "T_GOLD",
         "selected_itm_id": "I1", "selected_obj_l1": "1"},
        {"claim_measurement_id": "M2", "candidate_rank": "1",
         "mapping_status": "READY", "tbl_id": "T_GOLD2",
         "selected_itm_id": "WRONG", "selected_obj_l1": "2"},
    ]
    assert ready_coordinate_precision(validated, KEYS, GOLD) == {
        "precision": 0.0,
        "recall": 0.0,
        "correct": 0,
        "predicted": 1,
        "labeled": 2,
    }


def test_evaluate_flags_required_inputs_when_absent():
    result = evaluate("A", KEYS, CANDIDATES, [], [], {}, [])
    assert result["mapping_status"] == "validated_csv_required"
    assert result["verdict_reached"] == "verified_csv_required"
    assert result["avg_search_seconds"] == "stats_csv_required"
    assert "gold_tbl_id (정답 통계표)" in result["missing_gold"]
    assert result["ready_precision"] == "gold_required"
