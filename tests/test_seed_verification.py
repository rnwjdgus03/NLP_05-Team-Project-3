"""씨앗 좌표 검증의 판정 규칙 (2026-08-05).

**KOSIS 오류코드를 잘못 읽으면 멀쩡한 좌표를 버린다.**

    err:20   축을 덜 넘겼다      → 우리 잘못. 좌표는 아직 무죄
    err:30   자료가 없다         → 좌표는 형식상 맞다

오늘만 두 번 헷갈렸다. 프로브에서 축 0개로 28건을 조회해놓고 '좌표 오류' 로
셀 뻔했고(에러코드 분포가 `{'20': 11}` 이라 걸렸다), 8월 2일에는 objL2 를
빠뜨려 err:20 을 파이프라인 버그로 오해했다.

그래서 상태를 뭉뚱그리지 않고 **다섯으로 가른다.**
"""
import pytest

from verify_seed_coordinates import classify, first_periodicity


# --------------------------------------------------------------------------
# 응답 판정
# --------------------------------------------------------------------------

def test_rows_with_values_pass():
    status, code, rows = classify([{"PRD_DE": "2024", "DT": "51712619"}])
    assert status == "PASS"
    assert rows


def test_missing_axis_is_not_missing_data():
    """**이 구분이 이 파일의 존재 이유다.**"""
    assert classify({"err": "20", "errMsg": "..."})[0] == "ERR_AXIS"


def test_no_data_is_reported_separately():
    assert classify({"err": "30"})[0] == "NO_DATA"


def test_other_errors_keep_their_code():
    status, code, _ = classify({"err": "500"})
    assert status == "ERR_OTHER"
    assert code == "500"


def test_an_empty_list_is_no_data():
    assert classify([])[0] == "NO_DATA"
    assert classify(None)[0] == "NO_DATA"


def test_rows_without_values_are_no_data():
    """행은 오는데 DT 가 비어 있는 경우가 있다. 값이 없으면 확인이 안 된다."""
    assert classify([{"PRD_DE": "2024", "DT": ""}])[0] == "NO_DATA"


def test_the_latest_row_is_sampled():
    _, _, rows = classify([{"PRD_DE": "2023", "DT": "1"},
                           {"PRD_DE": "2024", "DT": "2"}])
    assert rows[-1]["PRD_DE"] == "2024"


# --------------------------------------------------------------------------
# 어느 주기로 확인하는가
# --------------------------------------------------------------------------

@pytest.mark.parametrize("listed,expected", [
    ("Y|Q|M", "Y"),
    ("Y|M", "Y"),
    ("M", "M"),
    ("Q|M", "Q"),
    ("", "Y"),
])
def test_the_coarsest_periodicity_is_used(listed, expected):
    """굵은 주기일수록 자료가 있을 확률이 높다. 확인이 목적이므로 유리한 쪽으로 묻는다."""
    assert first_periodicity({"prd_se_list": listed}) == expected


# --------------------------------------------------------------------------
# 축을 전부 넘기는가
# --------------------------------------------------------------------------

def test_the_second_axis_is_sent():
    """objL2 를 빠뜨리면 err:20 이 오고, 그걸 '좌표 틀림' 으로 읽게 된다.

    오늘 프로브가 정확히 그렇게 실패했다 — 분류축 0개로 28건 조회.
    """
    import inspect

    import verify_seed_coordinates as verify
    source = inspect.getsource(verify.check)
    assert 'extra["objL2"]' in source


def test_the_api_key_never_reaches_the_log():
    """requests 는 예외 메시지에 전체 URL(=키 포함)을 넣는다.

    오늘 그것 때문에 KOSIS 키를 폐기했다. 예외는 종류만 남긴다.
    """
    import inspect

    import verify_seed_coordinates as verify
    source = inspect.getsource(verify.check)
    assert "type(exc).__name__" in source
    assert "str(exc)" not in source
