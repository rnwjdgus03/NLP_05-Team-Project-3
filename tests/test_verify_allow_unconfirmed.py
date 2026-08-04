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


# --------------------------------------------------------------------------
# 게이트가 두 겹이었다 — 한 겹만 열면 아무 일도 일어나지 않는다
# --------------------------------------------------------------------------

def test_row_level_gate_also_honours_the_marker():
    """CLI 행 필터를 열어도 verify_row 안에서 다시 막히면 소용이 없다.

    2026-08-02: 실제로 그렇게 만들어서 24건이 전부 '판단불가'로 나왔다.
    validate 에서 고쳤던 이중 게이트와 같은 모양이다.
    """
    text = source()
    assert "diagnostic = str(row.get('verified_without_confirmation'" in text
    assert "and not diagnostic:" in text


def test_unmarked_rows_are_still_blocked_inside_verify_row():
    """표시가 없는 행은 예전처럼 막혀야 한다. 진단 통로가 기본이 되면 안 된다."""
    out = verify.verify_row(
        {"mapping_status": "NEEDS_CONFIRMATION", "value": "100", "period": "2024"},
        meta_cache={}, delay=0)
    assert out.get("verdict") == "판단불가"


def test_marked_row_passes_the_mapping_gate():
    """표시된 행은 매핑 게이트를 넘어가야 한다.

    그다음 단계(값·기간)에서 막히는 것은 정상이지만,
    막힌 이유가 'mapping'이면 게이트를 못 넘은 것이다.
    """
    out = verify.verify_row(
        {"mapping_status": "NEEDS_CONFIRMATION", "verified_without_confirmation": "Y",
         "value": "", "period": "2024"},
        meta_cache={}, delay=0)
    assert out.get("unverifiable_stage") != "mapping"
