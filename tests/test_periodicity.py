"""표가 어떤 주기를 제공하는가 (2026-08-04).

## 왜 필요한가

**표의 수록 주기를 어디에도 기록하지 않았다.** 표 요약(`data/reference/kosis_table_summary.csv`)에도,
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


# --------------------------------------------------------------------------
# 분기를 거부하지 않고 변환한다 (2단계)
# --------------------------------------------------------------------------
from kosis_claim_shape import claim_shape_exclusion, quarter_period
from kosis_verify_claim_values import aggregate_period, period_range

RETAIL = ("대표적인 내수경기 지표인 소매판매액지수는 2024년 3분기 100.6으로 1년 전보다 "
          "1.9% 감소했는데, 2022년 2분기(-0.2%) 이래 10개 분기 연속으로 감소세가 이어지고 있다.")


def test_the_holdout_case_is_converted():
    """홀드아웃1 [1]. 이걸 연간으로 물어봐서 거짓 불일치가 났다."""
    assert quarter_period(RETAIL, "2022") == "202202"


def test_the_year_decides_which_quarter():
    """같은 문장에 2024년 3분기도 있다. 이 측정의 해와 맞는 것만 잡아야 한다."""
    assert quarter_period(RETAIL, "2024") == "202403"


def test_a_year_without_a_quarter_returns_nothing():
    assert quarter_period(RETAIL, "2019") == ""


@pytest.mark.parametrize("text,expected", [
    ("2023년 1분기 수출은", "202301"),
    ("2023년 4/4분기 수출은", "202304"),
    ("2023년 4 분기 수출은", "202304"),
])
def test_quarter_forms(text, expected):
    assert quarter_period(text, "2023") == expected


def test_a_bare_half_year_is_not_converted():
    """'하반기 파업 영향' 은 연간 주장이다. 반기는 아직 열지 않는다."""
    text = "자동차 수출은 하반기 파업 영향으로 전년도와 보합세인 708억 달러를 기록했다."
    assert quarter_period(text, "2024") == ""


def test_a_convertible_quarter_is_no_longer_excluded():
    row = {"claim_text": RETAIL, "measurement_prd_se": "Y",
           "measurement_indicator": "소매판매액지수", "measurement_period": "2022"}
    assert claim_shape_exclusion(row) == ("", "")


def test_a_half_year_claim_is_still_excluded():
    """변환할 수 없으면 빼는 쪽이 맞다 — 틀린 답보다 모른다고 하는 편이 낫다."""
    row = {"claim_text": "2024년 상반기 수출은 3000억달러였다.", "measurement_prd_se": "Y",
           "measurement_indicator": "수출액", "measurement_period": "2024"}
    assert claim_shape_exclusion(row)[0] == "PERIOD_GRANULARITY_MISMATCH"


# --------------------------------------------------------------------------
# 조회와 집계
# --------------------------------------------------------------------------

def test_a_quarter_queries_that_quarter():
    params, _ = period_range("202202", "Q")
    assert params == {"startPrdDe": "202202", "endPrdDe": "202202"}


def test_a_quarter_with_a_comparison_spans_both():
    params, _ = period_range("202202", "Q", "202102")
    assert params == {"startPrdDe": "202102", "endPrdDe": "202202"}


def test_a_monthly_row_is_not_read_as_a_quarter():
    """'202202' 는 2022년 2분기이기도 하고 2022년 2월이기도 하다.

    PRD_SE 를 안 보면 2월 값을 2분기 값으로 답한다. 조용히 틀린다.
    """
    monthly = [{"PRD_DE": "202202", "DT": "99", "PRD_SE": "M"}]
    assert aggregate_period(monthly, "Q", "202202", "latest") == (None, "")


def test_a_quarterly_row_is_read():
    quarterly = [{"PRD_DE": "202202", "DT": "100.6", "PRD_SE": "Q"}]
    value, used = aggregate_period(quarterly, "Q", "202202", "latest")
    assert value == 100.6 and used == "202202"


def test_rows_without_a_periodicity_are_still_accepted_outside_spans():
    """옛 산출물에는 PRD_SE 가 없을 수 있다. 없으면 막지 않는다(구간 합산만 엄격하다)."""
    rows = [{"PRD_DE": "2022", "DT": "5.88"}]
    assert aggregate_period(rows, "Y", "2022", "latest")[0] == 5.88


def test_the_written_columns_include_periodicity(tmp_path):
    """사전에 키를 넣는 것만으로는 부족하다.

    DictWriter 가 extrasaction='ignore' 라 FIELDS 에 없는 키는 **조용히 버려진다.**
    2026-08-04 실측: 520개 표를 다 수집하고도 prd_se_list 컬럼이 없었다.
    사전만 검사하는 테스트(test_rows_carry_the_table_periodicity)는 이걸 통과시켰다.
    """
    import csv
    out = tmp_path / "meta.csv"
    table = {"org_id": "101", "tbl_id": "DT_X", "tbl_name": "표", "category_path": "",
             "prd_se_list": "Y|Q", "prd_ranges": "Q:196001~202504"}
    rows = builder.convert_meta_rows(table, [{"OBJ_ID": "ITEM", "ITM_ID": "T1"}])
    builder.append_csv(out, rows, write_header=True)
    written = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert "prd_se_list" in written[0]
    assert written[0]["prd_se_list"] == "Y|Q"
    assert written[0]["prd_ranges"] == "Q:196001~202504"


def test_every_produced_key_has_a_column():
    """convert_meta_rows 가 만드는 키는 전부 FIELDS 에 있어야 한다."""
    table = {"org_id": "1", "tbl_id": "T", "tbl_name": "", "category_path": "",
             "prd_se_list": "", "prd_ranges": ""}
    produced = set(builder.convert_meta_rows(table, [{"OBJ_ID": "ITEM"}])[0])
    assert produced - set(builder.FIELDS) == set()
