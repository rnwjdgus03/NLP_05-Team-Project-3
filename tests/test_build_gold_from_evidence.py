"""기존 근거 → 골드 좌표 확정 (2026-08-01).

원칙: **새 판단을 하지 않는다.** 실버 값 재현과 검증기 판정이라는 이미 있는 근거를
한 파일로 모으기만 한다. 등급이 근거의 강도를 그대로 들고 다녀야 한다.
"""
import build_gold_from_evidence as gold
from evaluate_chroma_hybrid_mapping import gold_alternatives, recall_at_k


def _silver(mid, tier, tbl, itm="I1", obj="1", tried="12"):
    return {"claim_measurement_id": mid, "tier": tier, "silver_tbl_id": tbl,
            "silver_itm_id": itm, "silver_obj_l1": obj, "coordinates_tried": tried,
            "claim_text": "문장"}


def _verified(mid, code, tbl, itm="I1", obj="1"):
    return {"claim_measurement_id": mid, "verdict_code": code, "tbl_id": tbl,
            "selected_itm_id": itm, "selected_obj_l1": obj, "value_diff": "0.01",
            "claim_text": "문장"}


CLAIMS = {"M1": {"claim_measurement_id": "M1", "claim_text": "문장", "value": "100"}}
KEYS = {"M1", "M2", "M3", "M4"}


def _build(silver_rows, verified_rows, claims=None):
    found = gold.collect(silver_rows, verified_rows, KEYS)
    return {r["claim_measurement_id"]: r for r in gold.build_rows(found, claims or CLAIMS)}


# --------------------------------------------------------------------------
# 근거 등급
# --------------------------------------------------------------------------

def test_value_reproduced_is_the_strongest_grade():
    rows = _build([_silver("M1", "SILVER_UNIQUE", "T1")], [])
    assert rows["M1"]["gold_grade"] == "VALUE_REPRODUCED"
    assert rows["M1"]["gold_confirmed"] == "Y"


def test_verdict_match_is_confirmed():
    rows = _build([], [_verified("M1", "MATCH", "T1")])
    assert rows["M1"]["gold_grade"] == "VERDICT_MATCH"
    assert rows["M1"]["gold_confirmed"] == "Y"


def test_revision_risk_is_plausible_not_confirmed():
    """'좌표로 데이터가 나왔다' 는 값 확인이 아니다 — 확정으로 올리면 안 된다."""
    rows = _build([], [_verified("M1", "REVISION_VINTAGE_RISK", "T1")])
    assert rows["M1"]["gold_grade"] == "COORD_PLAUSIBLE"
    assert rows["M1"]["gold_confirmed"] == "N"


def test_stronger_evidence_wins_when_both_exist():
    rows = _build([_silver("M1", "SILVER_UNIQUE", "T_SILVER")],
                  [_verified("M1", "REVISION_VINTAGE_RISK", "T_WEAK")])
    assert rows["M1"]["gold_grade"] == "VALUE_REPRODUCED"
    assert rows["M1"]["gold_tbl_id"] == "T_SILVER"


def test_mismapping_verdicts_are_ignored():
    rows = _build([], [_verified("M1", "LIKELY_MISMAPPING", "T1")])
    assert rows == {}


# --------------------------------------------------------------------------
# 복수 정답 — 같은 통계가 여러 표에 수록된 경우
# --------------------------------------------------------------------------

def test_ambiguous_silver_keeps_both_answers():
    rows = _build([_silver("M1", "SILVER_AMBIGUOUS", "T_A"),
                   _silver("M1", "SILVER_AMBIGUOUS", "T_B")], [])
    assert set(rows["M1"]["gold_tbl_id"].split("|")) == {"T_A", "T_B"}
    assert rows["M1"]["alternate_count"] == 2
    assert rows["M1"]["gold_confirmed"] == "Y"


def test_weaker_evidence_does_not_pollute_alternates():
    """등급이 다르면 섞지 않는다 — 강한 근거만으로 정답을 만든다."""
    rows = _build([_silver("M1", "SILVER_UNIQUE", "T_STRONG")],
                  [_verified("M1", "REVISION_VINTAGE_RISK", "T_WEAK")])
    assert "T_WEAK" not in rows["M1"]["gold_tbl_id"]


def test_duplicate_coordinate_is_recorded_once():
    rows = _build([_silver("M1", "SILVER_UNIQUE", "T1")],
                  [_verified("M1", "MATCH", "T1")])
    assert rows["M1"]["gold_tbl_id"] == "T1"


# --------------------------------------------------------------------------
# 검수 제외 — 근거를 코드에 남긴다
# --------------------------------------------------------------------------

def test_review_exclusions_are_dropped_with_reason():
    mid = next(iter(gold.REVIEW_EXCLUSIONS))
    rows = _build([_silver(mid, "SILVER_UNIQUE", "T1")], [])
    assert mid not in rows
    assert gold.REVIEW_EXCLUSIONS[mid]


def test_measurements_outside_the_evaluation_set_are_ignored():
    rows = _build([_silver("M_OUTSIDE", "SILVER_UNIQUE", "T1")], [])
    assert rows == {}


def test_row_without_table_id_is_skipped():
    rows = _build([_silver("M1", "SILVER_UNIQUE", "")], [])
    assert rows == {}


# --------------------------------------------------------------------------
# 평가 쪽이 복수 정답을 인식하는가
# --------------------------------------------------------------------------

def test_gold_alternatives_splits_on_pipe():
    assert gold_alternatives("A|B| C ") == {"A", "B", "C"}
    assert gold_alternatives("") == set()


def test_recall_counts_any_alternate_as_hit():
    """정답을 하나로 강제하면 맞은 것을 틀렸다고 센다."""
    ranked = {"M1": [{"tbl_id": "T_B"}]}
    result = recall_at_k(ranked, {"M1": "T_A|T_B"}, "tbl_id", ks=(1,))
    assert result["recall@1"] == 1.0


def test_recall_still_misses_when_no_alternate_matches():
    ranked = {"M1": [{"tbl_id": "T_C"}]}
    result = recall_at_k(ranked, {"M1": "T_A|T_B"}, "tbl_id", ks=(1,))
    assert result["recall@1"] == 0.0


def test_single_answer_behaviour_is_unchanged():
    ranked = {"M1": [{"tbl_id": "T_A"}]}
    assert recall_at_k(ranked, {"M1": "T_A"}, "tbl_id", ks=(1,))["recall@1"] == 1.0
