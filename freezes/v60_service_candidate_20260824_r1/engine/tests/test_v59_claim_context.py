import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENGINE = ROOT.parent if (ROOT.parent / "kosis_scope_gate.py").is_file() else ROOT / "engine"
sys.path.insert(0, str(ENGINE))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ENGINE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scope = _load("scope_v59", "kosis_scope_gate.py")
prepare = _load("prepare_v59", "prepare_kosis_mapping_input.py")


def test_official_national_claim_inside_company_article_is_not_title_blocked():
    row = {
        "title": "전기차 판매 부진 현대차… 울산 라인서 생산 중단",
        "claim_text": (
            "산업통상자원부에 따르면 지난달 대미 수출은 "
            "작년보다 6.8% 감소한 106억3000만달러로 집계됐다."
        ),
        "measurement_indicator": "대미 수출액",
    }
    decision = scope.gate_decision(row)
    assert decision["scope_gate_code"] == ""
    assert decision["scope_gate_blocked"] == "N"


def test_company_subject_still_blocks_company_metric():
    row = {
        "title": "현대차 수출 증가",
        "claim_text": "현대차는 지난달 수출액이 10% 증가했다고 밝혔다.",
        "measurement_indicator": "현대차 수출액",
    }
    decision = scope.gate_decision(row)
    assert decision["scope_gate_code"] == "SINGLE_COMPANY_METRIC"
    assert decision["scope_gate_blocked"] == "Y"


def test_unattributed_aggregate_in_company_article_remains_blocked():
    row = {
        "title": "현대차 수출 증가",
        "claim_text": "지난달 수출액은 10% 증가했다.",
        "measurement_indicator": "수출액",
    }
    decision = scope.gate_decision(row)
    assert decision["scope_gate_code"] == "SINGLE_COMPANY_METRIC"


def test_monthly_item_change_inherits_explicit_title_month():
    row = {
        "title": "국제 유가 하락에 4월 생산자물가 전월보다 하락",
        "date": "2025-05-22",
        "claim_text": (
            "전월 대비 상승폭을 품목별로 보면 농산물(-5.8%)이 "
            "전체 생산자물가를 끌어내렸다."
        ),
        "measurement_text": "5.8%",
        "measurement_indicator": "농산물 가격 변동",
        "measurement_period": "-",
        "measurement_prd_se": "-",
        "claim_period": "2025-04",
        "claim_prd_se": "M",
    }
    assert prepare.recover_contextual_title_month(row) == (
        "202504",
        "MONTH_FROM_ARTICLE_TITLE_CONTEXT",
    )


def test_contextual_month_normalization_restores_periodicity_and_comparison():
    row = {
        "claim_id": "A-c3",
        "claim_measurement_id": "A-c3-m1",
        "article_id": "A",
        "title": "국제 유가 하락에 4월 생산자물가 전월보다 하락",
        "date": "2025-05-22",
        "claim_text": "전월 대비 농산물(-5.8%)이 전체 생산자물가를 끌어내렸다.",
        "claim_domain_scope": "국내공식통계",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_text": "5.8%",
        "measurement_indicator": "농산물 가격 변동",
        "measurement_item": "농산물",
        "measurement_period": "-",
        "measurement_prd_se": "-",
        "claim_period": "2025-04",
        "claim_prd_se": "M",
        "measurement_role": "증감률",
        "value_type": "증감률",
        "change_base": "전월",
        "value": "5.8",
        "unit": "%",
        "needs_review": "Y",
        "review_reason": "measurement_period_ungrounded:2",
        "extraction_confidence": "high",
    }
    normalized = prepare.normalize_row(row)
    assert normalized["period"] == "202504"
    assert normalized["prd_se"] == "M"
    assert normalized["comparison_period"] == "202503"
    assert normalized["mapping_gate"] == "READY"


def test_contextual_title_month_requires_shared_statistical_subject():
    row = {
        "title": "4월 자동차 판매 증가",
        "date": "2025-05-22",
        "claim_text": "전월 대비 농산물 가격은 5.8% 하락했다.",
        "measurement_indicator": "농산물 가격 변동",
        "measurement_period": "-",
        "measurement_prd_se": "M",
    }
    assert prepare.recover_contextual_title_month(row) == ("", "")


def test_explicit_sentence_month_is_not_overwritten_by_title_month():
    row = {
        "title": "4월 생산자물가 전월보다 하락",
        "date": "2025-05-22",
        "claim_text": "5월 들어 평균 유가가 전월보다 6% 하락했다.",
        "measurement_indicator": "평균 유가",
        "measurement_period": "-",
        "measurement_prd_se": "-",
        "claim_period": "2025-04",
        "claim_prd_se": "M",
    }
    assert prepare.recover_contextual_title_month(row) == ("", "")


def test_age_band_is_not_treated_as_vehicle_count():
    row = {
        "claim_text": "연령대별로 20대(25.1%), 40대(10%), 50대(7.9%) 순이었다.",
        "measurement_text": "20대",
        "measurement_item": "20대",
    }
    assert prepare.demographic_label_measurement(row) is True


def test_actual_vehicle_quantity_is_not_age_band():
    row = {
        "claim_text": "전기차 20대를 판매했다.",
        "measurement_text": "20대",
        "measurement_item": "전기차",
    }
    assert prepare.demographic_label_measurement(row) is False
