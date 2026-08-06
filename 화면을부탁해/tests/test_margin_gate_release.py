"""상류 표 점수 마진 조건 제거 (2026-08-02).

이 조건은 '1·2위 표 점수가 비슷하면 표 선택이 애매하다'는 상류 신호였다.
여기까지 온 후보는 이미 메타·API·단위·기간·의미 가드를 모두 독립 통과했다.
약한 상류 신호가 강한 하류 증거를 덮고 있었다.

**두 번 재고 나서 풀었다.**
  1차(평가집합 103) 마진만으로 막힌 5건 → 회수 2 · 거짓 불일치 2. 1:1 이라 유지
  2차(평가집합 88)  마진만으로 막힌 4건 → 회수 2 · 거짓 불일치 0. 풀었다

바뀐 이유는 그 거짓 불일치 2건의 정체다.
  '한 달 전(1.4%)' 비교 기준 오독 → CHANGE_BASE_AMBIGUOUS 로 보류하게 고침
  '정부의 한은 차입'            → 범위 밖. 출처 전파 강화로 집합에서 빠짐
마진이 막고 있던 것은 다른 게이트가 맡아야 할 일이었다.
"""
from kosis_validate_mapping_candidates import downstream_validated_rank1

PASSING = {
    "item_meta_valid": "true", "obj_meta_valid": "true",
    "response_code_valid": "true", "unit_valid": "true", "period_valid": "true",
}
ROW = {"candidate_rank": "1", "candidate_status": "ALTERNATE",
       "industry_or_item": "", "claim_text": "작년 수출액은 6838억달러였다"}
RESULT = {**PASSING, "selected_obj_l1_name": "계"}


def test_thin_margin_no_longer_blocks():
    """실측에서 막혔던 마진(625/621, 653/647, 546/544)이 이제 통과한다."""
    for score, runner_up in ((625, 621), (653, 647), (546, 544)):
        row = {**ROW, "candidate_score": str(score),
               "candidate_runner_up_score": str(runner_up)}
        assert downstream_validated_rank1(row, RESULT)


def test_wide_margin_still_passes():
    row = {**ROW, "candidate_score": "700", "candidate_runner_up_score": "600"}
    assert downstream_validated_rank1(row, RESULT)


def test_missing_score_still_passes():
    assert downstream_validated_rank1(ROW, RESULT)


# --------------------------------------------------------------------------
# 남은 안전 조건 — 하나라도 느슨해지면 오매핑이 확정된다
# --------------------------------------------------------------------------

def test_rank_must_be_one():
    assert not downstream_validated_rank1({**ROW, "candidate_rank": "2"}, RESULT)


def test_upstream_reject_still_blocks():
    assert not downstream_validated_rank1({**ROW, "candidate_status": "REJECT"}, RESULT)


def test_api_failure_still_blocks():
    assert not downstream_validated_rank1(ROW, {**RESULT, "response_code_valid": "false"})


def test_unit_failure_still_blocks():
    assert not downstream_validated_rank1(ROW, {**RESULT, "unit_valid": "false"})


def test_period_failure_still_blocks():
    assert not downstream_validated_rank1(ROW, {**RESULT, "period_valid": "false"})


def test_metadata_failure_still_blocks():
    assert not downstream_validated_rank1(ROW, {**RESULT, "item_meta_valid": "false"})


def test_semantic_guard_still_blocks():
    """대상 없는 주장에 세부 분류 좌표 — 마진을 풀어도 이건 막아야 한다.

    실측 오매핑: '전체 수출액' 주장에 objL1=반도체.
    """
    assert not downstream_validated_rank1(ROW, {**RESULT, "selected_obj_l1_name": "반도체"})


def test_named_item_mismatch_still_blocks():
    row = {**ROW, "industry_or_item": "석유화학",
           "claim_text": "석유화학 수출은 480억 달러였다"}
    assert not downstream_validated_rank1(row, {**RESULT, "selected_obj_l1_name": "가공한 석면섬유"})
