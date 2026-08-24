import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "engine" if (ROOT / "engine").is_dir() else ROOT
sys.path.insert(0, str(ENGINE))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ENGINE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


meta = _load("kosis_meta_coordinates", "kosis_meta_coordinates.py")


def test_exact_scope_accepts_official_connective_aliases():
    assert meta.target_scope_exact_match(
        ["숙박음식점업"], ["숙박 및 음식점업"]
    )
    assert meta.target_scope_exact_match(
        ["석탄·석유제품"], ["석탄및석유제품"]
    )
    assert meta.target_scope_exact_match(
        ["석탄", "석유제품"], ["석탄및석유제품"]
    )


def test_exact_scope_still_rejects_narrower_or_extra_category():
    assert not meta.target_scope_exact_match(["숙박음식점업"], ["숙박업"])
    assert not meta.target_scope_exact_match(
        ["숙박음식점업"], ["숙박 및 음식점업", "서울"]
    )


def test_relative_month_change_is_preserved_as_target_period():
    prepare = _load("prepare_v53", "prepare_kosis_mapping_input.py")
    row = {
        "measurement_period": "202504",
        "measurement_prd_se": "M",
        "claim_period": "202505",
        "claim_prd_se": "M",
        "measurement_role": "증감률",
        "change_base": "전월",
        "_relative_measurement_period_status": "PREVIOUS_MONTH_FROM_ARTICLE_DATE",
    }
    assert prepare.align_change_period(row) == (
        "202504",
        "RELATIVE_MEASUREMENT_PERIOD_PRESERVED",
    )
    comparison_row = dict(row, measurement_period="202504")
    assert prepare.comparison_period(comparison_row, "rate_change") == "202503"


def test_nonrelative_base_binding_keeps_existing_alignment_behavior():
    prepare = sys.modules["prepare_v53"]
    row = {
        "measurement_period": "202504",
        "measurement_prd_se": "M",
        "claim_period": "202505",
        "claim_prd_se": "M",
        "measurement_role": "증감률",
        "change_base": "전월",
    }
    assert prepare.align_change_period(row) == (
        "202505",
        "COMPARISON_PERIOD_TO_TARGET",
    )


def test_title_relative_month_preserves_high_confidence_hcx_month():
    prepare = sys.modules["prepare_v53"]
    row = {
        "title": "지난달 생산자물가지수가 전월보다 하락했다",
        "date": "2025-05-23",
        "claim_text": "품목별로 농산물은 5.8% 하락했다.",
        "measurement_text": "5.8%",
        "measurement_period": "202504",
    }
    assert prepare.recover_relative_measurement_period(row) == (
        "202504",
        "PREVIOUS_MONTH_FROM_ARTICLE_TITLE",
    )


def test_unqualified_month_repairs_wrong_hcx_year_from_publication_date():
    prepare = sys.modules["prepare_v53"]
    row = {
        "date": "2025-04-14",
        "claim_text": "2월 숙박·음식점업 생산지수는 3.8% 감소했다.",
        "measurement_period": "202402",
        "measurement_prd_se": "M",
    }
    assert prepare.recover_single_month_period(row) == (
        "202502",
        "UNQUALIFIED_MONTH_FROM_ARTICLE_DATE",
    )
