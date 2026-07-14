import unittest

import build_kosis_holdout2_evaluation as evaluation


def base_row(claim_id, domain="물가"):
    return {
        "claim_id": claim_id,
        "holdout_domain": domain,
        "auto_decision": "보류",
        "auto_api_success": "N/A",
        "auto_org_id": "",
        "auto_tbl_id": "",
        "auto_obj_l1": "",
        "auto_obj_l2": "",
        "auto_itm_id": "",
        "auto_prd_se": "",
        "auto_target_number": "",
        "auto_target_period": "",
        "auto_prev_period": "",
        "auto_mode": "",
        "auto_verdict": "",
        "gold_verifiable": "N",
        "gold_exclusion_reason": "KOSIS 미제공",
        "gold_org_id": "",
        "gold_tbl_id": "",
        "gold_obj_l1": "",
        "gold_obj_l2": "",
        "gold_itm_id": "",
        "gold_prd_se": "",
        "gold_target_number": "",
        "gold_target_period": "",
        "gold_prev_period": "",
        "gold_mode": "",
        "gold_verdict": "",
        "gold_evidence": "수동 확인 근거",
        "gold_reviewer_note": "수동확정_검증불가",
    }


def make_verifiable(row):
    row.update({
        "gold_verifiable": "Y",
        "gold_exclusion_reason": "",
        "gold_org_id": "101",
        "gold_tbl_id": "DT_TEST",
        "gold_obj_l1": "00",
        "gold_obj_l2": "06",
        "gold_itm_id": "T1",
        "gold_prd_se": "M",
        "gold_target_number": "1.7",
        "gold_target_period": "202501",
        "gold_prev_period": "202401",
        "gold_mode": "ABS_TO_ABS",
        "gold_verdict": "일치",
        "gold_reviewer_note": "수동확정_검증가능_일치",
    })
    return row


class Holdout2EvaluationTest(unittest.TestCase):
    def test_exact_mapping_is_counted_as_full_match(self):
        row = make_verifiable(base_row("C1"))
        row.update({
            "auto_decision": "검증가능",
            "auto_api_success": "Y",
            "auto_org_id": "101",
            "auto_tbl_id": "DT_TEST",
            "auto_obj_l1": "00",
            "auto_obj_l2": "06",
            "auto_itm_id": "T1",
            "auto_prd_se": "M",
            "auto_target_number": "1.70",
            "auto_target_period": "202501",
            "auto_prev_period": "202401",
            "auto_mode": "ABS_TO_ABS",
            "auto_verdict": "일치",
        })

        result = evaluation.evaluate_rows([row])[0]

        self.assertEqual(result["eligibility_correct"], "Y")
        self.assertEqual(result["full_mapping_correct"], "Y")
        self.assertEqual(result["verdict_correct"], "Y")
        self.assertEqual(result["error_types"], "")

    def test_hold_on_verifiable_claim_is_a_strict_error(self):
        result = evaluation.evaluate_rows([make_verifiable(base_row("C2"))])[0]

        self.assertEqual(result["eligibility_correct"], "N")
        self.assertEqual(result["item_period_correct"], "N")
        self.assertIn("통계표", result["error_types"])
        self.assertIn("코드북", result["error_cause"])

    def test_mapping_an_unverifiable_claim_is_oververification(self):
        row = base_row("C3")
        row.update({"auto_decision": "검증가능", "auto_api_success": "Y"})

        result = evaluation.evaluate_rows([row])[0]

        self.assertEqual(result["eligibility_correct"], "N")
        self.assertEqual(result["full_mapping_correct"], "N/A")
        self.assertIn("과매핑", result["error_cause"])

    def test_validation_rejects_missing_gold_mapping(self):
        rows = []
        for domain in evaluation.DOMAINS:
            for number in range(20):
                rows.append(base_row(f"{domain}-{number}", domain))
        make_verifiable(rows[0])
        rows[0]["gold_tbl_id"] = ""

        with self.assertRaisesRegex(ValueError, "gold_tbl_id"):
            evaluation.validate_rows(rows)


if __name__ == "__main__":
    unittest.main()
