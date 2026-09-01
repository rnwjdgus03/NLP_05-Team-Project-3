#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
PY="$PROJECT/.venv/bin/python"
BASE_CODE="$PROJECT/freezes/v60_service_candidate_20260824_r1/engine"
CANDIDATE_OUT="$PROJECT/development/v64_period_survey_exact_20260824/article01_probe"
INPUT="$PROJECT/runs/service_v60_dev40_20260824_r1/jobs/f54e06bf280e47e4b9f780d68ad5f148/measurements.csv"
OUT="$PROJECT/development/v64_period_survey_exact_20260824/period_probe_ab"

test -s "$INPUT"
test -s "$CANDIDATE_OUT/prepared_all.csv"
test -s "$CANDIDATE_OUT/probe_summary.json"
test ! -e "$OUT"
mkdir -p "$OUT"

export PYTHONPATH="$BASE_CODE"
export PYTHONDONTWRITEBYTECODE=1
cd "$BASE_CODE"
"$PY" -u prepare_kosis_mapping_input.py --input "$INPUT" \
  --output "$OUT/v60_prepared_ready.csv" \
  --rejected-output "$OUT/v60_prepared_rejected.csv" \
  --enrich-output "$OUT/v60_prepared_enrich.csv" \
  --all-output "$OUT/v60_prepared_all.csv"

"$PY" - "$OUT/v60_prepared_all.csv" \
  "$CANDIDATE_OUT/prepared_all.csv" "$OUT/period_probe_ab_summary.json" <<'PY'
import csv
import json
import pathlib
import sys
from collections import Counter

baseline_path = pathlib.Path(sys.argv[1])
candidate_path = pathlib.Path(sys.argv[2])
output_path = pathlib.Path(sys.argv[3])

def load(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["claim_measurement_id"]: row for row in rows}
    assert len(by_id) == len(rows), f"duplicate measurement id in {path}"
    return rows, by_id

baseline_rows, baseline = load(baseline_path)
candidate_rows, candidate = load(candidate_path)
assert baseline.keys() == candidate.keys(), {
    "baseline_only": sorted(baseline.keys() - candidate.keys()),
    "candidate_only": sorted(candidate.keys() - baseline.keys()),
}

transitions = Counter()
details = []
for measurement_id in sorted(baseline):
    old = baseline[measurement_id]
    new = candidate[measurement_id]
    old_gate = old.get("mapping_gate", "")
    new_gate = new.get("mapping_gate", "")
    transitions[f"{old_gate}->{new_gate}"] += 1
    details.append({
        "claim_measurement_id": measurement_id,
        "measurement_text": new.get("measurement_text", ""),
        "baseline_gate": old_gate,
        "candidate_gate": new_gate,
        "baseline_period": old.get("period", ""),
        "candidate_period": new.get("period", ""),
        "candidate_period_alignment_status": new.get("period_alignment_status", ""),
    })

baseline_ready = sum(row.get("mapping_gate") == "READY" for row in baseline_rows)
candidate_ready = sum(row.get("mapping_gate") == "READY" for row in candidate_rows)
ready_regressions = sum(
    baseline[mid].get("mapping_gate") == "READY"
    and candidate[mid].get("mapping_gate") != "READY"
    for mid in baseline
)
period_repairs_to_ready = sum(
    baseline[mid].get("mapping_gate") != "READY"
    and candidate[mid].get("mapping_gate") == "READY"
    and "EXPLICIT_CLAIM_MONTH_INHERITED" in candidate[mid].get("period_alignment_status", "")
    for mid in baseline
)

checks = {
    "development_only": True,
    "blind_labels_used_zero": True,
    "same_measurement_ids": baseline.keys() == candidate.keys(),
    "input_rows_exact_4": len(candidate_rows) == 4,
    "candidate_ready_increased": candidate_ready > baseline_ready,
    "ready_regressions_zero": ready_regressions == 0,
    "period_repairs_to_ready_at_least_1": period_repairs_to_ready >= 1,
}
summary = {
    "schema_version": "kosis-v64-period-probe-ab-v1",
    "dataset_role": "DEVELOPMENT_ONLY",
    "blind_labels_used": 0,
    "baseline_engine": "v60_service_candidate_20260824_r1",
    "candidate_engine": "v64_period_survey_exact_20260824",
    "input_measurements": len(candidate_rows),
    "baseline_ready_measurements": baseline_ready,
    "candidate_ready_measurements": candidate_ready,
    "ready_delta": candidate_ready - baseline_ready,
    "ready_regressions": ready_regressions,
    "period_repairs_to_ready": period_repairs_to_ready,
    "gate_transitions": dict(sorted(transitions.items())),
    "checks": checks,
    "status": "PASS" if all(checks.values()) else "FAIL",
    "details": details,
}
output_path.write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
if summary["status"] != "PASS":
    raise SystemExit(2)
PY

sha256sum "$OUT/v60_prepared_all.csv" \
  "$CANDIDATE_OUT/prepared_all.csv" "$OUT/period_probe_ab_summary.json" \
  > "$OUT/artifact_sha256.txt"
echo V64_PERIOD_PROBE_AB_COMPLETE
