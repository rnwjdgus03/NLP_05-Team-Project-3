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


# --------------------------------------------------------------------------
# 파생 지표 — 두 항목의 연산이 필요해 단일 좌표로 조회 불가
# --------------------------------------------------------------------------

SHARED_SENTENCE = ("작년 한국의 수입액은 전년보다 1.6% 감소한 6320억달러로, "
                   "518억달러의 무역 흑자를 기록했다.")


def test_trade_balance_indicator_is_rejected():
    """관세청 수출입 표엔 수출액·수입액만 있고 무역수지 항목이 없다(메타 조회 확인).

    그런데 '무역수지' 가 이름에 든 표는 대부분 기술무역수지라 오매핑을 부른다.
    """
    code, _, severity = scope_violation(_row(
        SHARED_SENTENCE, measurement_indicator="무역 흑자",
        unit="달러", value="51800000000"))
    assert code == "DERIVED_INDICATOR" and severity == REJECT


def test_same_sentence_other_measurements_survive():
    """문장으로 판정하면 정상 매핑까지 버린다 — 지표 필드로만 봐야 한다."""
    for indicator, value in (("수입액", "632000000000"), ("수입액 증감률", "1.6")):
        code, _, _ = scope_violation(_row(
            SHARED_SENTENCE, measurement_indicator=indicator,
            unit="달러", value=value))
        assert code == "", f"{indicator} 가 잘못 차단됐다"


def test_balance_types_that_exist_in_kosis_are_kept():
    """경상수지·재정수지는 국제수지 표에 항목으로 실재한다 — 막으면 안 된다."""
    for indicator in ("경상수지", "재정수지", "상품수지"):
        code, _, _ = scope_violation(_row(
            f"{indicator}는 100억달러였다.", measurement_indicator=indicator,
            unit="달러", value="10000000000"))
        assert code == "", f"{indicator} 가 잘못 차단됐다"


def test_indicator_field_variants_are_read():
    code, _, _ = scope_violation({"claim_text": SHARED_SENTENCE,
                                  "indicator": "무역수지", "unit": "달러",
                                  "value": "51800000000"})
    assert code == "DERIVED_INDICATOR"


def test_missing_indicator_is_not_judged():
    code, _, _ = scope_violation(_row("어떤 문장", measurement_indicator=""))
    assert code != "DERIVED_INDICATOR"


# --------------------------------------------------------------------------
# 2차 확장 ① 장중·일별 시세 — KOSIS 는 월·연 평균만 수록
# --------------------------------------------------------------------------

def test_intraday_exchange_rate_is_reviewed():
    code, _, severity = scope_violation(_row(
        "2일 서울 외환시장에서 달러 대비 원화 환율은 오후 3시 30분 기준 "
        "전 거래일보다 5.9원 떨어진 달러당 1466.6원을 기록했다.",
        measurement_indicator="달러 대비 원화 환율", unit="원", value="1466.6"))
    assert code == "INTRADAY_MARKET_RATE" and severity == REVIEW


def test_daily_close_without_clock_time_is_reviewed():
    code, _, severity = scope_violation(_row(
        "환율은 전 거래일보다 오른 1470원에 마감했다.",
        measurement_indicator="환율", unit="원", value="1470"))
    assert code == "DAILY_MARKET_RATE" and severity == REVIEW


def test_monthly_average_rate_is_kept():
    """월평균·연평균 환율은 KOSIS 에 실재한다 — 막으면 안 된다."""
    code, _, _ = scope_violation(_row(
        "지난해 연평균 원달러 환율은 1364원이었다.",
        measurement_indicator="원달러 환율", unit="원", value="1364"))
    assert code == ""


def test_non_market_subject_with_clock_time_is_kept():
    """시각 표현만으로 막으면 안 된다 — 대상이 시세여야 한다."""
    code, _, _ = scope_violation(_row(
        "오후 3시에 발표된 출생아 수는 2만717명이다.",
        measurement_indicator="출생아 수", unit="명", value="20717"))
    assert code == ""


# --------------------------------------------------------------------------
# 2차 확장 ② 개별 기업 실적 — KOSIS 는 산업 집계만
# --------------------------------------------------------------------------

def test_company_in_indicator_is_rejected():
    code, _, severity = scope_violation(_row(
        "현대차는 지난해 판매량이 414만 1791대로, 2023년 대비 1.8% 감소했다.",
        measurement_indicator="현대차 판매량", unit="대", value="4141791"))
    assert code == "SINGLE_COMPANY_METRIC" and severity == REJECT


def test_company_only_in_text_goes_to_review():
    """문장에만 기업명이 있으면 대상이 산업 집계일 수도 있다 — 버리지 않는다."""
    code, _, severity = scope_violation(_row(
        "현대차 등 국내 완성차 업체들의 판매량이 0.6% 줄었다.",
        measurement_indicator="완성차 판매량", unit="%", value="0.6"))
    assert code == "POSSIBLE_COMPANY_METRIC" and severity == REVIEW


def test_industry_aggregate_is_kept():
    code, _, _ = scope_violation(_row(
        "작년 국내 완성차 업체들의 판매량이 2023년 대비 0.6% 줄었다.",
        measurement_indicator="완성차 판매량", unit="%", value="0.6"))
    assert code == ""


def test_company_name_without_metric_word_is_kept():
    """기업명이 출처로만 등장한 경우 — 대상이 아니다."""
    code, _, _ = scope_violation(_row(
        "삼성전자 관계자에 따르면 소비자물가지수는 2.3% 올랐다.",
        measurement_indicator="소비자물가지수", unit="%", value="2.3"))
    assert code == ""
