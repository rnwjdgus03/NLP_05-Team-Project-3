"""표가 어떤 주기를 제공하는가 (2026-08-04).

## 왜 필요한가

**표의 수록 주기를 어디에도 기록하지 않았다.** 표 요약(`kosis_table_summary.csv`)에도,
메타 인덱스에도 없다. 그래서 분기 주장에 태연히 연간을 물어봤고,
홀드아웃1 의 거짓 불일치 하나가 정확히 그것이었다 —
'소매판매액지수 2022년 **2분기** -0.2%' 를 2022년 **연간** +5.88% 와 대조했다.

## KOSIS 가 조용히 어긋나는 두 지점

**1. 없는 주기를 물어도 에러가 없다.** 실측(DT_127005_005, 좌표 고정):

    prdSe=Y   3행  PRD_DE ['2022','2023','2024']
    prdSe=M   6행  PRD_DE ['2019'..'2024']   <- 연간 행이 그대로 온다
    prdSe=Q   6행  PRD_DE ['2019'..'2024']   <- 마찬가지

**2. 분기 PRD_DE 가 월간과 모양이 같다.** 실측(DT_1K41012, prdSe=Q):

    202501 202502 202503 202504 202601 202602

분기를 2자리로 채운다. '202501' 이 1분기인지 1월인지 **글자로는 구분이 안 된다.**
PRD_SE 를 함께 봐야 한다.

## 어휘가 둘이다

    자료 행      PRD_SE = 'Y' / 'Q' / 'M'
    getMeta PRD  PRD_SE = '년' / '분기' / '월'

하나만 처리하면 조용히 어긋난다. 정규화를 **한 곳에만** 둔다
(`kosis_meta_coordinates.normalize_periodicity`).
같은 규칙을 두 군데 두었다가 어긋난 전례가 있다 — `claim_item_grounded`.
"""
import inspect

import pytest

import kosis_build_meta_index as builder
from kosis_meta_coordinates import normalize_periodicity
from kosis_verify_claim_values import row_periodicity


# --------------------------------------------------------------------------
# 어휘 정규화
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("Y", "Y"), ("년", "Y"), ("연간", "Y"),
    ("Q", "Q"), ("분기", "Q"),
    ("M", "M"), ("월", "M"), ("월간", "M"),
    ("H", "H"), ("반기", "H"),
])
def test_both_vocabularies_are_understood(value, expected):
    assert normalize_periodicity(value) == expected


@pytest.mark.parametrize("value", ["", None, "주", "격월", "unknown"])
def test_unknown_values_are_empty(value):
    """모르는 값을 아무거나로 넘기면 조용히 틀린 주기로 조회한다."""
    assert normalize_periodicity(value) == ""


def test_whitespace_is_stripped():
    assert normalize_periodicity(" 분기 ") == "Q"


def test_there_is_only_one_implementation():
    """같은 규칙이 두 곳에 있으면 언젠가 어긋난다. row_periodicity 는 얇은 껍데기여야 한다."""
    source = inspect.getsource(row_periodicity)
    assert "normalize_periodicity" in source
    assert "'분기'" not in source and '"분기"' not in source


def test_row_periodicity_reads_the_field():
    assert row_periodicity({"PRD_SE": "Q"}) == "Q"
    assert row_periodicity({}) == ""


# --------------------------------------------------------------------------
# 수집
# --------------------------------------------------------------------------

def _fake_get_meta(rows, calls=None):
    def inner(org_id, tbl_id, meta_type="ITM"):
        if calls is not None:
            calls.append(meta_type)
        return rows
    return inner


def test_periodicity_is_collected_and_joined(monkeypatch):
    monkeypatch.setattr(builder, "get_meta", _fake_get_meta([
        {"PRD_SE": "년", "STRT_PRD_DE": "1970", "END_PRD_DE": "2024"},
        {"PRD_SE": "분기", "STRT_PRD_DE": "196001", "END_PRD_DE": "202504"},
    ]))
    codes, spans = builder.collect_periodicity("101", "DT_X")
    assert codes == "Y|Q"
    assert "Q:196001~202504" in spans


def test_duplicates_are_not_repeated(monkeypatch):
    monkeypatch.setattr(builder, "get_meta", _fake_get_meta([
        {"PRD_SE": "월"}, {"PRD_SE": "M"},
    ]))
    assert builder.collect_periodicity("101", "DT_X")[0] == "M"


def test_an_annual_only_table(monkeypatch):
    """실측: DT_127005_005 는 getMeta type=PRD 가 {'PRD_SE': '년'} 하나만 준다."""
    monkeypatch.setattr(builder, "get_meta", _fake_get_meta([{"PRD_SE": "년"}]))
    assert builder.collect_periodicity("127", "DT_127005_005")[0] == "Y"


def test_a_failure_does_not_stop_collection(monkeypatch):
    """주기를 못 가져와도 메타 수집 자체는 계속돼야 한다."""
    def boom(*args, **kwargs):
        raise RuntimeError("timeout")
    monkeypatch.setattr(builder, "get_meta", boom)
    assert builder.collect_periodicity("101", "DT_X") == ("", "")


def test_unknown_codes_are_dropped(monkeypatch):
    monkeypatch.setattr(builder, "get_meta", _fake_get_meta([{"PRD_SE": "격월"}]))
    assert builder.collect_periodicity("101", "DT_X")[0] == ""


def test_it_asks_for_the_prd_type(monkeypatch):
    calls = []
    monkeypatch.setattr(builder, "get_meta", _fake_get_meta([{"PRD_SE": "년"}], calls))
    builder.collect_periodicity("101", "DT_X")
    assert calls == ["PRD"]


# --------------------------------------------------------------------------
# 출력에 실리는가
# --------------------------------------------------------------------------

def test_rows_carry_the_table_periodicity():
    table = {"org_id": "101", "tbl_id": "DT_X", "tbl_name": "표", "category_path": "",
             "prd_se_list": "Y|Q|M", "prd_ranges": "M:196001~202512"}
    rows = builder.convert_meta_rows(table, [{"OBJ_ID": "ITEM", "ITM_ID": "T1"}])
    assert rows[0]["prd_se_list"] == "Y|Q|M"
    assert rows[0]["prd_ranges"] == "M:196001~202512"


def test_missing_periodicity_is_blank_not_an_error():
    """--with-periodicity 없이 돌린 예전 산출물과도 호환돼야 한다."""
    table = {"org_id": "101", "tbl_id": "DT_X", "tbl_name": "표", "category_path": ""}
    rows = builder.convert_meta_rows(table, [{"OBJ_ID": "ITEM", "ITM_ID": "T1"}])
    assert rows[0]["prd_se_list"] == ""
