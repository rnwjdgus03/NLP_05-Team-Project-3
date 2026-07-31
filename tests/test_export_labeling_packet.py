import export_labeling_packet as packet

SILVER = [
    {"claim_measurement_id": "M1", "tier": "SILVER_UNIQUE"},
    {"claim_measurement_id": "M2", "tier": "SILVER_AMBIGUOUS"},
    {"claim_measurement_id": "M3", "tier": "NO_MATCH"},
    {"claim_measurement_id": "M4", "tier": "NEAR_MISS"},
]

REVIEW = [
    {"claim_measurement_id": "M2", "tbl_id": "T_B", "tbl_name": "표B", "sources": "C",
     "candidate_rank": "2", "selected_itm_id": "I2", "selected_itm_name": "수입액",
     "selected_obj_l1": "2", "selected_obj_l1_name": "총계",
     "kosis_actual_value": "500", "verdict": "일치"},
    {"claim_measurement_id": "M2", "tbl_id": "T_A", "tbl_name": "표A", "sources": "A",
     "candidate_rank": "1", "selected_itm_id": "I1", "selected_itm_name": "수출액",
     "selected_obj_l1": "1", "selected_obj_l1_name": "전체",
     "kosis_actual_value": "500", "verdict": "일치"},
]

CLAIMS = {"M2": {"claim_measurement_id": "M2", "claim_text": "수출액은 500억달러였다",
                 "value": "500", "unit": "억달러", "measurement_period": "2024",
                 "measurement_prd_se": "Y", "measurement_indicator": "수출액"}}


def test_only_unresolved_tiers_need_labels():
    result = packet.build_packet(SILVER, REVIEW, CLAIMS)
    ids = [r["claim_measurement_id"] for r in result]
    assert "M1" not in ids                    # 실버가 확정한 건 라벨 대상이 아니다
    assert set(ids) == {"M2", "M3", "M4"}


def test_candidates_are_sorted_by_code_not_pipeline_rank():
    """파이프라인 순위대로 보여주면 라벨러가 1위에 앵커링된다."""
    result = packet.build_packet(SILVER, REVIEW, CLAIMS)
    row = next(r for r in result if r["claim_measurement_id"] == "M2")
    assert row["candidates"].index("T_A") < row["candidates"].index("T_B")


def test_pipeline_choice_is_recorded_separately_for_audit():
    """라벨과 파이프라인이 같은 행은 상관 오류 위험이 높다 → 감사 표본 과대추출용."""
    result = packet.build_packet(SILVER, REVIEW, CLAIMS)
    row = next(r for r in result if r["claim_measurement_id"] == "M2")
    assert row["pipeline_choice"].startswith("T_A/I1")


def test_candidate_description_leads_with_names_and_values():
    line = packet.describe(REVIEW[1])
    assert line.startswith("표A")
    assert "항목=수출액" in line and "KOSIS값=500" in line


def test_label_columns_are_left_empty():
    result = packet.build_packet(SILVER, REVIEW, CLAIMS)
    for row in result:
        assert row["label_tbl_id"] == "" and row["label_evidence"] == ""


def test_measurement_without_candidates_still_appears():
    """NO_MATCH 는 후보가 없을 수 있다. 빠뜨리면 '기사가 틀린 건'을 놓친다."""
    result = packet.build_packet(SILVER, REVIEW, CLAIMS)
    row = next(r for r in result if r["claim_measurement_id"] == "M3")
    assert row["candidate_count"] == 0


def test_markdown_lists_claim_and_candidates():
    text = packet.to_markdown(packet.build_packet(SILVER, REVIEW, CLAIMS))
    assert "수출액은 500억달러였다" in text
    assert "표A" in text and "표B" in text
