from run_kosis_topk_experiment import summarize


def test_summarize_topk_combines_retrieval_mapping_and_verdict_metrics():
    gold = [{
        "claim_measurement_id": "m1",
        "gold_tbl_id": "T1",
        "gold_itm_id": "I1",
        "gold_obj_l1": "O1",
        "gold_verdict": "일치",
    }]
    candidates = [{
        "claim_measurement_id": "m1",
        "candidate_rank": "1",
        "tbl_id": "T1",
    }]
    validated = [{
        **candidates[0],
        "mapping_status": "READY",
        "selected_itm_id": "I1",
        "selected_obj_l1": "O1",
    }]
    verified = [{"claim_measurement_id": "m1", "verdict": "일치"}]

    result = summarize(1, gold, candidates, validated, verified)

    assert result["retrieval_hits"] == 1
    assert result["ready_rows"] == 1
    assert result["item_obj_correct"] == 1
    assert result["verdict_correct"] == 1
