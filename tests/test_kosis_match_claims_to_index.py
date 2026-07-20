from kosis_match_claims_to_index import (
    candidate_decision,
    claim_tokens,
    compact,
    item_mapping_type,
    norm_table_row,
    normalized_claim_row,
    rank_table_candidates,
    score_table,
)
from kosis_semantic_search import SemanticHit


def ready_claim(**overrides):
    row = {
        "claim_id": "A1-C1",
        "claim_measurement_id": "A1-C1-m1",
        "measurement_indicator": "반도체 수출 증가율",
        "measurement_item": "반도체",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "claim_domain_scope": "국내공식통계",
        "measurement_role": "증감률",
        "value": "20",
        "unit": "%",
        "value_type": "증감률",
        "mapping_eligible": "Y",
        "claim_text": "2024년 반도체 수출은 20% 증가했다.",
    }
    row.update(overrides)
    return row


def table(tbl_id, name, path="무역"):
    row = norm_table_row(
        {"ORG_ID": "1", "TBL_ID": tbl_id, "TBL_NM": name, "path": path}
    )
    row["_compact_tbl_name"] = compact(row["tbl_name"])
    row["_compact_category_path"] = compact(row["category_path"])
    return row


def test_measurement_fields_override_claim_fields():
    claim = normalized_claim_row(
        ready_claim(indicator="여러 지표", industry_or_item="화장품", period="2025")
    )
    assert claim["indicator"] == "반도체 수출 증가율"
    assert claim["industry_or_item"] == "반도체"
    assert claim["period"] == "2024"


def test_rate_claim_can_be_derived_from_level_item():
    claim = normalized_claim_row(ready_claim())
    mapping_type, reason = item_mapping_type(claim, "백만달러", "수출액")
    assert mapping_type == "rate_from_level"
    assert "증감률" in reason


def test_generic_trade_table_beats_wrong_product_and_archive():
    claim = normalized_claim_row(ready_claim())
    tokens = claim_tokens(claim)
    generic = table("DT_TRADE", "품목별 수출액, 수입액", "SITC에의한무역통계")
    cosmetics = table("DT_COSMETICS", "화장품 수입 및 수출액 현황", "화장품산업")
    archived = table("DT_TRADE_2019", "품목별 수출액, 수입액", "SITC에의한무역통계")

    generic_score = score_table(generic, tokens, claim)[0]
    cosmetics_score = score_table(cosmetics, tokens, claim)[0]
    archived_score = score_table(archived, tokens, claim)[0]

    assert generic_score > cosmetics_score
    assert archived_score < 0


def test_candidate_decision_keeps_ambiguity_and_formula_explicit():
    structured = {
        "selected_itm_id": "T1",
        "selected_obj_l1": "A1",
        "selected_obj_l1_name": "반도체",
    }
    meta = [{"is_item": "Y"}, {"is_item": "N"}]
    ambiguous = candidate_decision(1, 100, 95, structured, meta, normalized_claim_row(ready_claim()))
    assert ambiguous[0:2] == ("REVIEW", "AMBIGUOUS_TABLE")

    trade_balance = normalized_claim_row(
        ready_claim(
            measurement_indicator="무역수지",
            measurement_item="-",
            unit="달러",
            value_type="수준값",
            measurement_role="현재값",
        )
    )
    formula = candidate_decision(1, 100, 50, structured, meta, trade_balance)
    assert formula[0:2] == ("REVIEW", "FORMULA_REQUIRED")


def test_robot_adoption_and_robot_industry_populations_are_not_equated():
    claim = normalized_claim_row(
        ready_claim(
            measurement_indicator="로봇화에 뛰어든 기업 수",
            measurement_item="-",
            measurement_period="2023",
            claim_text="로봇을 도입한 기업이 2019년보다 13% 증가했다.",
        )
    )
    structured = {
        "selected_itm_id": "T1",
        "selected_obj_l1": "A1",
        "selected_obj_l1_name": "전체",
    }
    meta = [{"is_item": "Y"}, {"is_item": "N"}]
    decision = candidate_decision(
        1,
        100,
        50,
        structured,
        meta,
        claim,
        {"tbl_name": "사업체 수", "category_path": "로봇산업실태조사"},
    )
    assert decision[0:2] == ("REVIEW", "POPULATION_DEFINITION_MISMATCH")


class FakeSemanticRuntime:
    def __init__(self, semantic_hits, reranker_scores):
        self.semantic_hits = semantic_hits
        self.reranker_scores = reranker_scores

    def search(self, query, top_k):
        assert "반도체 수출 증가율" in query
        return self.semantic_hits[:top_k]

    def rerank(self, query, table_rows):
        by_table = {
            "DT_TRADE": 0.98,
            "DT_COSMETICS": 0.08,
        }
        return [by_table.get(row["tbl_id"], 0.1) for row in table_rows]


def test_hybrid_retrieval_uses_reranker_without_bypassing_rules():
    claim = normalized_claim_row(ready_claim())
    tables = [
        table("DT_TRADE", "품목별 수출액, 수입액", "SITC에의한무역통계"),
        table("DT_COSMETICS", "화장품 수입 및 수출액 현황", "화장품산업"),
    ]
    runtime = FakeSemanticRuntime(
        [
            SemanticHit("1", "DT_COSMETICS", 0.92, 1),
            SemanticHit("1", "DT_TRADE", 0.88, 2),
        ],
        [],
    )
    ranked = rank_table_candidates(
        tables,
        claim,
        min_score=2,
        top_tables=2,
        semantic_runtime=runtime,
        semantic_top_k=2,
        rerank_top_k=2,
    )

    assert ranked[0]["table"]["tbl_id"] == "DT_TRADE"
    assert ranked[0]["retrieval_backend"] == "hybrid+reranker"
    assert ranked[0]["reranker_score"] == 0.98
    assert ranked[0]["semantic_score"] == 0.88
