from __future__ import annotations

import csv
import json
import sys

from evaluate_coordinate_topk import main as evaluate_main
from kosis_meta_coordinates import claim_target_terms
from kosis_period_range import period_in_ranges, period_ordinals
from run_kosis_coordinate_stage_a import (
    item_table_recall_terms,
    merge_item_table_recall,
    reserve_item_recall_slots,
)
from merge_stage_a_channels import merge_packet
from run_kosis_coordinate_stage_c import locked_incumbent_top_k


def test_monthly_dotted_range_is_compared_as_months() -> None:
    rows = [{"prd_se": "M", "range_text": "1965.02~2026.07"}]
    assert period_in_ranges("202601", rows, "M") is True
    assert period_in_ranges("196501", rows, "M") is False
    assert period_in_ranges("202608", rows, "M") is False


def test_quarter_and_year_ranges_use_separate_ordinals() -> None:
    quarter_rows = [{"prd_se": "Q", "range_text": "2020Q1 ~ 2026년 4분기"}]
    year_rows = [{"prd_se": "Y", "range_text": "1999~2025"}]
    assert period_in_ranges("202603", quarter_rows, "Q") is True
    assert period_in_ranges("202701", quarter_rows, "Q") is False
    assert period_in_ranges("2024", year_rows, "Y") is True
    assert period_ordinals("202601", "M") != period_ordinals("2026", "Y")


def test_unparseable_or_wrong_periodicity_abstains() -> None:
    assert period_in_ranges("202601", [{"prd_se": "Y", "range_text": "2000~2026"}], "M") is None
    assert period_in_ranges("알 수 없음", [{"prd_se": "M", "range_text": "2000.01~2026.07"}], "M") is None


def test_consumer_price_does_not_infer_eggplant_obj() -> None:
    claim = {"claim_text": "소비자물가지수는 전월보다 0.4% 상승했다."}
    axes = [{"value": "가지", "axis_name": "품목별"}]
    assert claim_target_terms(claim, axes) == ()
    assert claim_target_terms({**claim, "industry_or_item": "가지"}, axes) == ("가지",)


def test_item_recall_terms_keep_employment_indicator_variants() -> None:
    terms = item_table_recall_terms({
        "measurement_indicator": "취업자수 전년동월비",
        "indicator": "실업률",
        "keywords": "경제활동인구, 취업자",
    })
    assert "취업자수" in terms
    assert "취업자" in terms
    assert "실업률" in terms
    assert terms.index("실업률") < terms.index("경제활동인구")


def test_workforce_indicator_adds_official_headcount_alias() -> None:
    terms = item_table_recall_terms({
        "measurement_indicator": "조선 산업기술인력 중 외국인 수",
    })
    assert "현재인원" in terms
    assert terms.index("현재인원") < terms.index("산업기술인력")


def test_workforce_change_keeps_level_alias_before_change_rate() -> None:
    terms = item_table_recall_terms({
        "measurement_indicator": "조선 산업기술인력 중 외국인 증가율",
    })
    assert terms.index("현재인원") < terms.index("증가율")


def test_export_change_indicator_adds_official_level_item_alias() -> None:
    terms = item_table_recall_terms({
        "measurement_indicator": "반도체 수출 증감률",
    })
    assert "수출액" in terms
    assert terms.index("수출액") < terms.index("반도체")


def test_item_recall_reserves_a_reranker_slot() -> None:
    lookup = {
        ("1", "A"): {"org_id": "1", "tbl_id": "A"},
        ("2", "B"): {"org_id": "2", "tbl_id": "B"},
    }
    fused = [{
        "org_id": "1", "tbl_id": "A", "table": lookup[("1", "A")],
        "lexical_rank": 1, "lexical_score": 1.0,
        "dense_rank": 1, "dense_score": 1.0, "rrf_score": 0.04,
    }]
    hits = [{
        "org_id": "2", "tbl_id": "B", "rank": 1, "score": 3,
        "matched_item_names": ["실업률"],
    }]
    merged = merge_item_table_recall(fused, hits, lookup)
    selected = reserve_item_recall_slots(fused, merged, hits, top_k=2, slots=1)
    assert [(row["org_id"], row["tbl_id"]) for row in selected][0] == ("2", "B")


def test_stage_a_channel_merge_never_replaces_incumbent_top10() -> None:
    baseline = {
        "claim_measurement_id": "C1", "claim_fingerprint": "same",
        "table_candidates": [
            {"org_id": "1", "tbl_id": str(index), "rank": index}
            for index in range(1, 11)
        ],
    }
    expanded = {
        "claim_measurement_id": "C1", "claim_fingerprint": "same",
        "table_candidates": [
            {"org_id": "2", "tbl_id": "A", "rank": 1},
            {"org_id": "2", "tbl_id": "B", "rank": 2},
        ],
    }
    merged = merge_packet(baseline, expanded, fallback_slots=2)
    candidates = merged["table_candidates"]
    assert [row["tbl_id"] for row in candidates[:10]] == [str(index) for index in range(1, 11)]
    assert [row["stage_a_channel"] for row in candidates[10:]] == [
        "ITEM_RECALL_FALLBACK", "ITEM_RECALL_FALLBACK",
    ]


def test_stage_c_locks_incumbent_top3_and_uses_expanded_tail() -> None:
    rows = [
        {
            "coordinate_id": f"base-{rank}", "org_id": "1",
            "tbl_id": f"base-{rank}", "stage_a_channel": "INCUMBENT_BASELINE",
        }
        for rank in range(1, 6)
    ]
    # Its global score position is first, but the fallback channel may not
    # displace the incumbent Top-3.
    rows.insert(0, {
        "coordinate_id": "item-new", "org_id": "2", "tbl_id": "item-new",
        "stage_a_channel": "ITEM_RECALL_FALLBACK",
    })
    selected = locked_incumbent_top_k(rows, 5)
    assert [row["coordinate_id"] for row in selected[:3]] == [
        "base-1", "base-2", "base-3",
    ]
    assert len(selected) == 5


def test_evaluator_counts_missing_prediction_as_failure(tmp_path, monkeypatch) -> None:
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "claim_measurement_id": "C1",
        "unique_api_candidates": [{"coordinate": {
            "org_id": "1", "tbl_id": "T", "item_id": "I",
            "axis_values": [], "prd_se": "Y", "target_period": "2025",
        }}],
    }) + "\n", encoding="utf-8")
    gold = tmp_path / "gold.csv"
    with gold.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "claim_measurement_id", "gold_ready", "gold_org_id",
            "gold_tbl_id", "gold_itm_id", "gold_prd_se", "gold_period",
        ])
        writer.writeheader()
        for claim_id in ("C1", "C2"):
            writer.writerow({
                "claim_measurement_id": claim_id, "gold_ready": "Y",
                "gold_org_id": "1", "gold_tbl_id": "T", "gold_itm_id": "I",
                "gold_prd_se": "Y", "gold_period": "2025",
            })
    summary = tmp_path / "summary.json"
    details = tmp_path / "details.csv"
    monkeypatch.setattr(sys, "argv", [
        "evaluate_coordinate_topk.py", "--predictions", str(predictions),
        "--gold", str(gold), "--summary", str(summary),
        "--details", str(details), "--ks", "1",
    ])
    evaluate_main()
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert result["eligible_gold_rows"] == 2
    assert result["prediction_overlap"] == 1
    assert result["missing_prediction_packets"] == 1
    assert result["metrics"]["full"]["accuracy_at_1"] == 0.5
