import importlib.util
import sys
from pathlib import Path


ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
spec = importlib.util.spec_from_file_location(
    "prepare_v61_period_context", ENGINE / "prepare_kosis_mapping_input.py"
)
prepare = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = prepare
spec.loader.exec_module(prepare)


def base_row(**overrides):
    row = {
        "claim_id": "DEV-c1",
        "claim_measurement_id": "DEV-c1-m1",
        "article_id": "DEV",
        "title": "8월 출생아 수 증가",
        "date": "2025-10-29",
        "claim_text": "지난 8월 출생아 수는 1년 전보다 증가한 2만867명이다.",
        "claim_domain_scope": "국내공식통계",
        "measurement_usage": "KOSIS_VALUE",
        "measurement_binding_source": "hcx",
        "measurement_text": "2만867명",
        "measurement_indicator": "출생아 수",
        "measurement_period": "-",
        "measurement_prd_se": "-",
        "claim_period": "2025-08",
        "claim_prd_se": "M",
        "measurement_role": "현재값",
        "value_type": "수준값",
        "change_base": "전년동기",
        "value": "20867",
        "unit": "명",
        "needs_review": "N",
        "extraction_confidence": "high",
    }
    row.update(overrides)
    return row


def test_explicit_single_month_inherits_complete_claim_period():
    row = base_row()
    assert prepare.recover_explicit_claim_period(row) == (
        "202508",
        "EXPLICIT_CLAIM_MONTH_INHERITED",
    )
    normalized = prepare.normalize_row(row)
    assert normalized["period"] == "202508"
    assert normalized["prd_se"] == "M"
    assert normalized["mapping_gate"] == "READY"
    assert "EXPLICIT_CLAIM_MONTH_INHERITED" in normalized["period_alignment_status"]


def test_cumulative_month_range_is_not_inherited_as_single_month():
    row = base_row(
        claim_text="1~8월 출생아 수는 16만8671명이다.",
        measurement_text="16만8671명",
        value="168671",
    )
    assert prepare.recover_explicit_claim_period(row) == ("", "")
    normalized = prepare.normalize_row(row)
    assert normalized["mapping_exclusion_code"] == "PERIOD_MISSING"


def test_different_explicit_year_is_not_overwritten():
    row = base_row(claim_text="2024년 8월 출생아 수는 2만867명이었다.")
    assert prepare.recover_explicit_claim_period(row) == ("", "")


def test_existing_measurement_period_always_wins():
    row = base_row(measurement_period="2024-08", measurement_prd_se="M")
    assert prepare.recover_explicit_claim_period(row) == ("2024-08", "")
