"""추출 프롬프트 — 무엇을 넣었고 무엇을 뺐는지 (2026-08-02).

프롬프트는 코드처럼 테스트할 수 없다. 다만 **결정이 지워지지 않았는지**는 지킬 수 있다.

## 뺀 것 — 품목 근거 규칙

거짓 불일치의 원인 중 하나가 상류 추출이었다.
`'작년 한 해 전체 수출액이 6838억달러'` 문장에 `item=반도체` 가 붙어
전체 수출액 6,838억을 반도체 수출액 1,420억과 대조하고 '불일치'라 단언했다.

프롬프트로 고치려 **두 번 시도했고 둘 다 원본보다 나빴다.** 444~449건 전수 측정:

| | 대상 있음 | 근거 없음 |
|---|---|---|
| 원본 | 222/443 (50%) | 39 |
| 1차 `'문장에 없으면 -'` | 117/444 (26%) | 14 |
| 2차 `'총계 문장에만'` 으로 좁힘 | 97/449 (22%) | 22 |

규칙을 좁혔는데 더 나빠졌다. 어떤 형태로 넣든 모델이 품목을 대거 버린다.
잃은 것 중에는 문장에 **있는** 품목이 많았다 —
`'폴크스바겐그룹 전기차 80만대'`, `'로봇이 주요 공정의 100%를 처리'`,
`'저비용항공사(LCC) 이용객 2419만명'`.

10문장 대조군에서는 이 문제가 안 보였다. 표본이 품목별 수출 유형뿐이었다.
**작은 표본으로 통과한 것을 전수로 다시 재는 것이 필요했다.**

→ 대신 하류에서 막는다: `prepare_kosis_mapping_input.claim_item_grounded`.

## 남긴 것 — 비교 기준 규칙

`'한 달 전(1.4%)'` 의 `change_base` 가 `전월` 로 잡혀 11월 대 10월(-2.1%)을 계산했다.
실제로는 11월의 전년동월비(+1.4%)였고 주장은 참이었다.
좁고 구체적인 규칙이라 남겼다. **다만 전수 검증은 하지 않았다.**
"""
import extract_hcx

PROMPT = extract_hcx.SYSTEM_PROMPT


# --------------------------------------------------------------------------
# 뺀 것이 다시 들어오지 않았는지
# --------------------------------------------------------------------------

def test_item_grounding_rule_is_not_in_the_prompt():
    """두 번 넣어봤고 두 번 다 나빴다. 다시 넣으려면 전수 측정부터 할 것."""
    for phrase in ("총계 문장에만", "[검증 대상 문장]에 나오면", "제목이나 앞뒤 문장의 품목"):
        assert phrase not in PROMPT


def test_schema_description_is_unconstrained():
    line = next(l for l in PROMPT.splitlines() if '"measurement_item"' in l)
    assert "총계" not in line and "[검증 대상 문장]" not in line


def test_the_experiment_is_recorded_in_source():
    """왜 뺐는지 남기지 않으면 다음 사람이 같은 시도를 반복한다."""
    import inspect
    source = inspect.getsource(extract_hcx)
    assert "두 번 시도했고 둘 다 원본보다 나빴다" in source
    assert "222/443" in source and "97/449" in source


def test_downstream_defence_is_named_as_the_alternative():
    import inspect
    assert "claim_item_grounded" in inspect.getsource(extract_hcx)


# --------------------------------------------------------------------------
# 남긴 것
# --------------------------------------------------------------------------

def test_change_base_rule_is_present():
    assert "시점을 가리키는 말은 change_base가 아니다" in PROMPT


def test_change_base_example_is_present():
    assert "한 달 전(1.4%)에 비해 오름폭을 키웠다" in PROMPT
    assert "전월이 아니다" in PROMPT


# --------------------------------------------------------------------------
# 프롬프트가 온전한지 — 문자열이 끊긴 적이 있다
# --------------------------------------------------------------------------

def test_prompt_is_not_truncated():
    """주석을 문자열 안에 넣어 프롬프트가 두 동강 난 적이 있다.

    그때 change_base 규칙과 마지막 규칙들이 통째로 사라졌는데
    코드는 정상 동작해서 눈치채기 어려웠다.
    """
    assert PROMPT.rstrip().endswith("빠짐없이 반영한다.")
    assert "## 출력 JSON 스키마" in PROMPT
    assert "## 판정 규칙" in PROMPT
    assert len(PROMPT) > 3000


def test_no_comment_leaked_into_the_prompt():
    assert "대상 있음 222" not in PROMPT
    assert "claim_item_grounded" not in PROMPT
