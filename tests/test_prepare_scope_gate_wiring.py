"""내용 기반 범위 게이트가 실제 파이프라인에 물렸는지 확인한다.

핵심: HCX 가 `measurement_usage=KOSIS_VALUE` + `claim_domain_scope=국내공식통계` 로
찍어도, 주장 내용이 KOSIS 범위 밖이면 in_ready 에서 빠져야 한다.
(기존 게이트는 이 라벨만 보고 전부 통과시켰다 — 실측 NO_MATCH 약 121건의 원인)
"""
from prepare_kosis_mapping_input import normalize_row


def measurement_row(**overrides):
    row = {
        "claim_id": "A1-C1",
        "claim_measurement_id": "A1-C1-m1",
        "claim_text": "2024년 반도체 수출액은 100억 달러였다.",
        # HCX 는 아래 두 라벨을 '정상'으로 찍은 상태다
        "claim_domain_scope": "국내공식통계",
        "measurement_usage": "KOSIS_VALUE",
        "indicator": "수출 통계",
        "industry_or_item": "반도체",
        "period": "2024",
        "prd_se": "Y",
        "measurement_indicator": "반도체 수출액",
        "measurement_item": "반도체",
        "measurement_period": "2024",
        "measurement_prd_se": "Y",
        "measurement_binding_source": "hcx",
        "measurement_role": "현재값",
        "value": "10000000000",
        "unit": "달러",
        "value_type": "수준값",
    }
    row.update(overrides)
    return row


def test_normal_claim_still_passes():
    out = normalize_row(measurement_row())
    assert out["in_ready"] == "Y"
    assert out["scope_gate_blocked"] == "N"
    assert out["mapping_gate"] == "READY"


def test_crypto_claim_is_blocked_despite_clean_hcx_labels():
    out = normalize_row(measurement_row(
        claim_text="비트코인은 전주 대비 1.31% 상승한 9만7000달러에 거래 중이다.",
        value="97000", unit="달러"))
    assert out["in_ready"] == "N"
    assert out["mapping_exclusion_code"] == "FOREIGN_MARKET_VALUE"
    assert out["mapping_gate"] == "REJECT"
    # 회수 대상이 아니므로 보강 액션을 주지 않는다
    assert out["enrichment_actions"] == ""


def test_forecast_claim_is_blocked():
    out = normalize_row(measurement_row(
        claim_text="기재부는 올해 경제 성장률이 1.8%로 전망된다고 밝혔다.",
        value="1.8", unit="%", value_type="비율"))
    assert out["in_ready"] == "N"
    assert out["mapping_exclusion_code"] == "FORECAST_VALUE"


def test_branded_product_price_is_blocked():
    out = normalize_row(measurement_row(
        claim_text="롤렉스는 ‘데이트저스트 오이스터스틸 36㎜’ 국내 판매가를 "
                   "1292만원에서 1373만원으로 올렸다.",
        value="13730000", unit="원"))
    assert out["in_ready"] == "N"
    assert out["mapping_exclusion_code"] == "BRANDED_PRODUCT_PRICE"


def test_review_severity_does_not_block_the_row():
    """애매한 건 버리지 않는다 — 컬럼에 표시만 하고 통과시킨다."""
    out = normalize_row(measurement_row(
        claim_text="2024년 전 세계 수출순위에서 우리나라는 6위를 달성했다."))
    assert out["scope_gate_severity"] == "REVIEW"
    assert out["scope_gate_blocked"] == "N"
    assert out["in_ready"] == "Y"


def test_existing_exclusion_code_is_not_overwritten():
    """기존 게이트가 먼저 걸렀으면 그 사유를 유지한다(진단 연속성)."""
    out = normalize_row(measurement_row(
        measurement_usage="배경설명",
        claim_text="비트코인은 9만7000달러에 거래 중이다."))
    assert out["mapping_exclusion_code"] == "NOT_KOSIS_VALUE"
    # 다만 범위 판정 결과는 별도 컬럼에 남는다
    assert out["scope_gate_code"] == "FOREIGN_MARKET_VALUE"


def test_scope_columns_always_present():
    out = normalize_row(measurement_row())
    for field in ("scope_gate_code", "scope_gate_reason",
                  "scope_gate_severity", "scope_gate_blocked"):
        assert field in out
