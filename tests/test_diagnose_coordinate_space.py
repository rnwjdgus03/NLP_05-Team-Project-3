"""좌표 공간 진단 — '집계가 있는데 놓쳤나' vs '애초에 없나' (2026-08-02).

이 분류가 처방을 가른다. 전자는 순위 문제, 후자는 표 선택 또는 상류 추출 문제다.
"""
from diagnose_coordinate_space import ALL_AGGREGATE, classify, is_item_row, load_axis_index


def _meta(tbl, axis_id, code, name, parent="", is_item="N", axis_name="분류"):
    return {"tbl_id": tbl, "axis_id": axis_id, "axis_name": axis_name,
            "code_id": code, "code_name": name, "parent_code_id": parent,
            "is_item": is_item}


def _cand(tbl, axis_id, name, axis_name="분류"):
    return {"tbl_id": tbl, "selected_obj_l1_axis_id": axis_id,
            "selected_obj_l1_name": name, "selected_obj_l1_axis_name": axis_name}


# --------------------------------------------------------------------------
# 항목행 제외
# --------------------------------------------------------------------------

def test_item_rows_are_recognised():
    for flag in ("Y", "y", "TRUE", "1"):
        assert is_item_row({"is_item": flag}) is True


def test_obj_rows_are_not_items():
    for flag in ("N", "", "false"):
        assert is_item_row({"is_item": flag}) is False


def test_item_rows_do_not_enter_the_axis_index():
    """항목(ITM)은 분류축이 아니다. 섞이면 집계 유무 판정이 오염된다."""
    index = load_axis_index([_meta("T", "A", "I1", "계", is_item="Y")])
    assert index[("T", "A")]["aggregate"] == set()


# --------------------------------------------------------------------------
# 집계 코드 존재 여부
# --------------------------------------------------------------------------

def test_axis_with_total_is_aggregate_available():
    index = load_axis_index([_meta("T", "A", "1", "계"),
                             _meta("T", "A", "2", "제조업")])
    cause, _ = classify(_cand("T", "A", "제조업"), index)
    assert cause == "AGGREGATE_AVAILABLE"


def test_axis_without_total_is_flagged():
    index = load_axis_index([_meta("T", "A", "1", "농림어업"),
                             _meta("T", "A", "2", "제조업")])
    cause, _ = classify(_cand("T", "A", "제조업"), index)
    assert cause == "NO_AGGREGATE_IN_AXIS"


def test_unknown_axis_is_its_own_cause():
    """메타에 없는 축을 '집계 없음'으로 세면 표 선택 문제로 오진한다."""
    cause, _ = classify(_cand("T", "ZZ", "제조업"), load_axis_index([]))
    assert cause == "AXIS_NOT_IN_META"


def test_reason_names_the_found_aggregate():
    index = load_axis_index([_meta("T", "A", "1", "전체"),
                             _meta("T", "A", "2", "제조업")])
    _, why = classify(_cand("T", "A", "제조업"), index)
    assert "전체" in why


def test_axes_are_kept_separate_within_one_table():
    """한 표의 다른 축에 있는 집계를 빌려오면 안 된다."""
    index = load_axis_index([_meta("T", "A", "1", "계"),
                             _meta("T", "B", "1", "단독주택")])
    cause, _ = classify(_cand("T", "B", "단독주택"), index)
    assert cause == "NO_AGGREGATE_IN_AXIS"


# --------------------------------------------------------------------------
# 계층 부모 노드
# --------------------------------------------------------------------------

def test_parent_node_is_detected():
    index = load_axis_index([_meta("T", "A", "A1", "매출액별"),
                             _meta("T", "A", "A11", "50억 미만", parent="A1")])
    assert "A1" in index[("T", "A")]["parents"]


def test_leaf_is_not_a_parent():
    index = load_axis_index([_meta("T", "A", "A11", "50억 미만", parent="A1")])
    assert "A11" not in index[("T", "A")]["parents"]


# --------------------------------------------------------------------------
# 집계 이름 목록 — 실패 사례에서 확인된 것만 더했다
# --------------------------------------------------------------------------

def test_total_index_is_included_here():
    """골드 정답이 T10(총지수)인데 집계로 인정 못 받아 밀린 실측 사례가 있다."""
    from kosis_validate_mapping_candidates import _normalize
    assert _normalize("총지수") in ALL_AGGREGATE


def test_known_gap_parenthesised_total_still_missed():
    """'원화대출금(계)' 는 축의 유일한 루트이자 집계인데 완전일치로는 안 잡힌다.

    실측에서 '집계 없음'으로 잘못 분류된 표다.
    접미사 매칭으로 넓힐지는 별도 측정 후 결정한다 — 지금은 구멍만 기록.
    """
    from kosis_validate_mapping_candidates import _normalize
    assert _normalize("원화대출금(계)") not in ALL_AGGREGATE
