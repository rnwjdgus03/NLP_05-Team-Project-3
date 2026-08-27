import csv
from argparse import Namespace

import pytest

from evaluate_e2e import evaluate


FIELDS = [
    "claim_measurement_id", "gold_verifiable", "mapping_status",
    "gold_tbl_id", "tbl_id", "gold_itm_id", "selected_itm_id",
    "gold_obj_l1", "selected_obj_l1", "gold_verdict", "verdict",
]


def write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_full_gold_universe(tmp_path):
    gold = tmp_path / "gold.csv"
    pred = tmp_path / "pred.csv"
    write(gold, [
        {"claim_measurement_id": "a", "gold_verifiable": "Y", "gold_tbl_id": "T1"},
        {"claim_measurement_id": "b", "gold_verifiable": "N"},
        {"claim_measurement_id": "c", "gold_verifiable": "Y", "gold_tbl_id": "T3"},
        {"claim_measurement_id": "d", "gold_verifiable": "N"},
    ])
    write(pred, [
        {"claim_measurement_id": "a", "mapping_status": "READY", "tbl_id": "T1"},
        {"claim_measurement_id": "b", "mapping_status": "READY"},
        {"claim_measurement_id": "c", "mapping_status": "NO_MATCH"},
        {"claim_measurement_id": "d", "mapping_status": "NO_MATCH"},
    ])
    args = Namespace(
        gold=str(gold), predictions=str(pred), id_col="claim_measurement_id",
        gold_verifiable_col="gold_verifiable", pred_ready_col="mapping_status",
        gold_tbl_col="gold_tbl_id", pred_tbl_col="tbl_id",
        gold_item_col="gold_itm_id", pred_item_col="selected_itm_id",
        gold_obj_col="gold_obj_l1", pred_obj_col="selected_obj_l1",
        gold_verdict_col="gold_verdict", pred_verdict_col="verdict",
    )
    result = evaluate(args)
    assert result["ready_gate"]["confusion"] == {"TP": 1, "FP": 1, "FN": 1, "TN": 1}
    assert result["dataset"]["missing_predictions"] == 0
    assert result["conditional_exact_match"]["tbl"]["total"] == 2
    assert result["conditional_exact_match"]["tbl"]["correct"] == 1


def test_duplicate_prediction_ids_fail_fast(tmp_path):
    gold = tmp_path / "gold.csv"
    pred = tmp_path / "pred.csv"
    write(gold, [{"claim_measurement_id": "a", "gold_verifiable": "Y"}])
    write(pred, [
        {"claim_measurement_id": "a", "mapping_status": "READY"},
        {"claim_measurement_id": "a", "mapping_status": "NO_MATCH"},
    ])
    args = Namespace(
        gold=str(gold), predictions=str(pred), id_col="claim_measurement_id",
        gold_verifiable_col="gold_verifiable", pred_ready_col="mapping_status",
        gold_tbl_col="gold_tbl_id", pred_tbl_col="tbl_id",
        gold_item_col="gold_itm_id", pred_item_col="selected_itm_id",
        gold_obj_col="gold_obj_l1", pred_obj_col="selected_obj_l1",
        gold_verdict_col="gold_verdict", pred_verdict_col="verdict",
    )
    with pytest.raises(ValueError, match="duplicate claim_measurement_id"):
        evaluate(args)


def test_missing_prediction_id_fails_conservation(tmp_path):
    gold = tmp_path / "gold.csv"
    pred = tmp_path / "pred.csv"
    write(gold, [
        {"claim_measurement_id": "a", "gold_verifiable": "N"},
        {"claim_measurement_id": "b", "gold_verifiable": "N"},
    ])
    write(pred, [{"claim_measurement_id": "a", "mapping_status": "NO_MATCH"}])
    args = Namespace(
        gold=str(gold), predictions=str(pred), id_col="claim_measurement_id",
        gold_verifiable_col="gold_verifiable", pred_ready_col="mapping_status",
        gold_tbl_col="gold_tbl_id", pred_tbl_col="tbl_id",
        gold_item_col="gold_itm_id", pred_item_col="selected_itm_id",
        gold_obj_col="gold_obj_l1", pred_obj_col="selected_obj_l1",
        gold_verdict_col="gold_verdict", pred_verdict_col="verdict",
    )
    with pytest.raises(ValueError, match="ID conservation failed"):
        evaluate(args)
