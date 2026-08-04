"""집계 우선을 '순위 신호'로 넣는다 (2026-08-02).

근거(잠근 125건, 대상 미특정 46건):
  같은 축에 집계 코드가 있는데 세부를 고른 건이 C 32건 / A 8건.
  A 는 build_coordinates 의 집계 우선 정렬이 남아 있고, C 는 리랭커가 그걸 덮었다.
  골드 12건 시뮬레이션에서도 C obj@1 50.0% -> 66.7% (개선 2, 악화 0).
"""
import pytest

from kosis_meta_coordinates import (
    AGGREGATE_OBJ_NAMES,
    claim_specifies_target,
    is_aggregate_name,
    metadata_is_aggregate,
)


# --------------------------------------------------------------------------
# 목록 통합 — 같은 개념이 두 군데서 갈라져 있던 결함
# --------------------------------------------------------------------------

def test_validate_uses_the_canonical_list():
    """kosis_validate_mapping_candidates 가 자체 목록을 다시 만들지 않는다."""
    from kosis_validate_mapping_candidates import AGGREGATE_OBJ_NAMES as validate_list
    assert validate_list is AGGREGATE_OBJ_NAMES


def test_total_index_is_recognised():
    """골드 정답 T10(총지수)이 집계로 인정받지 못해 밀린 실측 사례가 근거."""
    assert is_aggregate_name("총지수") is True


def test_build_time_list_stays_separate():
    """빌드용 목록을 바꾸면 인덱스를 재빌드해야 한다 — 일부러 분리해 둔 것."""
    from kosis_meta_coordinates import AGGREGATE_NAMES
    assert "총지수" not in AGGREGATE_NAMES


@pytest.mark.parametrize("name", ["전산업생산지수", "전산업생산지수(원지수)", "원화대출금(계)"])
def test_known_gaps_are_still_missed(name):
    """접두·접미 매칭은 아직 안 넣었다. 넣으면 오탐도 같이 는다 — 별도 측정 후 결정."""
    assert is_aggregate_name(name) is False


def test_partial_match_does_not_leak_in():
    assert is_aggregate_name("합계출산율") is False
    assert is_aggregate_name("전국체전") is False


def test_whitespace_and_punctuation_are_ignored():
    assert is_aggregate_name(" 총 계 ") is True


# --------------------------------------------------------------------------
# 좌표가 집계인가
# --------------------------------------------------------------------------

def test_all_levels_must_be_aggregate():
    assert metadata_is_aggregate({"obj_l1_name": "전체", "obj_l2_name": "계"}) is True
    assert metadata_is_aggregate({"obj_l1_name": "전체", "obj_l2_name": "제조업"}) is False


def test_axis_free_coordinate_counts_as_aggregate():
    """분류축이 없는 표를 세부분류로 오인해 뒤로 밀면 안 된다."""
    assert metadata_is_aggregate({}) is True
    assert metadata_is_aggregate(None) is True


def test_levels_beyond_the_limit_are_ignored():
    meta = {"obj_l1_name": "계", "obj_l4_name": "제조업"}
    assert metadata_is_aggregate(meta, max_level=3) is True


# --------------------------------------------------------------------------
# 주장이 대상을 특정했는가
# --------------------------------------------------------------------------

def test_named_item_is_a_target():
    assert claim_specifies_target({"measurement_item": "반도체"}) is True


def test_aggregate_tokens_are_not_targets():
    for token in ("", "-", "전체", "총계", "합계", "총액"):
        assert claim_specifies_target({"measurement_item": token}) is False


def test_industry_field_is_read_first():
    assert claim_specifies_target({"industry_or_item": "건설업",
                                   "measurement_item": ""}) is True


def test_missing_claim_is_not_a_target():
    assert claim_specifies_target(None) is False


# --------------------------------------------------------------------------
# 정렬 키 — prd_se 보다 뒤, 점수보다 앞
# --------------------------------------------------------------------------

def _sort(candidates, prefer_aggregate):
    return sorted(candidates, key=lambda c: (
        0 if c["prd_se_match"] else 1,
        0 if (not prefer_aggregate or c["obj_aggregate"]) else 1,
        -c["final_rank_score"],
    ))


def _c(name, *, prd=True, agg=False, score=0.0):
    return {"name": name, "prd_se_match": prd, "obj_aggregate": agg,
            "final_rank_score": score}


def test_aggregate_wins_over_a_higher_score():
    ordered = _sort([_c("세부", score=9.0), _c("집계", agg=True, score=1.0)], True)
    assert ordered[0]["name"] == "집계"


def test_score_still_decides_within_the_same_group():
    ordered = _sort([_c("집계A", agg=True, score=1.0),
                     _c("집계B", agg=True, score=5.0)], True)
    assert ordered[0]["name"] == "집계B"


def test_period_mismatch_outranks_aggregate_preference():
    """기간 불일치가 더 강한 제약이다. 집계라는 이유로 끌어올리면 안 된다."""
    ordered = _sort([_c("주기맞음_세부", prd=True, score=1.0),
                     _c("주기틀림_집계", prd=False, agg=True, score=9.0)], True)
    assert ordered[0]["name"] == "주기맞음_세부"


def test_ordering_is_untouched_when_claim_names_a_target():
    ordered = _sort([_c("세부", score=9.0), _c("집계", agg=True, score=1.0)], False)
    assert ordered[0]["name"] == "세부"
