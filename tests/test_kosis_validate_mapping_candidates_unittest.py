import unittest
import types
from unittest import mock

from kosis_api_test import KosisAPIResponseError, _raise_for_kosis_error, get_stat_data
from kosis_validate_mapping_candidates import (
    API_ERROR,
    API_LIMIT_REACHED,
    EMPTY_RESPONSE,
    INVALID_METADATA,
    INVALID_REQUEST,
    LOW_PRIORITY_CANDIDATE,
    NEEDS_CONFIRMATION,
    NOT_EVALUATED,
    READY,
    RESPONSE_CODE_MISMATCH,
    build_candidate_combinations,
    build_kosis_request,
    group_official_meta,
    is_low_priority_candidate,
    response_matches_request,
    resolve_measurement_level_ambiguity,
    validate_unit_and_period,
    _merge_seeded_candidates,
    _seeded_obj_candidates,
    validate_candidate_codes_against_meta,
    validate_mapping_candidates,
)


def meta_rows():
    rows = [
        {"OBJ_ID": "ITEM", "ITM_ID": "I1", "ITM_NM": "지표1"},
        {"OBJ_ID": "ITEM", "ITM_ID": "I2", "ITM_NM": "지표2"},
        {"OBJ_ID": "ITEM", "ITM_ID": "I3", "ITM_NM": "지표3"},
    ]
    for level in range(1, 9):
        rows.extend([
            {"OBJ_ID": f"A{level}", "OBJ_ID_SN": str(level), "OBJ_NM": f"축{level}",
             "ITM_ID": f"O{level}A", "ITM_NM": f"값{level}A"},
            {"OBJ_ID": f"A{level}", "OBJ_ID_SN": str(level), "OBJ_NM": f"축{level}",
             "ITM_ID": f"O{level}B", "ITM_NM": f"값{level}B"},
        ])
    return rows


def aggregate_meta():
    return [
        {"OBJ_ID": "ITEM", "ITM_ID": "I1", "ITM_NM": "지표1"},
        {"OBJ_ID": "REGION", "OBJ_ID_SN": "1", "OBJ_NM": "지역", "ITM_ID": "R_ALL", "ITM_NM": "전국"},
    ]


def obj_candidates(levels=8):
    return {
        level: [
            {"code": f"O{level}A", "name": f"값{level}A", "semantic_score": 0.7},
            {"code": f"O{level}B", "name": f"값{level}B", "semantic_score": 0.6},
        ]
        for level in range(1, levels + 1)
    }


def valid_rows(request, periods=("2023", "2024"), unit="명"):
    return [
        {
            "ITM_ID": request["itmId"],
            **{f"C{level}": request[f"objL{level}"] for level in range(1, 9) if f"objL{level}" in request},
            "PRD_DE": period,
            "UNIT_NM": unit,
            "DT": "1",
        }
        for period in periods
    ]


class KosisCandidateValidationTests(unittest.TestCase):
    def test_period_range_latest_n_and_exclusive_request_params(self):
        combo = build_candidate_combinations(["I1"], obj_candidates(), meta_rows())[0]
        ranged = build_kosis_request("ORG", "TBL", combo, periods=["2022", "2024"], new_est_prd_cnt=9)
        latest = build_kosis_request("ORG", "TBL", combo, new_est_prd_cnt=5)
        self.assertEqual((ranged["startPrdDe"], ranged["endPrdDe"]), ("2022", "2024"))
        self.assertNotIn("newEstPrdCnt", ranged)
        self.assertEqual(latest["newEstPrdCnt"], 5)
        self.assertNotIn("startPrdDe", latest)

    def test_get_stat_data_defaults_to_recent_three_without_period_range(self):
        captured = {}

        class Response:
            text = "[]"
            def raise_for_status(self):
                return None

        def fake_get(_url, params, timeout):
            captured.clear()
            captured.update(params)
            return Response()

        fake_requests = types.SimpleNamespace(get=fake_get)
        with mock.patch("kosis_api_test.API_KEY", "dummy"), mock.patch("kosis_api_test.requests", fake_requests):
            get_stat_data("ORG", "TBL", "O1", "I1")
            self.assertEqual(captured["newEstPrdCnt"], 3)
            get_stat_data("ORG", "TBL", "O1", "I1", startPrdDe="2020", endPrdDe="2024")
            self.assertNotIn("newEstPrdCnt", captured)

    def test_top_k_obj_k_max_combinations_and_l1_to_l8_are_preserved(self):
        combos = build_candidate_combinations(
            [{"code": f"I{i}", "semantic_score": 1.0 - i / 10} for i in range(1, 4)],
            obj_candidates(),
            meta_rows(),
            item_top_k=3,
            obj_top_k=2,
            max_combinations=20,
        )
        self.assertLessEqual(len(combos), 20)
        self.assertEqual({row["itm_id"] for row in combos}, {"I1", "I2", "I3"})
        self.assertTrue(all(row[f"objL{level}"] for row in combos for level in range(1, 9)))

    def test_invalid_item_obj_and_request_generation_failure_are_classified(self):
        grouped = group_official_meta(meta_rows())
        invalid_item = validate_candidate_codes_against_meta({"itm_id": "BAD", "objL1": "O1A"}, grouped)
        invalid_obj = validate_candidate_codes_against_meta({"itm_id": "I1", "objL1": "BAD"}, grouped)
        self.assertFalse(invalid_item["item_meta_valid"])
        self.assertFalse(invalid_obj["obj_meta_valid"])
        with self.assertRaisesRegex(ValueError, INVALID_METADATA):
            build_kosis_request("ORG", "TBL", {**invalid_obj, "itm_id": "I1", "objL1": "BAD"})
        with self.assertRaisesRegex(ValueError, INVALID_REQUEST):
            build_kosis_request("ORG", "TBL", {"itm_id": "I1", "metadata_valid": True})

    def test_http_200_error_empty_response_and_code_mismatch_are_distinct(self):
        with self.assertRaises(KosisAPIResponseError):
            _raise_for_kosis_error([{"err": "30", "errMsg": "bad params"}])
        kwargs = {
            "org_id": "ORG",
            "tbl_id": "TBL",
            "meta_rows": aggregate_meta(),
            "item_candidates": [{"code": "I1", "semantic_score": 0.9}],
            "obj_candidates": {},
            "expected_unit": "명",
            "required_periods": ["2024"],
            "claim": {"indicator": "지표1", "period": "2024"},
        }
        self.assertEqual(validate_mapping_candidates(**kwargs, data_fetcher=lambda _r: [])["mapping_status"], EMPTY_RESPONSE)
        self.assertEqual(validate_mapping_candidates(**kwargs, data_fetcher=lambda _r: (_ for _ in ()).throw(TimeoutError()))["mapping_status"], API_ERROR)
        mismatch = validate_mapping_candidates(
            **kwargs,
            data_fetcher=lambda _r: [{"ITM_ID": "OTHER", "C1": "R_ALL", "PRD_DE": "2024", "UNIT_NM": "명"}],
        )
        self.assertEqual(mismatch["mapping_status"], RESPONSE_CODE_MISMATCH)

    def test_response_item_and_c1_to_c8_mismatch_rejected(self):
        combo = build_candidate_combinations(["I1"], obj_candidates(), meta_rows())[0]
        request = build_kosis_request("ORG", "TBL", combo)
        self.assertFalse(response_matches_request(request, [{"ITM_ID": "BAD"}])["response_code_valid"])
        for level in range(1, 9):
            row = valid_rows(request, periods=("2024",))[0]
            row[f"C{level}"] = "BAD"
            self.assertFalse(response_matches_request(request, [row])["response_code_valid"])

    def test_api_limit_is_not_api_error_and_stops_further_calls(self):
        calls = []

        def fetcher(request):
            calls.append(dict(request))
            return valid_rows(request)

        result = validate_mapping_candidates(
            org_id="ORG",
            tbl_id="TBL",
            meta_rows=meta_rows(),
            item_candidates=[{"code": f"I{i}", "semantic_score": 1.0} for i in range(1, 4)],
            obj_candidates=obj_candidates(),
            data_fetcher=fetcher,
            expected_unit="명",
            required_periods=["2023", "2024"],
            claim={"indicator": "지표", "period": "2024"},
            max_combinations=20,
            api_call_limit=1,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["api_calls_used"], 1)
        self.assertGreater(result["not_evaluated_count"], 0)
        self.assertEqual(result["candidate_obj_combinations"][1]["candidate_status"], NOT_EVALUATED)
        self.assertEqual(result["candidate_obj_combinations"][1]["status_reason"], API_LIMIT_REACHED)
        self.assertNotEqual(result["mapping_status"], API_ERROR)
        self.assertNotEqual(result["mapping_status"], READY)
        self.assertFalse(result["evaluation_complete"])

    def test_partial_evaluation_close_margin_and_high_risk_are_conservative(self):
        base_kwargs = {
            "org_id": "ORG",
            "tbl_id": "TBL",
            "meta_rows": aggregate_meta(),
            "item_candidates": [{"code": "I1", "semantic_score": 0.9}],
            "obj_candidates": {},
            "data_fetcher": lambda request: valid_rows(request, periods=("2024",)),
            "expected_unit": "명",
            "required_periods": ["2024"],
        }
        high_risk = validate_mapping_candidates(**base_kwargs, claim={"period": "2024"})
        self.assertEqual(high_risk["mapping_status"], NEEDS_CONFIRMATION)
        self.assertIn("indicator", high_risk["high_risk_missing"])
        defaulted = validate_mapping_candidates(**base_kwargs, claim={"indicator": "지표1", "period": "2024"})
        self.assertIn("유일한 집계값 적용", defaulted["default_reason"])
        self.assertEqual(defaulted["default_risk"], "LOW")

    def test_axisless_or_malformed_meta_does_not_crash(self):
        result = validate_mapping_candidates(
            org_id="ORG",
            tbl_id="TBL",
            meta_rows=[{"OBJ_ID": "ITEM", "ITM_ID": "I1", "ITM_NM": "지표"}],
            item_candidates=[{"code": "I1", "semantic_score": 1.0}],
            obj_candidates={},
            data_fetcher=lambda _r: [],
            claim={"indicator": "지표", "period": "2024"},
        )
        self.assertIn(result["mapping_status"], {INVALID_REQUEST, EMPTY_RESPONSE})

    def test_seeded_selected_obj_uses_official_axis_order(self):
        grouped = group_official_meta([
            {"OBJ_ID": "ITEM", "ITM_ID": "I1", "ITM_NM": "지표"},
            {"OBJ_ID": "B_AXIS", "OBJ_ID_SN": "2", "OBJ_NM": "두번째축", "ITM_ID": "B01", "ITM_NM": "수출"},
            {"OBJ_ID": "A_AXIS", "OBJ_ID_SN": "1", "OBJ_NM": "첫번째축", "ITM_ID": "A01", "ITM_NM": "반도체"},
        ])
        row = {
            "selected_obj_l1_axis_id": "B_AXIS",
            "selected_obj_l1": "B01",
            "selected_obj_l1_name": "수출",
            "selected_obj_l2_axis_id": "A_AXIS",
            "selected_obj_l2": "A01",
            "selected_obj_l2_name": "반도체",
        }
        seeded = _seeded_obj_candidates(row, grouped)
        self.assertEqual(seeded[2][0]["code"], "B01")
        self.assertEqual(seeded[1][0]["code"], "A01")

    def test_seeded_candidates_are_hints_not_forced_semantic_winners(self):
        merged = _merge_seeded_candidates(
            [{"code": "I_TOTAL", "name": "취업자", "semantic_score": 0.8}],
            [{"code": "I_RATE", "name": "고용률", "semantic_score": 0.0}],
        )
        self.assertEqual(merged[0]["code"], "I_TOTAL")
        self.assertEqual(merged[1]["code"], "I_RATE")
        self.assertEqual(merged[1]["semantic_score"], 0.0)
        self.assertTrue(merged[1]["seeded_hint"])

    def test_unit_family_accepts_common_count_and_currency_variants(self):
        self.assertTrue(validate_unit_and_period([{"UNIT_NM": "업체"}], expected_unit="개사")["unit_valid"])
        self.assertTrue(validate_unit_and_period([{"UNIT_NM": "백만달러"}], expected_unit="달러")["unit_valid"])
        self.assertTrue(validate_unit_and_period([{"UNIT_NM": "건"}], expected_unit="개")["unit_valid"])
        self.assertFalse(validate_unit_and_period([{"UNIT_NM": "%p"}], expected_unit="%")["unit_valid"])

    def test_decisive_rank_one_survives_multiple_ready_alternatives(self):
        rows = [
            {"claim_measurement_id": "m1", "mapping_status": READY, "mapping_reason": "validated candidate",
             "candidate_rank": "1", "candidate_status": READY, "candidate_score": "400",
             "candidate_runner_up_score": "100"},
            {"claim_measurement_id": "m1", "mapping_status": READY, "mapping_reason": "validated candidate",
             "candidate_rank": "2", "candidate_status": "ALTERNATE", "candidate_score": "100"},
        ]
        resolve_measurement_level_ambiguity(rows)
        self.assertEqual(rows[0]["mapping_status"], READY)
        self.assertEqual(rows[1]["mapping_status"], NEEDS_CONFIRMATION)

    def test_close_rank_one_multiple_ready_goes_to_confirmation(self):
        rows = [
            {"claim_measurement_id": "m1", "mapping_status": READY, "mapping_reason": "validated candidate",
             "candidate_rank": "1", "candidate_status": READY, "candidate_score": "100",
             "candidate_runner_up_score": "95"},
            {"claim_measurement_id": "m1", "mapping_status": READY, "mapping_reason": "validated candidate",
             "candidate_rank": "2", "candidate_status": "ALTERNATE", "candidate_score": "95"},
        ]
        resolve_measurement_level_ambiguity(rows)
        self.assertEqual(rows[0]["mapping_status"], NEEDS_CONFIRMATION)
        self.assertEqual(rows[1]["mapping_status"], NEEDS_CONFIRMATION)

    def test_non_decisive_single_ready_is_downgraded(self):
        rows = [
            {"claim_measurement_id": "m1", "mapping_status": READY, "mapping_reason": "validated candidate",
             "candidate_rank": "5", "candidate_status": "ALTERNATE", "candidate_score": "50"},
            {"claim_measurement_id": "m2", "mapping_status": READY, "mapping_reason": "validated candidate",
             "candidate_rank": "1", "candidate_status": "REVIEW", "candidate_score": "100",
             "candidate_runner_up_score": "10"},
        ]
        resolve_measurement_level_ambiguity(rows)
        self.assertEqual(rows[0]["mapping_status"], NEEDS_CONFIRMATION)
        self.assertEqual(rows[1]["mapping_status"], NEEDS_CONFIRMATION)

    def test_low_priority_candidate_policy(self):
        self.assertTrue(is_low_priority_candidate({
            "candidate_rank": "3",
            "candidate_status": "ALTERNATE",
        }))
        self.assertFalse(is_low_priority_candidate({
            "candidate_rank": "2",
            "candidate_status": "ALTERNATE",
        }))
        self.assertFalse(is_low_priority_candidate({
            "candidate_rank": "5",
            "candidate_status": "REVIEW",
        }))


if __name__ == "__main__":
    unittest.main()
