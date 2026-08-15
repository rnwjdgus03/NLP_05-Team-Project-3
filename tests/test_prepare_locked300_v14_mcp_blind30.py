import csv
from pathlib import Path

from scripts.gold.prepare_locked300_v14_mcp_blind30 import (
    BLIND_IDS, DEVELOPMENT_IDS, NEW_IDS, RETAINED_UNTOUCHED_IDS, build,
)


def test_v14_freeze_has_30_unique_articles_and_excludes_development(tmp_path: Path):
    source = Path("data/locked300_v13_1_period_repaired_ready.csv").resolve()
    output = tmp_path / "blind30.csv"
    manifest = tmp_path / "blind30.json"
    summary = build(source, output, manifest)
    rows = list(csv.DictReader(output.open(encoding="utf-8-sig")))
    assert len(BLIND_IDS) == len(rows) == 30
    assert len({row["article_id"] for row in rows}) == 30
    assert not set(DEVELOPMENT_IDS) & {row["claim_measurement_id"] for row in rows}
    assert len(RETAINED_UNTOUCHED_IDS) == 16
    assert len(NEW_IDS) == 14
    assert summary["status"] == "FROZEN_UNLABELED"
