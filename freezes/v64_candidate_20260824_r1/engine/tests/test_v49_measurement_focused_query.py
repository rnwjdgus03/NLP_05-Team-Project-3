from kosis_hybrid_top3 import (
    lexical_query_document,
    measurement_context_conflict,
    measurement_focused_retrieval_claim,
    semantic_query_document,
)


def test_birth_measurement_suppresses_unrelated_employment_context():
    claim = {
        "measurement_indicator": "연간 출생아 수",
        "claim_indicator": "취업자 수",
        "metric_domain": "고용",
        "title": "취업자 수가 감소할 전망",
        "claim_text": "2020년생은 27만2000명이어서 취업자 수가 감소한다.",
        "measurement_prd_se": "Y",
        "unit": "명",
    }
    assert measurement_context_conflict(claim)
    lexical = lexical_query_document(claim)
    semantic = semantic_query_document(claim)
    assert "출생아" in lexical and "출생아" in semantic
    assert "취업자" not in lexical and "취업자" not in semantic
    assert "통계영역: 고용" not in semantic
    focused = measurement_focused_retrieval_claim(claim)
    assert focused["metric_domain"] == ""
    assert focused["indicator"] == "연간 출생아 수"
    assert focused["_measurement_focused_retrieval"] is True
    assert focused["title"] == ""
    assert focused["claim_text"] == ""
    # This is the actual call shape inside Stage A. Focus mode must survive
    # after the conflicting fields have been sanitized.
    focused_lexical = lexical_query_document(focused)
    focused_semantic = semantic_query_document(focused)
    assert "출생아" in focused_lexical and "출생아" in focused_semantic
    assert "취업자" not in focused_lexical and "취업자" not in focused_semantic


def test_wrong_population_domain_does_not_override_rice_area():
    claim = {
        "measurement_indicator": "벼 재배 면적",
        "claim_indicator": "벼 재배 면적",
        "metric_domain": "인구",
        "claim_text": "벼 재배 면적은 2.9% 감소했다.",
    }
    assert measurement_context_conflict(claim)
    assert "통계영역: 인구" not in semantic_query_document(claim)
    assert measurement_focused_retrieval_claim(claim)["metric_domain"] == ""


def test_consistent_trade_measurement_keeps_context():
    claim = {
        "measurement_indicator": "대미 수출액",
        "claim_indicator": "대미 수출액",
        "metric_domain": "무역",
        "title": "대미 수출 감소",
    }
    assert not measurement_context_conflict(claim)
    assert measurement_focused_retrieval_claim(claim) is claim
    assert "통계영역: 무역" in semantic_query_document(claim)
    assert "대미 수출 감소" in lexical_query_document(claim)
