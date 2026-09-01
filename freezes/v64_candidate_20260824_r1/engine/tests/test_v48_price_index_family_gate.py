from kosis_verify_claim_values import indicator_table_family_mismatch


def test_producer_price_claim_rejects_consumer_price_table():
    reason = indicator_table_family_mismatch(
        {
            "measurement_indicator": "농산물 생산자물가지수",
            "claim_text": "생산자물가가 전월보다 5.8% 하락했다.",
            "official_table_name": "품목성질별 소비자물가지수(2020=100)",
            "official_item_name": "소비자물가지수",
        }
    )
    assert "서로 다른 물가지수 계열" in reason


def test_producer_price_claim_accepts_producer_price_table():
    assert not indicator_table_family_mismatch(
        {
            "measurement_indicator": "생산자물가지수",
            "official_table_name": "생산자물가지수(기본분류)",
        }
    )


def test_consumer_price_claim_rejects_producer_price_table():
    assert indicator_table_family_mismatch(
        {
            "indicator": "소비자물가지수 전월비",
            "tbl_name": "생산자물가지수(품목별)",
        }
    )


def test_generic_price_claim_is_not_overblocked():
    assert not indicator_table_family_mismatch(
        {
            "indicator": "물가 상승률",
            "tbl_name": "월별 소비자물가 등락률",
        }
    )
