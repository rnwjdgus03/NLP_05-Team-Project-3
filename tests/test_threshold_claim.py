"""한계값 서술을 값 주장으로 판정하지 않는다 (2026-08-02).

실측 거짓 불일치:
  "성장률과 물가 상승률이 모두 2%를 밑돈 경우는 2020년이 마지막이었다"
  2% 는 측정값이 아니라 한계값이다. 2020년 실제 물가상승률 0.54% 는 2% 미만이므로
  **주장은 참**인데 검증기가 '주장 2 vs 실제 0.54 → 불일치'로 단언했다.

한계값 비교를 제대로 구현하려면 방향(미만/초과)을 정확히 읽어야 하고,
틀리면 새로운 거짓 판정이 생긴다. 지금은 판정하지 않는다 —
틀린 답을 내는 것보다 못 한다고 말하는 편이 낫다.
"""
import pytest

from kosis_verify_claim_values import threshold_expression


# --------------------------------------------------------------------------
# 잡아야 하는 것
# --------------------------------------------------------------------------

def test_the_observed_false_mismatch():
    text = "성장률과 물가 상승률이 모두 2%를 밑돈 경우는 2020년이 마지막이었다."
    assert threshold_expression(text, 2.0)


@pytest.mark.parametrize("text,value", [
    ("2년 연속 700억 달러 이상의 호실적을 이어갔다", 700),
    ("환율이 1400원 선을 넘어섰다", 1400),
    ("증가율이 3% 미만에 그쳤다", 3),
    ("실업률이 4%를 웃돌았다", 4),
])
def test_threshold_forms(text, value):
    assert threshold_expression(text, value)


# --------------------------------------------------------------------------
# 잡으면 안 되는 것 — 정상 값 주장
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("작년 12월 수출은 613억8000만달러로 1년 전 대비 6.6% 늘었다", 6.6),
    ("반도체가 43.9% 증가한 1419억 달러를 기록했다", 43.9),
    ("전체 수입이 전년 대비 1.6% 감소했다", 1.6),
])
def test_plain_value_claims_are_not_thresholds(text, value):
    assert threshold_expression(text, value) == ""


def test_marker_far_from_the_value_is_ignored():
    """문장 어딘가에 '이상'이 있다는 이유로 막으면 정상 주장까지 잃는다."""
    text = "수출이 6.6% 늘었고, 이는 기대 이상의 결과라는 평가가 시장에서 나오고 있다"
    assert threshold_expression(text, 6.6) == ""


# --------------------------------------------------------------------------
# 경계
# --------------------------------------------------------------------------

def test_missing_inputs():
    assert threshold_expression("", 2.0) == ""
    assert threshold_expression("2%를 밑돈", None) == ""
    assert threshold_expression(None, 2.0) == ""


def test_value_not_in_text():
    assert threshold_expression("수출이 늘었다", 6.6) == ""


def test_integer_value_formatting():
    """2.0 을 '2.0'으로 찾으면 '2%'를 놓친다."""
    assert threshold_expression("2%를 밑돈 해였다", 2.0)


def test_returned_text_shows_the_evidence():
    got = threshold_expression("성장률이 2%를 밑돈 해", 2.0)
    assert "밑돈" in got


# --------------------------------------------------------------------------
# 검증기에 연결됐는가
# --------------------------------------------------------------------------

def test_verify_row_abstains_on_threshold_claims():
    import kosis_verify_claim_values as verify
    out = verify.verify_row(
        {"mapping_status": "READY", "value": "2", "unit": "%", "period": "2020",
         "claim_text": "성장률과 물가 상승률이 모두 2%를 밑돈 경우는 2020년이 마지막이었다.",
         "mapping_type": "direct"},
        meta_cache={}, delay=0)
    assert out["verdict"] == "판단불가"
    assert out["verdict_code"] == "THRESHOLD_CLAIM_UNSUPPORTED"
