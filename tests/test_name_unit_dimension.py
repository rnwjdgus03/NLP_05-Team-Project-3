"""단위가 없는 KOSIS 항목을 이름으로 보완한다 (2026-08-02).

실측: 메타의 ITEM 452개 중 158개(35%)가 unit_name 이 비어 있다.
      그 결과 item_mapping_type 이 빈 값을 내고 verify 가 MAPPING_TYPE_UNSUPPORTED 로
      막아, 잠근 103건 중 58건이 판정 자체를 못 받았다.
      그 58건의 KOSIS 항목 단위는 43건이 빈값이었다.

이름 추론은 틀릴 수 있고 틀리면 잘못된 좌표가 확정된다. 그래서 목록을 좁게 잡고
순서를 지킨다 — '매출액 증가율'은 금액이 아니라 비율이다.
"""
import pytest

from kosis_match_claims_to_index import meta_unit_dimension, name_unit_dimension


# --------------------------------------------------------------------------
# 순서 — 비율이 먼저다
# --------------------------------------------------------------------------

def test_rate_wins_over_currency_in_a_compound_name():
    """'매출액 증가율'에 '매출액'이 들어 있어도 비율이다. 이 순서가 무너지면 오판한다."""
    assert name_unit_dimension("매출액 증가율") == "rate"


def test_rate_wins_over_count():
    assert name_unit_dimension("사업체수 증감률") == "rate"


# --------------------------------------------------------------------------
# 실측에서 막혀 있던 이름들
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["바이오헬스산업 매출액", "생산 품목별 수출 금액(합계)",
                                  "품목별 수출액", "정부의 차입금"])
def test_currency_names(name):
    assert name_unit_dimension(name) == "currency"


@pytest.mark.parametrize("name", ["종사자수", "산업기술인력", "취업자 수"])
def test_person_count_names(name):
    assert name_unit_dimension(name) == "person_count"


@pytest.mark.parametrize("name", ["사업체수", "업체수", "사례수"])
def test_count_names(name):
    assert name_unit_dimension(name) == "count"


# --------------------------------------------------------------------------
# 모르면 모른다고 한다
# --------------------------------------------------------------------------

def test_unrelated_name_stays_unknown():
    """넓게 추론하면 잘못된 좌표가 확정된다. 확신 없으면 unknown 이 맞다."""
    assert name_unit_dimension("주로 이용하는 디지털 헬스케어 서비스") == "unknown"


def test_empty_name_is_unknown():
    assert name_unit_dimension("") == "unknown"
    assert name_unit_dimension(None) == "unknown"


# --------------------------------------------------------------------------
# 기존 동작을 깨지 않는다
# --------------------------------------------------------------------------

def test_explicit_unit_still_wins_over_the_name():
    """단위가 있으면 그것이 우선이다. 이름 추론은 보완일 뿐이다."""
    assert meta_unit_dimension("%", "매출액") == "rate"


def test_index_detection_is_unchanged():
    assert meta_unit_dimension("2020=100", "무엇이든") == "index"
    assert meta_unit_dimension("", "소비자물가지수") == "index"


def test_rate_from_name_still_works():
    assert meta_unit_dimension("", "구성비율") == "rate"


def test_currency_unit_is_unchanged():
    assert meta_unit_dimension("천달러", "수출액") == "currency"


# --------------------------------------------------------------------------
# 파생 판정으로 이어지는가
# --------------------------------------------------------------------------

def test_rate_claim_on_a_name_inferred_level_becomes_derivable():
    """단위 없는 '매출액' 항목에서도 증감률을 유도할 수 있어야 한다."""
    from kosis_match_claims_to_index import item_mapping_type
    claim = {"semantic_type": "rate_change", "unit_dimension": "rate", "unit": "%"}
    mapping_type, _ = item_mapping_type(claim, "", "바이오헬스산업 매출액")
    assert mapping_type == "rate_from_level"


def test_unknown_name_still_yields_no_mapping_type():
    from kosis_match_claims_to_index import item_mapping_type
    claim = {"semantic_type": "rate_change", "unit_dimension": "rate", "unit": "%"}
    mapping_type, reason = item_mapping_type(claim, "", "디지털 헬스케어 서비스 이용 여부")
    assert mapping_type == "" and reason
