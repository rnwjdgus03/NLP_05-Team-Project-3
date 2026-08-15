from __future__ import annotations

import sqlite3
from pathlib import Path

from kosis_sqlite_metadata import connect, create_schema
from merge_kosis_sqlite_periodicities import merge_periodicities


def make_db(path: Path, periods: list[tuple[str, str, str]]) -> None:
    connection = connect(path)
    try:
        create_schema(connection)
        connection.executemany(
            """
            INSERT INTO kosis_tables(
                org_id,tbl_id,tbl_name,normalized_tbl_name,stat_id,
                category_path,organization_name,updated_at
            ) VALUES(?,?,?,?,'','','','test')
            """,
            [(org_id, tbl_id, tbl_id, tbl_id) for org_id, tbl_id in sorted({
                (org_id, tbl_id) for org_id, tbl_id, _ in periods
            })],
        )
        connection.executemany(
            "INSERT INTO kosis_periodicities(org_id,tbl_id,prd_se) VALUES(?,?,?)", periods
        )
        connection.commit()
    finally:
        connection.close()


def test_merge_periodicities_keeps_base_and_adds_new_rows(tmp_path: Path) -> None:
    base, supplement, output = tmp_path / "base.db", tmp_path / "supp.db", tmp_path / "out.db"
    make_db(base, [("101", "A", "Y")])
    connection = connect(base)
    try:
        connection.execute(
            """
            INSERT INTO kosis_tables(
                org_id,tbl_id,tbl_name,normalized_tbl_name,stat_id,
                category_path,organization_name,updated_at
            ) VALUES('101','B','B','B','','','','test')
            """
        )
        connection.commit()
    finally:
        connection.close()
    make_db(supplement, [("101", "A", "Y"), ("101", "A", "M"), ("101", "B", "Q")])
    summary = merge_periodicities(base, supplement, output)
    connection = sqlite3.connect(output)
    try:
        rows = connection.execute(
            "SELECT org_id,tbl_id,prd_se FROM kosis_periodicities ORDER BY 1,2,3"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [("101", "A", "M"), ("101", "A", "Y"), ("101", "B", "Q")]
    assert summary["inserted_periodicities"] == 2
