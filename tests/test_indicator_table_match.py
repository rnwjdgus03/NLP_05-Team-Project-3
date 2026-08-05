"""고른 표가 지표와 무관한 것은 아닌가 (2026-08-05).

## 이 검사가 없어서 생긴 일

    자사주 직접취득 11.8조  →  '데이터 판매 서비스업 시장 규모' 14.6조
                               차이율 24%. extreme_error(300%) 아래라 확정됐고
                               시스템이 '불일치'라고 단언했다. **기사가 맞았다.**

값 임계값으로는 원리적으로 못 잡는다. 크기가 비슷하면 통과한다.
**값이 아니라 의미로 막아야 한다.**

## 과잉 차단이 더 무섭다

전례가 셋이다 — 추출 프롬프트 품목 규칙(대상 있음 50%→22%),
1차 출처 전파, `share_claim`(수출액 1274억달러까지 구성비로 판정).
그래서 아래 「막지 말아야 할 것」이 「막아야 할 것」보다 많다.
"""
import pytest

from kosis_indicator_table_match import (bigrams, indicator_table_mismatch,
                                         perception_table)


# --------------------------------------------------------------------------
# 막아야 할 것 — 전부 실측이다
# --------------------------------------------------------------------------

def test_the_holdout3_false_mismatch():
    """차이율 24%. 값으로는 절대 못 잡는다."""
    reason = indicator_table_mismatch("자사주 직접취득 금액",
                                      "데이터 판매 서비스업 시장 규모",
                                      itm_name="매출액")
    assert reason
    assert "어휘" in reason


def test_the_second_holdout3_case():
    assert indicator_table_mismatch("자사주 신탁취득 금액",
                                    "데이터 판매 서비스업 시장 규모",
                                    itm_name="매출액")


def test_a_perception_table_cannot_answer_a_price_claim():
    """홀드아웃4: '수입 커피 1년 전보다 94.3% 폭등' 에 붙은 표다.

    '커피' 가 표 이름에 있어서 어휘 겹침으로는 안 걸린다. 의견 표라서 막는다.
    """
    reason = indicator_table_mismatch(
        "수입 커피 가격 상승률",
        "최근 1년간 가공식품 품목별 구입경험 및 구입 변화(커피 및 차)")
    assert reason
    assert "구입경험" in reason


def test_another_perception_table():
    reason = indicator_table_mismatch(
        "가공식품 가격 상승률", "가격변화가 가장 심한 가공식품 품목 인식")
    assert reason and "인식" in reason


@pytest.mark.parametrize("word", ["만족도", "애로", "의향", "인지도", "체감"])
def test_perception_words(word):
    assert perception_table(f"중소기업 {word} 조사") == word


# --------------------------------------------------------------------------
# **막지 말아야 할 것** — 여기가 진짜 위험한 쪽이다
# --------------------------------------------------------------------------

@pytest.mark.parametrize("indicator,table,item", [
    # 오늘 씨앗 채점에서 '어긋남' 으로 나왔지만 **우리가 맞은** 것들
    ("소비자물가 상승률", "월별 소비자물가 등락률", "전월비"),
    ("생활물가 상승률", "생활물가지수(2020=100)", "지수"),
    ("고용률", "연령별 경제활동상태", "고용률"),
    ("취업자수", "성별 경제활동인구 총괄", "취업자"),
    # 첫 50건에서 '일치' 가 났던 계열. 이게 막히면 회귀다
    ("수출액", "국가별 수출액, 수입액", "수출액"),
    ("수출 증감률", "품목별 수출액, 수입액", "수출액"),
    ("산업생산지수", "전산업생산지수", "지수"),
    ("소매판매액지수", "소매판매액지수(계절조정)", "지수"),
    ("원·달러 환율", "주요국 통화의 대원화환율", "환율"),
    ("완성차 판매량", "자동차 국내판매 현황", "판매대수"),
    # 표 이름이 길고 한정어가 많아도, 지표어가 있으면 통과해야 한다
    ("취업자수", "행정구역(시도)/산업별(제조업 중분류) 고용", "취업자수"),
    ("출생아 수", "월.분기.연간 인구동향", "출생아수"),
])
def test_it_does_not_over_fire(indicator, table, item):
    assert indicator_table_mismatch(indicator, table, itm_name=item) == "", \
        f"{indicator} / {table} / {item}"


def test_the_table_name_alone_never_blocks():
    """**표 이름만으로는 판단하지 않는다.**

    1차 구현이 이걸 놓쳐 '취업자수 ↔ 성별 경제활동인구 총괄' 같은
    정당한 매칭을 넷이나 막았다. 지표어는 항목·분류축에 있는 경우가 많다.
    """
    assert indicator_table_mismatch("취업자수", "성별 경제활동인구 총괄") == ""
    assert indicator_table_mismatch("출생아 수", "월.분기.연간 인구동향") == ""


def test_the_item_name_can_rescue_a_match():
    assert indicator_table_mismatch("사망자수", "월.분기.연간 인구동향",
                                    itm_name="사망자수") == ""


def test_the_axis_name_can_rescue_a_match():
    assert indicator_table_mismatch("반도체 수출액", "품목별 무역 통계",
                                    itm_name="금액", obj_names="반도체") == ""


# --------------------------------------------------------------------------
# 모르면 막지 않는다
# --------------------------------------------------------------------------
# `periodicity_unavailable` 과 같은 원칙이다. 오늘 아침에 이걸 놓쳐
# 커버리지를 통째로 날릴 뻔했다.

@pytest.mark.parametrize("indicator,table", [
    ("", "데이터 판매 서비스업 시장 규모"),
    ("자사주 직접취득", ""),
    (None, None),
])
def test_missing_information_never_blocks(indicator, table):
    assert indicator_table_mismatch(indicator, table, itm_name="매출액") == ""


def test_a_numeric_only_indicator_does_not_block():
    """토큰이 안 나오면 판단 근거가 없다."""
    assert indicator_table_mismatch("...", "데이터 판매 서비스업",
                                    itm_name="매출액") == ""


# --------------------------------------------------------------------------
# 2-그램
# --------------------------------------------------------------------------

def test_korean_is_split_into_bigrams():
    assert bigrams("수출액") == {"수출", "출액"}


def test_english_stays_whole():
    """'GDP' 를 'GD','DP' 로 쪼개면 잡음이 생긴다."""
    assert "GDP" in bigrams("GDP 성장률")
    assert "GD" not in bigrams("GDP 성장률")


def test_common_fragments_do_not_count_as_overlap():
    """'현황'·'지수'만 겹치는 것은 겹친 게 아니다.

    이걸 안 빼면 표 이름 대부분이 통과해 게이트가 무의미해진다.
    """
    assert "현황" not in bigrams("자동차 등록 현황")
    assert indicator_table_mismatch("자사주 취득 현황", "반도체 수출 현황",
                                    itm_name="수출액")


# --------------------------------------------------------------------------
# 파이프라인에 연결됐는가
# --------------------------------------------------------------------------

def test_validate_runs_the_gate():
    """함수만 만들고 연결하지 않으면 아무 일도 일어나지 않는다.

    오늘 `periodicity_unavailable` 에서 변수명 하나로 20분을 날렸다.
    """
    import inspect

    import kosis_validate_mapping_candidates as validate
    source = inspect.getsource(validate.semantic_ready_gate)
    assert "indicator_table_mismatch(" in source
    assert "INDICATOR_TABLE_MISMATCH" in source


def test_it_defers_rather_than_rejects():
    """**'불일치'라고 단언하지 않는다.**

    semantic_ready_gate 의 사유는 NEEDS_CONFIRMATION 으로 내려간다.
    오늘 확정 14건 중 불일치 8건이었고 최소 6건이 오판이었다.
    참인 기사에 거짓 딱지를 붙이는 것이 최악이다.
    """
    import inspect

    import kosis_validate_mapping_candidates as validate
    source = inspect.getsource(validate.apply_semantic_ready_gate)
    assert "NEEDS_CONFIRMATION" in source


def test_there_is_one_implementation():
    """가드가 두 벌이면 반드시 어긋난다. 오늘 그 실수를 세 번 했다."""
    import kosis_indicator_table_match as canonical
    import kosis_validate_mapping_candidates as validate
    assert validate.indicator_table_mismatch is canonical.indicator_table_mismatch
