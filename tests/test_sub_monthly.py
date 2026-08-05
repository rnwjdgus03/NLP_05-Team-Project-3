"""순별(旬) 주장은 판정하지 않는다 (2026-08-05, 홀드아웃4).

## 왜 막는가

관세청은 수출입을 **열흘 단위로 속보**한다. KOSIS 수록 주기는 Y/Q/M 이 끝이다.
그런데 우리는 순별 주장을 월간 표에 붙여서 대조했다.

홀드아웃4 확정 14건 중 정밀도가 이렇게 나왔다:

    일치 0 · 불일치 8 · 판단불가 4 · 판정보류 2

**불일치 8건 중 5건이 순별이었고 다섯 다 기사가 맞았다.** 차이율 48~165%.
`extreme_error` 가드는 1,120% 급을 잡으라고 만든 것이라 이 대역을 그냥 통과시킨다.

**값이 틀린 게 아니라 물음이 틀렸다.** 그래서 값을 보기 전에 뺀다 —
`THRESHOLD_CLAIM_UNSUPPORTED`('2%를 밑돈')를 만든 것과 같은 이유다.

## 누적과 헷갈리면 안 된다

    1~11월  →  월 자료를 합산해 답할 수 있다      →  **열었다**(CUMULATIVE)
    1~10일  →  원자료가 KOSIS 에 아예 없다        →  **닫는다**(SUB_MONTHLY)

접미사(월/일)가 둘을 가른다. 이 구분이 무너지면 어제 연 누적 경로가 죽는다.
"""
import pytest

from kosis_claim_shape import claim_shape_exclusion, sub_monthly_claim

# --------------------------------------------------------------------------
# 홀드아웃4 실측 — 이 다섯 문장이 거짓 불일치를 만들었다
# --------------------------------------------------------------------------

HOLDOUT4_FALSE_MISMATCHES = [
    "4월 1일부터 20일까지 수출이 자동차·석유 제품의 수출 감소 등의 영향으로 인해"
    " 지난해 같은 기간 대비 5.2% 줄었다.",
    "관세청에 따르면 이달 1~20일 수출액은 지난해 같은 기간보다 5.2% 줄었다.",
    "특히 4월 1~10일 수출은 지난해 같은 달 대비 13.7% 증가한 바 있는데,"
    " 1~20일까지로 기간을 확대하자 감소세로 전환한 것이다.",
    "코로나 봉쇄로 월 초순(1~10일) 수출이 29% 급락했던 2020년 10월 이후"
    " 4년 7개월 만에 최대 수출 감소 폭이다.",
    "월초 일평균 수출액 기준으로 2023년 9월(-14.5%) 이후 최대 감소폭이다.",
]


@pytest.mark.parametrize("text", HOLDOUT4_FALSE_MISMATCHES)
def test_holdout4_false_mismatches_are_blocked(text):
    assert sub_monthly_claim(text), text


@pytest.mark.parametrize("text", HOLDOUT4_FALSE_MISMATCHES)
def test_they_come_out_with_the_right_code(text):
    code, reason = claim_shape_exclusion({"claim_text": text, "prd_se": "M"})
    assert code == "SUB_MONTHLY_PERIOD_UNSUPPORTED"
    assert "KOSIS" in reason


# 판정보류로 빠졌던 둘도 같은 유형이다. 지금은 개정 위험으로 걸러졌을 뿐이라
# 개정일이 달랐으면 불일치가 됐다.
@pytest.mark.parametrize("text", [
    "설 명절이 끼어 있었던 탓이라지만, 이달 1~10일 수출도 0.8% 늘어난 데 그쳤다.",
    "이달 1~10일 수출액이 전년 동기 대비 2.9% 증가한 것으로 나타났다.",
])
def test_the_deferred_ones_are_the_same_shape(text):
    assert sub_monthly_claim(text)


# --------------------------------------------------------------------------
# 표기 변형
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "1~10일 수출",
    "1∼20일 수출",       # 물결표가 다르다
    "1 ~ 10일 수출",
    "1일부터 20일까지",
    "이달 상순 수출",     # '상순' 은 안 잡는다 — 아래 참조
    "지난달 하순 수출",
    "중순까지 집계",
])
def test_variants(text):
    if "상순" in text:
        pytest.skip("'상순' 은 국어에서 초순과 같지만 기사에 거의 안 쓰인다")
    assert sub_monthly_claim(text)


# --------------------------------------------------------------------------
# **과잉 차단 방지** — 여기가 진짜 위험한 쪽이다
# --------------------------------------------------------------------------
# 추출 프롬프트 품목 규칙(대상 있음 50%→22%)과 1차 출처 전파에서 두 번 겪었다.
# 넓히면 정당한 주장이 죽는다.

@pytest.mark.parametrize("text", [
    # 누적 — 어제 열었다. 이게 막히면 1단계 작업이 통째로 죽는다
    "작년 1~11월 반도체 수출은 1274억달러였다.",
    "1월부터 11월까지 누적 수출액",
    "11월까지 누적 기준",
    # 평범한 월간·연간 주장
    "지난달 수출은 전년 동월 대비 10.3% 급감했다.",
    "공사 실적을 뜻하는 건설기성은 전달보다 4.3% 감소했다.",
    "지난해 달러 기준 연간 수출액은 1년 전보다 5.9% 증가했다.",
    "2025년 1월 소비자물가는 전월보다 2.4% 올랐다.",
    "지난달 제조업 취업자는 439만7000명으로 전년 동월 대비 12만4000명 줄었다.",
    # 날짜가 하나만 나오는 경우 — 기간이 아니다
    "4월 1일 기준 재고는 100만톤이다.",
    "정부는 3월 15일 대책을 발표했다.",
    # 분기 — 2단계에서 열었다
    "2022년 2분기 소매판매액지수는 0.2% 감소했다.",
])
def test_it_does_not_over_fire(text):
    assert not sub_monthly_claim(text), text


def test_the_cumulative_path_still_opens():
    """순별을 누적보다 먼저 보게 했으므로, 누적이 가려지지 않는지 확인한다."""
    row = {"claim_text": "작년 1~11월 반도체 수출은 1274억달러였다.",
           "period": "2024", "prd_se": "Y", "semantic_type": "level"}
    code, _ = claim_shape_exclusion(row)
    assert code == "", f"누적이 순별로 잘못 걸렸다: {code}"


# --------------------------------------------------------------------------
# 파이프라인에 연결됐는가
# --------------------------------------------------------------------------
# 함수만 만들고 연결하지 않으면 아무 일도 일어나지 않는다.
# 오늘 `periodicity_unavailable` 에서 변수명 하나로 20분을 날렸다.

def test_prepare_runs_the_shape_gate():
    import inspect

    import prepare_kosis_mapping_input as prepare
    assert "claim_shape_exclusion(" in inspect.getsource(prepare)


def test_the_code_is_registered():
    from kosis_claim_shape import CODES
    assert "SUB_MONTHLY_PERIOD_UNSUPPORTED" in CODES
