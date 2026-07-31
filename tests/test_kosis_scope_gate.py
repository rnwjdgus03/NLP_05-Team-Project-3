"""KOSIS 범위 게이트 테스트.

모든 케이스는 silver_coordinates.csv 의 실제 NO_MATCH 주장에서 그대로 가져왔다.
(기존 게이트가 HCX 라벨만 보고 전부 통과시켰던 것들)
"""
from kosis_scope_gate import REJECT, REVIEW, gate_decision, scope_violation


def _row(claim_text, **kw):
    base = {"claim_text": claim_text, "unit": "%", "value": "1.0"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 해외 자산·지수
# --------------------------------------------------------------------------

def test_crypto_price_is_rejected():
    code, _, severity = scope_violation(_row(
        "비트코인은 전주 대비 1.31% 상승한 9만7000달러, 이더리움은 3.63% 상승한 3400달러 선에서 거래 중이다."))
    assert code == "FOREIGN_MARKET_VALUE" and severity == REJECT


def test_foreign_index_is_rejected():
    code, _, severity = scope_violation(_row(
        "나스닥종합지수와 S&P500지수의 연간 상승률은 30% 안팎을 기록했다."))
    assert code == "FOREIGN_MARKET_VALUE" and severity == REJECT


def test_domestic_index_is_not_touched():
    """코스피·코스닥은 국내 통계라 걸리면 안 된다."""
    code, _, _ = scope_violation(_row(
        "코스피지수와 코스닥지수는 연초보다 각각 9.9%, 21.7% 하락한 채 장을 마쳤다."))
    assert code == ""


# --------------------------------------------------------------------------
# 세계 집계 vs 한국의 세계 비교
# --------------------------------------------------------------------------

def test_world_average_is_rejected():
    code, _, severity = scope_violation(_row("전 세계 평균(1만명당 162대)의 6배가 넘는 수치다."))
    assert code == "GLOBAL_SCOPE_VALUE" and severity == REJECT


def test_korea_compared_to_world_is_reviewed_not_rejected():
    """'전 세계 수출순위' 는 한국 실적 이야기다 — 버리지 말고 사람이 본다."""
    code, _, severity = scope_violation(_row(
        "2024년 1~9월 기준으로 전 세계 수출순위도 2023년 8위에서 6위를 달성했다."))
    assert code == "GLOBAL_COMPARISON" and severity == REVIEW


# --------------------------------------------------------------------------
# 전망·계획
# --------------------------------------------------------------------------

def test_forecast_is_rejected():
    code, _, severity = scope_violation(_row(
        "기재부는 올해 경제 성장률이 1.8%로 전망된다고 밝혔다."))
    assert code == "FORECAST_VALUE" and severity == REJECT


def test_plan_is_rejected():
    code, _, severity = scope_violation(_row(
        "673조3000억원 규모의 새해 예산 중 67%를 상반기 안으로 집행하겠다고도 했다."))
    assert code == "PLAN_VALUE" and severity == REJECT


def test_realized_statistic_is_not_flagged_as_forecast():
    code, _, _ = scope_violation(_row(
        "작년 12월 수출은 613억8000만달러로 1년 전 대비 6.6% 늘었다.", unit="달러", value="61380000000"))
    assert code == ""


# --------------------------------------------------------------------------
# 제도 파라미터
# --------------------------------------------------------------------------

def test_tax_rate_change_is_rejected():
    code, _, severity = scope_violation(_row(
        "신차 구매 시 개별소비세 인하(세율 5%→3.5%)를 1년 반 만에 부활했다.", value="3.5"))
    assert code == "POLICY_PARAMETER" and severity == REJECT


def test_completed_policy_change_is_policy_not_plan():
    """'확대했다' 는 이미 시행된 제도다 — 계획으로 분류하면 사유가 틀린다."""
    code, reason, severity = scope_violation(_row(
        "기업별 외국 인력 도입 허용 비율도 내국인 근로자의 20%에서 30%로 "
        "2년간 한시적으로 확대했다.", value="30"))
    assert code == "POLICY_PARAMETER" and severity == REJECT
    assert "허용 비율" in reason


def test_quota_is_rejected():
    code, _, severity = scope_violation(_row(
        "지난해 9월 전국 가축방역관 정원은 1061명이었다.", unit="명", value="1061"))
    assert code == "POLICY_PARAMETER" and severity == REJECT


# --------------------------------------------------------------------------
# 개별 브랜드 상품가
# --------------------------------------------------------------------------

def test_branded_product_price_is_rejected():
    code, _, severity = scope_violation(_row(
        "롤렉스는 인기 모델인 ‘데이트저스트 오이스터스틸·화이트골드 36㎜’ 국내 판매가를 "
        "기존 1292만원에서 1373만원으로 올렸다.", unit="원", value="13730000"))
    assert code == "BRANDED_PRODUCT_PRICE" and severity == REJECT


def test_quoted_name_without_price_word_goes_to_review():
    code, _, severity = scope_violation(_row(
        "에르메스는 반지 제품인 ‘에버 헤라클레스 웨딩 밴드’를 기존 477만원에서 527만원으로 인상했다.",
        unit="원", value="5270000"))
    assert code == "POSSIBLE_PRODUCT_PRICE" and severity == REVIEW


def test_non_currency_unit_is_not_product_price():
    code, _, _ = scope_violation(_row("‘산업활동동향’ 지표는 0.4% 감소했다.", unit="%", value="0.4"))
    assert code != "BRANDED_PRODUCT_PRICE"


# --------------------------------------------------------------------------
# 파생 차액 — 문장 안 두 값의 차이를 measurement 로 뽑은 경우
# --------------------------------------------------------------------------

def test_difference_between_two_values_is_rejected():
    """'1292만원 → 1373만원' 의 차이 81만원은 KOSIS 항목이 아니다."""
    code, _, severity = scope_violation(_row(
        "롤렉스는 판매가를 기존 1292만원에서 1373만원으로 81만원(6.3%) 올렸다.",
        unit="원", value="810000"))
    assert code in {"DERIVED_DIFFERENCE", "BRANDED_PRODUCT_PRICE"} and severity == REJECT


def test_plain_difference_is_detected_without_brand():
    code, _, severity = scope_violation(_row(
        "참그린 세제는 3900원에서 4500원으로 600원이나 올랐다.", unit="원", value="600"))
    assert code == "DERIVED_DIFFERENCE" and severity == REJECT


def test_level_value_is_not_mistaken_for_difference():
    """수준값 자체는 남겨야 한다."""
    code, _, _ = scope_violation(_row(
        "작년 한 해 전체 수출액이 6838억달러로 증가했다.", unit="달러", value="683800000000"))
    assert code == ""


def test_difference_needs_a_change_expression():
    """단순히 두 숫자가 있다고 차액으로 보면 안 된다."""
    code, _, _ = scope_violation(_row(
        "2023년 1601명과 4248명이 각각 집계됐다.", unit="명", value="2647"))
    assert code == ""


# --------------------------------------------------------------------------
# 통과해야 하는 정상 주장 (오탐 방지)
# --------------------------------------------------------------------------

def test_normal_export_statistic_passes():
    code, _, _ = scope_violation(_row(
        "12월 수출도 반도체가 31.5% 증가한 145억 달러를 기록했다.", unit="%", value="31.5"))
    assert code == ""


def test_normal_cpi_statistic_passes():
    code, _, _ = scope_violation(_row(
        "지난해 연간 소비자물가지수 상승폭은 2.3%였다.", unit="%", value="2.3"))
    assert code == ""


def test_empty_claim_text_is_not_judged():
    assert scope_violation({"claim_text": ""}) == ("", "", "")


# --------------------------------------------------------------------------
# 출력 형태 — 기존 게이트를 덮어쓰지 않고 컬럼만 추가
# --------------------------------------------------------------------------

def test_gate_decision_adds_columns_only():
    decision = gate_decision(_row("비트코인은 9만7000달러에 거래됐다."))
    assert decision["scope_gate_blocked"] == "Y"
    assert set(decision) == {"scope_gate_code", "scope_gate_reason",
                             "scope_gate_severity", "scope_gate_blocked"}


def test_review_severity_does_not_block():
    decision = gate_decision(_row(
        "2024년 전 세계 수출순위에서 한국은 6위를 달성했다."))
    assert decision["scope_gate_severity"] == REVIEW
    assert decision["scope_gate_blocked"] == "N"


def test_clean_claim_reports_no_code():
    decision = gate_decision(_row("12월 수출은 614억달러로 6.6% 증가했다.", unit="%", value="6.6"))
    assert decision["scope_gate_code"] == "" and decision["scope_gate_blocked"] == "N"
