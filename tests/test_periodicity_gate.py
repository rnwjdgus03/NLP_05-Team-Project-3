"""표가 못 주는 주기는 조회하지 않는다 (2026-08-04).

## 왜 조회 전에 막는가

**KOSIS 는 없는 주기를 물어도 에러를 내지 않는다.** 실측(DT_127005_005, 좌표 고정):

    prdSe=Y   3행  PRD_DE ['2022','2023','2024']
    prdSe=M   6행  PRD_DE ['2019'..'2024']   <- 연간 행이 그대로 온다
    prdSe=Q   6행  PRD_DE ['2019'..'2024']   <- 마찬가지

그대로 조회하면 분기 주장에 연간값이 붙는다. 홀드아웃1 의 거짓 불일치 하나가
정확히 그것이다 — '소매판매액지수 2022년 2분기 -0.2%' 를 2022년 연간 +5.88% 와 대조했다.

집계 쪽에도 PRD_SE 가드가 있지만(`aggregate_period`), 조회 자체를 안 하는 편이 낫다.
API 호출을 아끼고 사유도 분명해진다.

## 모르면 막지 않는다

`prd_se_list` 는 `--with-periodicity` 로 수집해야 채워진다.
그 전 산출물에는 없다. **없는 것을 '못 준다'로 읽으면 전부 죽는다.**
이 구분을 놓쳐 커버리지를 통째로 날린 적이 있다 —
`prepare` 가 `industry_or_item` 만 지워 하류가 옛 값을 보던 일과 같은 계열이다.
"""
import pytest

from kosis_validate_mapping_candidates import (periodicity_unavailable,
                                               table_periodicities)


def _meta(*lists):
    return [{"prd_se_list": value} for value in lists]


# --------------------------------------------------------------------------
# 표가 제공하는 주기 읽기
# --------------------------------------------------------------------------

def test_codes_are_parsed():
    assert table_periodicities(_meta("Y|Q|M")) == {"Y", "Q", "M"}


def test_korean_labels_are_accepted():
    assert table_periodicities(_meta("년|분기")) == {"Y", "Q"}


def test_rows_agree_so_duplicates_collapse():
    """표 단위 값이라 행마다 같다. 집합으로 모은다."""
    assert table_periodicities(_meta("Y|Q", "Y|Q", "Y|Q")) == {"Y", "Q"}


def test_missing_column_is_unknown():
    assert table_periodicities([{"code_name": "총지수"}]) == set()


def test_unknown_codes_are_dropped():
    assert table_periodicities(_meta("Y|격월")) == {"Y"}


# --------------------------------------------------------------------------
# 막을 것과 막지 않을 것
# --------------------------------------------------------------------------

def test_a_quarterly_claim_against_an_annual_table_is_blocked():
    """홀드아웃1 [1] 의 상황. 이걸 조회해서 연간값과 대조했다."""
    reason = periodicity_unavailable({"prd_se": "Q"}, _meta("Y"))
    assert reason.startswith("PERIODICITY_NOT_AVAILABLE")
    assert "Y" in reason and "Q" in reason


def test_a_monthly_claim_against_an_annual_table_is_blocked():
    assert periodicity_unavailable({"prd_se": "M"}, _meta("Y"))


def test_a_supported_periodicity_passes():
    assert periodicity_unavailable({"prd_se": "Q"}, _meta("Y|Q|M")) == ""


def test_an_annual_claim_against_an_annual_table_passes():
    assert periodicity_unavailable({"prd_se": "Y"}, _meta("Y")) == ""


def test_an_unknown_table_periodicity_does_not_block():
    """--with-periodicity 없이 만든 옛 메타. 모르는 것을 '못 준다'로 읽으면 전부 죽는다."""
    assert periodicity_unavailable({"prd_se": "Q"}, [{"code_name": "총지수"}]) == ""
    assert periodicity_unavailable({"prd_se": "Q"}, []) == ""


@pytest.mark.parametrize("value", ["", None, "격월"])
def test_an_unknown_claim_periodicity_does_not_block(value):
    """주장 쪽 주기를 모르면 판단 근거가 없다. 막지 않는다."""
    assert periodicity_unavailable({"prd_se": value}, _meta("Y")) == ""


def test_it_reads_the_measurement_field_too():
    assert periodicity_unavailable({"measurement_prd_se": "Q"}, _meta("Y"))


def test_korean_claim_periodicity():
    assert periodicity_unavailable({"prd_se": "분기"}, _meta("Y"))


# --------------------------------------------------------------------------
# 파이프라인에 연결됐는가
# --------------------------------------------------------------------------

def test_validate_calls_the_gate():
    """함수만 만들고 연결하지 않으면 아무 일도 일어나지 않는다."""
    import inspect

    import kosis_validate_mapping_candidates as validate
    source = inspect.getsource(validate.main)
    assert "periodicity_unavailable(row, meta_rows)" in source


# --------------------------------------------------------------------------
# 격년 조사표 (2026-08-04 실측)
# --------------------------------------------------------------------------
# 245개 표 중 **69개(28%)** 가 PRD_SE='2년' 이었다. 처음엔 모르는 값이라 빈칸이 됐는데
# 실패가 아니라 실제 주기다. '전년 대비 고객사 수 증감 현황', '물품기부' 같은 조사표들이다.

def test_a_biennial_table_answers_an_annual_claim():
    """격년이라도 그 해 자료가 있으면 답할 수 있다. 없으면 빈 응답으로 걸러진다."""
    assert periodicity_unavailable({"prd_se": "Y"}, _meta("2년")) == ""


def test_a_biennial_table_cannot_answer_a_quarterly_claim():
    """더 굵은 주기로 분기를 대신할 수 없다. 이게 이 가드의 요점이다."""
    assert periodicity_unavailable({"prd_se": "Q"}, _meta("2년"))


def test_monthly_tables_can_answer_an_annual_claim():
    """월 자료는 합산해 연간을 만들 수 있다(aggregate_period 가 한다)."""
    assert periodicity_unavailable({"prd_se": "Y"}, _meta("M")) == ""


def test_a_monthly_table_cannot_answer_a_quarterly_claim():
    """월->분기 합산은 아직 구현하지 않았다. 못 하는 것은 못 한다고 한다."""
    assert periodicity_unavailable({"prd_se": "Q"}, _meta("M"))


@pytest.mark.parametrize("label,code", [("2년", "Y2"), ("3년", "Y3"), ("5년", "Y5")])
def test_multi_year_labels_are_recognised(label, code):
    from kosis_meta_coordinates import normalize_periodicity
    assert normalize_periodicity(label) == code
