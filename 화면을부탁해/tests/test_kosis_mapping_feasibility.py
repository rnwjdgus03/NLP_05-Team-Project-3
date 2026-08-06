import unittest

from kosis_mapping_feasibility import classify_mapping_feasibility
from kosis_mapping_status import READY, REVIEW, decide_final_status


BASE_READY = {
    "mapping_status": "READY",
    "metadata_combination_valid": "Y",
    "item_meta_valid": "Y",
    "obj_meta_valid": "Y",
    "api_request_success": "Y",
    "api_coordinate_exact_match": "Y",
    "unit_compatible": "Y",
    "period_compatible": "Y",
    "api_value_exists": "Y",
    "semantic_ready_gate_passed": "Y",
}


class KosisMappingFeasibilityTests(unittest.TestCase):
    def test_trade_balance_single_import_item_is_not_ready(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "무역수지",
            "selected_itm_name": "수입액",
            "selected_tbl_id": "DT_1R11001_FRM101",
            "mapping_type": "direct",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "DERIVED_FROM_ITEMS")
        self.assertEqual(row["table_can_represent_claim"], "N")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_trade_balance_change_requires_four_coordinates(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "무역수지 증감액",
            "selected_itm_name": "수입액",
            "selected_tbl_id": "DT_1R11001_FRM101",
            "mapping_type": "difference_from_level",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "DERIVED_FROM_ITEMS_AND_PERIODS")
        self.assertEqual(row["required_item_count"], "2")
        self.assertEqual(row["required_period_count"], "2")
        self.assertEqual(row["table_can_represent_claim"], "N")

    def test_rate_claim_requires_base_period(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "수출 증가율",
            "unit": "%",
            "selected_itm_name": "수출액",
            "mapping_type": "rate_from_level",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "DERIVED_FROM_PERIODS")
        self.assertEqual(row["table_can_represent_claim"], "N")

    def test_partial_period_is_not_replaced_by_annual_period(self):
        row = {
            **BASE_READY,
            "claim_text": "2024년 1~9월 수출 증가율은 높았다",
            "measurement_indicator": "수출 증가율",
            "period": "2024",
            "unit": "%",
            "selected_itm_name": "수출액",
            "mapping_type": "rate_from_level",
            "comparison_period": "2023",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "PERIOD_SCOPE_MISMATCH")
        self.assertEqual(row["period_scope_valid"], "N")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_rank_claim_is_unsupported_by_commodity_table(self):
        row = {
            **BASE_READY,
            "claim_text": "세계 수출순위는 6위였다",
            "measurement_indicator": "세계 수출순위",
            "selected_itm_name": "수출액",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "UNSUPPORTED_BY_TABLE")
        self.assertEqual(row["table_can_represent_claim"], "N")

    def test_cosmetics_broad_claim_requires_codeset(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "화장품 수출액",
            "claim_text": "화장품 수출액이 증가했다",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "13102112831A.553",
            "selected_obj_l1_name": "탈모제 향수 화장품이나 달리 명시되지 않은 화장용품",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "CODESET_AGGREGATION")
        self.assertEqual(row["requires_codeset"], "Y")
        self.assertEqual(row["table_can_represent_claim"], "N")

    def test_car_broad_claim_single_passenger_car_code_is_review(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "자동차 수출",
            "claim_text": "자동차 전체 수출",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "13102112831A.781",
            "selected_obj_l1_name": "승용자동차 및 기타의 차량",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["classification_alignment"], "BROADER_THAN_KOSIS_CODE")
        self.assertEqual(row["table_can_represent_claim"], "N")

    def test_direct_export_amount_can_remain_ready(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "수출액",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "13102112831A.A",
            "selected_obj_l1_name": "총액",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "DIRECT_COORDINATE")
        self.assertEqual(row["table_can_represent_claim"], "Y")
        self.assertEqual(decide_final_status(row)["final_status"], READY)

    def test_unreviewed_capability_alone_does_not_make_ready(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "수출액",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "합계",
            "capability_source": "AUTO_INFERRED",
            "capability_review_status": "UNREVIEWED",
            "direct_coordinate_official_meta_evidence": "N",
        }
        row.update(classify_mapping_feasibility(row))
        row["direct_coordinate_official_meta_evidence"] = "N"
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_official_reviewed_direct_coordinate_can_be_ready(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "수출액",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "13102112831A.A",
            "selected_obj_l1_name": "총액",
            "capability_source": "KOSIS_PAGE",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(decide_final_status(row)["final_status"], READY)

    def test_auto_inferred_codeset_is_review(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "화장품 수출액",
            "claim_text": "화장품 수출액",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "553",
            "selected_obj_l1_name": "향수 화장품",
            "capability_source": "AUTO_INFERRED",
            "capability_review_status": "UNREVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["mapping_feasibility"], "CODESET_AGGREGATION")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_derived_metric_without_required_coordinates_is_review(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "무역수지 증감액",
            "selected_itm_name": "수입액",
            "selected_obj_l1": "A",
            "selected_obj_l1_name": "총액",
            "mapping_type": "difference_from_level",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["required_item_count"], "2")
        self.assertEqual(row["required_period_count"], "2")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_cpi_claim_cannot_use_tourism_satisfaction_table(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "소비자 물가 상승률",
            "claim_text": "소비자 물가 상승률은 1.8%로 전망됐다.",
            "tbl_name": "관광 숙박여행 만족도_관광지 물가",
            "selected_itm_name": "만족도",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "관광지 물가",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["semantic_mismatch_code"], "CPI_TOURISM_TABLE_MISMATCH")
        self.assertEqual(row["table_can_represent_claim"], "N")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_exchange_rate_claim_cannot_use_loan_or_deposit_table(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "원화 환율",
            "claim_text": "달러 대비 원화 환율이 올랐다.",
            "tbl_name": "한국은행 원화대출금",
            "selected_itm_name": "대출금",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "총액",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["semantic_mismatch_code"], "EXCHANGE_RATE_LOAN_TABLE_MISMATCH")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_revenue_growth_claim_is_not_direct_export_stat(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "메모리반도체 매출 성장세",
            "claim_text": "WSTS는 메모리반도체 매출 성장세를 전망했다.",
            "tbl_name": "품목별 수출액, 수입액",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "반도체",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["semantic_mismatch_code"], "REVENUE_EXPORT_SOURCE_MISMATCH")
        self.assertEqual(row["table_can_represent_claim"], "N")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_employment_increase_amount_is_not_current_level_coordinate(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "취업자 수 증가폭",
            "claim_text": "취업자 수 증가폭은 12만명으로 전망됐다.",
            "tbl_name": "경제활동인구조사 취업자",
            "selected_itm_name": "취업자",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "계",
            "mapping_type": "direct",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["required_period_count"], "2")
        self.assertEqual(row["formula_valid"], "N")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_monthly_claim_is_not_ready_with_annual_scope(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "수출 증가율",
            "claim_text": "2025년 1월 수출 증가율",
            "measurement_period": "202501",
            "period": "2025",
            "unit": "%",
            "tbl_name": "연도별 수출액",
            "selected_itm_name": "수출액",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "총액",
            "mapping_type": "rate_from_level",
            "comparison_period": "202401",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(row["period_scope_valid"], "N")
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_official_reviewed_table_still_reviews_meaning_mismatch(self):
        row = {
            **BASE_READY,
            "measurement_indicator": "원화 환율",
            "claim_text": "환율",
            "tbl_name": "한국은행 원화대출금",
            "selected_itm_name": "대출금",
            "selected_obj_l1": "A01",
            "selected_obj_l1_name": "총액",
            "capability_source": "KOSIS_PAGE",
            "capability_review_status": "OFFICIAL_REVIEWED",
        }
        row.update(classify_mapping_feasibility(row))
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)


if __name__ == "__main__":
    unittest.main()
