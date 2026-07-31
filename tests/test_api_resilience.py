"""KOSIS API 불안정성 대응 (2026-07-31).

실측: 같은 입력으로 검증을 두 번 돌렸는데 결과가 달랐다.
  1차 → 판단불가 1/12 (KOSIS_API_ERROR)
  2차 → 판단불가 3/9  (RemoteDisconnected 2, Read timed out 1)
재시도가 없으면 네트워크 상태가 verdict 분포를 바꾼다 = 재현성이 없다.
"""
import requests

import kosis_api_test as api


def test_session_has_retry_adapter():
    adapter = api.SESSION.get_adapter("https://kosis.kr/openapi/")
    assert adapter.max_retries.total == api.RETRY_TOTAL


def test_retry_covers_connect_and_read_failures():
    """실측 오류는 RemoteDisconnected(connect/read) 계열이었다."""
    retry = api.SESSION.get_adapter("https://kosis.kr/openapi/").max_retries
    assert retry.connect == api.RETRY_TOTAL
    assert retry.read == api.RETRY_TOTAL


def test_backoff_is_exponential_not_immediate():
    """즉시 재시도는 끊긴 서버를 더 밀어붙인다."""
    retry = api.SESSION.get_adapter("https://kosis.kr/openapi/").max_retries
    assert retry.backoff_factor >= 1.0


def test_server_errors_and_rate_limit_are_retried():
    retry = api.SESSION.get_adapter("https://kosis.kr/openapi/").max_retries
    for status in (429, 500, 502, 503, 504):
        assert status in retry.status_forcelist


def test_timeout_is_longer_than_the_old_ten_seconds():
    """read timeout=10 에서 실제로 끊겼다."""
    assert api.REQUEST_TIMEOUT > 10


def test_all_endpoints_share_the_retry_session():
    """한 곳만 고치면 나머지 엔드포인트에서 같은 문제가 반복된다."""
    source = open(api.__file__, encoding="utf-8").read()
    assert "requests.get(" not in source, "재시도 없는 직접 호출이 남아 있다"
    assert source.count("SESSION.get(") == 3    # list / data / meta


def test_session_is_a_requests_session():
    assert isinstance(api.SESSION, requests.Session)
