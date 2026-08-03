"""출처 귀속 판정을 기사 단위로 전파한다 (2026-08-02).

실측: 정부의 한은 일시차입 관련 7문장 중 '제출받은 자료'라는 출처 표현이 있는 건
      1문장뿐이었다. 나머지는 같은 기사의 후속 문장이라 게이트를 통과했다.
      기사는 출처를 한 번만 밝히고 수치는 여러 문장에 흩어놓는다.

전파 대상을 좁게 잡는 것이 핵심이다. 출처는 기사에 걸리는 속성이지만,
'개별 기업 실적'은 문장마다 다르다 — 같은 기사에 산업 집계 문장이 섞여 있다.
"""
from kosis_scope_gate import ARTICLE_SCOPED_CODES, propagate_by_article

SOURCE_SENTENCE = ("1일 임광현 의원이 한은에서 제출받은 자료에 따르면, "
                   "정부는 지난해 총 173조원을 일시 차입했다.")
FOLLOW_UP = "지난해 이 같은 일시 대출에 따라 정부가 부담한 이자는 2092억원에 달했다."


def _rows(*pairs):
    return [{"article_id": a, "claim_text": t} for a, t in pairs]


# --------------------------------------------------------------------------
# 전파가 실제로 일어나는가
# --------------------------------------------------------------------------

def test_follow_up_sentence_inherits_the_source():
    rows = _rows(("A1", SOURCE_SENTENCE), ("A1", FOLLOW_UP))
    got = propagate_by_article(rows)
    assert got[1]["scope_gate_blocked"] == "Y"
    assert got[1]["scope_gate_code"] == "INTERNAL_DOCUMENT_SOURCE"


def test_propagated_rows_are_marked():
    """원 판정과 전파 판정을 구분할 수 있어야 나중에 근거를 되짚는다."""
    got = propagate_by_article(_rows(("A1", SOURCE_SENTENCE), ("A1", FOLLOW_UP)))
    assert got[0]["scope_gate_propagated"] == "N"
    assert got[1]["scope_gate_propagated"] == "Y"


def test_reason_says_it_came_from_another_sentence():
    got = propagate_by_article(_rows(("A1", SOURCE_SENTENCE), ("A1", FOLLOW_UP)))
    assert "같은 기사" in got[1]["scope_gate_reason"]


# --------------------------------------------------------------------------
# 번지면 안 되는 경계
# --------------------------------------------------------------------------

def test_other_articles_are_untouched():
    rows = _rows(("A1", SOURCE_SENTENCE), ("A2", FOLLOW_UP))
    got = propagate_by_article(rows)
    assert got[1]["scope_gate_blocked"] == "N"


def test_company_metric_does_not_propagate():
    """같은 기사에 개별 기업 문장과 산업 집계 문장이 섞여 있다(완성차 기사).

    전파하면 정상 주장을 잃는다 — 오탐이 미탐보다 나쁘다.
    """
    rows = _rows(
        ("A1", "현대차는 지난해 판매량이 414만 1791대로 1.8% 감소했다."),
        ("A1", "작년 국내 완성차 업체들의 판매량이 2023년 대비 0.6% 줄었다."),
    )
    got = propagate_by_article(rows)
    assert got[0]["scope_gate_blocked"] == "Y"
    assert got[1]["scope_gate_blocked"] == "N"


def test_company_code_is_not_in_the_propagation_set():
    assert "SINGLE_COMPANY_METRIC" not in ARTICLE_SCOPED_CODES
    assert "ENUMERATED_COMPANIES" not in ARTICLE_SCOPED_CODES
    assert "INTERNAL_DOCUMENT_SOURCE" in ARTICLE_SCOPED_CODES


def test_missing_article_id_does_not_group_everything_together():
    """article_id 가 비면 서로 다른 기사가 한 덩어리로 묶여 무차별 차단된다."""
    rows = _rows(("", SOURCE_SENTENCE), ("", "수출액이 6838억달러를 기록했다."))
    got = propagate_by_article(rows)
    assert got[1]["scope_gate_blocked"] == "N"


# --------------------------------------------------------------------------
# 기존 판정을 덮어쓰지 않는다
# --------------------------------------------------------------------------

def test_already_blocked_rows_keep_their_own_code():
    rows = _rows(
        ("A1", SOURCE_SENTENCE),
        ("A1", "현대차는 지난해 판매량이 414만 1791대로 1.8% 감소했다."),
    )
    got = propagate_by_article(rows)
    assert got[1]["scope_gate_code"] == "SINGLE_COMPANY_METRIC"
    assert got[1]["scope_gate_propagated"] == "N"


def test_clean_article_stays_clean():
    rows = _rows(
        ("A1", "작년 한 해 전체 수출액이 6838억달러로 8.2% 증가했다."),
        ("A1", "반도체가 43.9% 증가한 1419억 달러를 기록했다."),
    )
    assert all(d["scope_gate_blocked"] == "N" for d in propagate_by_article(rows))


def test_empty_input():
    assert propagate_by_article([]) == []
