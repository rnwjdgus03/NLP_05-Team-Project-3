"""claim 품목 가드를 **모든 확정 경로**에 적용한다 (2026-08-02).

실측 실패: '작년 한 해 전체 수출액이 6838억달러' 주장에 objL1=반도체 좌표가 붙은 채
READY 로 확정됐고, 시스템이 '불일치'라고 단언했다. 참인 기사에 거짓 딱지를 붙인 것이다.

원인: claim_item_matches_selection 이 downstream_validated_rank1(회수 경로)에만 있었다.
상류가 결정적이면(rank==1 and candidate_status==READY) 그 검사를 건너뛰고 확정된다.

오늘 세 번째로 같은 모양의 결함이다.
  1차 — 가드가 확정 게이트에만 있고 검색 순위에 없었다
  2차 — verify 의 진단 통로가 CLI 필터와 verify_row 두 겹에 막혀 있었다
  3차 — 이 건. 가드가 회수 경로에만 있고 확정 경로에 없었다
같은 코드베이스에서 '한 경로에만 있는 가드'가 반복된다.
"""
from kosis_validate_mapping_candidates import apply_semantic_ready_gate, semantic_ready_gate

TOTAL_EXPORT_CLAIM = {
    "claim_text": "작년 한 해 전체 수출액이 6838억달러로 2023년에 비해 8.2% 증가했다.",
    "industry_or_item": "",          # 대상 미특정 → 좌표도 집계여야 한다
    "indicator": "총수출액",
    "candidate_rank": "1",
    "candidate_status": "READY",
}


def _result(obj_name, status="READY"):
    return {"mapping_status": status, "selected_obj_l1_name": obj_name,
            "selected_itm_name": "수출액", "tbl_name": "수출 및 수입액",
            "mapping_reason": "validated candidate"}


# --------------------------------------------------------------------------
# 회귀 — 실측 실패를 그대로 재현
# --------------------------------------------------------------------------

def test_total_claim_with_a_specific_coordinate_is_blocked():
    """전체 수출액 주장 + objL1=반도체 → 확정되면 안 된다."""
    gate = semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("반도체"))
    assert gate["semantic_gate_valid"] is False
    assert "CLAIM_ITEM_MISMATCH" in gate["semantic_gate_details"]


def test_confirmation_is_demoted_not_just_flagged():
    """표시만 하고 READY 를 유지하면 여전히 '불일치'가 나간다."""
    out = apply_semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("반도체"))
    assert out["mapping_status"] == "NEEDS_CONFIRMATION"


def test_aggregate_coordinate_still_confirms():
    """정상 건까지 막으면 안 된다 — 같은 주장에 '계' 좌표는 통과해야 한다."""
    out = apply_semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("계"))
    assert out["mapping_status"] == "READY"


def test_named_item_matching_the_coordinate_confirms():
    """반도체 주장 + objL1=반도체 는 정상이다."""
    claim = {**TOTAL_EXPORT_CLAIM, "industry_or_item": "반도체",
             "claim_text": "반도체 수출액이 1419억달러로 역대 최대치를 기록했다."}
    out = apply_semantic_ready_gate(claim, _result("반도체"))
    assert out["mapping_status"] == "READY"


def test_named_item_with_an_unrelated_coordinate_is_blocked():
    claim = {**TOTAL_EXPORT_CLAIM, "industry_or_item": "석유화학",
             "claim_text": "석유화학 수출은 480억 달러였다."}
    out = apply_semantic_ready_gate(claim, _result("가공한 석면섬유"))
    assert out["mapping_status"] == "NEEDS_CONFIRMATION"


# --------------------------------------------------------------------------
# 경계
# --------------------------------------------------------------------------

def test_already_unconfirmed_rows_are_untouched():
    """READY/PROVISIONAL 이 아니면 상태를 바꾸지 않는다."""
    out = apply_semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("반도체", status="MAPPING_FAILED"))
    assert out["mapping_status"] == "MAPPING_FAILED"


def test_provisional_is_also_gated():
    out = apply_semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("반도체", status="PROVISIONAL"))
    assert out["mapping_status"] == "NEEDS_CONFIRMATION"


def test_reason_is_recorded_so_the_block_is_traceable():
    out = apply_semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("반도체"))
    assert out["mapping_reason"] == "CLAIM_ITEM_MISMATCH"


# --------------------------------------------------------------------------
# 문장에 없는 대상 — 실측 거짓 불일치의 진짜 원인
# --------------------------------------------------------------------------

TOTAL_EXPORT_SENTENCE = ("작년 한 해 전체 수출액이 6838억달러(약 1006조원)로 "
                         "2023년에 비해 8.2% 증가했다고 산업통상자원부와 관세청이 1일 밝혔다.")


def test_item_absent_from_the_sentence_blocks_confirmation():
    """상류 추출이 기사 전체 맥락에서 '반도체'를 이 문장에 붙였다.

    그 결과 '대상=반도체 · 좌표=반도체'로 가드를 정상 통과해 확정됐고,
    전체 수출액(6838억)을 반도체 수출액(1420억)과 비교해 '불일치'로 단언했다.
    """
    claim = {"claim_text": TOTAL_EXPORT_SENTENCE, "industry_or_item": "반도체",
             "candidate_rank": "1", "candidate_status": "READY"}
    out = apply_semantic_ready_gate(claim, _result("반도체"))
    assert out["mapping_status"] == "NEEDS_CONFIRMATION"
    assert "UNGROUNDED_CLAIM_ITEM" in out["semantic_gate_details"]


def test_item_present_in_the_sentence_still_confirms():
    """같은 기사의 정상 건까지 막으면 안 된다."""
    claim = {"claim_text": "품목별로는 최대 수출품목인 반도체가 43.9% 증가한 1419억 달러를 기록했다.",
             "industry_or_item": "반도체", "candidate_rank": "1", "candidate_status": "READY"}
    out = apply_semantic_ready_gate(claim, _result("반도체"))
    assert out["mapping_status"] == "READY"


def test_spacing_does_not_break_the_check():
    claim = {"claim_text": "석유 화학 수출은 480억 달러였다.", "industry_or_item": "석유화학",
             "candidate_rank": "1", "candidate_status": "READY"}
    out = apply_semantic_ready_gate(claim, _result("석유화학"))
    assert out["mapping_status"] == "READY"


def test_empty_item_is_not_flagged_as_ungrounded():
    """대상이 없는 주장은 이 규칙의 대상이 아니다(집계 규칙이 따로 본다)."""
    out = apply_semantic_ready_gate(TOTAL_EXPORT_CLAIM, _result("계"))
    assert "UNGROUNDED_CLAIM_ITEM" not in out.get("semantic_gate_details", "")


def test_gate_and_recovery_share_one_implementation():
    """가드가 두 벌이면 반드시 어긋난다. 오늘 그래서 세 번 틀렸다."""
    import inspect

    import kosis_validate_mapping_candidates as validate
    import recover_downstream_validated as recover
    assert "claim_item_matches_selection" in inspect.getsource(validate.semantic_ready_gate)
    assert "claim_item_matches_selection" in inspect.getsource(recover.item_semantics_ok)
