"""씨앗 사전 채점 (2026-08-05).

**합치도는 정확도가 아니다.** 같은 통계가 여러 표에 실린다.
그래서 이 스크립트가 지켜야 할 것은 정확한 백분율이 아니라 **가리지 않는 것**이다 —
어긋난 건이 출력에 남아야 사람이 볼 수 있다.
"""
import pytest

from score_against_seed import build_lookup, compare, match_keyword, normalize

SEED = [
    {"keyword": "물가", "tbl_id": "DT_1J22001", "itm_id": "T", "obj_l1": "T10",
     "tbl_name": "지출목적별 소비자물가지수", "check_status": "PASS"},
    {"keyword": "소비자물가지수", "tbl_id": "DT_1J22001", "itm_id": "T", "obj_l1": "T10",
     "tbl_name": "지출목적별 소비자물가지수", "check_status": "PASS"},
    {"keyword": "취업자수", "tbl_id": "DT_1DA7001S", "itm_id": "T30", "obj_l1": "0",
     "tbl_name": "성별 경제활동인구 총괄", "check_status": "PASS"},
    {"keyword": "낡은것", "tbl_id": "DT_OLD", "itm_id": "X", "obj_l1": "0",
     "tbl_name": "폐지된 표", "check_status": "NO_DATA"},
]


@pytest.fixture
def lookup():
    return build_lookup(SEED)


@pytest.fixture
def keys(lookup):
    return sorted(lookup, key=len, reverse=True)


# --------------------------------------------------------------------------
# 검증을 통과한 것만 정답지가 된다
# --------------------------------------------------------------------------

def test_unverified_coordinates_are_excluded(lookup):
    """PASS 가 아닌 좌표를 정답으로 쓰면 맞는 답에 오답 딱지를 붙인다."""
    assert "낡은것" not in lookup
    assert len(lookup) == 3


# --------------------------------------------------------------------------
# 지표를 키워드에 붙이기
# --------------------------------------------------------------------------

def test_exact_match(lookup, keys):
    assert match_keyword("취업자수", lookup, keys) == "취업자수"


def test_the_longest_keyword_wins(lookup, keys):
    """'소비자물가지수' 가 '물가' 보다 먼저 걸려야 한다.

    짧은 것이 이기면 지표가 뭉개진다 — 씨앗의 요점이 좌표 구분인데
    구분을 잃으면 채점이 무의미해진다.
    """
    assert match_keyword("소비자물가지수", lookup, keys) == "소비자물가지수"


def test_partial_match(lookup, keys):
    assert match_keyword("소비자물가 상승률", lookup, keys) != ""


def test_spacing_and_middots_are_ignored(lookup, keys):
    assert normalize("원·달러 환율") == "원달러환율"
    assert normalize("취업자 수") == "취업자수"
    assert match_keyword("취업자 수", lookup, keys) == "취업자수"


def test_an_unknown_indicator_returns_empty(lookup, keys):
    """씨앗은 국가/시도 총계뿐이다. 못 덮는 것이 정상이고 조용히 넘기면 안 된다."""
    assert match_keyword("대미 수출액", lookup, keys) == ""
    assert match_keyword("", lookup, keys) == ""


# --------------------------------------------------------------------------
# 표가 다르면 아래 축은 비교하지 않는다
# --------------------------------------------------------------------------

def test_everything_agrees():
    record = compare(
        {"tbl_id": "DT_A", "itm_id": "T10", "obj_l1": "00"},
        {"tbl_id": "DT_A", "selected_itm_id": "T10", "selected_obj_l1": "00"})
    assert record["table_agrees"]
    assert record["item_agrees"]
    assert record["obj_agrees"]


def test_a_different_table_fails_everything():
    """**표마다 코드 체계가 다르다.** 실측으로 'T10' 은 수출액(DT_1YL6901),
    혼인율(DT_1B83A34), 범죄율(DT_1YL3001) 셋 다에 있다.
    표를 무시하고 비교하면 셋을 '항목 일치' 로 센다.
    """
    record = compare(
        {"tbl_id": "DT_1YL6901", "itm_id": "T10", "obj_l1": "00"},
        {"tbl_id": "DT_1B83A34", "selected_itm_id": "T10", "selected_obj_l1": "00"})
    assert not record["table_agrees"]
    assert not record["item_agrees"], "다른 표의 T10 을 같다고 세면 안 된다"
    assert not record["obj_agrees"]


def test_the_axis_can_differ_within_the_same_table():
    """홀드아웃3 의 거짓 불일치가 이 모양이었다 —
    표는 `국가별 수출액` 으로 맞혔는데 분류1을 '계' 로 골랐다.
    """
    record = compare(
        {"tbl_id": "DT_A", "itm_id": "T10", "obj_l1": "CN"},
        {"tbl_id": "DT_A", "selected_itm_id": "T10", "selected_obj_l1": "00"})
    assert record["table_agrees"] and record["item_agrees"]
    assert not record["obj_agrees"], "축이 다른데 통과하면 그 병목을 못 잡는다"


def test_an_empty_table_never_agrees():
    """좌표를 못 고른 행이 빈 값끼리 만나 '일치' 가 되면 안 된다.

    오늘 프로브가 정확히 그 방식으로 축 0개를 조회했다.
    """
    record = compare({"tbl_id": "", "itm_id": "", "obj_l1": ""},
                     {"tbl_id": "", "selected_itm_id": "", "selected_obj_l1": ""})
    assert not record["table_agrees"]
    assert not record["item_agrees"]


def test_disagreements_are_printed():
    """**어긋난 건이 사라지면 이 도구는 쓸모가 없다.**

    백분율만 보면 오판을 못 본다 — 오늘 아침 확정 12건 중 불일치 3건이
    전부 오판이었다.
    """
    import inspect

    import score_against_seed as score
    assert "어긋난 건" in inspect.getsource(score.main)


def test_uncovered_indicators_can_be_reported():
    """못 덮는 지표가 다음 확장 대상이다. 세지 않으면 어디를 넓힐지 모른다."""
    import inspect

    import score_against_seed as score
    assert "report-uncovered" in inspect.getsource(score.main)
