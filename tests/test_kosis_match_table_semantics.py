from kosis_match_claims_to_index import normalized_claim_row, score_table


def _table(tbl_name):
    return {"tbl_name": tbl_name, "category_path": "", "_compact_tbl_name": tbl_name.replace(" ", ""), "_compact_category_path": ""}


def test_cpi_claim_excludes_tourism_satisfaction_table():
    score, hits = score_table(_table("관광 숙박여행 만족도_관광지 물가"), [], normalized_claim_row({"indicator": "소비자 물가 상승률"}))
    assert score <= -10**8
    assert "CPI_TOURISM_TABLE_MISMATCH" in hits


def test_exchange_rate_claim_excludes_loan_table():
    score, hits = score_table(_table("한국은행 원화대출금"), [], normalized_claim_row({"indicator": "원화 환율"}))
    assert score <= -10**8
    assert "EXCHANGE_RATE_LOAN_TABLE_MISMATCH" in hits


def test_revenue_growth_claim_excludes_export_table():
    score, hits = score_table(_table("품목별 수출액, 수입액"), [], normalized_claim_row({"indicator": "메모리반도체 매출 성장세"}))
    assert score <= -10**8
    assert "REVENUE_EXPORT_SOURCE_MISMATCH" in hits
