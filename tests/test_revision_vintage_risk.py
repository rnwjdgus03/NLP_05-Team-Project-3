from kosis_verify_claim_values import (
    _compact_date,
    latest_revision_date,
    revision_vintage_risk,
)


def _rows(lst_chn="2026-02-25"):
    return [
        {"PRD_DE": "202409", "DT": "113.2", "LST_CHN_DE": lst_chn},
        {"PRD_DE": "202408", "DT": "113.9", "LST_CHN_DE": lst_chn},
    ]


BASE = {"date": "2024-11-01", "value_type": "증감률"}


def test_compact_date_formats():
    assert _compact_date("2026-02-25") == "20260225"
    assert _compact_date("20260225") == "20260225"
    assert _compact_date("2026.2") == ""
    assert _compact_date(None) == ""


def test_latest_revision_date_filters_periods():
    rows = [
        {"PRD_DE": "202409", "LST_CHN_DE": "20250101"},
        {"PRD_DE": "202301", "LST_CHN_DE": "20991231"},
    ]
    assert latest_revision_date(rows, ["202409"]) == "20250101"


def test_holds_derived_rate_revised_after_article():
    revised, article = revision_vintage_risk(
        BASE, _rows(), "rate_from_level", "202409", "202408")
    assert revised == "20260225"
    assert article == "20241101"


def test_no_hold_when_revision_before_article():
    revised, _ = revision_vintage_risk(
        BASE, _rows("2024-10-15"), "rate_from_level", "202409", "202408")
    assert revised == ""


def test_no_hold_for_direct_level_mapping():
    row = {"date": "2024-11-01", "value_type": "수준"}
    revised, _ = revision_vintage_risk(row, _rows(), "direct", "202409", "202408")
    assert revised == ""


def test_no_hold_without_article_date():
    row = {"date": "", "value_type": "증감률"}
    revised, _ = revision_vintage_risk(row, _rows(), "rate_from_level", "202409", "202408")
    assert revised == ""


def test_no_hold_for_future_period():
    row = {"date": "2024-01-05", "value_type": "증감률"}
    rows = [{"PRD_DE": "202409", "DT": "1", "LST_CHN_DE": "20260225"}]
    revised, _ = revision_vintage_risk(row, rows, "rate_from_level", "202409", "202408")
    assert revised == ""


def test_no_hold_without_lst_chn_de():
    rows = [{"PRD_DE": "202409", "DT": "1"}]
    revised, _ = revision_vintage_risk(BASE, rows, "rate_from_level", "202409", "202408")
    assert revised == ""
