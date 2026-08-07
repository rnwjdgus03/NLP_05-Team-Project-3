"""고른 표가 지표와 **아무 관계 없는** 것은 아닌가 (2026-08-05).

## 왜 필요한가

**병목은 좌표 선택이다.** 네 번 독립으로 쟀고 매번 같았다 —
홀드아웃3 38/46(83%), 홀드아웃4 95/119(80%). 표본을 3배로 늘려도 비율이 같다.

그런데 지금 파이프라인에는 **표가 지표와 맞는지 보는 검사가 없다.**
값이 그럴듯하면 통과한다. 실측:

    자사주 직접취득 11.8조   →  '데이터 판매 서비스업 시장 규모' 14.6조
                                차이율 24%. extreme_error(300%) 아래라 확정됐다.

    수입 커피 94.3% 폭등     →  '가공식품 품목별 구입경험 및 구입 변화'
    수출입물가지수 7% 상승   →  '연도별 소비자물가 등락률'

**값이 아니라 의미로 막아야 한다.** `CLAIM_ITEM_MISMATCH` 를 만든 것과 같은 이유다.

## 무엇으로 판단하는가

형태소 분석기 없이, **문자 2-그램이 하나도 안 겹치는가**를 본다.

    '자사주 직접취득'  →  자사 사주 직접 접취 취득
    '데이터 판매 서비스업 시장 규모'  →  데이 이터 판매 서비 비스 스업 시장 장규 규모
    교집합 없음  →  **무관하다**

    '소비자물가 상승률'  →  소비 비자 자물 물가 상승 승률
    '월별 소비자물가 등락률'  →  월별 별소 소비 비자 자물 물가 등락 락률
    교집합 있음  →  통과 (실제로 이건 우리가 맞다)

**겹침이 0 이라는 것은 매우 강한 신호다.** 한국어 통계 표 이름은 지표어를 거의
반드시 포함한다. 0 이면 검색이 엉뚱한 곳으로 간 것이다.

## 조사·인식 표는 뉴스 수치를 답할 수 없다

'구입경험', '인식', '만족도' 같은 표는 **의견을 측정한다.** 수출액·물가 같은
수준값 주장의 답이 될 수 없다. 어휘가 겹쳐도(커피↔커피) 막는다.

어제 출처 가린 라벨링에서 `없음` 8건 중 상당수가 이 계열이었다 —
로봇산업실태조사, 중소기업 도입률. `score_article_kosis_affinity.WEAK` 와 같은 관찰이다.

## **거부가 아니라 확정 보류다**

`semantic_ready_gate` 의 다른 사유들과 같이 `NEEDS_CONFIRMATION` 으로 내린다.
**'불일치'라고 단언하지 않는다.** 오늘 확정 14건 중 8건이 불일치였고
최소 6건이 오판이었다. 참인 기사에 거짓 딱지를 붙이는 것이 최악이다.

## 넓히지 말 것

전례가 셋 있다 — 추출 프롬프트 품목 규칙(대상 있음 50%→22%),
1차 출처 전파(로봇산업진흥원), `share_claim` 과잉 발동(수출액 1274억달러).
**바꾸면 첫 50건에서 기존 '일치' 7건이 하나도 안 빠지는지 반드시 확인할 것.**
"""
from __future__ import annotations

import re

# 의견·경험을 재는 표. 수준값 주장의 답이 될 수 없다.
# '실태조사' 는 넣지 않았다 — 로봇산업실태조사처럼 실제 수치를 담은 것도 있다.
_PERCEPTION = ("인식", "구입경험", "이용경험", "만족도", "애로", "의향",
               "선호도", "인지도", "필요성", "체감", "설문")

# 2-그램에서 뺄 흔한 조각. 이것만 겹치는 것은 겹친 게 아니다.
_STOP_BIGRAMS = frozenset({
    "현황", "총괄", "지수", "통계", "조사", "전체", "기타", "합계", "구성",
    "별로", "에서", "하는", "이상", "미만", "관련", "부문", "규모",
})

_TOKEN = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+")


# '물가'라는 공통 어휘만으로 서로 다른 물가지표가 통과하면 안 된다.
# 가격지표는 조사·작성기관까지 안정적으로 분리돼 있어 좁은 명시 규칙을 쓸 수 있다.
# KOSIS 기관코드: 101=통계청, 301=한국은행.
_PRICE_FAMILIES = (
    (
        "IMPORT_PRICE_CONCEPT_MISMATCH",
        ("수입물가", "수입물가지수"),
        ("수입물가", "수입물가지수", "수출입물가"),
        "301",
        ("한국은행",),
    ),
    (
        "EXPORT_PRICE_CONCEPT_MISMATCH",
        ("수출물가", "수출물가지수"),
        ("수출물가", "수출물가지수", "수출입물가"),
        "301",
        ("한국은행",),
    ),
    (
        "PRODUCER_PRICE_CONCEPT_MISMATCH",
        ("생산자물가", "생산자물가지수"),
        ("생산자물가", "생산자물가지수", "국내공급물가", "총산출물가"),
        "301",
        ("한국은행",),
    ),
    (
        "CONSUMER_PRICE_CONCEPT_MISMATCH",
        ("소비자물가", "소비자물가지수", "생활물가"),
        ("소비자물가", "소비자물가지수", "생활물가"),
        "101",
        ("통계청",),
    ),
)

_ALL_PRICE_FAMILY_TERMS = frozenset(
    term
    for _reason, claim_terms, mapped_terms, _org_id, _org_names in _PRICE_FAMILIES
    for term in (*claim_terms, *mapped_terms)
)


def _t(value) -> str:
    return "" if value is None else str(value).strip()


def bigrams(text) -> set[str]:
    """문자 2-그램. 형태소 분석기 없이 어휘 겹침을 재는 가장 단순한 방법이다.

    영문·숫자는 토큰 통째로 넣는다('GDP' 를 'GD','DP' 로 쪼개면 잡음이 생긴다).
    """
    out: set[str] = set()
    for token in _TOKEN.findall(_t(text)):
        if re.fullmatch(r"[가-힣]+", token):
            out.update(token[i:i + 2] for i in range(len(token) - 1))
        else:
            out.add(token.upper())
    return out - _STOP_BIGRAMS


def perception_table(tbl_name, itm_name="") -> str:
    """의견·경험을 재는 표인가. 맞으면 걸린 낱말."""
    haystack = f"{_t(tbl_name)} {_t(itm_name)}"
    for word in _PERCEPTION:
        if word in haystack:
            return word
    return ""


def _price_family_mismatch(
    indicator, mapped_text, *, org_id="", org_name="",
) -> str:
    """명시된 물가지표 계열과 표·분야·기관이 충돌하면 사유를 돌려준다."""
    claim = re.sub(r"\s+", "", _t(indicator))
    mapped = re.sub(r"\s+", "", _t(mapped_text))
    mapped_families = {
        term for term in _ALL_PRICE_FAMILY_TERMS if term in mapped
    }
    for reason, claim_terms, allowed_terms, expected_org_id, expected_org_names in _PRICE_FAMILIES:
        if not any(term in claim for term in claim_terms):
            continue
        if any(term in mapped for term in allowed_terms):
            return ""
        if mapped_families:
            return f"{reason}: 주장 '{_t(indicator)[:24]}' 과 선택 통계 '{_t(mapped_text)[:48]}' 의 물가지표 계열이 다르다"
        actual_org_id = _t(org_id)
        actual_org_name = _t(org_name)
        if actual_org_id and actual_org_id != expected_org_id:
            return f"{reason}: 주장 물가지표의 작성기관과 KOSIS 기관코드 {actual_org_id}가 다르다"
        if actual_org_name and not any(name in actual_org_name for name in expected_org_names):
            return f"{reason}: 주장 물가지표의 작성기관과 '{actual_org_name[:24]}'가 다르다"
        return ""
    return ""


def indicator_table_mismatch(
    indicator, tbl_name, itm_name="", obj_names="", category_path="",
    org_id="", org_name="",
) -> str:
    """표·항목이 지표와 무관하면 사유. 아니면 ''.

    **모르면 막지 않는다.** 지표가 비었거나 표 이름이 없으면 판단 근거가 없다 —
    `periodicity_unavailable` 과 같은 원칙이다. 없는 것을 '틀렸다'로 읽으면
    커버리지가 통째로 죽는다(오늘 아침에 한 번 밟았다).
    """
    indicator_text = _t(indicator)
    table_text = _t(tbl_name)
    if not indicator_text or not table_text:
        return ""

    word = perception_table(table_text, itm_name)
    if word:
        return f"의견·경험 표('{word}')는 수준값 주장을 답할 수 없다: {table_text[:40]}"

    mapped_context = " ".join(
        value for value in (
            table_text, _t(category_path), _t(itm_name), _t(obj_names), _t(org_name),
        ) if value
    )
    price_reason = _price_family_mismatch(
        indicator_text,
        mapped_context,
        org_id=org_id,
        org_name=org_name,
    )
    if price_reason:
        return price_reason

    # **표 이름만으로는 판단하지 않는다.** 지표어를 항목·분류축이 담는 경우가 많다 —
    #   취업자수   ↔  '성별 경제활동인구 총괄'  + 항목 '취업자'
    #   출생아 수  ↔  '월.분기.연간 인구동향'   + 분류2 '출생아수(명)'
    # 1차 구현이 표 이름만 봐서 이 넷을 전부 막았다. 테스트로 잡았다.
    # 항목·축 이름이 둘 다 없으면 정보가 모자란 것이므로 **막지 않는다.**
    detail = f"{_t(category_path)} {_t(itm_name)} {_t(obj_names)} {_t(org_name)}".strip()
    if not detail:
        return ""

    want = bigrams(indicator_text)
    if not want:
        return ""
    if want & bigrams(f"{table_text} {detail}"):
        return ""
    return (f"지표 '{indicator_text[:24]}' 가 표 '{table_text[:28]}' ·"
            f" 항목 '{detail[:24]}' 와 어휘를 하나도 공유하지 않는다")
