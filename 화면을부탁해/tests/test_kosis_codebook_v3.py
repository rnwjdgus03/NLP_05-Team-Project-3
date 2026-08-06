import unittest

import kosis_codebook_v3 as codebook


class KosisCodebookV3P0Test(unittest.TestCase):
    def test_foreign_cause_does_not_exclude_domestic_oil_price(self):
        config, exclusion = codebook.map_by_codebook({
            "date": "2025-05-02",
            "title": "물가 상승률 4개월 째 2%대",
            "claim_text": "연초 미국의 석유 증산 등으로 국제 유가가 떨어졌던 게 시차를 두고 반영되면서, 지난달 석유류 가격은 1.7% 떨어졌다.",
            "metric": "비율·증감률",
        })

        self.assertIsNone(exclusion)
        self.assertEqual(config["tbl_id"], "DT_1J22112")
        self.assertEqual(config["obj_l1"], "T10")
        self.assertEqual(config["obj_l2"], "B05")
        self.assertEqual(config["itm_id"], "T")
        self.assertEqual(config["target_number"], -1.7)
        self.assertEqual(config["target_period"], "202504")
        self.assertEqual(config["prev_period"], "202404")

    def test_two_month_price_history_is_not_reduced_to_one_item(self):
        config, exclusion = codebook.map_by_codebook({
            "date": "2025-11-04",
            "title": "10월 소비자물가 2.4% 상승",
            "claim_text": "소비자 물가 상승률은 지난 8월 요금 인하 효과로 1.7%를 기록했다가, 가공식품과 먹거리 물가가 오르면서 9월 2.1%로 올라선 바 있다.",
            "metric": "위치·거리정보",
        })

        self.assertIsNone(config)
        self.assertEqual(exclusion[0], "정보 부족")

    def test_private_kcar_results_are_not_national_retail_index(self):
        config, exclusion = codebook.map_by_codebook({
            "date": "2025-06-01",
            "title": "중고차 시장 호조",
            "claim_text": "케이카의 올해 1분기 실적에 따르면 중고차의 소매 평균거래가격(ASP)은 전년 대비 3% 상승했지만, 소매판매 대수는 5% 감소했다.",
            "metric": "비율·증감률",
        })

        self.assertIsNone(config)
        self.assertEqual(exclusion[0], "KOSIS 미제공")

    def test_v2_rules_are_delegated_unchanged(self):
        config, exclusion = codebook.map_by_codebook({
            "claim_text": "2024년 혼인·이혼 통계에 따르면 작년 전체 혼인 건수는 22만2400건이었다.",
            "date": "2025-03-20",
            "metric": "인구지표",
        })

        self.assertIsNone(exclusion)
        self.assertEqual(config["tbl_id"], "DT_1B8000F")
        self.assertEqual(config["target_number"], 222400)


if __name__ == "__main__":
    unittest.main()
