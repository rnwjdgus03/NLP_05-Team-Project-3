"""C 경로가 mapping_type 을 계산하게 한다 (2026-08-02).

mapping_type 은 주장에서 오는 값이 아니라 **항목을 고를 때** 계산되는 값이다.
A 경로(kosis_match_claims_to_index)는 item_mapping_type 으로 채우는데
C 경로(Chroma)는 좌표만 가져오고 계산을 안 했다.
validate 가 빈 값을 'direct' 로 메우면서 증감률 주장이 수준값 항목과
'단위 불일치'로 막혔다 — 잠근 125건에서 UNIT_MISMATCH 46건 전부 mapping_type 이 비었고
그중 30건이 증감률 주장이었다(실측).
"""
from kosis_chroma_hybrid_search import resolve_mapping_type

RATE_CLAIM = {"semantic_type": "rate_change", "unit_dimension": "rate",
              "unit": "%", "indicator": "수출 증가율"}


# --------------------------------------------------------------------------
# 핵심: 증감률 주장 + 수준값 항목 = 유도 가능
# --------------------------------------------------------------------------

def test_rate_claim_on_a_level_item_is_derivable():
    """% 주장을 천달러 항목에서 계산할 수 있다. 이게 막혀 있던 12건이다."""
    mapping_type, _ = resolve_mapping_type(RATE_CLAIM, {"unit": "천달러", "itm_name": "수출액"})
    assert mapping_type == "rate_from_level"


def test_absolute_change_on_a_matching_level_item():
    claim = {"semantic_type": "absolute_change", "unit_dimension": "currency", "unit": "원"}
    mapping_type, _ = resolve_mapping_type(claim, {"unit": "억원", "itm_name": "수출액"})
    assert mapping_type == "difference_from_level"


# --------------------------------------------------------------------------
# 단위를 모르면 비워둔다 — 이건 정상 동작이다
# --------------------------------------------------------------------------

def test_unit_can_be_inferred_from_the_item_name():
    """2026-08-02 변경: 단위가 없어도 항목 이름으로 차원을 보완한다.

    이전에는 여기서 빈 값이 나왔다. KOSIS 메타의 ITEM 35%가 단위가 비어 있고,
    그 때문에 잠근 103건 중 58건이 판정 자체를 못 받고 있었다(실측).
    단위 없는 항목은 이름에 단위가 들어 있는 경우가 많다 — '수출액', '매출액'.
    """
    mapping_type, _ = resolve_mapping_type(RATE_CLAIM, {"unit": "", "itm_name": "수출액"})
    assert mapping_type == "rate_from_level"


def test_name_without_a_hint_still_yields_no_mapping_type():
    """이름으로도 모르면 비워둔다. 확인 못 하는 좌표를 자동 확정하면 안 된다."""
    mapping_type, reason = resolve_mapping_type(
        RATE_CLAIM, {"unit": "", "itm_name": "디지털 헬스케어 서비스 이용 여부"})
    assert mapping_type == ""
    assert reason


def test_reason_is_recorded_so_the_block_is_traceable():
    """왜 막혔는지 CSV 에 남아야 나중에 추적할 수 있다."""
    _, reason = resolve_mapping_type(RATE_CLAIM, {"unit": "명", "itm_name": "종사자 수"})
    assert isinstance(reason, str) and reason


# --------------------------------------------------------------------------
# 이미 값이 있으면 덮어쓰지 않는다
# --------------------------------------------------------------------------

def test_existing_mapping_type_wins():
    claim = {**RATE_CLAIM, "mapping_type": "direct"}
    mapping_type, reason = resolve_mapping_type(claim, {"unit": "천달러", "itm_name": "수출액"})
    assert mapping_type == "direct"
    assert reason == ""


# --------------------------------------------------------------------------
# 검색이 죽으면 안 된다
# --------------------------------------------------------------------------

def test_missing_metadata_does_not_raise():
    assert resolve_mapping_type(RATE_CLAIM, {}) == ("", "증감률을 계산할 수 없는 KOSIS 단위=-")


def test_empty_claim_does_not_raise():
    mapping_type, _ = resolve_mapping_type({}, {"unit": "천달러", "itm_name": "수출액"})
    assert isinstance(mapping_type, str)


# --------------------------------------------------------------------------
# 출력 행에 실제로 실린다
# --------------------------------------------------------------------------

def test_output_row_carries_mapping_type_and_reason():
    from kosis_chroma_hybrid_search import build_output_row
    candidate = {"coordinate_id": "c1",
                 "metadata": {"tbl_id": "T", "unit": "천달러", "itm_name": "수출액",
                              "itm_id": "I1", "org_id": "101"}}
    row = build_output_row(RATE_CLAIM, {"tbl_id": "T"}, candidate, 1)
    assert row["mapping_type"] == "rate_from_level"
    assert "unit_compatibility_reason" in row
