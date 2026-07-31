from pathlib import Path

from kosis_match_claims_to_index import (
    load_period_routes,
    norm_table_row,
    period_route_candidates,
)


def _table(tbl_id, tbl_name):
    row = norm_table_row(
        {
            "org_id": "101",
            "tbl_id": tbl_id,
            "tbl_name": tbl_name,
            "category_path": "로봇",
        }
    )
    row["_compact_tbl_name"] = "".join(str(row["tbl_name"]).split())
    row["_compact_category_path"] = "".join(str(row["category_path"]).split())
    return row


def test_robot_import_period_routes_select_different_tables_by_year():
    routes = load_period_routes(Path("data/claims/kosis_period_table_routes.csv"))
    tables = [
        _table("R2007", "로봇단품 및 부품 수입현황"),
        _table("R2013", "로봇 단품 및 부품 국가별 수입 현황"),
        _table("R2019", "로봇산업 수입 현황"),
    ]

    cases = {
        "2010": "R2007",
        "2015": "R2013",
        "2020": "R2019",
    }
    for year, expected_tbl_id in cases.items():
        hits = period_route_candidates(
            tables,
            {
                "measurement_indicator": "로봇 수입",
                "measurement_item": "로봇",
                "measurement_period": year,
                "claim_text": f"{year}년 로봇 수입이 증가했다.",
            },
            routes,
        )
        assert hits
        assert hits[0]["table"]["tbl_id"] == expected_tbl_id
        assert hits[0]["period_route_series_group"] == "robot_import"
