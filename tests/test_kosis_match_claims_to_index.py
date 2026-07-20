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


def test_trade_population_and_metric_mismatches_are_hard_rejected():
    semiconductor = normalized_claim_row(ready_claim())
    innovation = table(
        "DT_INNOVATION",
        "매출액 및 수출액 수준",
        "한국기업혁신조사 > 제조업 기업혁신조사",
    )
    assert score_table(innovation, claim_tokens(semiconductor), semiconductor)[0] <= -10**8

    biohealth = normalized_claim_row(
        ready_claim(
            measurement_indicator="바이오헬스 수출 증가율",
            measurement_item="바이오헬스",
        )
    )
    domestic_sales = table(
        "DT_MEDICAL_SALES",
        "국내 매출액 및 수입판매액 및 유지보수 매출액",
        "의료기기산업통계",
    )
    assert score_table(domestic_sales, claim_tokens(biohealth), biohealth)[0] <= -10**8


def test_aggregate_trade_claim_rejects_partial_and_average_tables():
    cosmetics = normalized_claim_row(
        ready_claim(
            measurement_indicator="화장품 수출액",
            measurement_item="화장품",
            value_type="수준값",
            measurement_role="현재값",
            claim_text="2024년 화장품 수출액은 102억 달러였다.",
        )
    )
    top_ten = table(
        "DT_COSMETICS_TOP10",
        "화장품 수출액 상위 10개국 현황",
        "화장품산업현황 > 화장품 수출입 현황",
    )
    assert score_table(top_ten, claim_tokens(cosmetics), cosmetics)[0] <= -10**8

    agriculture = normalized_claim_row(
        ready_claim(
            measurement_indicator="농수산식품 수출액",
            measurement_item="농수산식품",
            value_type="수준값",
            measurement_role="현재값",
            claim_text="농수산식품 수출액은 117억 달러였다.",
        )
    )
    average = table(
        "DT_AGRI_AVG",
        "품목별 수출액(평균)",
        "농촌융복합산업실태조사",
    )
    assert score_table(average, claim_tokens(agriculture), agriculture)[0] <= -10**8


def test_generic_trade_balance_rejects_narrow_domain_balance():
    claim = normalized_claim_row(
        ready_claim(
            measurement_indicator="무역수지",
            measurement_item="-",
            value_type="수준값",
            measurement_role="현재값",
            claim_text="전체 무역수지는 697억 달러 흑자였다.",
        )
    )
    intellectual_property = table(
        "DT_IP_BALANCE",
        "지식재산권 무역수지(유형별)",
        "국제수지통계 > 지식재산권 무역수지",
    )
    generic = table("DT_TRADE", "품목별 수출액, 수입액", "SITC에의한무역통계")

    assert score_table(intellectual_property, claim_tokens(claim), claim)[0] <= -10**8
    assert score_table(generic, claim_tokens(claim), claim)[0] > 0


def test_air_passenger_and_mechanic_population_mismatches_are_hard_rejected():
    passengers = normalized_claim_row(
        ready_claim(
            measurement_indicator="국제선 여객수",
            measurement_item="LCC",
            unit="명",
            value_type="수준값",
            measurement_role="현재값",
        )
    )
    regional_travel = table(
        "DT_REGIONAL_TRAVEL",
        "지역 간 통행량(승용차, 버스, 철도, 항공, 해운)",
        "국가교통조사",
    )
    assert score_table(regional_travel, claim_tokens(passengers), passengers)[0] <= -10**8

    mechanics = normalized_claim_row(
        ready_claim(
            measurement_indicator="LCC 정비사 수",
            measurement_item="항공 정비사",
            unit="명",
            value_type="수준값",
            measurement_role="현재값",
        )
    )
    shortage = table(
        "DT_SHORTAGE",
        "직무별 부족인원 및 부족률",
        "항공산업실태조사",
    )
    assert score_table(shortage, claim_tokens(mechanics), mechanics)[0] <= -10**8


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


class OverconfidentSemanticRuntime:
    def search(self, query, top_k):
        return [
            SemanticHit("1", "DT_SALES", 0.99, 1),
            SemanticHit("1", "DT_TRADE", 0.70, 2),
        ][:top_k]

    def rerank(self, query, table_rows):
        scores = {"DT_SALES": 0.999, "DT_TRADE": 0.10}
        return [scores[row["tbl_id"]] for row in table_rows]


def test_semantic_only_candidate_cannot_override_rule_eligible_candidate():
    claim = normalized_claim_row(ready_claim())
    tables = [
        table("DT_TRADE", "품목별 수출액, 수입액", "SITC에의한무역통계"),
        table("DT_SALES", "산업별 매출액", "기업경영통계"),
    ]
    ranked = rank_table_candidates(
        tables,
        claim,
        min_score=2,
        top_tables=2,
        semantic_runtime=OverconfidentSemanticRuntime(),
        semantic_top_k=2,
        rerank_top_k=2,
    )

    assert ranked[0]["table"]["tbl_id"] == "DT_TRADE"
    assert ranked[0]["lexical_eligible"] is True
    assert ranked[1]["lexical_eligible"] is False
