import sqlite3

from kosis_sqlite_table_fts import ensure_fts, focused_terms, retrieve


def catalog():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE kosis_tables(org_id TEXT, tbl_id TEXT, tbl_name TEXT, category_path TEXT)"
    )
    connection.executemany(
        "INSERT INTO kosis_tables VALUES (?, ?, ?, ?)",
        [
            ("101", "RIGHT", "시군구 경제활동인구 총괄", "지역별고용조사 > 시군구"),
            ("101", "WRONG", "연령별 취업자 및 고용률", "경제활동인구조사 > 전국"),
            ("101", "FARM", "행정구역(시군구)별 농가, 농가인구", "농림어업조사"),
        ],
    )
    return connection


def test_region_and_indicator_catalog_retrieval_finds_total_table():
    connection = catalog()
    ensure_fts(connection)
    rows = retrieve(
        connection,
        {
            "claim_text": "2024년 하반기 지역별 고용조사에서 울릉군의 고용률은 83.5%였다.",
            "measurement_indicator": "고용률",
            "measurement_item": "울릉군",
            "region": "울릉군",
        },
        limit=3,
    )
    assert any(row["tbl_id"] == "RIGHT" for row in rows)


def test_named_survey_and_indicator_terms_are_kept():
    terms = focused_terms({
        "claim_text": "지난해 국내 농가 수가 집계됐다.",
        "measurement_indicator": "농가 수",
    })
    assert "농가" in terms
    assert "지난해" not in terms


def test_current_period_and_requested_axis_beat_archived_detail_table():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE kosis_tables(org_id TEXT, tbl_id TEXT, tbl_name TEXT, category_path TEXT)"
    )
    connection.executemany(
        "INSERT INTO kosis_tables VALUES (?, ?, ?, ?)",
        [
            ("101", "OLD", "연령별 농가 수", "농림어업총조사 > 2010년 > 농가"),
            ("101", "CURRENT", "행정구역(시군구)별 농가, 농가인구", "농업 > 2010년~"),
        ],
    )
    ensure_fts(connection)
    rows = retrieve(connection, {
        "claim_text": "지난해 국내 농가 수는 97만 가구다.",
        "measurement_indicator": "농가 수",
        "measurement_period": "2024",
    }, limit=2)
    assert rows[0]["tbl_id"] == "CURRENT"
    assert "PERIOD_NOT_COVERED" in rows[1]["catalog_exact_reasons"]


def test_named_household_survey_retrieves_axis_table_without_indicator_in_title():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE kosis_tables(org_id TEXT, tbl_id TEXT, tbl_name TEXT, category_path TEXT)"
    )
    connection.executemany(
        "INSERT INTO kosis_tables VALUES (?, ?, ?, ?)",
        [
            ("101", "PANEL", "자산 및 부채, 순자산 보유액", "국민노후보장패널조사"),
            ("101", "SURVEY", "가구주연령계층별(10세) 자산, 부채, 소득 현황", "가계금융복지조사 > 2017년 이후 > 총괄"),
        ],
    )
    ensure_fts(connection)
    rows = retrieve(connection, {
        "claim_text": "통계청의 2024년 가계금융복지조사 결과 60세 이상 가구의 순자산 보유액은 5억원이었다.",
        "measurement_indicator": "순자산 보유액",
        "age_group": "60세 이상",
        "measurement_period": "2024",
    }, limit=2)
    assert rows[0]["tbl_id"] == "SURVEY"


def test_korean_compound_prefix_and_official_synonym_retrieve_misunsold_table():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE kosis_tables(org_id TEXT, tbl_id TEXT, tbl_name TEXT, category_path TEXT)"
    )
    connection.executemany(
        "INSERT INTO kosis_tables VALUES (?, ?, ?, ?)",
        [
            ("116", "RIGHT", "공사완료후 미분양현황", "주택 > 미분양"),
            ("101", "WRONG", "농업용수개발사업 준공 현황", "농업"),
        ],
    )
    ensure_fts(connection)
    rows = retrieve(connection, {
        "measurement_indicator": "준공 후 미분양 주택 수",
        "measurement_period": "202412",
    }, limit=2)
    assert rows[0]["tbl_id"] == "RIGHT"


def test_default_household_scope_penalizes_city_two_plus_and_sampling_error():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE kosis_tables(org_id TEXT, tbl_id TEXT, tbl_name TEXT, category_path TEXT)"
    )
    connection.executemany(
        "INSERT INTO kosis_tables VALUES (?, ?, ?, ?)",
        [
            ("101", "RIGHT", "가구당 월평균 가계수지 (전국,1인이상)", "가계동향조사"),
            ("101", "CITY", "가구당 월평균 가계수지 (도시,1인이상)", "가계동향조사"),
            ("101", "TWO", "가구당 월평균 가계수지 (전국,2인이상)", "가계동향조사"),
            ("101", "ERROR", "가구당 월평균 가계수지 표본오차 (전국,1인이상)", "가계동향조사"),
        ],
    )
    ensure_fts(connection)
    rows = retrieve(connection, {
        "claim_text": "가계동향조사 결과 가구당 월평균 소득은 535만원이었다.",
        "measurement_indicator": "가구당 월평균 소득",
    }, limit=4)
    assert rows[0]["tbl_id"] == "RIGHT"
