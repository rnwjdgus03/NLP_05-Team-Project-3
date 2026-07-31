import build_silver_coordinates as silver
from kosis_verify_claim_values import pin_item


def _cand(**kw):
    base = {"claim_measurement_id": "M1", "org_id": "101", "tbl_id": "T1",
            "selected_itm_id": "I1", "selected_obj_l1": "1", "candidate_rank": "1"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 좌표 고정 검증 (verify 가 ITEM 을 다시 고르면 좌표 비교가 성립하지 않는다)
# --------------------------------------------------------------------------

META = [{"ITM_ID": "I1", "ITM_NM": "수출액", "UNIT_NM": "천달러", "OBJ_ID": "ITEM"},
        {"ITM_ID": "I2", "ITM_NM": "수입액", "UNIT_NM": "천달러", "OBJ_ID": "ITEM"}]


def test_pin_item_uses_selected_itm_id_instead_of_rechoosing():
    item, reason = pin_item(META, {"selected_itm_id": "I2"})
    assert item["ITM_NM"] == "수입액" and "고정" in reason


def test_pin_item_reports_missing_code_instead_of_falling_back():
    item, reason = pin_item(META, {"selected_itm_id": "I9"})
    assert item is None and "메타에 없음" in reason


def test_pin_item_requires_selected_itm_id():
    item, reason = pin_item(META, {})
    assert item is None and "selected_itm_id 없음" in reason


# --------------------------------------------------------------------------
# 좌표 수집 / 중복 제거
# --------------------------------------------------------------------------

def test_same_coordinate_from_both_sides_is_probed_once():
    grouped = silver.collect_candidates(
        [("A", [_cand()]), ("C", [_cand(candidate_rank="3")])], {"M1"})
    assert len(grouped["M1"]) == 1
    (_key, (_row, labels)), = grouped["M1"].items()
    assert labels == {"A", "C"}


def test_different_obj_makes_a_different_coordinate():
    grouped = silver.collect_candidates(
        [("A", [_cand()]), ("C", [_cand(selected_obj_l1="2")])], {"M1"})
    assert len(grouped["M1"]) == 2


def test_measurements_outside_the_fixed_set_are_ignored():
    grouped = silver.collect_candidates([("A", [_cand(claim_measurement_id="M9")])], {"M1"})
    assert grouped == {} or "M9" not in grouped


# --------------------------------------------------------------------------
# tier 판정 — 실버는 '유일하게 재현될 때'만 채택한다
# --------------------------------------------------------------------------

def _result(key, verdict):
    return {"coordinate_key": key, "verdict": verdict}


def test_single_reproducing_coordinate_becomes_silver():
    tier, winners = silver.classify([_result("k1", "일치"), _result("k2", "불일치")])
    assert tier == "SILVER_UNIQUE" and len(winners) == 1


def test_two_reproducing_coordinates_are_not_adopted():
    """서로 다른 좌표가 같은 숫자를 내면 기계는 고를 수 없다 — 사람 몫."""
    tier, _ = silver.classify([_result("k1", "일치"), _result("k2", "일치")])
    assert tier == "SILVER_AMBIGUOUS"


def test_same_coordinate_matching_twice_is_still_unique():
    tier, _ = silver.classify([_result("k1", "일치"), _result("k1", "일치")])
    assert tier == "SILVER_UNIQUE"


def test_uncertainty_band_only_goes_to_human():
    tier, _ = silver.classify([_result("k1", "판정보류"), _result("k2", "불일치")])
    assert tier == "NEAR_MISS"


def test_no_reproducing_coordinate_yields_no_label():
    """기사 숫자가 틀린 경우가 여기로 온다 → 실버가 참인 주장에 편향되는 지점."""
    tier, winners = silver.classify([_result("k1", "불일치"), _result("k2", "판단불가")])
    assert tier == "NO_MATCH" and winners == []


# --------------------------------------------------------------------------
# probe 행 구성
# --------------------------------------------------------------------------

CLAIM = {"claim_measurement_id": "M1", "value": "6838", "unit": "억달러",
         "measurement_period": "2024", "measurement_prd_se": "Y",
         "semantic_type": "rate_change", "unit_dimension": "rate",
         "claim_text": "작년 수출액이 8.2% 증가했다"}


def test_probe_fills_period_and_bypasses_upstream_gates():
    probe = silver.build_probe_row(_cand(), CLAIM)
    assert probe["period"] == "2024" and probe["prd_se"] == "Y"
    # 좌표 자체를 시험하는 것이 목적이므로 상류 상태 게이트는 통과시킨다
    assert probe["mapping_status"] == "READY" and probe["candidate_rank"] == "1"


def test_probe_keeps_existing_mapping_type():
    probe = silver.build_probe_row(_cand(mapping_type="direct"), CLAIM)
    assert probe["mapping_type"] == "direct"


def test_probe_derives_mapping_type_when_missing():
    """C 경로는 mapping_type 이 비어 있다 — 좌표 단위에서 계산해야 한다."""
    probe = silver.build_probe_row(
        _cand(selected_itm_unit="천달러", selected_itm_name="수출액"), CLAIM)
    assert probe["mapping_type"] in {"direct", "rate_from_level", "difference_from_level"}


def test_probe_does_not_overwrite_candidate_own_fields():
    probe = silver.build_probe_row(_cand(period="202412", value="100"), CLAIM)
    assert probe["period"] == "202412" and probe["value"] == "100"
