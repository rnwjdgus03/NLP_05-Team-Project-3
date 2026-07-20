import csv

import pytest

from run_kosis_measurement_pipeline import validate_reusable_candidates


def write_csv(path, rows):
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_validate_reusable_candidates_accepts_matching_measurements(tmp_path):
    ready = tmp_path / "ready.csv"
    candidates = tmp_path / "candidates.csv"
    write_csv(
        ready,
        [
            {"claim_id": "C1", "claim_measurement_id": "C1-m1"},
            {"claim_id": "C2", "claim_measurement_id": "C2-m1"},
        ],
    )
    write_csv(
        candidates,
        [
            {"claim_id": "C1", "claim_measurement_id": "C1-m1", "candidate_rank": "1"},
            {"claim_id": "C1", "claim_measurement_id": "C1-m1", "candidate_rank": "2"},
            {"claim_id": "C2", "claim_measurement_id": "C2-m1", "candidate_rank": "1"},
        ],
    )

    validate_reusable_candidates(ready, candidates)


def test_validate_reusable_candidates_rejects_stale_file(tmp_path):
    ready = tmp_path / "ready.csv"
    candidates = tmp_path / "candidates.csv"
    write_csv(ready, [{"claim_id": "C1", "claim_measurement_id": "C1-m1"}])
    write_csv(
        candidates,
        [{"claim_id": "OLD", "claim_measurement_id": "OLD-m1", "candidate_rank": "1"}],
    )

    with pytest.raises(ValueError, match="measurement 집합"):
        validate_reusable_candidates(ready, candidates)
