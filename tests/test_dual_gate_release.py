"""이중 게이트 해제 (2026-07-31).

validate 는 공식 메타 코드 + 실제 API 응답 + 단위·기간 정합을 **이미 독립 검증**한다.
그 뒤에 상류 표 후보가 rank-1 READY 가 아니라는 이유로 다시 강등하면
같은 불확실성을 두 번 요구하는 셈이다.

해제하되 안전 조건은 `downstream_validated_rank1` 이 그대로 지킨다.
여기서는 **무엇이 여전히 막혀야 하는지**를 집중적으로 고정한다.
"""
from kosis_validate_mapping_candidates import downstream_validated_rank1


def _row(**kw):
    base = {
        "candidate_rank": "1",
        "candidate_status": "REVIEW",          # 상류가 확신 못 한 상태
        "candidate_score": "600",
        "candidate_runner_up_score": "500",
        "indicator": "반도체 수출액",
        "measurement_item": "반도체",
    }
    base.update(kw)
    return base


def _result(**kw):
    base = {
        "item_meta_valid": True, "obj_meta_valid": True,
        "response_code_valid": True, "unit_valid": True, "period_valid": True,
        "selected_itm_name": "반도체", "selected_obj_l1_name": "반도체",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 해제되는 경우 — 하류 실측이 전부 통과한 rank-1
# --------------------------------------------------------------------------

def test_downstream_validated_rank1_is_now_decisive():
    assert downstream_validated_rank1(_row(), _result()) is True


def test_missing_score_info_still_accepted_on_measurements_alone():
    row = _row(candidate_score="", candidate_runner_up_score="")
    assert downstream_validated_rank1(row, _result()) is True


# --------------------------------------------------------------------------
# 여전히 막혀야 하는 경우 — 해제가 '전부 통과'가 되면 안 된다
# --------------------------------------------------------------------------

def test_rank_two_is_not_decisive():
    assert downstream_validated_rank1(_row(candidate_rank="2"), _result()) is False


def test_upstream_reject_is_respected():
    """REJECT 는 '의미상 맞는 ITEM 없음' 같은 의미 실패라 하류가 뒤집으면 안 된다."""
    assert downstream_validated_rank1(_row(candidate_status="REJECT"), _result()) is False


def test_failed_api_response_blocks():
    assert downstream_validated_rank1(_row(), _result(response_code_valid=False)) is False


def test_invalid_unit_blocks():
    assert downstream_validated_rank1(_row(), _result(unit_valid=False)) is False


def test_invalid_period_blocks():
    assert downstream_validated_rank1(_row(), _result(period_valid=False)) is False


def test_invalid_metadata_blocks():
    assert downstream_validated_rank1(_row(), _result(item_meta_valid=False)) is False


def test_tie_between_top_two_tables_stays_manual():
    """1·2위 점수차가 작으면 어느 표인지 사람이 봐야 한다."""
    row = _row(candidate_score="600", candidate_runner_up_score="598")
    assert downstream_validated_rank1(row, _result()) is False


def test_semantic_guard_blocks_unrelated_item():
    """실측 오매핑: 농수산식품 수출 → '건조기(농산물용의 것)'."""
    row = _row(indicator="농수산식품 수출", measurement_item="농수산식품")
    result = _result(selected_itm_name="건조기(농산물용의 것)",
                     selected_obj_l1_name="건조기(농산물용의 것)")
    assert downstream_validated_rank1(row, result) is False


def test_semantic_guard_blocks_semiconductor_mismatch():
    row = _row(indicator="반도체 수출", measurement_item="반도체")
    result = _result(selected_itm_name="인산에스테르 및 그 염",
                     selected_obj_l1_name="인산에스테르 및 그 염")
    assert downstream_validated_rank1(row, result) is False


# --------------------------------------------------------------------------
# CLI 계약
# --------------------------------------------------------------------------

def test_both_flags_exist_for_compatibility_and_rollback():
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "kosis_validate_mapping_candidates.py", "--help"],
                         capture_output=True, text=True)
    # 기존 명령이 깨지지 않도록 옛 플래그를 남긴다
    assert "--trust-downstream-validation" in out.stdout
    # 옛 동작으로 되돌릴 수 있어야 회귀 비교가 가능하다
    assert "--require-upstream-ready" in out.stdout
