import csv
import json
import subprocess
import sys
from pathlib import Path


def write_claims(path: Path, ids: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["claim_measurement_id"])
        writer.writeheader(); writer.writerows({"claim_measurement_id": value} for value in ids)


def test_filter_uses_intersection_for_mixed_gate_inputs(tmp_path: Path) -> None:
    claims = tmp_path / "claims.csv"; source = tmp_path / "source.jsonl"; output = tmp_path / "out.jsonl"
    write_claims(claims, ["ready", "rejected"])
    source.write_text(json.dumps({"claim_measurement_id": "ready"}) + "\n", encoding="utf-8")
    completed = subprocess.run([
        sys.executable, str(Path(__file__).parents[1] / "filter_jsonl_by_claims.py"),
        "--claims", str(claims), "--input", str(source), "--output", str(output),
    ], capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)["missing_in_jsonl"] == 1
    assert json.loads(output.read_text())["claim_measurement_id"] == "ready"


def test_filter_can_enforce_strict_mode(tmp_path: Path) -> None:
    claims = tmp_path / "claims.csv"; source = tmp_path / "source.jsonl"; output = tmp_path / "out.jsonl"
    write_claims(claims, ["ready", "missing"])
    source.write_text(json.dumps({"claim_measurement_id": "ready"}) + "\n", encoding="utf-8")
    completed = subprocess.run([
        sys.executable, str(Path(__file__).parents[1] / "filter_jsonl_by_claims.py"),
        "--claims", str(claims), "--input", str(source), "--output", str(output), "--require-all",
    ], capture_output=True, text=True)
    assert completed.returncode != 0
