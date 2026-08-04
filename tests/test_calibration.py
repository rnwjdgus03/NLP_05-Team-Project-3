"""라벨링 교정 — 문제지 누출 방지와 채점 (2026-08-02).

실버(값 재현)로 만드는 골드는 12건에서 멈췄다. 원리상 그렇다 —
실버는 기사 숫자가 맞는 건만 라벨하는데, 숫자가 틀렸는지 밝히는 게 목적이다.
남은 건은 값과 무관하게 좌표를 판단해야 하고, 그 판단을 믿을 근거가 먼저 필요하다.
"""
from export_calibration_packet import LEAKY, coordinate_key, describe
from score_calibration import matches, option_map, parse_responses


# --------------------------------------------------------------------------
# 문제지 — 정답이 새면 안 된다
# --------------------------------------------------------------------------

def test_description_has_metadata_only():
    """실제 조회값이 보이면 답이 보인다."""
    row = {"tbl_id": "T1", "tbl_name": "품목별 수출액",
           "selected_itm_name": "수출액", "selected_itm_unit": "천달러",
           "selected_obj_l1_name": "총계", "selected_obj_l1_axis_name": "품목별",
           "kosis_actual_value": "683800000", "verdict": "일치"}
    text = describe(row)
    assert "683800000" not in text and "일치" not in text
    assert "수출액" in text and "총계" in text


def test_missing_unit_is_shown_as_unknown():
    """단위 미상은 숨기지 말아야 한다 — 판단에 필요한 정보다."""
    assert "단위 미상" in describe({"tbl_id": "T", "selected_itm_name": "수출액"})


def test_leaky_column_list_covers_value_and_rank():
    for name in ("kosis_actual_value", "verdict", "candidate_rank", "mapping_status"):
        assert name in LEAKY


def test_coordinate_key_is_the_three_axes():
    row = {"tbl_id": "T", "selected_itm_id": "I", "selected_obj_l1": "O"}
    assert coordinate_key(row) == ("T", "I", "O")


# --------------------------------------------------------------------------
# 답안 파싱 — 자유 형식을 받는다
# --------------------------------------------------------------------------

def test_simple_answers():
    assert parse_responses("1=A\n2=C") == {1: "A", 2: "C"}


def test_korean_prefix_and_spaces():
    assert parse_responses("문제 3 = B") == {3: "B"}


def test_abstain_and_none_are_kept_distinct():
    got = parse_responses("1=없음\n2=모름")
    assert got == {1: "없음", 2: "모름"}


def test_lowercase_is_normalised():
    assert parse_responses("1=a") == {1: "A"}


def test_prose_around_answers_is_ignored():
    assert parse_responses("고민했지만 1=A 로 하겠다. 2=B 이유는...") == {1: "A", 2: "B"}


# --------------------------------------------------------------------------
# 채점
# --------------------------------------------------------------------------

def test_option_map_parses_coordinates():
    row = {"options": "A=T1/I1/O1 | B=T2/I2/O2"}
    assert option_map(row)["B"] == ("T2", "I2", "O2")


def test_option_without_obj_is_padded():
    assert option_map({"options": "A=T1/I1"})["A"] == ("T1", "I1", "")


def test_exact_match_counts():
    assert matches(("T", "I", "O"), ("T", "I", "O"))


def test_multi_answer_gold_accepts_either():
    """골드는 파이프로 복수 정답을 담는다(표가 중복 수록되는 경우)."""
    assert matches(("T2", "I", "O"), ("T1|T2", "I", "O"))


def test_empty_gold_level_is_not_checked():
    """골드에 분류축이 없으면 그 축은 채점하지 않는다."""
    assert matches(("T", "I", "무엇이든"), ("T", "I", ""))


def test_wrong_table_fails():
    assert not matches(("T9", "I", "O"), ("T", "I", "O"))
