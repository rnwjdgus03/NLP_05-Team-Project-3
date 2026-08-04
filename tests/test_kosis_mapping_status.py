import unittest

from kosis_mapping_status import READY, REVIEW, NOT_KOSIS, decide_final_status


class MappingStatusTests(unittest.TestCase):
    def test_ready_requires_all_gates(self):
        row = {
            "mapping_status": "READY",
            "metadata_combination_valid": "Y",
            "item_meta_valid": "Y",
            "obj_meta_valid": "Y",
            "api_request_success": "Y",
            "api_coordinate_exact_match": "Y",
            "unit_compatible": "Y",
            "period_compatible": "Y",
            "semantic_ready_gate_passed": "Y",
            "api_value_exists": "Y",
        }
        self.assertEqual(decide_final_status(row)["final_status"], READY)

    def test_api_response_without_coordinate_match_is_review(self):
        row = {
            "mapping_status": "READY",
            "metadata_combination_valid": "Y",
            "item_meta_valid": "Y",
            "obj_meta_valid": "Y",
            "api_request_success": "Y",
            "api_coordinate_exact_match": "N",
            "unit_compatible": "Y",
            "period_compatible": "Y",
            "semantic_ready_gate_passed": "Y",
            "api_value_exists": "Y",
        }
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_missing_official_meta_is_review(self):
        row = {"mapping_status": "READY", "metadata_combination_valid": "N"}
        self.assertEqual(decide_final_status(row)["final_status"], REVIEW)

    def test_api_request_failure_is_review(self):
        row = {
            "mapping_status": "READY",
            "metadata_combination_valid": "Y",
            "item_meta_valid": "Y",
            "obj_meta_valid": "Y",
            "api_request_success": "N",
            "api_coordinate_exact_match": "Y",
            "unit_compatible": "Y",
            "period_compatible": "Y",
            "semantic_ready_gate_passed": "Y",
            "api_value_exists": "Y",
        }
        out = decide_final_status(row)
        self.assertEqual(out["final_status"], REVIEW)
        self.assertIn("api_request_success", out["review_reason"])

    def test_ready_gate_rejects_each_missing_required_evidence(self):
        base = {
            "mapping_status": "READY",
            "metadata_combination_valid": "Y",
            "item_meta_valid": "Y",
            "obj_meta_valid": "Y",
            "api_request_success": "Y",
            "api_coordinate_exact_match": "Y",
            "unit_compatible": "Y",
            "period_compatible": "Y",
            "semantic_ready_gate_passed": "Y",
            "api_value_exists": "Y",
        }
        for gate in [
            "metadata_combination_valid",
            "api_coordinate_exact_match",
            "unit_compatible",
            "period_compatible",
            "semantic_ready_gate_passed",
            "api_value_exists",
        ]:
            with self.subTest(gate=gate):
                row = dict(base)
                row[gate] = "N"
                out = decide_final_status(row)
                self.assertEqual(out["final_status"], REVIEW)
                self.assertIn(gate, out["review_reason"])

    def test_non_kosis_scopes(self):
        for scope in ("기업통계", "해외통계", "정책값"):
            self.assertEqual(decide_final_status({"claim_domain_scope": scope})["final_status"], NOT_KOSIS)


if __name__ == "__main__":
    unittest.main()
