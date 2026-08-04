from lock_gold_measurement import build_metrics, lock_rows


def row(measurement_id, usage="KOSIS_VALUE", verifiable="Y", correct="Y"):
    return {
        "claim_measurement_id": measurement_id,
        "measurement_usage": usage,
        "measurement_role": "current",
        "measurement_indicator": "indicator",
        "value": "10",
        "unit": "%",
        "gold_verifiable": verifiable,
        "gold_measurement_correct": correct,
        "in_ready": "N",
    }


def test_lock_changes_only_non_kosis_usage_and_merges_ready():
    rows = [
        row("m1", usage="KOSIS_VALUE", verifiable="Y"),
        row("m2", usage="CONTEXT", verifiable="Y"),
        row("m3", usage="POLICY_VALUE", verifiable="N"),
    ]

    locked, audit = lock_rows(rows, {"m1", "m2"})

    assert [item["gold_verifiable"] for item in locked] == ["Y", "N", "N"]
    assert [item["in_ready"] for item in locked] == ["Y", "Y", "N"]
    assert locked[0]["gold_label_rule"] == "HUMAN_LABEL_PRESERVED"
    assert locked[1]["gold_label_rule"] == "NON_KOSIS_USAGE_TO_N"
    assert [item["claim_measurement_id"] for item in audit] == ["m2"]


def test_metrics_use_locked_labels():
    rows, audit = lock_rows(
        [
            row("m1", verifiable="Y", correct="Y"),
            row("m2", verifiable="N", correct="N"),
            row("m3", usage="CONTEXT", verifiable="Y", correct="Y"),
        ],
        {"m1", "m2"},
    )

    metrics = build_metrics(rows, len(audit))

    assert metrics["ready"] == 2
    assert metrics["gate_true_positive"] == 1
    assert metrics["gate_false_positive"] == 1
    assert metrics["gate_false_negative"] == 0
    assert metrics["gate_precision"] == 0.5
    assert metrics["gate_recall"] == 1.0
    assert metrics["ready_extraction_accuracy"] == 0.5


def test_duplicate_measurement_ids_are_rejected():
    rows = [row("m1"), row("m1")]

    try:
        lock_rows(rows, {"m1"})
    except ValueError as exc:
        assert "duplicate claim_measurement_id" in str(exc)
    else:
        raise AssertionError("duplicate measurement IDs must fail")
