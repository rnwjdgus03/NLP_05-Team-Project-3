"""출처 귀속 전파는 prepare 에서 해야 한다 (2026-08-04).

깨끗한 재실행에서 드러난 버그. 손으로 패치한 파이프라인에서는 안 보였다.

전파는 lock_evaluation_set 에만 있었다. 그런데 prepare 가 먼저 게이트를 돌려
**출처를 밝힌 문장을 이미 제거**하므로, lock 은 전파할 출처를 찾지 못한다.
실제로 lock 이 '입력 103 → 확정 103 (제외 0)' 을 냈고,
'정부의 연간 누적 대출'(한은 제출자료)이 확정까지 가서 '불일치'로 판정됐다.
범위 밖 주장에 거짓 딱지를 붙인 것이다.

교훈: 같은 규칙을 두 단계에서 돌릴 때는 **순서가 결과를 바꾼다.**
앞 단계가 입력을 줄이면 뒷 단계의 근거가 사라진다.
"""
import prepare_kosis_mapping_input as prepare

SOURCE = "1일 임광현 의원이 한은에서 제출받은 자료에 따르면 정부는 173조원을 일시 차입했다."
FOLLOW_UP = "정부의 연간 누적 대출은 2019년 36조5072억원에서 크게 뛰었다."


def _row(article, text, blocked="N", eligible="Y"):
    return {"article_id": article, "claim_text": text,
            "scope_gate_blocked": blocked, "mapping_eligible": eligible}


def test_follow_up_is_blocked_by_the_article_source():
    rows = [_row("A1", SOURCE, blocked="Y", eligible="N"), _row("A1", FOLLOW_UP)]
    assert prepare.apply_article_scope(rows) == 1
    assert rows[1]["mapping_eligible"] == "N"
    assert rows[1]["mapping_exclusion_code"] == "INTERNAL_DOCUMENT_SOURCE"


def test_reason_is_recorded():
    rows = [_row("A1", SOURCE, blocked="Y", eligible="N"), _row("A1", FOLLOW_UP)]
    prepare.apply_article_scope(rows)
    assert rows[1]["mapping_exclusion_reason"]
    assert rows[1]["in_ready"] == "N"


def test_already_blocked_rows_are_not_touched():
    rows = [_row("A1", SOURCE, blocked="Y", eligible="N")]
    assert prepare.apply_article_scope(rows) == 0


def test_other_articles_are_untouched():
    rows = [_row("A1", SOURCE, blocked="Y", eligible="N"), _row("A2", FOLLOW_UP)]
    assert prepare.apply_article_scope(rows) == 0
    assert rows[1]["mapping_eligible"] == "Y"


def test_sentence_with_its_own_source_survives():
    """'한국로봇산업진흥원에 따르면' 은 그 문장의 출처다. 전파로 막으면 안 된다."""
    rows = [_row("A1", "국제로봇연맹(IFR)에 따르면 로봇 1012대를 쓰는 나라였다.",
                 blocked="Y", eligible="N"),
            _row("A1", "한국로봇산업진흥원에 따르면 로봇화 기업은 2524곳이었다.")]
    assert prepare.apply_article_scope(rows) == 0
    assert rows[1]["mapping_eligible"] == "Y"


def test_clean_article_is_untouched():
    rows = [_row("A1", "작년 수출액이 6838억달러였다."),
            _row("A1", "반도체는 1419억달러였다.")]
    assert prepare.apply_article_scope(rows) == 0


def test_both_item_fields_are_cleared():
    """한쪽만 지우면 하류 게이트가 옛 값을 보고 다시 막는다.

    claim_item_grounded 는 measurement_item 을 **먼저** 읽는다:
        raw = nz(row.get("measurement_item")) or nz(row.get("industry_or_item"))

    2026-08-04 실측: prepare 가 industry_or_item 만 지워서
    '전체 수출액 6838억' 이 UNGROUNDED_CLAIM_ITEM 으로 재차단됐고 확정 3건을 잃었다.
    """
    import inspect
    source = inspect.getsource(prepare.normalize_row)
    assert 'out["industry_or_item"] = ""' in source
    assert 'out["measurement_item"] = ""' in source


def test_cleared_row_passes_the_grounding_check():
    """지운 뒤에는 근거 검사를 통과해야 한다(대상 없는 주장으로 취급)."""
    row = {"measurement_item": "", "industry_or_item": "",
           "claim_text": "작년 한 해 전체 수출액이 6838억달러였다"}
    assert prepare.claim_item_grounded(row)


def test_prepare_calls_it():
    """함수만 만들고 파이프라인에 연결하지 않으면 아무 일도 일어나지 않는다."""
    import inspect
    assert "apply_article_scope(normalized)" in inspect.getsource(prepare.prepare)
