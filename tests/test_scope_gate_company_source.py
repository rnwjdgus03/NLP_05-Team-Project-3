"""게이트 보강 — 개별 기업 실적·기관 제출자료·국제기구 자료 (2026-08-02).

근거: 잠근 125건의 고유 문장 67개를 검수하니 30개(45%)가 KOSIS 범위 밖이었고,
      그중 20개가 개별 기업 실적(13)과 기관 제출자료(7)였다.
      기존 게이트는 기업명이 문장에만 있으면 REVIEW 로 두고 REJECT 하지 않았다.

원칙: '확정 못 했으니 뺀다'가 아니라 '**KOSIS 에 있을 수 없으니** 뺀다'.
      게이트를 조이면 분모가 줄어 커버리지 비율이 공짜로 오르므로,
      기준은 결과가 아니라 대상의 성격이어야 한다.
"""
import pytest

from kosis_scope_gate import REJECT, REVIEW, company_is_subject, gate_decision, scope_violation


def code_of(text):
    return scope_violation({"claim_text": text})[0]


def blocked(text):
    return gate_decision({"claim_text": text})["scope_gate_blocked"] == "Y"


# --------------------------------------------------------------------------
# 기업이 주장의 주체인가 — 조사로 가른다
# --------------------------------------------------------------------------

@pytest.mark.parametrize("particle", ["는", "가", "도", "의"])
def test_company_with_a_subject_particle(particle):
    assert company_is_subject(f"현대차{particle} 지난해 414만대를 판매했다") == "현대차"


def test_company_mentioned_without_a_particle_is_not_the_subject():
    """'현대차 등 완성차 업체' 처럼 예시로만 스치는 경우."""
    assert company_is_subject("현대차 등 완성차 업체들의 판매량이 줄었다") == ""


def test_industry_aggregate_passes():
    """이걸 막으면 정상 주장을 잃는다. 오탐 쪽이 더 나쁘다."""
    assert not blocked("작년 국내 완성차 업체들의 판매량이 2023년 대비 0.6% 줄었다")


# --------------------------------------------------------------------------
# 개별 기업 실적 → REJECT
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "현대차는 지난해 판매량이 414만 1791대로, 2023년 대비 1.8% 감소했다.",
    "기아는 작년 국내외에서 308만 9457대를 팔아 최고 실적을 올렸다.",
    "지난해 GM 한국사업장은 해외에 10.6% 증가한 47만 4735대를 판매했다.",
])
def test_single_company_metric_is_rejected(text):
    assert code_of(text) == "SINGLE_COMPANY_METRIC"
    assert blocked(text)


def test_company_without_a_metric_word_is_not_blocked():
    """실적 지표가 없으면 개별 기업 '자료'라 볼 근거가 약하다."""
    assert not blocked("현대차는 올해 신차를 세 종 선보인다")


# --------------------------------------------------------------------------
# 기업 열거 → REJECT
# --------------------------------------------------------------------------

def test_enumerated_companies_are_rejected():
    text = ("국내 완성차 5사(현대차, 기아, GM 한국사업장, KG모빌리티, 르노코리아)는 "
            "작년 794만7170대를 국내외에 판매했다.")
    assert code_of(text) == "ENUMERATED_COMPANIES"


def test_one_company_alone_is_not_enumeration():
    from kosis_scope_gate import enumerated_companies
    assert enumerated_companies("현대차 판매량이 줄었다", {}) is None


# --------------------------------------------------------------------------
# 기관 제출자료 → REJECT
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "임광현 의원이 한은에서 제출받은 자료에 따르면 정부는 173조원을 일시 차입했다.",
    "31일 본지가 국토교통부의 항공 정비사 통계를 분석한 결과 72.6%를 차지했다.",
    "의원실이 확보한 자료를 보면 이자는 2092억원이었다.",
])
def test_internal_document_source_is_rejected(text):
    assert code_of(text) in {"INTERNAL_DOCUMENT_SOURCE", "SINGLE_COMPANY_METRIC"}
    assert blocked(text)


def test_official_survey_is_not_an_internal_document():
    """'산업기술인력 수급 실태조사'는 KOSIS 수록 국가승인통계다."""
    assert not blocked("산업통상자원부의 산업기술인력 수급 실태조사에 따르면 5만8528명이었다")


# --------------------------------------------------------------------------
# 국제기구 — 확실한 것만 막는다
# --------------------------------------------------------------------------

def test_ifr_is_rejected():
    text = "국제로봇연맹(IFR)에 따르면 2023년 우리나라는 로봇 1012대를 쓰는 나라였다."
    assert code_of(text) == "FOREIGN_ORG_SOURCE"


def test_oecd_is_not_blocked_here():
    """OECD·IMF 는 KOSIS 국제통계에 일부 수록된다. 넓게 막으면 정상 주장을 잃는다."""
    assert code_of("OECD에 따르면 한국의 고용률은 62.7%였다") != "FOREIGN_ORG_SOURCE"


# --------------------------------------------------------------------------
# 통과해야 하는 것 — 오탐 방어
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "작년 한 해 전체 수출액이 6838억달러로 2023년에 비해 8.2% 증가했다.",
    "품목별로는 반도체가 43.9% 증가한 1419억 달러를 기록했다.",
    "통계청의 11월 산업활동동향에 따르면 생산은 3개월 연속 감소했다.",
    "11월 소매판매는 전년 동월과 비교하면 1.9% 줄었다.",
])
def test_verifiable_claims_still_pass(text):
    assert not blocked(text)


def test_severity_values_are_the_documented_ones():
    assert REJECT == "REJECT" and REVIEW == "REVIEW"
