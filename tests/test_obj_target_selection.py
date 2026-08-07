"""문장 대상어가 OBJ 집계 우선보다 앞서는지 지키는 회귀 테스트 (2026-08-05)."""
import csv
from pathlib import Path

from kosis_chroma_hybrid_search import InMemoryCoordinateSearcher, search_measurement
from kosis_meta_coordinates import (
    claim_specifies_target,
    claim_target_terms,
    seed_region_terms,
    target_terms_match_text,
)
from kosis_validate_mapping_candidates import semantic_ready_gate


def test_country_in_sentence_is_target_even_when_extracted_item_is_empty():
    claim = {"claim_text": "중국 수출은 3.4% 증가했다", "industry_or_item": ""}
    assert claim_specifies_target(claim) is True
    assert "중국" in claim_target_terms(claim)


def test_country_alias_matches_canonical_axis_value():
    terms = claim_target_terms({"claim_text": "대미 수출은 1.4% 증가했다"})
    assert terms == ("미국",)
    assert target_terms_match_text(terms, ["미국"]) is True


def test_ambiguous_country_shorthand_does_not_fire_without_trade_context():
    assert claim_target_terms({"claim_text": "대중교통 이용률은 3% 늘었다"}) == ()
    assert claim_target_terms({"claim_text": "이란 문장은 통계 주장이 아니다"}) == ()


def test_axis_value_recovers_sentence_only_item():
    claim = {"claim_text": "반도체 수출액은 10% 늘었다", "industry_or_item": ""}
    assert "반도체" in claim_target_terms(claim, ["계", "반도체", "자동차"])


def test_only_target_typed_axes_can_supply_sentence_terms():
    claim = {"claim_text": "고용은 줄고 실업률은 높아졌으며 GDP와 수출은 둔화했다"}
    values = [
        {"name": "고용", "axis_name": "특성별"},
        {"name": "실업률", "axis_name": "경제활동별"},
        {"name": "GDP", "axis_name": "세목별"},
        {"name": "수출", "axis_name": "현황별"},
    ]
    assert claim_target_terms(claim, values) == ()


def test_time_and_superlative_axis_values_are_not_targets():
    claim = {"claim_text": "1월 수출은 9월 이후 가장 큰 폭으로 늘었다"}
    values = [
        {"name": "1월", "axis_name": "통계분류"},
        {"name": "9월", "axis_name": "통계분류"},
        {"name": "가장", "axis_name": "품목별"},
    ]
    assert claim_target_terms(claim, values) == ()


def test_item_axis_can_still_recover_a_missing_structured_item():
    claim = {"claim_text": "반도체 수출액은 10% 늘었다", "industry_or_item": ""}
    values = [
        {"name": "계", "axis_name": "품목별"},
        {"name": "반도체", "axis_name": "품목별"},
    ]
    assert claim_target_terms(claim, values) == ("반도체",)


def test_aggregate_region_is_not_a_target():
    claim = {"claim_text": "서울의 주유소는 줄었다", "region": "전국"}
    assert claim_target_terms(claim) == ("서울",)


def test_multiple_structured_targets_are_split_instead_of_concatenated():
    countries = claim_target_terms({
        "claim_text": "폴란드와 말레이시아에 수출했다",
        "destination_country": "폴란드, 말레이시아",
    })
    assert countries == ("말레이시아", "폴란드")

    industries = claim_target_terms({
        "claim_text": "제조업과 도소매업 취업자가 감소했다",
        "industry_or_item": "제조업, 도소매업",
    })
    assert industries == ("도소매업", "제조업")


def test_region_seed_file_has_all_six_code_systems_and_108_rows():
    path = Path(__file__).resolve().parents[1] / "data" / "seed_region_codes.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 108
    assert len({row["scheme"] for row in rows}) == 6
    assert {"서울", "부산", "제주"} <= seed_region_terms(str(path))


META = [
    {"org_id": "101", "tbl_id": "TRADE", "tbl_name": "국가별 수출액, 수입액",
     "axis_id": "ITEM", "code_id": "EXP", "code_name": "수출액",
     "is_item": "Y", "unit_name": "천달러"},
    {"org_id": "101", "tbl_id": "TRADE", "axis_id": "A", "axis_name": "국가별",
     "axis_order": "1", "code_id": "TOT", "code_name": "계", "is_item": "N"},
    {"org_id": "101", "tbl_id": "TRADE", "axis_id": "A", "axis_name": "국가별",
     "axis_order": "1", "code_id": "CN", "code_name": "중국", "is_item": "N"},
    {"org_id": "101", "tbl_id": "TRADE", "axis_id": "A", "axis_name": "국가별",
     "axis_order": "1", "code_id": "US", "code_name": "미국", "is_item": "N"},
]
TABLES = [{"rank": 1, "org_id": "101", "tbl_id": "TRADE",
           "tbl_name": "국가별 수출액, 수입액", "candidate_status": "READY"}]


class AggregateFavoringReranker:
    def score(self, query, documents):
        return [10.0 if "국가별: 계" in document else 1.0 for document in documents]


def test_sentence_country_outranks_aggregate_even_when_reranker_prefers_total():
    claim = {
        "claim_measurement_id": "H3-CN",
        "claim_text": "중국 수출은 3.4% 증가했다",
        "measurement_indicator": "수출액",
        "industry_or_item": "",
        "unit_dimension": "rate",
    }
    candidates, stats = search_measurement(
        claim, TABLES, InMemoryCoordinateSearcher(META),
        dense_top_k=10, lexical_top_k=10, rerank_top_k=10, final_top_k=3,
        reranker=AggregateFavoringReranker(),
    )
    assert candidates[0]["metadata"]["obj_l1_name"] == "중국"
    assert candidates[0]["obj_target_match"] is True
    assert stats["prefer_aggregate"] is False
    assert stats["claim_target_terms"] == "중국"


def test_exact_target_enters_rerank_even_when_dense_and_lexical_return_nothing():
    claim = {
        "claim_measurement_id": "H3-US",
        "claim_text": "미국 수출은 1.4% 증가했다",
        "measurement_indicator": "수출액",
        "industry_or_item": "",
        "unit_dimension": "rate",
    }
    candidates, _ = search_measurement(
        claim, TABLES, InMemoryCoordinateSearcher(META),
        dense_top_k=0, lexical_top_k=0, rerank_top_k=1, final_top_k=1,
    )
    assert candidates[0]["metadata"]["obj_l1_name"] == "미국"


def test_target_missing_from_selected_axis_is_held_for_confirmation():
    row = {
        "claim_text": "중국 수출은 3.4% 증가했다",
        "indicator": "수출액",
        "tbl_name": "국가별 수출액, 수입액",
    }
    result = {
        "mapping_status": "READY",
        "tbl_name": "국가별 수출액, 수입액",
        "selected_itm_name": "수출액",
        "selected_obj_l1_name": "계",
    }
    gate = semantic_ready_gate(row, result)
    assert gate["semantic_gate_valid"] is False
    assert "CLAIM_ITEM_MISMATCH" in gate["semantic_gate_details"]


def test_matching_country_axis_can_still_confirm():
    row = {
        "claim_text": "중국 수출은 3.4% 증가했다",
        "indicator": "수출액",
        "tbl_name": "국가별 수출액, 수입액",
    }
    result = {
        "mapping_status": "READY",
        "tbl_name": "국가별 수출액, 수입액",
        "selected_itm_name": "수출액",
        "selected_obj_l1_name": "중국",
    }
    gate = semantic_ready_gate(row, result)
    assert gate["semantic_gate_valid"] is True


def test_region_in_sentence_cannot_confirm_as_national_total():
    row = {
        "claim_text": "부산 아파트 가격은 2.1% 올랐다",
        "indicator": "아파트 가격",
        "tbl_name": "지역별 아파트 가격지수",
    }
    result = {
        "mapping_status": "READY",
        "tbl_name": "지역별 아파트 가격지수",
        "selected_itm_name": "아파트 가격지수",
        "selected_obj_l1_name": "전국",
    }
    gate = semantic_ready_gate(row, result)
    assert "CLAIM_ITEM_MISMATCH" in gate["semantic_gate_details"]
