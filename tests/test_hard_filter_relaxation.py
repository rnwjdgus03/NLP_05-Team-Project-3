"""hard filter 완화 3건에 대한 회귀 테스트 (2026-07-31 실측 진단 결과 반영).

실측 근거 (why_chroma_missed.csv / which_filter_rejected.csv, 정답 좌표 110개):
  UNIT_DIM_FILTER 25건 — 그중 rate 주장이 수준값 좌표와 잘린 것 18건
  PRD_SE_FILTER   17건 — (M↔Y) 16건, (Q↔Y) 1건. 그중 8건은 후보가 0개가 됨
  count/person_count 이름만 다른 동일 차원 3건
"""
import pytest

from kosis_chroma_hybrid_search import InMemoryCoordinateSearcher, search_measurement
from kosis_meta_coordinates import (
    build_chroma_where,
    claim_prd_se,
    normalize_dimension,
    passes_hard_filter,
    prd_se_compatible,
    unit_dimension_compatible,
)


# --------------------------------------------------------------------------
# 1) rate 예외 — mapping_type 이 비어 있어도 작동해야 한다
# --------------------------------------------------------------------------

def test_rate_claim_is_compatible_even_when_mapping_type_is_missing():
    """실제 버그: mapping_type 은 (주장, 좌표) 쌍에서 정해져 검색 단계엔 비어 있다."""
    assert unit_dimension_compatible("rate", "currency", "") is True
    assert unit_dimension_compatible("rate", "count", "") is True
    assert unit_dimension_compatible("rate", "index") is True


def test_mapping_type_exception_still_works_when_present():
    assert unit_dimension_compatible("currency", "count", "rate_from_level") is True
    assert unit_dimension_compatible("currency", "count", "difference_from_level") is True


def test_non_derived_dimension_conflict_is_still_rejected():
    """완화가 '전부 통과'가 되면 안 된다 — 수준값끼리의 충돌은 그대로 배제."""
    assert unit_dimension_compatible("currency", "count", "") is False
    assert unit_dimension_compatible("currency", "person_count", "") is False


def test_where_clause_drops_unit_dimension_for_rate_claims():
    where = build_chroma_where({"unit_dimension": "rate"}, ["T1"])
    payload = where["$and"] if "$and" in where else [where]
    assert not any("unit_dimension" in clause for clause in payload)


# --------------------------------------------------------------------------
# 2) 차원 별칭 통합 — count / person_count
# --------------------------------------------------------------------------

def test_person_count_is_normalized_to_count():
    assert normalize_dimension("person_count") == "count"
    assert normalize_dimension("COUNT") == "count"
    assert unit_dimension_compatible("count", "person_count", "") is True
    assert unit_dimension_compatible("person_count", "count", "") is True


def test_where_clause_allows_alias_dimensions():
    where = build_chroma_where({"unit_dimension": "count"}, ["T1"])
    payload = where["$and"] if "$and" in where else [where]
    clause = next(c for c in payload if "unit_dimension" in c)
    allowed = clause["unit_dimension"]["$in"]
    assert "person_count" in allowed and "count" in allowed
    assert "" in allowed and "unknown" in allowed


# --------------------------------------------------------------------------
# 3) prd_se 강등 — 배제하지 않는다
# --------------------------------------------------------------------------

def test_prd_se_no_longer_excludes_in_hard_filter():
    """표당 단일 prd_se 로 배제하면 정답 좌표가 통째로 사라진다(실측 17건)."""
    claim = {"measurement_prd_se": "Y", "unit_dimension": "currency"}
    meta = {"tbl_id": "T1", "prd_se": "M", "unit_dimension": "currency"}
    assert passes_hard_filter(claim, meta, ["T1"]) is True


def test_prd_se_clause_absent_from_chroma_where():
    where = build_chroma_where({"measurement_prd_se": "M"}, ["T1"])
    payload = where["$and"] if "$and" in where else [where]
    assert not any("prd_se" in clause for clause in payload)


def test_prd_se_compatible_still_reports_mismatch_for_ranking():
    assert prd_se_compatible("M", "M") is True
    assert prd_se_compatible("M", "") is True          # 좌표 주기 미상은 감점하지 않음
    assert prd_se_compatible("M", "Y") is False        # 강등 신호로는 살아 있어야 한다


def test_claim_prd_se_reads_both_field_names():
    assert claim_prd_se({"measurement_prd_se": "Q"}) == "Q"
    assert claim_prd_se({"prd_se": "Y"}) == "Y"
    assert claim_prd_se({}) == ""


def test_table_filter_is_still_hard():
    """완화가 표 제한까지 풀면 안 된다."""
    claim = {"unit_dimension": "currency"}
    meta = {"tbl_id": "T_OTHER", "prd_se": "", "unit_dimension": "currency"}
    assert passes_hard_filter(claim, meta, ["T1"]) is False


# --------------------------------------------------------------------------
# 4) 강등이 검색 결과 순서에 실제로 반영되는가
# --------------------------------------------------------------------------

META = [
    {"org_id": "101", "tbl_id": "T1", "tbl_name": "표", "axis_id": "ITEM",
     "code_id": "I_Y", "code_name": "연간 수출액", "is_item": "Y", "unit_name": "달러"},
    {"org_id": "101", "tbl_id": "T1", "axis_id": "B", "axis_name": "품목별",
     "axis_order": "1", "code_id": "1", "code_name": "총계", "is_item": "N"},
]

CLAIM = {
    "claim_measurement_id": "M1",
    "claim_text": "연간 수출액은 6838억달러였다",
    "unit_dimension": "currency",
    "measurement_prd_se": "Y",
    "mapping_type": "",
}

TABLES = [{"rank": 1, "org_id": "101", "tbl_id": "T1", "tbl_name": "표",
           "candidate_status": "REVIEW"}]


def _searcher(coordinate_prd_se):
    searcher = InMemoryCoordinateSearcher(META)
    for entry in searcher.entries:
        entry["metadata"]["prd_se"] = coordinate_prd_se
    return searcher


def test_period_mismatched_coordinate_survives_search_instead_of_vanishing():
    """예전에는 후보 0개가 됐다. 이제는 남되 prd_se_match=False 로 표시된다."""
    candidates, stats = search_measurement(
        CLAIM, TABLES, _searcher("M"), dense_top_k=5, lexical_top_k=5,
        rerank_top_k=5, final_top_k=5)
    assert candidates, "주기 불일치로 후보가 전멸하면 안 된다"
    assert all(c["prd_se_match"] is False for c in candidates)
    assert stats["prd_se_demoted"] == len(candidates)


def test_matching_period_is_not_demoted():
    candidates, stats = search_measurement(
        CLAIM, TABLES, _searcher("Y"), dense_top_k=5, lexical_top_k=5,
        rerank_top_k=5, final_top_k=5)
    assert candidates and all(c["prd_se_match"] is True for c in candidates)
    assert stats["prd_se_demoted"] == 0


def test_matching_period_outranks_mismatched_even_with_lower_score():
    """강등은 점수보다 우선한다 — 리랭커 점수가 음수여도 순서가 뒤집히면 안 된다."""
    matched = {"coordinate_id": "C_OK", "document": "d1", "metadata": {"prd_se": "Y"},
               "final_rank_score": -9.0, "prd_se_match": None}
    mismatched = {"coordinate_id": "C_NG", "document": "d2", "metadata": {"prd_se": "M"},
                  "final_rank_score": 9.0, "prd_se_match": None}

    for entry in (matched, mismatched):
        entry["prd_se_match"] = prd_se_compatible(
            claim_prd_se(CLAIM), entry["metadata"]["prd_se"])
    ordered = sorted([mismatched, matched],
                     key=lambda c: (0 if c["prd_se_match"] else 1, -c["final_rank_score"]))
    assert [c["coordinate_id"] for c in ordered] == ["C_OK", "C_NG"]


def test_output_row_records_demotion_without_dropping_candidate():
    from kosis_chroma_hybrid_search import build_output_row

    candidates, _ = search_measurement(
        CLAIM, TABLES, _searcher("M"), dense_top_k=5, lexical_top_k=5,
        rerank_top_k=5, final_top_k=1)
    row = build_output_row(CLAIM, TABLES[0], candidates[0], 1)
    assert row["prd_se_match"] is False
    assert row["coordinate_prd_se"] == "M"


@pytest.mark.parametrize("claim_dim,coord_dim,expected", [
    ("rate", "currency", True),        # 실측 12건
    ("rate", "count", True),           # 실측 6건
    ("count", "person_count", True),   # 실측 3건
    # 아래 둘은 실측에서 잘린 건이지만 '완화하지 않는다'.
    # 주장이 수준값인데 좌표가 %면 그 좌표에서 금액을 얻을 수 없다.
    # response_code_valid 는 코드 일치만 보증할 뿐 값의 정당성을 보증하지 않으므로,
    # 실측 4건에 맞추려고 필터를 무력화하지 않는다.
    ("currency", "rate", False),       # 실측 3건 — 계속 배제
    ("count", "currency", False),      # 실측 1건 — 계속 배제
])
def test_measured_rejection_pairs(claim_dim, coord_dim, expected):
    assert unit_dimension_compatible(claim_dim, coord_dim, "") is expected
