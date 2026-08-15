from merge_kosis_table_candidate_pools import merge_pools


def test_union_recovers_catalog_only_table_and_deduplicates_agreement():
    claims = [{
        "claim_id": "C1", "claim_measurement_id": "C1-m1",
        "measurement_indicator": "고용률", "measurement_period": "2024",
    }]
    vectors = [
        {"claim_measurement_id": "C1-m1", "org_id": "101", "tbl_id": "V", "candidate_rank": "1", "fusion_score": "0.90"},
        {"claim_measurement_id": "C1-m1", "org_id": "101", "tbl_id": "BOTH", "candidate_rank": "2", "fusion_score": "0.80"},
    ]
    catalogs = [
        {"claim_measurement_id": "C1-m1", "org_id": "101", "tbl_id": "ONLY", "candidate_rank": "1", "catalog_exact_boost": "10"},
        {"claim_measurement_id": "C1-m1", "org_id": "101", "tbl_id": "BOTH", "candidate_rank": "2", "catalog_exact_boost": "8"},
    ]
    rows = merge_pools(claims, vectors, catalogs, limit=10)
    assert {row["tbl_id"] for row in rows} == {"V", "BOTH", "ONLY"}
    both = next(row for row in rows if row["tbl_id"] == "BOTH")
    assert both["hybrid_agreement"] == "Y"
    assert both["vector_rank"] == 2
    assert both["catalog_rank"] == 2


def test_unrelated_claim_rows_are_filtered():
    claims = [{"claim_id": "C1", "claim_measurement_id": "C1-m1"}]
    rows = merge_pools(claims, [{
        "claim_measurement_id": "OTHER-m1", "org_id": "101", "tbl_id": "X",
        "candidate_rank": "1", "fusion_score": "1",
    }], [], limit=10)
    assert rows == []
