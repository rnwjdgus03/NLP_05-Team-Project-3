"""OBJ 선택 진단 · 집계 우선 재정렬 시뮬레이션 (2026-08-01).

고치기 전에 이득을 먼저 잰다. 오늘 여섯 번 틀린 이유가 전부 '측정 없이 고친 것'이었다.
"""
from diagnose_obj_selection import (
    aggregate_first,
    blocking_axis_name,
    claim_names_a_target,
    evaluate_side,
    gold_values,
    scan_rank1_shape,
    unrecognised_obj_names,
)


def _cand(rank, obj, obj_name="", mid="M1"):
    return {"claim_measurement_id": mid, "candidate_rank": str(rank),
            "selected_obj_l1": obj, "selected_obj_l1_name": obj_name}


# --------------------------------------------------------------------------
# 주장이 세부 대상을 특정했는가
# --------------------------------------------------------------------------

def test_claim_with_item_names_a_target():
    assert claim_names_a_target({"measurement_item": "반도체"}) is True


def test_claim_without_item_does_not():
    assert claim_names_a_target({"measurement_item": ""}) is False


def test_aggregate_token_is_not_a_target():
    """'전체'·'총계' 는 대상 특정이 아니라 집계 표시다."""
    for token in ("전체", "총계", "합계", "-"):
        assert claim_names_a_target({"measurement_item": token}) is False


# --------------------------------------------------------------------------
# 복수 정답
# --------------------------------------------------------------------------

def test_gold_values_split_on_pipe():
    assert gold_values({"gold_obj_l1": "A|B"}) == {"A", "B"}
    assert gold_values({"gold_obj_l1": ""}) == set()


# --------------------------------------------------------------------------
# 집계 우선 재정렬 — 점수가 아니라 정렬 키로만 쓴다
# --------------------------------------------------------------------------

def test_aggregate_candidate_moves_to_front():
    rows = [_cand(1, "41", "자가주거비"), _cand(2, "T10", "총계")]
    assert aggregate_first(rows, prefer_aggregate=True)[0]["selected_obj_l1"] == "T10"


def test_original_order_kept_when_not_preferring():
    rows = [_cand(1, "41", "자가주거비"), _cand(2, "T10", "총계")]
    assert aggregate_first(rows, prefer_aggregate=False)[0]["selected_obj_l1"] == "41"


def test_known_gap_total_index_is_not_recognised_as_aggregate():
    """실측으로 드러난 구멍을 문서화한다.

    소비자물가지수의 집계 축 이름은 '총지수' 인데 AGGREGATE_OBJ_NAMES 에 없다.
    → 집계 우선 규칙이 이 표에서는 아예 작동하지 않는다.
    이름 목록을 넓히는 건 진단 결과(어떤 이름이 실제로 많이 나오는지)를 보고 결정한다.
    지금 추측으로 넓히면 오늘 여섯 번 틀린 방식을 반복하는 것이다.
    """
    rows = [_cand(1, "41", "자가주거비"), _cand(2, "T10", "총지수")]
    assert aggregate_first(rows, prefer_aggregate=True)[0]["selected_obj_l1"] == "41"


def test_rank_breaks_ties_within_the_same_group():
    rows = [_cand(3, "T30", "계"), _cand(1, "T10", "총계")]
    ordered = aggregate_first(rows, prefer_aggregate=True)
    assert [r["candidate_rank"] for r in ordered] == ["1", "3"]


def test_candidate_without_obj_counts_as_aggregate():
    """분류축이 없는 표를 세부분류로 오인해 뒤로 밀면 안 된다."""
    rows = [_cand(2, "", ""), _cand(1, "41", "자가주거비")]
    assert aggregate_first(rows, prefer_aggregate=True)[0]["candidate_rank"] == "2"


# --------------------------------------------------------------------------
# 집계 판정을 막은 축이 정확히 어디인가
# --------------------------------------------------------------------------

def test_fully_aggregate_selection_has_no_blocker():
    assert blocking_axis_name({"selected_obj_l1_name": "전체",
                               "selected_obj_l2_name": "계"}) is None


def test_blocker_is_reported_with_its_level():
    """L1 이 '전체' 여도 L2 가 세부면 집계가 아니다 — 범인은 L2 다.

    이걸 L1 이름으로 보고하면 '전체가 집계로 인정 안 된다'는 잘못된 결론이 나온다.
    실제 첫 실행에서 그렇게 잘못 보고했다.
    """
    blocker = blocking_axis_name({"selected_obj_l1_name": "전체",
                                  "selected_obj_l2_name": "1차금속 제조업"})
    assert blocker == (2, "1차금속 제조업")


def test_first_blocking_level_wins():
    blocker = blocking_axis_name({"selected_obj_l1_name": "건설",
                                  "selected_obj_l2_name": "단독주택"})
    assert blocker == (1, "건설")


def test_empty_axis_is_skipped_not_blamed():
    assert blocking_axis_name({"selected_obj_l1_name": "계",
                               "selected_obj_l2_name": ""}) is None


def test_prefix_match_is_not_enough():
    """'전산업생산지수' 는 '전산업' 으로 시작하지만 별개의 지표다 — 완전일치만 인정."""
    assert blocking_axis_name({"selected_obj_l1_name": "전산업생산지수"}) == (1, "전산업생산지수")


def test_scan_ignores_claims_that_name_a_target():
    by_mid = {"M1": [_cand(1, "9", "반도체")]}
    claims = {"M1": {"measurement_item": "반도체"}}
    assert unrecognised_obj_names(by_mid, claims) == []


def test_scan_labels_names_with_level():
    by_mid = {"M1": [_cand(1, "9", "건설")]}
    claims = {"M1": {"measurement_item": ""}}
    assert unrecognised_obj_names(by_mid, claims) == [("L1 건설", 1)]


# --------------------------------------------------------------------------
# rank-1 모양 집계
# --------------------------------------------------------------------------

def test_shape_scan_separates_claim_and_coordinate():
    by_mid = {"M1": [_cand(1, "41", "자가주거비")], "M2": [_cand(1, "T10", "총계", mid="M2")]}
    claims = {"M1": {"measurement_item": ""}, "M2": {"measurement_item": "반도체"}}
    shape = scan_rank1_shape(by_mid, claims)
    assert shape["주장:총계 / 좌표:세부"] == 1
    assert shape["주장:세부 / 좌표:집계"] == 1


# --------------------------------------------------------------------------
# 시뮬레이션 — 개선과 악화를 모두 센다
# --------------------------------------------------------------------------

CLAIMS_NO_ITEM = {"M1": {"measurement_item": "", "claim_text": "물가 상승률은 2%였다"}}
GOLD_TOTAL = {"M1": {"gold_obj_l1": "T10"}}


def test_improvement_is_counted():
    by_mid = {"M1": [_cand(1, "41", "자가주거비"), _cand(2, "T10", "총계")]}
    summary, changed = evaluate_side("A", by_mid, CLAIMS_NO_ITEM, GOLD_TOTAL)
    assert summary["obj@1_now"] == 0.0
    assert summary["obj@1_aggregate_first"] == 1.0
    assert summary["improved"] == 1 and summary["worsened"] == 0
    assert changed[0]["direction"] == "개선"


def test_regression_is_counted_too():
    """집계 우선이 정답(세부분류)을 밀어내는 경우도 반드시 세야 한다."""
    claims = {"M1": {"measurement_item": "", "claim_text": "문장"}}
    gold = {"M1": {"gold_obj_l1": "41"}}
    by_mid = {"M1": [_cand(1, "41", "자가주거비"), _cand(2, "T10", "총계")]}
    summary, changed = evaluate_side("A", by_mid, claims, gold)
    assert summary["worsened"] == 1
    assert changed[0]["direction"] == "악화"


def test_claim_naming_a_target_is_left_alone():
    """주장이 품목을 특정하면 집계 우선을 적용하지 않는다."""
    claims = {"M1": {"measurement_item": "반도체", "claim_text": "문장"}}
    gold = {"M1": {"gold_obj_l1": "41"}}
    by_mid = {"M1": [_cand(1, "41", "반도체"), _cand(2, "T10", "총계")]}
    summary, _ = evaluate_side("A", by_mid, claims, gold)
    assert summary["obj@1_now"] == summary["obj@1_aggregate_first"] == 1.0


def test_measurements_without_gold_are_excluded_from_denominator():
    by_mid = {"M1": [_cand(1, "T10", "총계")], "M2": [_cand(1, "9", "기타", mid="M2")]}
    summary, _ = evaluate_side("A", by_mid, CLAIMS_NO_ITEM, GOLD_TOTAL)
    assert summary["labeled"] == 1


def test_measurement_without_candidates_is_skipped():
    summary, _ = evaluate_side("A", {}, CLAIMS_NO_ITEM, GOLD_TOTAL)
    assert summary["labeled"] == 0 and summary["obj@1_now"] is None
