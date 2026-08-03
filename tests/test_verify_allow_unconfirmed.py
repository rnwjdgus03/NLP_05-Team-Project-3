"""확정 안 된 매핑을 진단 목적으로 조회하는 통로 (2026-08-02).

배경: 커버리지 58건 중 '후보가 결정적이지 않음'이 24건으로 가장 크다.
      그 좌표가 정말 틀렸는지 재려면 조회는 해봐야 하는데,
      verify 는 READY 만 처리하도록 막혀 있었다(설계상 옳다).

원칙: 통로는 열되 **결과가 판정으로 오해되지 않게** 표시한다.
      좌표가 확정되지 않았으므로 값이 맞아도 우연일 수 있고,
      틀려도 주장이 거짓이라는 뜻이 아니다.
"""
import inspect

import kosis_verify_claim_values as verify


def source() -> str:
    return inspect.getsource(verify)


def test_default_still_filters_to_ready():
    """기본 동작이 느슨해지면 파이프라인 원칙이 깨진다."""
    text = source()
    assert "if not args.allow_unconfirmed:" in text
    assert "r.get('mapping_status') == 'READY'" in text


def test_flag_exists_and_is_opt_in():
    text = source()
    assert "--allow-unconfirmed" in text
    assert "action='store_true'" in text


def test_diagnostic_rows_are_marked_in_the_output():
    """표시가 없으면 이 파일이 나중에 진짜 판정으로 쓰일 수 있다."""
    text = source()
    assert "verified_without_confirmation" in text
    assert "'Y'" in text


def test_marker_column_is_added_to_the_header():
    assert "fields.append('verified_without_confirmation')" in source()


def test_flag_help_warns_against_using_it_as_a_verdict():
    text = source()
    assert "진단 전용" in text
    assert "판정으로 쓰면 안 된다" in text


def test_console_warning_is_printed():
    assert "[진단 모드]" in source()


def test_ready_only_path_is_unchanged_for_files_without_status():
    """mapping_status 컬럼이 없는 후보 파일은 기존대로 rank 로 거른다."""
    assert "str(r.get('candidate_rank', '')).strip() == str(args.rank)" in source()
