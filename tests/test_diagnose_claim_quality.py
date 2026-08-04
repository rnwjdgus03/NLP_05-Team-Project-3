"""상류 추출 품질 진단 테스트.

실제 실패 사례에서 관찰된 패턴을 그대로 고정한다:
  "…화장품 수출("            괄호가 열린 채 잘림
  "7 2023년 국적기로…"        앞에 숫자 파편
  롤렉스/포카리스웨트 개별 상품가  KOSIS 범위 밖 (기계로는 판정 불가 → 사람 확인)
"""
from diagnose_claim_quality import (
    diagnose,
    period_in_text,
    quality_flags,
    token_overlap,
    unit_in_text,
    value_in_text,
)


def _claim(**kw):
    base = {"claim_measurement_id": "M1", "claim_text": "작년 수출액은 6838억달러였다.",
            "value": "6838", "unit": "억달러", "measurement_period": "2024",
            "measurement_indicator": "수출액", "mapping_type": "direct"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 원문 대조 — 추출값이 문장에 실제로 있는가
# --------------------------------------------------------------------------

def test_value_matches_ignoring_commas():
    assert value_in_text("4720", "여객 4,720만여 명") is True
    assert value_in_text("1373", "1373만원으로 올렸다") is True


def test_value_absent_from_text_is_detected():
    """추출값이 원문에 없으면 추출 오류다 — 검색을 아무리 잘해도 못 맞춘다."""
    assert value_in_text("9999", "작년 수출액은 6838억달러였다") is False


def test_empty_value_is_not_a_match():
    assert value_in_text("", "6838억달러") is False


def test_unit_alias_is_recognized():
    assert unit_in_text("%", "6.3퍼센트 올랐다") is True
    assert unit_in_text("달러", "151억 달러를 기록") is True
    assert unit_in_text("명", "4720만여 명") is True


def test_relative_period_expression_counts_as_grounded():
    """'작년'만 있어도 문장 안에 시점 근거가 있는 것으로 본다."""
    assert period_in_text("2024", "작년 수출액은 6838억달러였다") is True
    assert period_in_text("202412", "2024년 12월 수출은") is True


def test_period_with_no_textual_anchor_is_inherited():
    assert period_in_text("2024", "수출액은 6838억달러였다") is False


def test_indicator_token_overlap():
    assert token_overlap("수출액", "작년 수출액은") is True
    assert token_overlap("산업생산지수", "출생아 수가 늘었다") is False


# --------------------------------------------------------------------------
# 문장 경계 품질 — 실제 관찰된 파손 패턴
# --------------------------------------------------------------------------

def test_sentence_cut_mid_word_is_flagged_as_truncated():
    flags = quality_flags(_claim(
        claim_text="농수산식품 수출은 117억 달러(7.6%), 화장품 수출("), 1)
    assert flags["truncated"] is True
    assert flags["unbalanced_paren"] is True


def test_leading_numeric_fragment_is_flagged():
    flags = quality_flags(_claim(
        claim_text="7 2023년 국적기로 국제선을 이용한 여객 4720만여 명이었다."), 1)
    assert flags["leading_fragment"] is True


def test_well_formed_sentence_is_not_flagged():
    flags = quality_flags(_claim(), 1)
    assert flags["truncated"] is False
    assert flags["leading_fragment"] is False
    assert flags["unbalanced_paren"] is False
    assert flags["problem_count"] == 0


def test_quote_after_ending_still_counts_as_complete():
    flags = quality_flags(_claim(claim_text='"자금 조달이 어렵다"고 대답했다.'), 1)
    assert flags["truncated"] is False


# --------------------------------------------------------------------------
# 한 문장에서 measurement 를 여러 개 쪼갠 경우
# --------------------------------------------------------------------------

def test_crowded_sentence_is_flagged():
    """롤렉스 문장 하나에서 m2/m3/m4 세 개가 나왔다."""
    flags = quality_flags(_claim(), siblings=3)
    assert flags["crowded_sentence"] is True


def test_two_measurements_is_not_yet_crowded():
    assert quality_flags(_claim(), siblings=2)["crowded_sentence"] is False


def test_siblings_counted_from_shared_claim_text():
    same = "롤렉스는 1292만원에서 1373만원으로 81만원(6.3%) 올렸다."
    claims = [_claim(claim_measurement_id=f"M{i}", claim_text=same) for i in range(3)]
    rows = diagnose(claims, [])
    assert all(r["measurements_from_same_text"] == 3 for r in rows)
    assert all(r["crowded_sentence"] for r in rows)


# --------------------------------------------------------------------------
# 스키마 결측
# --------------------------------------------------------------------------

def test_missing_mapping_type_is_flagged():
    """오늘 확인된 실제 결측 — C 경로 rate 예외가 이것 때문에 죽어 있었다."""
    assert quality_flags(_claim(mapping_type=""), 1)["mapping_type_missing"] is True


def test_missing_period_counts_as_problem():
    flags = quality_flags(_claim(measurement_period=""), 1)
    assert flags["period_missing"] is True
    assert "period_missing" in flags["problems"]


# --------------------------------------------------------------------------
# 검색 결과와의 결합
# --------------------------------------------------------------------------

def test_retrieval_outcome_is_joined():
    rows = diagnose([_claim()], [{"claim_measurement_id": "M1",
                                  "failure_class": "TABLE_MISS"}])
    assert rows[0]["retrieval_outcome"] == "TABLE_MISS"


def test_measurement_without_retrieval_row_is_marked():
    rows = diagnose([_claim()], [])
    assert rows[0]["retrieval_outcome"] == "(평가대상아님)"


def test_clean_claim_is_routed_to_human_check():
    """기계가 문제를 못 찾았다고 '정상'이 아니다 — 의미·범위는 사람이 봐야 한다."""
    rows = diagnose([_claim()], [])
    assert rows[0]["needs_human_check"] is True
