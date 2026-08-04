"""기사 전체가 범위 밖일 때 홀로 남는 문장 (2026-08-04).

골드 라벨링을 하다가 드러났다. 12건을 라벨했는데 정답 좌표가 0건이었고,
그중 넷이 같은 문장이었다 — CES 전시 분야 비중.

CES 기사(A0005)는 네 문장 중 셋이 OUT_OF_KOSIS_SCOPE 로 정확히 거부됐다.
남은 하나 '분야는 생활가전(18%) 디지털헬스(17%)...' 가 평가 집합 88건에 들어와 있었다.
**무엇의 분야인지가 그 문장에 없다.** 주어가 앞 문장에 있다.
미국 CTA 주최 행사 자료라 KOSIS 에 있을 수 없는데, 문장만 봐서는 알 방법이 없다.

'정부의 연간 누적 대출'과 같은 계열이다 — 앞 문장에 기대는 문장이 홀로 남는 것.
다만 촉발 코드가 다르다. 그쪽은 출처 귀속이고 이쪽은 주제 범위다.

## 왜 조건을 셋이나 거는가

전파를 넓히면 정당한 문장이 죽는다. 전례가 둘 있다.
  · 추출 프롬프트에 품목 근거 규칙을 넣었더니 대상 있음이 50% -> 22% 로 떨어졌다.
  · 1차 출처 전파가 '한국로봇산업진흥원에 따르면 로봇화 기업 2524곳'을 부당하게 막았다.

전수 측정: 88건 중 4건 제거, **확정 16건은 하나도 안 빠진다.**
조건을 넓히려면 다시 측정하고 확정 건이 안 빠지는지 확인할 것.
"""
import prepare_kosis_mapping_input as prepare
from kosis_scope_gate import starts_with_anaphor

CES = "분야는 생활가전(18%) 디지털헬스(17%), 인공지능(16%), 스마트 홈(12%) 순으로 집계됐다."


def _rejected(article, text, code="OUT_OF_KOSIS_SCOPE"):
    return {"article_id": article, "claim_text": text,
            "mapping_eligible": "N", "mapping_exclusion_code": code}


def _alive(article, text):
    return {"article_id": article, "claim_text": text, "mapping_eligible": "Y",
            "mapping_exclusion_code": ""}


# --------------------------------------------------------------------------
# 걸러야 하는 것
# --------------------------------------------------------------------------

def test_the_ces_sentence_is_removed():
    rows = [_rejected("A0005", "이는 지난해 443개보다 2개 늘어난 역대 최대 규모다."),
            _rejected("A0005", "약 900개사가 참가한다."),
            _alive("A0005", CES)]
    assert prepare.apply_orphan_scope(rows) == 1
    assert rows[2]["mapping_eligible"] == "N"
    assert rows[2]["mapping_exclusion_code"] == "ORPHAN_IN_OUT_OF_SCOPE_ARTICLE"
    assert rows[2]["in_ready"] == "N"


def test_every_measurement_of_that_sentence_is_removed():
    """한 문장에서 측정이 넷 나왔다. 넷 다 빠져야 한다."""
    rows = [_rejected("A0005", "약 900개사가 참가한다.")] + [_alive("A0005", CES)] * 4
    assert prepare.apply_orphan_scope(rows) == 4


# --------------------------------------------------------------------------
# 건드리면 안 되는 것 — 조건 하나씩 무너뜨려 확인한다
# --------------------------------------------------------------------------

def test_untouched_when_the_article_has_a_standalone_sentence():
    """자기 주어가 있는 문장이 하나라도 살아 있으면 기사 전체가 범위 밖은 아니다."""
    rows = [_rejected("A1", "약 900개사가 참가한다."),
            _alive("A1", CES),
            _alive("A1", "작년 수출액은 6838억달러였다.")]
    assert prepare.apply_orphan_scope(rows) == 0
    assert rows[1]["mapping_eligible"] == "Y"


def test_untouched_when_a_rejection_is_not_a_scope_code():
    """기간 누락 같은 이유로 빠진 것은 '범위 밖 기사'의 근거가 못 된다."""
    rows = [_rejected("A1", "약 900개사가 참가한다.", code="PERIOD_MISSING"),
            _alive("A1", CES)]
    assert prepare.apply_orphan_scope(rows) == 0


def test_sentence_with_its_own_source_survives():
    """'한국로봇산업진흥원에 따르면' 은 그 문장의 출처다. 1차 전파가 이걸 죽였었다."""
    rows = [_rejected("A1", "약 900개사가 참가한다."),
            _alive("A1", "이 조사는 한국로봇산업진흥원에 따르면 2524곳이었다.")]
    assert prepare.apply_orphan_scope(rows) == 0


def test_untouched_when_nothing_was_rejected():
    rows = [_alive("A1", CES), _alive("A1", "이는 최대 규모다.")]
    assert prepare.apply_orphan_scope(rows) == 0


def test_other_articles_are_untouched():
    rows = [_rejected("A1", "약 900개사가 참가한다."), _alive("A2", CES)]
    assert prepare.apply_orphan_scope(rows) == 0


def test_rows_without_an_article_id_are_untouched():
    rows = [_rejected("", "약 900개사가 참가한다."), _alive("", CES)]
    assert prepare.apply_orphan_scope(rows) == 0


# --------------------------------------------------------------------------
# 지시어 판정
# --------------------------------------------------------------------------

def test_anaphoric_openers():
    for text in (CES, "이는 최대 규모다.", "그중 절반이 중소기업이다.", "전체 참가사는 900곳이다."):
        assert starts_with_anaphor(text)


def test_standalone_openers_are_not_anaphoric():
    for text in ("작년 수출액은 6838억달러였다.", "반도체가 43.9% 증가했다.",
                 "한국은행이 발표한 자료다."):
        assert not starts_with_anaphor(text)


def test_leading_whitespace_does_not_matter():
    assert starts_with_anaphor("  " + CES)


def test_prepare_calls_it():
    """함수만 만들고 연결하지 않으면 아무 일도 일어나지 않는다."""
    import inspect
    assert "apply_orphan_scope(normalized)" in inspect.getsource(prepare.prepare)
