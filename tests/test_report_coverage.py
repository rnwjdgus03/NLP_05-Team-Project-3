"""커버리지 보고 — '실패'와 '확인 불가'를 가른다 (2026-08-02).

"103건 중 12건 확정"은 두 가지를 섞고 있다.
시스템이 못 한 것과, 애초에 확인할 수 없는 것.
팩트체커에게 '확인할 수 없다'는 실패가 아니라 결론이다.

동시에 분모를 몰래 줄이면 안 된다. 확인 불가를 빼면 확정률이 공짜로 오른다.
그래서 두 기준을 **함께** 낸다.
"""
from datetime import date

from report_coverage import BUCKETS, CONFIRMED, SYSTEM_GAP, UNVERIFIABLE, best_row, bucket_of

ARTICLE = {"date": "2025-01-01", "claim_text": "문장"}


def _row(status, reason="", period="2023", prd_se="Y"):
    return {"mapping_status": status, "mapping_reason": reason,
            "period": period, "prd_se": prd_se}


# --------------------------------------------------------------------------
# 확정
# --------------------------------------------------------------------------

def test_ready_is_confirmed():
    assert bucket_of(_row("READY"), ARTICLE) == "CONFIRMED"


def test_provisional_counts_as_confirmed():
    assert bucket_of(_row("PROVISIONAL"), ARTICLE) == "CONFIRMED"


# --------------------------------------------------------------------------
# 확인 불가 — 사실만 쓴다
# --------------------------------------------------------------------------

def test_future_period_is_unverifiable():
    """기사일 2025-01-01 에 2025 연간을 요청 — 그 시점에 존재할 수 없다."""
    row = _row("MAPPING_FAILED", "EMPTY_RESPONSE", period="2025")
    assert bucket_of(row, ARTICLE) == "PERIOD_AFTER_ARTICLE"


def test_past_period_without_data_is_a_different_bucket():
    row = _row("MAPPING_FAILED", "EMPTY_RESPONSE", period="2020")
    assert bucket_of(row, ARTICLE) == "NO_DATA_AT_COORDINATE"


def test_publication_lag_is_not_used_as_a_bucket():
    """'아직 미발표로 추정'은 버킷으로 쓰지 않는다.

    실측에서 그렇게 분류된 55건 중 11건이 실제로는 READY 였다(20% 이상 오탐).
    추정을 사실처럼 세면 커버리지를 부풀린다.
    """
    row = _row("MAPPING_FAILED", "EMPTY_RESPONSE", period="2024")
    assert bucket_of(row, ARTICLE) == "NO_DATA_AT_COORDINATE"
    assert "LIKELY_UNPUBLISHED" not in BUCKETS


def test_period_missing_is_unverifiable():
    assert BUCKETS[bucket_of(_row("MAPPING_FAILED", "PERIOD_MISSING"), ARTICLE)][0] == UNVERIFIABLE


# --------------------------------------------------------------------------
# 시스템 한계 — 고칠 여지가 있는 것
# --------------------------------------------------------------------------

def test_unit_mismatch_is_a_system_gap():
    bucket = bucket_of(_row("NEEDS_CONFIRMATION", "UNIT_MISMATCH"), ARTICLE)
    assert bucket == "UNIT_UNVERIFIABLE" and BUCKETS[bucket][0] == SYSTEM_GAP


def test_non_decisive_candidate_is_a_system_gap():
    row = _row("NEEDS_CONFIRMATION", "upstream table candidate is not decisive rank-1 READY")
    assert bucket_of(row, ARTICLE) == "CANDIDATE_NOT_DECISIVE"


def test_invalid_combination_is_a_system_gap():
    assert bucket_of(_row("MAPPING_FAILED", "INVALID_COMBINATION"), ARTICLE) == "COORDINATE_NOT_FOUND"


def test_api_error_is_a_system_gap():
    assert BUCKETS[bucket_of(_row("API_ERROR"), ARTICLE)][0] == SYSTEM_GAP


# --------------------------------------------------------------------------
# 분류 순서 — 먼저 걸리는 것이 이긴다
# --------------------------------------------------------------------------

def test_confirmed_wins_over_any_reason():
    assert bucket_of(_row("READY", "UNIT_MISMATCH"), ARTICLE) == "CONFIRMED"


def test_best_status_per_measurement_is_used():
    """한 measurement 에 여러 후보 행이 있으면 가장 좋은 상태로 센다."""
    rows = [_row("MAPPING_FAILED"), _row("READY"), _row("NEEDS_CONFIRMATION")]
    assert best_row(rows)["mapping_status"] == "READY"


def test_unknown_status_is_not_silently_confirmed():
    assert bucket_of(_row("SOMETHING_NEW"), ARTICLE) != "CONFIRMED"


# --------------------------------------------------------------------------
# 버킷 정의
# --------------------------------------------------------------------------

def test_ungrounded_claim_item_has_its_own_bucket():
    """'분류되지 않음'으로 뭉뚱그리면 무엇을 고쳐야 하는지 흐려진다.

    이 사유는 상류 추출이 문장에 없는 대상을 붙여서 생긴다 —
    확정을 잃는 대신 거짓 불일치를 없앤 건이라 실패와 성격이 다르다.
    """
    row = _row("NEEDS_CONFIRMATION", "UNGROUNDED_CLAIM_ITEM")
    assert bucket_of(row, ARTICLE) == "CLAIM_ITEM_UNGROUNDED"
    assert BUCKETS["CLAIM_ITEM_UNGROUNDED"][0] == SYSTEM_GAP


def test_claim_item_mismatch_has_its_own_bucket():
    row = _row("NEEDS_CONFIRMATION", "CLAIM_ITEM_MISMATCH")
    assert bucket_of(row, ARTICLE) == "CLAIM_ITEM_MISMATCH"


def test_wrong_coordinate_bucket_is_a_system_gap():
    """재조회에서 어느 기간에도 값이 없으면 좌표가 틀린 것이다 — 확인 불가가 아니다.

    실측: 그렇게 분류된 24건 중 12건이 여기 해당했다.
    가르지 않으면 확인 가능 기준 확정률이 20.7% 로 부풀려진다(실제 17.1%).
    """
    assert BUCKETS["COORDINATE_RETURNS_NOTHING"][0] == SYSTEM_GAP


def test_api_error_warning_exists():
    """한 실행의 숫자를 기록하면 노이즈를 성능으로 착각한다.

    실측: 같은 입력으로 두 번 돌렸더니 API_ERROR 48행(measurement 8개) -> 0,
    확정 11 -> 12. 재시도·백오프가 있는데도 그렇다.
    """
    import inspect

    import report_coverage
    text = inspect.getsource(report_coverage.main)
    assert "이 숫자를 기록하지 말 것" in text
    assert "api_errors" in text


def test_every_bucket_has_a_group_and_description():
    for bucket, (group, description) in BUCKETS.items():
        assert group in {CONFIRMED, UNVERIFIABLE, SYSTEM_GAP}
        assert description


def test_missing_article_date_does_not_raise():
    row = _row("MAPPING_FAILED", "EMPTY_RESPONSE", period="2025")
    assert bucket_of(row, {"claim_text": "문장"}) in BUCKETS
