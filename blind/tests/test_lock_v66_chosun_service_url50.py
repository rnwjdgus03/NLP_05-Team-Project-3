import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "lock_v66_chosun_service_url50.py"
CATEGORIES = (
    "employment_population",
    "industry",
    "prices_income",
    "trade_goods",
    "ratio_other",
)


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_lock_excludes_prior_urls_and_binds_blind_pass(tmp_path: Path) -> None:
    pool = tmp_path / "pool.json"
    preflight = tmp_path / "preflight.json"
    freeze = tmp_path / "freeze.json"
    blind = tmp_path / "blind.json"
    prior = tmp_path / "prior.json"
    out = tmp_path / "out"
    rows = []
    checks = []
    prior_rows = []
    for category in CATEGORIES:
        for index in range(12):
            url = f"https://example.test/{category}/{index}"
            rows.append({"category": category, "url": url})
            checks.append(
                {"url": url, "status": "SUCCEEDED", "extracted_claims": 1}
            )
        prior_rows.append({"category": category, "url": rows[-12]["url"]})
    write(pool, {"urls": rows})
    write(preflight, {"results": checks})
    write(
        freeze,
        {
            "freeze_id": "v64_candidate_20260824_r1",
            "status": "FROZEN_CANDIDATE_PENDING_NEW_BLIND100",
            "components": {"engine": {"tree_sha256": "abc"}},
        },
    )
    write(
        blind,
        {
            "promotion_gate": "PASS",
            "candidate_freeze_id": "v64_candidate_20260824_r1",
            "candidate_engine_tree_sha256": "abc",
        },
    )
    write(prior, {"urls": prior_rows})
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidate-pool",
            str(pool),
            "--public-preflight",
            str(preflight),
            "--freeze-manifest",
            str(freeze),
            "--blind-gate",
            str(blind),
            "--exclude-lock",
            str(prior),
            "--output-dir",
            str(out),
        ],
        check=False,
    )
    assert result.returncode == 0
    locked = json.loads((out / "locked_urls50.json").read_text())
    assert len(locked["urls"]) == 50
    selected = {row["url"].rstrip("/") for row in locked["urls"]}
    assert not selected & {row["url"] for row in prior_rows}


def test_lock_rejects_failed_blind_gate(tmp_path: Path) -> None:
    pool = tmp_path / "pool.json"
    preflight = tmp_path / "preflight.json"
    freeze = tmp_path / "freeze.json"
    blind = tmp_path / "blind.json"
    out = tmp_path / "out"
    write(pool, {"urls": []})
    write(preflight, {"results": []})
    write(
        freeze,
        {
            "freeze_id": "v64_candidate_20260824_r1",
            "status": "FROZEN_CANDIDATE_PENDING_NEW_BLIND100",
            "components": {"engine": {"tree_sha256": "abc"}},
        },
    )
    write(
        blind,
        {
            "promotion_gate": "FAIL",
            "candidate_freeze_id": "v64_candidate_20260824_r1",
            "candidate_engine_tree_sha256": "abc",
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidate-pool",
            str(pool),
            "--public-preflight",
            str(preflight),
            "--freeze-manifest",
            str(freeze),
            "--blind-gate",
            str(blind),
            "--output-dir",
            str(out),
        ],
        check=False,
    )
    assert result.returncode != 0
    assert not out.exists()
