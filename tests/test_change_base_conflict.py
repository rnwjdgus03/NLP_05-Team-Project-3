"""비교 기준이 문장과 어긋나면 판정하지 않는다 (2026-08-02).

네 번째 거짓 불일치 원인. 앞의 셋과 성격이 또 달랐다.
  1 확정 경로에 claim 품목 가드 누락
  2 상류 추출이 문장에 없는 대상을 부착
  3 한계값 서술을 값 주장으로 처리
  4 이 건 — 시점 지시어를 비교 기준으로 오독

실측:
  "작년 12월 수출은 613억8000만달러로 1년 전 대비 6.6% 늘어
   한 달 전(1.4%)에 비해 오름폭을 키웠다"
  '한 달 전(1.4%)'은 11월의 **전년동월비**다. 추출이 '한 달 전'을 비교 기준으로 읽어
  change_base=전월 로 넣었고, 검증기가 11월 vs 10월(-2.1%)을 계산해 '불일치'라 단언했다.
  실제 11월 전년동월비는 +1.4% 로 주장은 참이다.
"""
import pytest

from kosis_verify_claim_values import change_base_conflicts

OBSERVED = ("작년 12월 수출은 613억8000만달러로 1년 전 대비 6.6% 늘어 "
            "한 달 전(1.4%)에 비해 오름폭을 키웠다.")


# --------------------------------------------------------------------------
# 잡아야 하는 것
# --------------------------------------------------------------------------

def test_the_observed_false_mismatch():
    assert change_base_conflicts({"change_base": "전월", "claim_text": OBSERVED})


@pytest.mark.parametrize("phrase", ["1년 전 대비", "전년 대비", "전년 동월", "작년 같은 달"])
def test_year_basis_phrases(phrase):
    assert change_base_conflicts({"change_base": "전월",
                                  "claim_text": f"수출이 {phrase} 6.6% 늘었다"})


def test_reason_names_the_evidence():
    got = change_base_conflicts({"change_base": "전월", "claim_text": OBSERVED})
    assert "1년 전" in got and "전월" in got


# --------------------------------------------------------------------------
# 잡으면 안 되는 것
# --------------------------------------------------------------------------

def test_explicit_month_basis_wins():
    """문장이 전월 기준을 명시하면 충돌이 아니다."""
    text = "11월 생산은 전월 대비 0.4% 줄었다"
    assert change_base_conflicts({"change_base": "전월", "claim_text": text}) == ""


def test_both_phrases_present_is_not_a_conflict():
    """전월 기준이 명시돼 있으면 전년 표현이 함께 있어도 통과시킨다."""
    text = "11월 생산은 전월 대비 0.4% 줄었고, 전년 대비로는 늘었다"
    assert change_base_conflicts({"change_base": "전월", "claim_text": text}) == ""


def test_year_base_is_not_checked():
    """change_base 가 전년이면 이 규칙의 대상이 아니다."""
    assert change_base_conflicts({"change_base": "전년", "claim_text": OBSERVED}) == ""


def test_empty_inputs():
    assert change_base_conflicts({}) == ""
    assert change_base_conflicts({"change_base": "전월", "claim_text": ""}) == ""


def test_month_basis_without_year_phrase_is_fine():
    text = "지난달보다 소폭 늘었다"
    assert change_base_conflicts({"change_base": "전월", "claim_text": text}) == ""


# --------------------------------------------------------------------------
# 검증기에 연결됐는가
# --------------------------------------------------------------------------

def test_verify_row_abstains_on_conflict():
    import kosis_verify_claim_values as verify
    out = verify.verify_row(
        {"mapping_status": "READY", "value": "1.4", "unit": "%", "period": "202411",
         "change_base": "전월", "comparison_period": "202410",
         "claim_text": OBSERVED, "mapping_type": "direct"},
        meta_cache={}, delay=0)
    assert out["verdict"] == "판단불가"
    assert out["verdict_code"] == "CHANGE_BASE_AMBIGUOUS"
