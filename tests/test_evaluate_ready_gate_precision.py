from evaluate_ready_gate_precision import apply_gate, ready_metrics


def _gold(gold_id, table, item):
    return {
        "gold_id": gold_id, "gold_org_id": "101", "gold_tbl_id": table,
        "gold_itm_id": item, "gold_prd_se": "Y", "gold_period": "2024",
    }


def _pred(gold_id, indicator, table, item, table_name, item_name):
    return {
        "gold_id": gold_id, "org_id": "101", "tbl_id": table,
        "selected_itm_id": item, "prd_se": "Y", "period": "2024",
        "measurement_indicator": indicator, "tbl_name": table_name,
        "selected_itm_name": item_name,
    }


def test_semantic_gate_improves_ready_precision_by_abstaining_on_wrong_concept():
    gold = [_gold("G1", "T1", "I1"), _gold("G2", "T2", "I2")]
    mapped = [
        _pred("G1", "수출액", "T1", "I1", "품목별 수출액", "수출액"),
        _pred("G2", "1인당 국민소득", "WRONG", "W1", "1인당 급여비", "급여비용"),
    ]
    baseline, _ = ready_metrics(gold, apply_gate(mapped, False))
    gated, _ = ready_metrics(gold, apply_gate(mapped, True))
    assert baseline["ready_table_precision"] == 0.5
    assert gated["ready_rows"] == 1
    assert gated["ready_table_precision"] == 1.0
    assert gated["ready_table_correct_coverage"] == 0.5
