import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "verify_frozen_url_run_identity.py"


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_identity_passes_only_for_bound_engine(tmp_path: Path) -> None:
    lock = tmp_path / "lock.json"
    lock_manifest = tmp_path / "lock_manifest.json"
    engine = tmp_path / "engine.json"
    state = tmp_path / "state.json"
    summary = tmp_path / "summary.json"
    output = tmp_path / "output.json"
    write(
        lock,
        {
            "candidate_freeze_id": "freeze-1",
            "candidate_engine_tree_sha256": "sha-1",
            "urls": [{"url": "https://example.test/1"}],
        },
    )
    import hashlib

    lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
    write(
        lock_manifest,
        {"artifact_sha256": {"locked_urls50.json": lock_sha}},
    )
    write(engine, {"freeze_id": "freeze-1", "code_tree_sha256": "sha-1"})
    write(state, {"records": {"1": {"job_status": "SUCCEEDED"}}})
    write(
        summary,
        {
            "locked_urls": 1,
            "jobs_succeeded": 1,
            "engine_counts": {"freeze-1|sha-1": 1},
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--lock",
            str(lock),
            "--lock-manifest",
            str(lock_manifest),
            "--engine-manifest",
            str(engine),
            "--state",
            str(state),
            "--summary",
            str(summary),
            "--output",
            str(output),
        ],
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(output.read_text())["status"] == "PASS"


def test_identity_rejects_mixed_engine_results(tmp_path: Path) -> None:
    lock = tmp_path / "lock.json"
    lock_manifest = tmp_path / "lock_manifest.json"
    engine = tmp_path / "engine.json"
    state = tmp_path / "state.json"
    summary = tmp_path / "summary.json"
    output = tmp_path / "output.json"
    write(
        lock,
        {
            "candidate_freeze_id": "freeze-1",
            "candidate_engine_tree_sha256": "sha-1",
            "urls": [{"url": "https://example.test/1"}],
        },
    )
    import hashlib

    write(
        lock_manifest,
        {
            "artifact_sha256": {
                "locked_urls50.json": hashlib.sha256(lock.read_bytes()).hexdigest()
            }
        },
    )
    write(engine, {"freeze_id": "freeze-1", "code_tree_sha256": "sha-1"})
    write(state, {"records": {"1": {"job_status": "SUCCEEDED"}}})
    write(
        summary,
        {
            "locked_urls": 1,
            "jobs_succeeded": 1,
            "engine_counts": {"freeze-1|sha-1": 1, "other|sha": 1},
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--lock",
            str(lock),
            "--lock-manifest",
            str(lock_manifest),
            "--engine-manifest",
            str(engine),
            "--state",
            str(state),
            "--summary",
            str(summary),
            "--output",
            str(output),
        ],
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(output.read_text())["checks"]["single_expected_engine"] is False
