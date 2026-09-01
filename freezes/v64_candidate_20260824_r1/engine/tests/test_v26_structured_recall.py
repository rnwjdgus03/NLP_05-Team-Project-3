from __future__ import annotations

from kosis_component_search import mandatory_target_default_combinations
from kosis_meta_coordinates import (
    claim_target_terms,
    claim_target_terms,
    target_scope_exact_match,
    target_terms_match_text,
)
from prepare_kosis_mapping_input import (
    canonicalize_period,
    explicit_obj_targets,
    grounded_demographic_value,
    repair_extracted_contract,
)
from run_kosis_coordinate_stage_a import item_table_recall_terms
from kosis_taxonomy import industry_label_equivalent


def test_excel_serial_date_repairs_relative_month_and_change_contract():
    repaired, statuses = repair_extracted_contract({
        "date": "45838.0",
        "title": "5월 산업활동동향",
        "claim_text": "건설기성도 전달보다 3.9% 줄었다.",
        "period": "202305",
        "prd_se": "M",
        "indicator": "건설기성 증감률",
        "unit": "%",
        "value_type": "수준값",
        "measurement_role": "현재값",
    })
    assert repaired["period"] == "202505"
    assert repaired["change_base"] == "전월"
    assert repaired["value_type"] == "증감률"
    assert "TITLE_MONTH_YEAR_FROM_ARTICLE_DATE" in statuses
    assert "CHANGE_RATE_FROM_TEXT" in statuses


def test_explicit_title_year_month_is_not_replaced_by_article_year():
    repaired, statuses = repair_extracted_contract({
        "date": "2025-09-25",
        "title": "2024년 12월 서울 사망자 수 공식통계",
        "claim_text": "2024년 12월 서울 사망자 수는 4,684명으로 집계됐다.",
        "measurement_period": "202412",
        "period": "202412",
        "measurement_prd_se": "M",
        "prd_se": "M",
        "measurement_indicator": "서울 사망자 수",
        "unit": "명",
    })
    assert repaired["measurement_period"] == "202412"
    assert repaired["period"] == "202412"
    assert "TITLE_MONTH_YEAR_FROM_ARTICLE_DATE" not in statuses


def test_relative_quarter_sequence_preserves_quarter_period():
    repaired, statuses = repair_extracted_contract({
        "date": "45761.0",
        "title": "고용동향",
        "claim_text": (
            "취업자의 전년 동기 대비 감소 폭은 작년 2분기, 3분기, "
            "4분기 8만9000명으로 확대됐다가 올해 1분기에 줄었다."
        ),
        "period": "2023",
        "prd_se": "Q",
        "indicator": "취업자 감소 폭",
        "unit": "명",
        "value_type": "수준값",
        "measurement_role": "현재값",
    })
    assert repaired["period"] == "202404"
    assert canonicalize_period(repaired["period"], "Q") == "202404"
    assert repaired["change_base"] == "전년동기"
    assert repaired["value_type"] == "증감량"
    assert "RELATIVE_QUARTER_FROM_ARTICLE_DATE" in statuses


def test_monthly_average_metric_is_not_forced_to_monthly_period():
    repaired, statuses = repair_extracted_contract({
        "date": "45722.0",
        "title": "근로실태",
        "claim_text": "지난해 근로자 월평균 명목임금은 407만9000원이다.",
        "period": "2023",
        "prd_se": "M",
        "indicator": "월평균 명목임금",
        "unit": "원",
    })
    assert repaired["period"] == "2024"
    assert repaired["prd_se"] == "Y"
    assert "ANNUAL_METRIC_NOT_MONTHLY_PERIOD" in statuses


def test_structured_recall_terms_include_obj_targets_and_official_aliases():
    terms = item_table_recall_terms({
        "measurement_indicator": "월평균 명목임금",
        "obj_target_terms": "1인가구",
    })
    assert "1인가구" in terms
    assert "임금총액" in terms


def test_qualified_total_indicator_is_not_a_detail_obj_target():
    assert claim_target_terms({
        "measurement_indicator": "사망자 수",
        "obj_target_terms": "전체 사망자",
        "region": "전국",
    }) == ()
    assert claim_target_terms({
        "measurement_indicator": "여성 사망자 수",
        "obj_target_terms": "전체 사망자",
        "gender": "여성",
    }) == ("여성",)


def test_official_industry_connective_is_recall_equivalent():
    assert target_terms_match_text(
        ["숙박·음식점업"], ["I 숙박 및 음식점업(55~56)"],
    )
    assert industry_label_equivalent(
        "숙박·음식점업", "I 숙박 및 음식점업(55~56)",
    )


def test_literal_age_and_spouse_targets_are_preserved():
    assert explicit_obj_targets({
        "claim_text": "60세 이상 비임금 근로자는 269만명이다."
    }) == ("60세이상",)
    assert explicit_obj_targets({
        "claim_text": "아내가 연상인 초혼은 3만건이다."
    }) == ("여자연상",)


def test_explanatory_tail_demographic_is_not_bound_to_measurement():
    row = {
        "claim_text": "실업률이 낮아진 현상의 상당 부분이 청년층의 구직 포기 때문이다.",
        "measurement_indicator": "실업률",
        "age_group": "청년",
    }
    assert grounded_demographic_value(row, "age_group") == "-"


def test_unspoken_broad_age_label_is_replaced_by_literal_range():
    row = {
        "claim_text": "60세 이상 비임금 근로자는 269만명이다.",
        "measurement_indicator": "비임금 근로자 수",
        "age_group": "고령층",
    }
    assert grounded_demographic_value(row, "age_group") == "-"


def test_target_default_coordinate_uses_exact_target_and_other_totals():
    items = [{
        "org_id": "1", "tbl_id": "T", "itm_id": "I", "itm_name": "사망자수",
        "rank_score": 0.8, "component_score": 0.8,
    }]
    axes = {
        1: [
            {"axis_order": 1, "axis_name": "사망원인", "axis_id": "A1",
             "obj_code": "0", "obj_name": "계", "component_score": 0.2},
            {"axis_order": 1, "axis_name": "사망원인", "axis_id": "A1",
             "obj_code": "SIDS", "obj_name": "영아급사증후군", "component_score": 0.7},
        ],
        2: [
            {"axis_order": 2, "axis_name": "성별", "axis_id": "A2",
             "obj_code": "0", "obj_name": "계", "component_score": 0.3},
            {"axis_order": 2, "axis_name": "성별", "axis_id": "A2",
             "obj_code": "M", "obj_name": "남자", "component_score": 0.6},
        ],
    }
    rows = mandatory_target_default_combinations(
        items, axes, ["영아급사증후군"], {"obj_target_terms": "영아급사증후군"},
    )
    assert len(rows) == 1
    assert rows[0]["objects"][1]["obj_code"] == "SIDS"
    assert rows[0]["objects"][2]["obj_code"] == "0"
    assert rows[0]["mandatory_target_default"] is True


def test_measurement_item_is_item_signal_not_obj_target():
    claim = {
        "claim_text": "주민등록인구는 5천만명이다.",
        "measurement_item": "주민등록인구",
        "industry_or_item": "-",
    }
    assert claim_target_terms(claim) == ()


def test_gender_aliases_satisfy_exact_obj_scope():
    assert target_scope_exact_match(["남성"], ["남자", "계"])
    assert target_scope_exact_match(["여성"], ["여", "전국"])
    assert target_terms_match_text(["남성"], ["남자"])
    assert target_terms_match_text(["여성"], ["여"])


def test_qualified_official_totals_do_not_become_detail_targets():
    assert claim_target_terms({"obj_target_terms": "전체 인구"}) == ()
    assert claim_target_terms({"obj_target_terms": "전체 상품군"}) == ()
    assert claim_target_terms({"obj_target_terms": "평균 농가"}) == ()
