import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kosis_verify_claim_values import (
    derive_actual,
    infer_comparison_period,
    item_compatible,
    parse_number,
    prepare_rows_for_verification,
    read_csv,
    unit_factor,
    verify_row,
)


def test_scientific_notation_claim_value_is_not_truncated():
    assert parse_number("1.42E+11") == 142_000_000_000


def test_base_unit_conversion_uses_multiplication_for_canonical_claim_values():
    assert unit_factor("백만달러", "달러")[0] == 1_000_000
    assert unit_factor("백만원", "원")[0] == 1_000_000
    assert unit_factor("천명", "명")[0] == 1_000
    assert unit_factor("백만달러", "원")[0] is None


def test_explicit_year_over_year_text_infers_comparison_period():
    monthly, monthly_reason = infer_comparison_period({
        "period": "202412",
        "claim_text": "12월 수출액은 전년 동월 대비 6.6% 증가했다.",
    })
    yearly, yearly_reason = infer_comparison_period({
        "period": "2024",
        "claim_text": "전체 수입이 전년 대비 1.6% 감소했다.",
    })

    assert monthly == "202312"
    assert "비교 월" in monthly_reason
    assert yearly == "2023"
    assert "비교 연도" in yearly_reason


def test_comparison_period_is_not_guessed_without_explicit_yoy_text():
    period, reason = infer_comparison_period({
        "period": "202412",
        "claim_text": "수출 증가율이 6.6%를 기록했다.",
    })
    assert period == ""
    assert reason == ""


def test_rate_from_monthly_flow_uses_previous_year_sum():
    rows = [
        {"PRD_DE": "202301", "DT": "40"},
        {"PRD_DE": "202302", "DT": "60"},
        {"PRD_DE": "202401", "DT": "50"},
        {"PRD_DE": "202402", "DT": "70"},
    ]
    row = {
        "indicator": "반도체 수출액",
        "mapping_type": "rate_from_level",
        "comparison_period": "2023",
    }
    actual, current, previous, reason = derive_actual(rows, "M", "2024", row)
    assert actual == 20
    assert current == "202401+202402"
    assert previous == "202301+202302"
    assert "증감률" in reason


def test_rate_change_accepts_kosis_index_level_item():
    row = {
        "indicator": "서비스업 생산지수",
        "semantic_type": "rate_change",
        "mapping_type": "rate_from_level",
        "unit": "%",
        "unit_dimension": "rate",
    }
    assert item_compatible("불변지수", "2020＝100", row)[0] is True


def test_rate_change_rejects_unknown_non_index_level_item():
    row = {
        "indicator": "서비스업 생산지수",
        "semantic_type": "rate_change",
        "mapping_type": "rate_from_level",
        "unit": "%",
        "unit_dimension": "rate",
    }
    assert item_compatible("기타 항목", "-", row)[0] is False


def test_stock_measurement_uses_latest_not_sum():
    rows = [
        {"PRD_DE": "202401", "DT": "100"},
        {"PRD_DE": "202402", "DT": "110"},
    ]
    row = {"indicator": "정비사 수", "mapping_type": "direct"}
    actual, period, _, reason = derive_actual(rows, "M", "2024", row)
    assert actual == 110
    assert period == "202402"
    assert "latest" in reason


def test_non_ready_candidate_stops_before_api_call():
    row = {
        "candidate_rank": "1",
        "candidate_status": "REVIEW",
        "candidate_status_code": "AMBIGUOUS_TABLE",
        "candidate_status_reason": "1·2위 점수 차이 부족",
        "value": "10",
    }
    out = verify_row(row, {}, 0)
    assert out["verdict"] == "판단불가"
    assert out["verdict_code"] == "FINAL_STATUS_NOT_READY"
    assert out["verdict_stage"] == "final_status"
    assert out["verification_skipped"] == "Y"


class KosisVerifierAdditionalSafetyTests(unittest.TestCase):
    def test_extreme_error_flags_likely_mismapping(self):
        from kosis_verify_claim_values import extreme_error
        self.assertTrue(extreme_error(10, 10000))

    def test_rate_judge_supports_percentage_point_mode(self):
        from kosis_verify_claim_values import judge
        verdict, reason = judge(0.4, -0.59, 0.5, 1.5, rate_point_mode=True)
        self.assertEqual(verdict, '판정보류')
        self.assertIn('%p', reason)


class FinalStatusVerificationGateTests(unittest.TestCase):
    def test_mapping_ready_but_final_review_skips_value_verification(self):
        row = {
            "mapping_status": "READY",
            "final_status": "REVIEW",
            "review_reason": "candidate margin 부족",
            "value": "10",
        }
        out = verify_row(row, {}, 0)
        self.assertEqual(out["verdict"], "판단불가")
        self.assertEqual(out["verdict_code"], "FINAL_STATUS_NOT_READY")
        self.assertEqual(out["verification_skipped"], "Y")
        self.assertIn("candidate margin", out["verification_skip_reason"])

    def test_mapping_ready_but_final_not_kosis_skips_value_verification(self):
        row = {
            "mapping_status": "READY",
            "final_status": "NOT_KOSIS",
            "not_kosis_reason": "claim_domain_scope=해외통계",
            "value": "10",
        }
        out = verify_row(row, {}, 0)
        self.assertEqual(out["verdict"], "검증대상아님")
        self.assertEqual(out["verdict_code"], "NOT_KOSIS")
        self.assertEqual(out["verification_skipped"], "Y")
        self.assertIn("해외통계", out["verification_skip_reason"])

    def test_final_ready_is_the_execution_gate_even_if_mapping_status_differs(self):
        row = {
            "claim_id": "C1",
            "claim_measurement_id": "M1",
            "mapping_status": "REVIEW",
            "final_status": "READY",
            "value": "100",
            "unit": "달러",
            "period": "2024",
            "prd_se": "Y",
            "indicator": "수출액",
            "mapping_type": "direct",
            "org_id": "101",
            "tbl_id": "DT_TEST",
        }
        meta = [{"OBJ_ID": "ITEM", "ITM_ID": "T1", "ITM_NM": "수출액", "UNIT_NM": "달러"}]
        data = [{"PRD_DE": "2024", "DT": "100", "UNIT_NM": "달러", "ITM_ID": "T1"}]
        with patch("kosis_verify_claim_values.get_meta", return_value=meta), patch(
            "kosis_verify_claim_values.get_stat_data", return_value=data
        ):
            out = verify_row(row, {}, 0)
        self.assertEqual(out["verdict"], "일치")
        self.assertEqual(out["verification_skipped"], "N")

    def test_legacy_csv_without_final_status_uses_mapping_status_fallback(self):
        rows, fields, warnings = prepare_rows_for_verification(
            [{"mapping_status": "READY", "value": "10"}],
            ["mapping_status", "value"],
        )
        self.assertEqual(rows[0]["legacy_status_fallback"], "Y")
        self.assertIn("legacy_status_fallback", fields)
        self.assertTrue(any("final_status" in warning for warning in warnings))
        out = verify_row(rows[0], {}, 0)
        self.assertEqual(out["legacy_status_fallback"], "Y")

    def test_validated_columns_are_preserved_when_skipped(self):
        row = {
            "mapping_status": "READY",
            "final_status": "REVIEW",
            "review_reason": "좌표 검토 필요",
            "api_coordinate_exact_match": "N",
            "value": "10",
        }
        out = verify_row(row, {}, 0)
        self.assertEqual(out["api_coordinate_exact_match"], "N")
        self.assertEqual(out["final_status"], "REVIEW")

    def test_small_validated_csv_flow_keeps_skip_rows_without_external_api(self):
        fields = [
            "claim_measurement_id",
            "mapping_status",
            "final_status",
            "review_reason",
            "not_kosis_reason",
            "api_coordinate_exact_match",
            "value",
        ]
        fixture_rows = [
            {
                "claim_measurement_id": "M_REVIEW",
                "mapping_status": "READY",
                "final_status": "REVIEW",
                "review_reason": "좌표 exact match 실패",
                "not_kosis_reason": "",
                "api_coordinate_exact_match": "N",
                "value": "10",
            },
            {
                "claim_measurement_id": "M_NOT_KOSIS",
                "mapping_status": "READY",
                "final_status": "NOT_KOSIS",
                "review_reason": "",
                "not_kosis_reason": "정책값",
                "api_coordinate_exact_match": "",
                "value": "10",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "validated_fixture.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(fixture_rows)
            rows, loaded_fields = read_csv(path)
            prepared, _, warnings = prepare_rows_for_verification(rows, loaded_fields)
        self.assertEqual(warnings, [])
        out_rows = [verify_row(row, {}, 0) for row in prepared]
        self.assertEqual(out_rows[0]["verdict"], "판단불가")
        self.assertEqual(out_rows[0]["verification_skipped"], "Y")
        self.assertEqual(out_rows[1]["verdict"], "검증대상아님")
        self.assertEqual(out_rows[1]["verification_skipped"], "Y")
