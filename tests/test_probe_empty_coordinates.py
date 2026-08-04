"""빈 응답 좌표 재조회 — 좌표를 손으로 재구성하지 않는다 (2026-08-02).

같은 검사를 손으로 두 번 짰다가 두 번 다 틀렸다.
  1차 — validate 출력의 selected_* 를 썼는데 실패한 행은 그 칸이 비어 있다.
        좌표 없이 조회해놓고 '데이터가 없다'고 결론 낼 뻔했다.
  2차 — 후보에서 좌표를 가져왔지만 objL1 만 넘기고 objL2 를 빠뜨렸다.
        KOSIS 가 err:20(세부항목 누락)을 돌려줬고 그걸 파이프라인 버그로 오해했다.

둘 다 '좌표를 손으로 재구성'하다 생긴 일이다. 이 테스트가 그 재발을 막는다.
"""
import inspect

import probe_empty_coordinates as probe
from probe_empty_coordinates import axes_used, combination_from


def test_all_eight_axes_are_carried():
    """축을 하나라도 빠뜨리면 KOSIS 가 err:20 을 준다 — 데이터 없음이 아니다."""
    row = {f"selected_obj_l{level}": f"C{level}" for level in range(1, 9)}
    row["selected_itm_id"] = "I1"
    combination = combination_from(row)
    for level in range(1, 9):
        assert combination[f"objL{level}"] == f"C{level}"


def test_second_axis_is_not_dropped():
    """2차 실패를 그대로 재현하는 회귀 테스트."""
    row = {"selected_itm_id": "T002", "selected_obj_l1": "A12", "selected_obj_l2": "B01"}
    assert combination_from(row)["objL2"] == "B01"


def test_empty_axes_are_omitted_not_sent_blank():
    row = {"selected_itm_id": "I", "selected_obj_l1": "A", "selected_obj_l2": ""}
    assert "objL2" not in combination_from(row)


def test_item_is_carried():
    assert combination_from({"selected_itm_id": "T05"})["itm_id"] == "T05"


def test_axis_count_is_reported():
    """축을 몇 개 넘겼는지 출력에 남겨야 나중에 이 실수를 다시 잡을 수 있다."""
    row = {"selected_itm_id": "I", "selected_obj_l1": "A", "selected_obj_l2": "B"}
    assert axes_used(combination_from(row)) == 2


def test_nan_strings_are_treated_as_empty():
    row = {"selected_itm_id": "I", "selected_obj_l1": "A", "selected_obj_l2": "nan"}
    assert "objL2" not in combination_from(row)


# --------------------------------------------------------------------------
# 요청은 파이프라인 코드로 만든다
# --------------------------------------------------------------------------

def test_uses_the_pipelines_request_builder():
    """손으로 파라미터를 조립하면 같은 실수가 반복된다."""
    source = inspect.getsource(probe)
    assert "build_kosis_request" in source


def test_metadata_valid_is_set_so_the_builder_does_not_reject():
    assert combination_from({"selected_itm_id": "I"})["metadata_valid"] is True
