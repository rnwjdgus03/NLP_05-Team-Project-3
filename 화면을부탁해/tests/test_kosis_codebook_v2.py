import unittest

import kosis_codebook_v2 as codebook


class KosisCodebookV2Test(unittest.TestCase):
    def assert_mapping(self, row, expected):
        config, exclusion = codebook.map_by_codebook(row)
        self.assertIsNone(exclusion)
        self.assertIsNotNone(config)
        for key, value in expected.items():
            self.assertEqual(config[key], value, key)

    def test_policy_context_does_not_hide_quarterly_retail_metric(self):
        self.assert_mapping(
            {
                "title": "3분기로 보면 소매판매 1.5% 증가",
                "claim_text": "소비쿠폰 지급에도 3분기 소비는 직전 분기보다 1.5% 증가했다.",
                "date": "2025-10-31",
                "tbl_id": "DT_1K41012",
                "metric": "비율·증감률",
            },
            {"tbl_id": "DT_1K41012", "obj_l1": "G0", "itm_id": "T3", "prd_se": "Q", "target_period": "202503", "prev_period": "202502", "target_number": 1.5},
        )

    def test_employment_point_change_selects_change_not_level(self):
        self.assert_mapping(
            {"claim_text": "지난달 65세 이상 고용률은 40.4%로 전년 동월 대비 1.2%포인트 올랐다.", "date": "2025-05-14", "metric": "고용지표"},
            {"tbl_id": "DT_1DA7002S", "obj_l1": "602", "itm_id": "T90", "target_period": "202504", "prev_period": "202404", "target_number": 1.2},
        )

    def test_total_export_monthly_change(self):
        self.assert_mapping(
            {"claim_text": "10월 수출은 전년 동월 대비 3.6% 증가에 그쳤다.", "date": "2025-11-09", "metric": "무역지표"},
            {"tbl_id": "DT_1R11001_FRM101", "itm_id": "13103112831T1", "target_period": "202510", "prev_period": "202410", "target_number": 3.6},
        )

    def test_multiple_historical_values_selects_current_retail_change(self):
        self.assert_mapping(
            {"claim_text": "소매 판매는 전달 대비 0.9% 감소하면서 지난 3월(-1.0%)부터 두 달 연속 감소했다.", "title": "4월 생산·소비·투자 감소", "date": "2025-05-31", "metric": "비율·증감률", "tbl_id": "DT_1K41012"},
            {"tbl_id": "DT_1K41012", "obj_l1": "G0", "itm_id": "T3", "target_period": "202504", "prev_period": "202503", "target_number": -0.9},
        )

    def test_private_survey_without_official_metric_remains_unverifiable(self):
        config, exclusion = codebook.map_by_codebook({"claim_text": "기업 설문에서 채용 의향 비율이 12%로 나타났다.", "metric": "고용지표"})
        self.assertIsNone(config)
        self.assertEqual(exclusion[0], "KOSIS 미제공")

    def test_internal_economy_word_does_not_trigger_gyeonggi_region(self):
        self.assert_mapping(
            {"claim_text": "대표적인 내수경기 지표인 소매판매액지수는 2024년 3분기 100.6으로 1년 전보다 1.9% 감소했다.", "date": "2025-01-06", "metric": "판매·생산량"},
            {"tbl_id": "DT_1K41012", "obj_l1": "G0", "itm_id": "T2", "prd_se": "Q", "target_period": "202403", "prev_period": "202303", "target_number": -1.9},
        )

    def test_historical_month_does_not_override_last_month(self):
        self.assert_mapping(
            {"claim_text": "지난달 가공식품 물가 상승률은 전년 대비 4.6%로, 2023년 11월(5.1%) 이후 가장 높았다.", "date": "2025-07-01", "metric": "물가지표"},
            {"tbl_id": "DT_1J22112", "obj_l2": "B01", "target_period": "202506", "prev_period": "202406", "target_number": 4.6},
        )

    def test_annual_marriage_level(self):
        self.assert_mapping(
            {"claim_text": "2024년 혼인·이혼 통계에 따르면 작년 전체 혼인 건수는 22만2400건이었다.", "date": "2025-03-20", "metric": "인구지표"},
            {"tbl_id": "DT_1B8000F", "obj_l1": "41", "itm_id": "T1", "prd_se": "Y", "target_period": "2024", "target_number": 222400},
        )

    def test_previous_sentence_can_supply_marriage_metric_and_month(self):
        self.assert_mapping(
            {"title": "2월 혼인 증가", "prev_sentence": "지난 2월 혼인 건수는 1만9370건이었다.", "claim_text": "이는 지난해 같은 달 대비 14.3% 증가한 수치다.", "date": "2025-04-23", "metric": "인구지표"},
            {"tbl_id": "DT_1B83A35", "obj_l1": "00", "itm_id": "T3", "target_period": "202502", "prev_period": "202402", "target_number": 14.3},
        )

    def test_foreign_retail_is_not_mapped_to_korea(self):
        config, exclusion = codebook.map_by_codebook({"claim_text": "1분기 중국 소매 판매는 작년 동기 대비 4.6% 증가했다.", "date": "2025-04-20", "metric": "판매·생산량"})
        self.assertIsNone(config)
        self.assertEqual(exclusion[0], "KOSIS 미제공")

    def test_marriage_and_birth_multi_metric_is_not_auto_mapped(self):
        config, exclusion = codebook.map_by_codebook({"claim_text": "지난 4월 혼인 건수와 출생아 수가 각각 4.9%, 8.7% 늘었다.", "date": "2025-06-25", "metric": "인구지표"})
        self.assertIsNone(config)
        self.assertEqual(exclusion[0], "정보 부족")


if __name__ == "__main__":
    unittest.main()
