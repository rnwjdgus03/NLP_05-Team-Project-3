"""추출 프롬프트에 상류 오류 두 가지를 막는 규칙이 있는지 (2026-08-02).

프롬프트는 코드처럼 테스트할 수 없지만, **규칙이 지워지지 않았는지**는 지킬 수 있다.
아래 둘은 실측에서 거짓 불일치를 만든 원인이고, 지금은 하류에서 방어만 하고 있다.
프롬프트가 근본 수정이므로 규칙이 사라지면 방어에만 의존하게 된다.

  1. 문장에 없는 품목 부착
     '작년 한 해 전체 수출액이 6838억달러' 문장에 item=반도체가 붙었다.
     기사 제목이 반도체를 다뤘고, 프롬프트가 제목·앞뒤 문장을 함께 준다.
     그 결과 전체 수출액(6,838억)을 반도체 수출액(1,420억)과 대조해 '불일치'라 단언했다.

  2. 시점 지시어를 비교 기준으로 오독
     '한 달 전(1.4%)'의 change_base가 전월로 잡혔다. 실제로는 11월의 전년동월비다.
     11월 대 10월(-2.1%)을 계산해 '불일치'라 단언했고, 주장은 참이었다.
"""
import extract_hcx


PROMPT = extract_hcx.SYSTEM_PROMPT


# --------------------------------------------------------------------------
# 규칙 1 — 품목 근거
# --------------------------------------------------------------------------

def test_item_must_appear_in_the_target_sentence():
    assert "[검증 대상 문장]에 나올 때만" in PROMPT


def test_title_and_neighbours_are_explicitly_excluded():
    assert "제목이나 앞뒤 문장의 품목을 끌어오지 않는다" in PROMPT


def test_aggregate_sentence_example_is_present():
    """추상 규칙만으로는 모델이 안 지킨다. 실패한 문장을 그대로 예시로 넣었다."""
    assert "전체 수출액이 6838억달러" in PROMPT
    assert "item은 -다" in PROMPT


def test_legitimate_ellipsis_is_still_allowed():
    """앞 문장에서 대상을 이어받는 생략까지 막으면 정상 추출을 잃는다."""
    assert "앞 문장의 대상을 이어받는 생략은 허용한다" in PROMPT


def test_schema_fields_carry_the_same_constraint():
    """규칙 목록에만 쓰고 스키마 설명에 없으면 모델이 스키마를 따른다."""
    assert PROMPT.count("[검증 대상 문장]") >= 3


# --------------------------------------------------------------------------
# 규칙 2 — 비교 기준
# --------------------------------------------------------------------------

def test_time_pointer_is_not_a_change_base():
    assert "시점을 가리키는 말은 change_base가 아니다" in PROMPT


def test_change_base_example_is_present():
    assert "한 달 전(1.4%)에 비해 오름폭을 키웠다" in PROMPT
    assert "전월이 아니다" in PROMPT


# --------------------------------------------------------------------------
# 실측 근거를 프롬프트에 남긴다
# --------------------------------------------------------------------------

def test_observed_failures_are_recorded_in_the_prompt():
    """왜 이 규칙이 있는지 남기지 않으면 다음 사람이 지운다."""
    assert PROMPT.count("실측 오류") >= 2
