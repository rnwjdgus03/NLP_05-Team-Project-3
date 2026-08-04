import json

import pytest

from lock_evaluation_set import apply_gate, build_manifest, rule_snapshot, write_csv


def _row(claim_measurement_id, claim_text, **kw):
    base = {"claim_measurement_id": claim_measurement_id, "claim_text": claim_text,
            "unit": "%", "value": "1.0"}
    base.update(kw)
    return base


CLEAN = _row("M1", "12월 수출은 614억달러로 6.6% 증가했다.", value="6.6")
CRYPTO = _row("M2", "비트코인은 9만7000달러에 거래 중이다.", unit="달러", value="97000")
FORECAST = _row("M3", "올해 성장률이 1.8%로 전망된다.", value="1.8")
WORLD_CMP = _row("M4", "전 세계 수출순위에서 우리나라는 6위를 달성했다.", value="6")


def test_reject_rows_are_dropped_and_review_rows_are_kept():
    kept, dropped = apply_gate([CLEAN, CRYPTO, FORECAST, WORLD_CMP])
    assert {r["claim_measurement_id"] for r in dropped} == {"M2", "M3"}
    assert {r["claim_measurement_id"] for r in kept} == {"M1", "M4"}


def test_kept_rows_carry_the_gate_columns():
    kept, _ = apply_gate([CLEAN, WORLD_CMP])
    review = next(r for r in kept if r["claim_measurement_id"] == "M4")
    assert review["scope_gate_severity"] == "REVIEW"
    assert review["scope_gate_blocked"] == "N"


def test_original_columns_survive():
    kept, _ = apply_gate([_row("M1", "정상 문장이다.", extra_field="보존")])
    assert kept[0]["extra_field"] == "보존"


# --------------------------------------------------------------------------
# manifest — 재현 가능성이 목적이다
# --------------------------------------------------------------------------

def _manifest(tmp_path, kept, dropped, silver=None):
    ready = tmp_path / "ready.csv"
    ready.write_text("claim_measurement_id\nM1\n", encoding="utf-8")
    out = tmp_path / "eval.csv"
    write_csv(out, kept)
    return build_manifest(ready, out, kept, dropped, silver)


def test_manifest_records_hashes_and_counts(tmp_path):
    kept, dropped = apply_gate([CLEAN, CRYPTO, FORECAST])
    manifest = _manifest(tmp_path, kept, dropped)
    assert manifest["input_measurements"] == 3
    assert manifest["locked_measurements"] == 1
    assert manifest["excluded_measurements"] == 2
    assert len(manifest["source_ready_sha256"]) == 64
    assert len(manifest["output_sha256"]) == 64


def test_manifest_breaks_down_exclusions_by_code(tmp_path):
    kept, dropped = apply_gate([CLEAN, CRYPTO, FORECAST])
    manifest = _manifest(tmp_path, kept, dropped)
    assert manifest["excluded_by_code"]["FOREIGN_MARKET_VALUE"] == 1
    assert manifest["excluded_by_code"]["FORECAST_VALUE"] == 1


def test_manifest_snapshots_the_rules_so_changes_are_detectable(tmp_path):
    kept, dropped = apply_gate([CLEAN])
    manifest = _manifest(tmp_path, kept, dropped)
    assert "비트코인" in manifest["gate_rules"]["foreign_market"]
    assert manifest["gate_rules"] == rule_snapshot()


def test_manifest_counts_review_rows_that_were_kept(tmp_path):
    kept, dropped = apply_gate([CLEAN, WORLD_CMP])
    manifest = _manifest(tmp_path, kept, dropped)
    assert manifest["review_flagged_but_kept"] == 1


def test_manifest_flags_false_positive_against_silver(tmp_path):
    """값이 재현된 건(SILVER_UNIQUE)을 제외했다면 오탐이다."""
    kept, dropped = apply_gate([CLEAN, CRYPTO])
    silver = [{"claim_measurement_id": "M2", "tier": "SILVER_UNIQUE"},
              {"claim_measurement_id": "M1", "tier": "NO_MATCH"}]
    manifest = _manifest(tmp_path, kept, dropped, silver)
    assert manifest["false_positive_check"]["silver_unique_excluded"] == 1


def test_manifest_reports_zero_false_positives_when_clean(tmp_path):
    kept, dropped = apply_gate([CLEAN, CRYPTO])
    silver = [{"claim_measurement_id": "M1", "tier": "SILVER_UNIQUE"},
              {"claim_measurement_id": "M2", "tier": "NO_MATCH"}]
    manifest = _manifest(tmp_path, kept, dropped, silver)
    assert manifest["false_positive_check"]["silver_unique_excluded"] == 0
    assert manifest["silver_tier_kept"]["SILVER_UNIQUE"] == 1


def test_manifest_is_json_serializable(tmp_path):
    kept, dropped = apply_gate([CLEAN, CRYPTO])
    manifest = _manifest(tmp_path, kept, dropped)
    assert json.loads(json.dumps(manifest, ensure_ascii=False))["schema_version"]


def test_manifest_keeps_honest_limitations(tmp_path):
    """게이트가 문장 단위라는 한계를 manifest 가 스스로 들고 다녀야 한다."""
    kept, dropped = apply_gate([CLEAN])
    manifest = _manifest(tmp_path, kept, dropped)
    assert any("문장 단위" in note for note in manifest["notes"])


def test_changing_a_rule_changes_the_manifest(tmp_path, monkeypatch):
    import lock_evaluation_set as module
    before = module.rule_snapshot()
    monkeypatch.setattr(module, "FOREIGN_MARKET", ("비트코인", "새규칙"))
    assert module.rule_snapshot() != before
