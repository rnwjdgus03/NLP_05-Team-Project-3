"""메타 인덱스에서 좌표 후보를 뽑는다 (2026-08-02).

파이프라인 후보에서 골드를 만들면 시스템이 못 찾은 좌표는 영원히 골드가 못 된다.
그런 골드로 recall 을 재면 '찾은 것 중에 정답이 있었나'를 재는 셈이라 과대평가된다.

실측: 후보 기반 라벨 문제지 12건 중 11건에 정답이 없었다.
      '석유화학 수출액'의 후보가 간장·경석·가죽·석면섬유였다 — 같은 표에 석유화학이 있는데도.
"""
from export_meta_labeling_packet import (
    describe,
    is_aggregate,
    keywords,
    overlap,
    rank_coordinates,
)


def _table(name="품목별 수출액, 수입액", items=None, values=None):
    return {
        "tbl_id": "T1", "tbl_name": name,
        "items": items or [{"code": "I1", "name": "수출액", "unit": "천달러"}],
        "axes": {1: {"axis_id": "A", "axis_name": "품목별",
                     "values": values or [{"code": "O1", "name": "석유화학"}]}},
    }


# --------------------------------------------------------------------------
# 검색어 추출
# --------------------------------------------------------------------------

def test_keywords_from_indicator_and_item():
    assert "석유화학" in keywords("석유화학 수출액", "석유화학")


def test_generic_words_are_dropped():
    """'증감률'·'비율'은 어느 표에나 있어서 검색어로 쓸모없다."""
    assert "증감률" not in keywords("석유화학 수출 증감률")


def test_duplicates_are_removed():
    assert keywords("반도체", "반도체") == ["반도체"]


def test_single_character_tokens_are_ignored():
    assert keywords("가 나") == []


# --------------------------------------------------------------------------
# 점수
# --------------------------------------------------------------------------

def test_longer_keyword_scores_higher():
    """'석유화학'(4자)이 '수출'(2자)보다 변별력이 크다."""
    assert overlap("석유화학제품", ["석유화학"]) > overlap("수출액", ["수출"])


def test_no_overlap_scores_zero():
    assert overlap("간 장", ["석유화학"]) == 0


def test_spacing_is_ignored():
    assert overlap("가 죽", ["가죽"]) > 0


# --------------------------------------------------------------------------
# 집계값
# --------------------------------------------------------------------------

def test_aggregate_names_are_recognised():
    assert is_aggregate("계") and is_aggregate("총액") and is_aggregate("총지수")


def test_specific_category_is_not_aggregate():
    assert not is_aggregate("석유화학")


def test_aggregate_is_always_offered():
    """주장이 대상을 특정하지 않으면 집계값이 정답이다 — 후보에서 빠지면 안 된다."""
    table = _table(values=[{"code": "O1", "name": "석유화학"},
                           {"code": "O9", "name": "총액"}])
    picked = rank_coordinates(table, ["없는품목"], ["수출액"])
    assert any(value and value["name"] == "총액" for _, value in picked)


def test_matching_category_is_offered():
    table = _table(values=[{"code": "O1", "name": "석유화학"},
                           {"code": "O2", "name": "간 장"},
                           {"code": "O9", "name": "총액"}])
    picked = rank_coordinates(table, ["석유화학"], ["석유화학", "수출액"])
    assert any(value and value["name"] == "석유화학" for _, value in picked)


def test_table_without_an_axis_still_yields_an_option():
    table = {"tbl_id": "T", "tbl_name": "무역", "items": [{"code": "I", "name": "수출액"}],
             "axes": {}}
    assert rank_coordinates(table, [], ["수출액"])


# --------------------------------------------------------------------------
# 설명 — 라벨러가 읽을 것
# --------------------------------------------------------------------------

def test_description_names_table_item_and_category():
    table = _table()
    text = describe(table, table["items"][0], table["axes"][1]["values"][0])
    assert "품목별 수출액" in text and "수출액" in text and "석유화학" in text


def test_missing_unit_is_flagged():
    table = _table(items=[{"code": "I", "name": "수출액", "unit": ""}])
    assert "단위 미상" in describe(table, table["items"][0], None)


def test_axis_free_coordinate_is_labelled():
    assert "분류축 없음" in describe(_table(), None, None)
