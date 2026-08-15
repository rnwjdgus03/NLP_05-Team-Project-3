from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "data/locked_holdout_300_articles.csv"
ASSIGNMENTS = ROOT / "data/locked_holdout_300_assignments.csv"
MANIFEST = ROOT / "data/locked_holdout_300_manifest.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prior_urls() -> set[str]:
    sources = (
        (ROOT / "data/gold/mcp_full_gold_250.csv", "url"),
        (ROOT / "data/holdout5_articles.csv", "URL"),
        (ROOT / "data/holdout6_articles.csv", "URL"),
        (ROOT / "data/holdout7_disjoint_articles.csv", "URL"),
        (ROOT / "data/holdout8_stratified_articles.csv", "URL"),
    )
    return {
        row[field].strip()
        for path, field in sources
        if path.exists()
        for row in read_csv(path)
        if row.get(field, "").strip()
    }


def test_locked_holdout_has_300_unique_articles_and_urls() -> None:
    rows = read_csv(ASSIGNMENTS)
    assert len(rows) == 300
    assert len({row["holdout_id"] for row in rows}) == 300
    assert len({row["article_id"] for row in rows}) == 300
    assert len({row["url"] for row in rows}) == 300
    assert all(re.fullmatch(r"A\d{4,}", row["article_id"]) for row in rows)
    assert {row["url"] for row in rows}.isdisjoint(prior_urls())


def test_locked_article_rows_match_assignments() -> None:
    article_rows = read_csv(ARTICLES)
    assignment_rows = read_csv(ASSIGNMENTS)
    assert len(article_rows) == 300
    assert all(row["lock_status"] == "LOCKED_DO_NOT_TUNE" for row in article_rows)
    assert {
        (row["holdout_id"], row["article_id"], row["URL"])
        for row in article_rows
    } == {
        (row["holdout_id"], row["article_id"], row["url"])
        for row in assignment_rows
    }


def test_manifest_matches_locked_files() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = read_csv(ASSIGNMENTS)
    assert manifest["lock_status"] == "LOCKED_DO_NOT_TUNE"
    assert manifest["label_status"] == "UNSEEN_LOCKED_INPUT_NOT_YET_MCP_GOLD"
    assert manifest["row_count"] == 300
    assert manifest["unique_url_count"] == 300
    assert manifest["unique_article_id_count"] == 300
    assert manifest["prior_url_overlap"] == 0
    assert manifest["articles_sha256"] == sha256(ARTICLES)
    assert manifest["assignments_sha256"] == sha256(ASSIGNMENTS)
    assert manifest["stratum_counts"] == dict(Counter(row["stratum"] for row in rows))
    assert sum(manifest["stratum_counts"].values()) == 300
