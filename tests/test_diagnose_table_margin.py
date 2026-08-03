"""표 검색이 1위와 2위를 구분하는가 (2026-08-02).

'후보 비결정' 24건에서 맞는 매핑 3건이 전부 점수 마진에 걸렸다.
625/621, 653/647, 546/544 — 모두 1% 미만이다.
그런데 그건 3건짜리 근거다. 표 검색 전반이 그런지는 재본 적이 없다.

핵심 질문은 '얇은 마진이 흔한가'가 아니라 **'얇은 마진이 나쁜 결과와 이어지는가'** 다.
1위가 맞는 표라면 마진이 얇아도 문제가 아니다.
'구분을 못 한다'와 '구분할 필요가 없다'는 다르다.
"""
from diagnose_table_margin import MIN_ABSOLUTE, MIN_RELATIVE, bucket_label, is_thin, margin_of


def _row(score, runner_up):
    return {"candidate_score": str(score), "candidate_runner_up_score": str(runner_up)}


# --------------------------------------------------------------------------
# 마진 계산
# --------------------------------------------------------------------------

def test_margin_is_the_gap_to_the_runner_up():
    absolute, relative = margin_of(_row(625, 621))
    assert absolute == 4
    assert round(relative, 4) == round(4 / 625, 4)


def test_missing_score_yields_none():
    assert margin_of({"candidate_score": "", "candidate_runner_up_score": "5"}) == (None, None)
    assert margin_of({"candidate_score": "abc", "candidate_runner_up_score": "5"}) == (None, None)


def test_zero_score_does_not_divide_by_zero():
    absolute, relative = margin_of(_row(0, 0))
    assert absolute == 0 and relative is None


# --------------------------------------------------------------------------
# 게이트와 같은 기준을 쓴다
# --------------------------------------------------------------------------

def test_threshold_matches_the_gate():
    """진단이 게이트와 다른 잣대를 쓰면 결론이 어긋난다."""
    from recover_downstream_validated import _margin_ok
    for score, runner_up in ((625, 621), (653, 647), (546, 544), (700, 600), (100, 99)):
        row = _row(score, runner_up)
        absolute, _ = margin_of(row)
        assert is_thin(absolute, float(score)) == (not _margin_ok(row))


def test_observed_failures_are_thin():
    """실측에서 막힌 세 건이 얇은 것으로 나와야 한다."""
    for score, runner_up in ((625, 621), (653, 647), (546, 544)):
        absolute, _ = margin_of(_row(score, runner_up))
        assert is_thin(absolute, float(score))


def test_wide_margin_is_not_thin():
    absolute, _ = margin_of(_row(700, 600))
    assert not is_thin(absolute, 700.0)


def test_absolute_floor_applies_to_small_scores():
    """점수가 작으면 1% 로는 부족하다 — 절대 하한이 있다."""
    absolute, _ = margin_of(_row(100, 97))
    assert absolute == 3 and MIN_ABSOLUTE == 5.0 and is_thin(absolute, 100.0)


def test_relative_threshold_applies_to_large_scores():
    absolute, _ = margin_of(_row(1000, 994))
    assert absolute == 6 and MIN_RELATIVE == 0.01 and is_thin(absolute, 1000.0)


def test_missing_margin_is_not_counted_as_thin():
    """점수가 없는 것을 얇다고 세면 문제를 부풀린다."""
    assert not is_thin(None, None)


# --------------------------------------------------------------------------
# 분포 구간
# --------------------------------------------------------------------------

def test_near_tie_bucket():
    assert bucket_label(0.2) == "거의 동점 (<0.5)"


def test_wide_bucket():
    assert bucket_label(250) == "100 이상"


def test_missing_score_has_its_own_bucket():
    assert bucket_label(None) == "점수 없음"


def test_buckets_are_contiguous():
    labels = [bucket_label(v) for v in (0.1, 1, 3, 10, 50, 500)]
    assert len(set(labels)) == 6
