from pathlib import Path

from hydrate_kosis_sqlite_candidates import (
    hydrate,
    parse_kosis_json,
    prepare_database,
    select_candidate_tables,
)
from kosis_sqlite_metadata import connect, create_schema, upsert_table


def test_select_candidate_tables_uses_top_k_per_claim_without_gold() -> None:
    rows = [
        {"claim_measurement_id": "c1", "org_id": "101", "tbl_id": "A", "candidate_rank": "1"},
        {"claim_measurement_id": "c1", "org_id": "101", "tbl_id": "B", "candidate_rank": "2"},
        {"claim_measurement_id": "c1", "org_id": "101", "tbl_id": "C", "candidate_rank": "3"},
        {"claim_measurement_id": "c2", "org_id": "101", "tbl_id": "B", "candidate_rank": "1"},
        {"claim_measurement_id": "c2", "org_id": "101", "tbl_id": "D", "candidate_rank": "2"},
    ]
    selected = select_candidate_tables(rows, top_k=2)

    assert [(row["tbl_id"], row["claim_count"]) for row in selected] == [
        ("A", "1"),
        ("B", "2"),
        ("D", "1"),
    ]


def test_parse_kosis_json_accepts_unquoted_keys_and_single_object() -> None:
    assert parse_kosis_json('[{OBJ_ID:"ITEM",ITM_ID:"T1"}]') == [
        {"OBJ_ID": "ITEM", "ITM_ID": "T1"}
    ]
    assert parse_kosis_json('{PRD_SE:"Y"}') == [{"PRD_SE": "Y"}]


def test_hydrate_commits_item_axis_periodicity_and_resumes(tmp_path: Path) -> None:
    base_db = tmp_path / "base.sqlite"
    output_db = tmp_path / "run.sqlite"
    meta_output = tmp_path / "hydrated.csv"
    status_output = tmp_path / "status.csv"
    connection = connect(base_db)
    create_schema(connection)
    upsert_table(connection, {
        "org_id": "101", "tbl_id": "DT_TEST", "tbl_name": "테스트 통계표"
    })
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    prepare_database(base_db, output_db, meta_output)

    candidates = [{
        "claim_measurement_id": "c1",
        "org_id": "101",
        "tbl_id": "DT_TEST",
        "tbl_name": "테스트 통계표",
        "candidate_rank": "1",
    }]
    calls: list[str] = []

    def fake_fetch(org_id: str, tbl_id: str, meta_type: str):
        assert (org_id, tbl_id) == ("101", "DT_TEST")
        calls.append(meta_type)
        if meta_type == "PRD":
            return [{"PRD_SE": "Y", "STRT_PRD_DE": "2020", "END_PRD_DE": "2025"}]
        return [
            {
                "OBJ_ID": "ITEM", "OBJ_NM": "항목", "OBJ_ID_SN": "0",
                "ITM_ID": "T1", "ITM_NM": "인구", "UNIT_ID": "1", "UNIT_NM": "명",
            },
            {
                "OBJ_ID": "A", "OBJ_NM": "지역", "OBJ_ID_SN": "1",
                "ITM_ID": "00", "ITM_NM": "전국", "UP_ITM_ID": "",
            },
        ]

    first = hydrate(
        candidates=candidates,
        output_db=output_db,
        meta_output=meta_output,
        status_output=status_output,
        top_k=10,
        delay=0,
        fetch_meta=fake_fetch,
    )

    assert calls == ["ITM", "PRD"]
    assert first["hydrated"] == 1
    connection = connect(output_db)
    assert connection.execute("SELECT COUNT(*) FROM kosis_items").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM kosis_axes").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM kosis_axis_values").fetchone()[0] == 1
    assert connection.execute("SELECT prd_se FROM kosis_periodicities").fetchone()[0] == "Y"
    connection.close()

    second = hydrate(
        candidates=candidates,
        output_db=output_db,
        meta_output=meta_output,
        status_output=status_output,
        top_k=10,
        delay=0,
        fetch_meta=fake_fetch,
    )
    assert second["attempted"] == 0
    assert calls == ["ITM", "PRD"]
