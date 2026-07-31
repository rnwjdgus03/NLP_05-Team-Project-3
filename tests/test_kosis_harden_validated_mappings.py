import csv

from kosis_harden_validated_mappings import harden_validated_rows, write_ready_rows


def test_harden_validated_rows_only_demotes_ready_semantic_mismatch():
    rows = [
        {
            "claim_measurement_id": "bad",
            "mapping_status": "READY",
            "mapping_reason": "validated candidate",
            "claim_text": "\ub300\uc911 \uc218\ucd9c\uc740 100\uc5b5\ub2ec\ub7ec\uc600\ub2e4.",
            "indicator": "\uc218\ucd9c\uc561",
            "tbl_name": "\uc218\ucd9c \ubc0f \uc218\uc785\uc561",
            "selected_itm_name": "\uc218\ucd9c\uc561",
            "selected_combination": '{"objL1_name": "\ubc18\ub3c4\uccb4"}',
        },
        {
            "claim_measurement_id": "good",
            "mapping_status": "READY",
            "mapping_reason": "validated candidate",
            "claim_text": "\ubc18\ub3c4\uccb4 \uc218\ucd9c\uc561\uc740 100\uc5b5\ub2ec\ub7ec\uc600\ub2e4.",
            "indicator": "\ubc18\ub3c4\uccb4 \uc218\ucd9c\uc561",
            "tbl_name": "\ud488\ubaa9\ubcc4 \uc218\ucd9c\uc561",
            "selected_itm_name": "\uc218\ucd9c\uc561",
            "selected_combination": '{"objL1_name": "\ubc18\ub3c4\uccb4"}',
        },
        {
            "claim_measurement_id": "existing-review",
            "mapping_status": "NEEDS_CONFIRMATION",
            "mapping_reason": "UNIT_MISMATCH",
        },
    ]

    hardened = harden_validated_rows(rows)

    assert hardened[0]["mapping_status"] == "NEEDS_CONFIRMATION"
    assert hardened[0]["mapping_reason"] == "CHINA_SCOPE_MISMATCH"
    assert hardened[1]["mapping_status"] == "READY"
    assert hardened[1]["semantic_gate_valid"] is True
    assert hardened[2]["mapping_status"] == "NEEDS_CONFIRMATION"
    assert hardened[2]["mapping_reason"] == "UNIT_MISMATCH"


def test_write_ready_rows_preserves_headers_when_no_rows_remain(tmp_path):
    output = tmp_path / "ready.csv"
    write_ready_rows(
        output,
        [],
        [{"claim_id": "c1", "mapping_status": "NEEDS_CONFIRMATION"}],
    )

    with output.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["claim_id", "mapping_status"]
        assert list(reader) == []
