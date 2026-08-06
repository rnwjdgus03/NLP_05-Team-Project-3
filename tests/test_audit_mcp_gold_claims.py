"""MCP 골드셋(200건) 검수 (2026-08-06).

`mcp_full_gold_200.csv` 실측 — REFUTES 172/200(86%), human_reviewed 전부 'N'.
REFUTES 를 직접 읽고 찾은 네 패턴을 그대로 테스트로 박는다.
"""
import pytest

from audit_mcp_gold_claims import (audit, close_call_without_tolerance,
                                   hypothetical, narrow_item_mismatch,
                                   sub_monthly)


def row(**kwargs):
    base = {"claim_text": "", "claim_type": "CHANGE_RATE", "claim_value": "",
            "gold_label": "REFUTES", "gold_actual_value": "",
            "gold_category_name": ""}
    base.update(kwargs)
    return base


# --------------------------------------------------------------------------
# ① 좁은 품목코드 오매핑 — 실측 17건 중 대표 사례
# --------------------------------------------------------------------------

def test_a_total_export_claim_mismatched_to_a_narrow_semiconductor_code():
    reason = narrow_item_mismatch(
        "작년 한 해 전체 수출액이 6838억달러(약 1006조원)로 2023년에 비해 8.2% 증가했다",
        "다이오드트랜지스터 기타 이와 유사한 반도체 디바이스")
    assert reason
    assert "품목명" in reason


def test_a_trade_balance_claim_mismatched():
    """472억달러 무역수지 적자를 수출액 표와 대조한 사례."""
    reason = narrow_item_mismatch(
        "2022년 당시 수출액은 역대 최대를 기록하면서도 472억달러 적자를 냈던 것과 다른 결과다.",
        "다이오드트랜지스터 기타 이와 유사한 반도체 디바이스")
    assert reason


def test_a_genuine_semiconductor_claim_is_not_flagged():
    """**'반도체' 를 실제로 언급하면 막지 않는다.** 17건이 전부 오매핑은 아니다 —
    사람이 볼 대상으로 좁히는 것이지 자동으로 뒤집는 게 아니다.
    """
    reason = narrow_item_mismatch(
        "최대 수출품목인 반도체가 43.9% 증가한 1000억달러를 기록했다",
        "다이오드트랜지스터 기타 이와 유사한 반도체 디바이스")
    assert reason == ""


def test_missing_information_does_not_flag():
    assert narrow_item_mismatch("", "다이오드트랜지스터") == ""
    assert narrow_item_mismatch("전체 수출액", "") == ""


def test_aggregate_category_names_are_never_flagged():
    """**집계 이름은 예외다.** `총액`·`전국`·`총지수` 는 맞는 좌표라도

    뉴스 문장에 그 글자가 그대로 나오는 일이 거의 없다
    ('전체 수출액'은 '총액' 이라는 글자를 안 담는다).
    1차 구현이 이걸 놓쳐 120건 중 90건이 헛불이었다. `kosis_meta_coordinates`
    의 `AGGREGATE_OBJ_NAMES` 를 그대로 가져와 막는다 — 가드는 한 벌만 둔다.
    """
    assert narrow_item_mismatch("작년 한 해 전체 수출액이 6838억달러", "총액") == ""
    assert narrow_item_mismatch("전월보다 2.4% 올랐다", "총지수") == ""
    assert narrow_item_mismatch("소비자물가는 2.4% 올랐다", "전국") == ""


def test_a_genuine_age_bracket_mismatch_is_still_caught():
    """홀드아웃4 실측 — '60~64세' 은퇴 주장이 '15세 이상 전체' 로,

    '50대' 취업자 주장이 '30-39세' 로 매핑됐다. 집계 예외가 아니라
    **구체적인 다른 연령대** 라서 이건 계속 잡아야 한다.
    """
    reason = narrow_item_mismatch(
        "법적 정년 이후인 60~64세에 그만뒀다는 응답이 가장 많았다",
        "15세 이상 전체")
    assert reason


def test_a_genuine_narrow_item_mismatch_is_still_caught():
    """총지수 주장이 특정 품목('가전제품')에 매핑된 경우도 잡아야 한다."""
    reason = narrow_item_mismatch(
        "임시 공휴일 지정에도 소매 판매액 지수가 전월 대비 0.8% 감소했다",
        "가전제품")
    assert reason


# --------------------------------------------------------------------------
# ② 허용오차 없는 근접 판정 — 실측 23건 중 대표 사례
# --------------------------------------------------------------------------

def test_close_change_rate_is_flagged():
    """'18% vs 실제 17.57%' — 차이 0.43%p. 기사가 반올림한 것뿐이다."""
    reason = close_call_without_tolerance(row(
        claim_type="CHANGE_RATE", claim_value="18.0",
        gold_actual_value="17.567889494710244"))
    assert reason
    assert "%p" in reason


def test_a_genuinely_large_gap_is_not_flagged():
    """'16% vs 실제 -12.61%' — 부호까지 반대다. 이건 진짜 큰 차이다."""
    reason = close_call_without_tolerance(row(
        claim_type="CHANGE_RATE", claim_value="16.7",
        gold_actual_value="-12.61"))
    assert reason == ""


def test_close_level_uses_relative_error():
    """수준값은 %p 가 아니라 상대오차로 잰다. 절대값 자체가 다르기 때문이다."""
    reason = close_call_without_tolerance(row(
        claim_type="LEVEL", claim_value="6838.0", gold_actual_value="6836.09488"))
    assert reason
    assert "상대오차" in reason


def test_supports_rows_are_never_flagged_by_this_check():
    """이미 SUPPORTS 인 것은 볼 필요가 없다. REFUTES 만 재심사 대상이다."""
    reason = close_call_without_tolerance(row(
        gold_label="SUPPORTS", claim_type="CHANGE_RATE",
        claim_value="18.0", gold_actual_value="17.57"))
    assert reason == ""


def test_missing_values_do_not_flag():
    assert close_call_without_tolerance(row(claim_value="", gold_actual_value="")) == ""


# --------------------------------------------------------------------------
# ③ 순별 — kosis_claim_shape 와 같은 판정을 쓴다
# --------------------------------------------------------------------------

def test_sub_monthly_claim_is_flagged():
    reason = sub_monthly(row(
        claim_text="13일 관세청이 발표한 올해 1월 1일~10일 수출입현황에 따르면, "
                   "수출은 160억400만달러로 전년 같은 기간보다 3.8% 늘었다"))
    assert reason
    assert "순별" in reason


def test_a_monthly_claim_is_not_flagged():
    reason = sub_monthly(row(claim_text="지난달 수출은 전년 동월 대비 10.3% 급감했다"))
    assert reason == ""


def test_it_uses_the_same_function_as_the_pipeline():
    """가드가 두 벌이면 반드시 어긋난다. 오늘 이미 세 번 겪었다."""
    import audit_mcp_gold_claims as audit_mod
    import kosis_claim_shape as canonical
    assert audit_mod.sub_monthly_claim is canonical.sub_monthly_claim


# --------------------------------------------------------------------------
# ④ 가정법·전망
# --------------------------------------------------------------------------

def test_a_conditional_claim_is_flagged():
    reason = hypothetical(row(
        claim_text="1월 수출이 감소할 경우 2023년 9월(-4.4%) 이후 1년 4개월 만에 처음으로"
                   " 전년 동월 대비 수출액이 마이너스를 기록"))
    assert reason
    assert "가정법" in reason


def test_a_forecast_claim_is_flagged():
    reason = hypothetical(row(
        claim_text="연구원은 올해 내수가 완만히 개선되는 가운데 수출 증가세가 둔화하면서"
                   " 경제성장률은 작년에 비해 다소 하락한 2% 수준이 될 것으로 전망했다"))
    assert reason


def test_a_factual_claim_is_not_flagged():
    assert hypothetical(row(claim_text="지난달 수출은 전년 동월 대비 10.3% 급감했다")) == ""


# --------------------------------------------------------------------------
# 통합 — 여러 패턴에 동시에 걸릴 수 있다
# --------------------------------------------------------------------------

def test_audit_collects_every_hit():
    hits = audit(row(
        claim_text="1월 1일~10일 수출은 3.8% 늘었다",
        claim_type="CHANGE_RATE", claim_value="3.8",
        gold_actual_value="-4.97",
        gold_category_name="다이오드트랜지스터 기타 이와 유사한 반도체 디바이스"))
    codes = {code for code, _ in hits}
    assert "SUB_MONTHLY" in codes
    assert "NARROW_ITEM_MISMATCH" in codes


def test_a_clean_row_has_no_hits():
    """네 패턴 중 아무것도 안 걸리는 정상 행이 있어야 이 도구가 의미가 있다.

    차이가 허용폭(5%p) 을 크게 넘고, 품목명('중국')이 문장에 그대로 있고,
    순별·가정법도 아닌 경우다.
    """
    hits = audit(row(
        claim_text="지난해 중국 수출액은 1330억2600만달러로 전년 대비 6.6% 늘었다",
        claim_type="CHANGE_RATE", claim_value="6.6", gold_actual_value="25.4",
        gold_category_name="중국"))
    assert hits == []


def test_the_abbreviation_daejung_is_a_known_gap():
    """**한계를 숨기지 않는다.** '대중 수출'(對中, 중국을 향한) 처럼 줄임말을 쓰면

    '중국' 이라는 글자가 문장에 없어 2-그램이 안 겹친다. 이 경우 오탐이
    날 수 있다 — 그래서 결과를 자동으로 뒤집지 않고 '의심'으로만 둔다.
    """
    reason = narrow_item_mismatch("대중 수출액은 1330억2600만달러로 늘었다", "중국")
    assert reason, "이 한계를 스크립트를 넓혀 고치기 전엔 실측으로 먼저 확인할 것"


# --------------------------------------------------------------------------
# 자동으로 라벨을 뒤집지 않는다
# --------------------------------------------------------------------------

def test_the_script_only_splits_it_does_not_relabel():
    """'의심' 은 사람이 볼 대상이지 오답이 확정된 것이 아니다.

    main() 이 gold_label 을 다시 쓰면 안 된다 — 이 도구의 역할은 분류이지 채점이 아니다.
    """
    import inspect

    import audit_mcp_gold_claims as audit_mod
    main_source = inspect.getsource(audit_mod.main)
    assert '["gold_label"]' not in main_source
    assert "gold_label\"] =" not in main_source
    assert "이 스크립트가 아는 네 가지" in main_source
