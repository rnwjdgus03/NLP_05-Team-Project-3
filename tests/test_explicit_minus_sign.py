"""원문에 명시된 마이너스 부호 복원 (2026-07-31).

실측 사고:
  기사 "생산은 작년 9월(-0.4%)·10월(-0.2%)·11월(-0.4%) 등 3개월 연속으로 전월 대비 감소했다"
  추출 value = 0.4 (부호 없음)
  KOSIS 실제 = -0.61%
  → 부호가 빠져 차이가 1.01%p 로 부풀었다. 올바른 비교는 |-0.61 - (-0.4)| = 0.21%p.

'감소' 는 값에서 20자 넘게 떨어져 있어 기존 방향어 규칙(값 뒤 6자)이 닿지 않았다.
원문의 마이너스가 더 확실한 신호이므로 이를 먼저 본다.
"""
from kosis_verify_claim_values import signed_claim_value


def _row(claim_text, value, **kw):
    base = {"claim_text": claim_text, "value": str(value),
            "measurement_text": str(value), "value_type": "증감률"}
    base.update(kw)
    return base


REAL = ("지난달 30일 발표된 통계청의 ‘11월 산업활동동향’에 따르면, 생산은 "
        "작년 9월(-0.4%)·10월(-0.2%)·11월(-0.4%) 등 3개월 연속으로 전월 대비 감소했다.")


# --------------------------------------------------------------------------
# 실측 사례
# --------------------------------------------------------------------------

def test_minus_inside_parenthesis_is_restored():
    assert signed_claim_value(_row(REAL, "0.2"), 0.2) == -0.2


def test_first_occurrence_of_the_value_is_used():
    """'0.4' 는 9월과 11월 두 번 나오는데 둘 다 음수라 결과가 같아야 한다."""
    assert signed_claim_value(_row(REAL, "0.4"), 0.4) == -0.4


def test_positive_value_without_marker_is_untouched():
    text = "12월 수출은 614억달러로 6.6% 증가했다."
    assert signed_claim_value(_row(text, "6.6"), 6.6) == 6.6


# --------------------------------------------------------------------------
# 부호 표기 변형
# --------------------------------------------------------------------------

def test_various_minus_marks():
    for mark in ("-", "−", "△", "▲", "↓"):
        text = f"성장률은 {mark}0.5% 였다."
        assert signed_claim_value(_row(text, "0.5"), 0.5) == -0.5, mark


def test_minus_with_space_and_bracket():
    assert signed_claim_value(_row("전월비 ( -1.2% ) 를 기록", "1.2"), 1.2) == -1.2


# --------------------------------------------------------------------------
# 오탐 방지 — 값 앞의 다른 문자가 마이너스를 가리면 안 된다
# --------------------------------------------------------------------------

def test_hyphen_in_range_is_not_a_sign():
    """'1~9월' 같은 범위 표기의 물결/하이픈을 부호로 읽으면 안 된다."""
    text = "2024년 1~9월 수출증가율은 9.6% 였다."
    assert signed_claim_value(_row(text, "9.6"), 9.6) == 9.6


def test_letter_before_value_blocks_the_sign():
    text = "증가율 A0.4% 수준"
    assert signed_claim_value(_row(text, "0.4"), 0.4) == 0.4


def test_level_value_is_never_signed():
    """수준값(억달러 등)에는 방향 부호를 적용하지 않는다."""
    text = "수입액은 -6320억달러였다."
    row = _row(text, "6320", value_type="수준값", measurement_role="현재값")
    assert signed_claim_value(row, 6320.0) == 6320.0


# --------------------------------------------------------------------------
# 기존 방향어 규칙과의 우선순위
# --------------------------------------------------------------------------

def test_explicit_direction_field_still_wins():
    row = _row("전월 대비 0.4% 였다", "0.4", direction="증가")
    assert signed_claim_value(row, 0.4) == 0.4


def test_adjacent_direction_word_still_works():
    text = "전체 수입이 전년 대비 1.6% 감소한 덕에"
    assert signed_claim_value(_row(text, "1.6"), 1.6) == -1.6


def test_distant_direction_word_still_ignored():
    """'1.4%로 계속 감소 중' 은 추세 서술이므로 부호를 건드리지 않는다(기존 규칙 유지)."""
    text = "물가는 1.4%로 계속 감소 추세다"
    assert signed_claim_value(_row(text, "1.4"), 1.4) == 1.4


def test_missing_value_returns_none():
    assert signed_claim_value(_row("문장", "1"), None) is None
