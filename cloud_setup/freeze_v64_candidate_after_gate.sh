#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
SOURCE=$PROJECT/development/v64_period_survey_exact_20260824/candidate/engine
GATE=$PROJECT/development/v64_period_survey_exact_20260824/mapping_memory_dev600/promotion_gate.json
MEMORY=$SOURCE/mapping_memory_dev600.json
PROBE=$PROJECT/development/v64_period_survey_exact_20260824/article01_probe/probe_summary.json
PERIOD_AB=$PROJECT/development/v64_period_survey_exact_20260824/period_probe_ab/period_probe_ab_summary.json
DEV_MANIFEST=$PROJECT/development/v62_generalization_dev600_20260824_r1/dev_manifest.json
FREEZE_ID=v64_candidate_20260824_r1
FREEZE=$PROJECT/freezes/$FREEZE_ID
PY=$PROJECT/.venv/bin/python

test -d "$SOURCE"
test -s "$GATE"
test -s "$MEMORY"
test -s "$PROBE"
test -s "$PERIOD_AB"
test -s "$DEV_MANIFEST"
test ! -e "$FREEZE"

"$PY" - "$GATE" "$MEMORY" "$PROBE" "$PERIOD_AB" "$DEV_MANIFEST" <<'PY'
import json
import pathlib
import sys

gate, memory, probe, period_ab, manifest = (
    json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for path in sys.argv[1:]
)
assert gate["promotion_gate"] == "PASS", gate.get("checks")
assert all(gate["checks"].values()), gate["checks"]
assert gate["evaluation_mode"] == "SUPERVISED_EXACT_MAPPING_CACHE_RESUBSTITUTION"
assert float(gate["candidate"]["item_accuracy_at_5"]) >= 0.75
assert float(gate["candidate"]["coordinate_accuracy_at_5"]) >= 0.70
assert int(gate["blind_labels_used"]) == 0
assert memory["dataset_role"] == "DEVELOPMENT_SUPERVISED_CACHE"
assert int(memory["blind_labels_used"]) == 0
assert int(memory["entry_count"]) >= 500
assert probe["dataset_role"] == "DEVELOPMENT_ONLY"
assert int(probe["blind_labels_used"]) == 0
assert period_ab["status"] == "PASS", period_ab.get("checks")
assert all(period_ab["checks"].values()), period_ab["checks"]
assert int(period_ab["ready_delta"]) >= 1
assert int(period_ab["ready_regressions"]) == 0
assert manifest["development_only"] is True
assert int(manifest["blind_label_rows_used_for_tuning"]) == 0
assert int(manifest["historical_table_overlap"]) == 0
print("V64_MAPPING_FREEZE_PREFLIGHT=PASS")
PY

export PYTHONPATH="$SOURCE"
export PYTHONDONTWRITEBYTECODE=1
"$PY" -m pytest -q "$SOURCE/tests"

mkdir -p "$FREEZE/engine"
tar -C "$SOURCE" \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.test-tmp-*' \
  --exclude='freeze_manifest.json' --exclude='code_files_sha256*.txt' \
  --exclude='code_tree_sha256*.txt' \
  -cf - . | tar -C "$FREEZE/engine" -xf -

find "$FREEZE/engine" -type f -print0 \
  | sort -z | xargs -0 sha256sum > "$FREEZE/code_files_sha256.txt"
sha256sum "$FREEZE/code_files_sha256.txt" > "$FREEZE/code_tree_sha256.txt"

"$PY" - "$FREEZE" "$FREEZE_ID" "$GATE" "$MEMORY" "$PROBE" "$PERIOD_AB" "$DEV_MANIFEST" <<'PY'
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

freeze = pathlib.Path(sys.argv[1])
freeze_id = sys.argv[2]
gate_path, memory_path, probe_path, period_ab_path, dev_manifest_path = map(pathlib.Path, sys.argv[3:])

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

gate = json.loads(gate_path.read_text(encoding="utf-8"))
memory = json.loads(memory_path.read_text(encoding="utf-8"))
probe = json.loads(probe_path.read_text(encoding="utf-8"))
period_ab = json.loads(period_ab_path.read_text(encoding="utf-8"))
tree_sha = freeze.joinpath("code_tree_sha256.txt").read_text().split()[0]
manifest = {
    "schema_version": "kosis-v64-mapping-candidate-freeze-v1",
    "freeze_id": freeze_id,
    "status": "FROZEN_CANDIDATE_PENDING_NEW_BLIND100",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "code_tree_sha256": tree_sha,
    "frozen_before_new_blind_selection": True,
    "components": {"engine": {"path": "engine", "tree_sha256": tree_sha}},
    "development_evaluation": {
        "dataset_role": gate["dataset_role"],
        "evaluation_mode": gate["evaluation_mode"],
        "claims": gate["expected_claims"],
        "promotion_gate": gate["promotion_gate"],
        "item_accuracy_at_5": gate["candidate"]["item_accuracy_at_5"],
        "coordinate_accuracy_at_5": gate["candidate"]["coordinate_accuracy_at_5"],
        "baseline_item_accuracy_at_5": gate["baseline"]["item_accuracy_at_5"],
        "baseline_coordinate_accuracy_at_5": gate["baseline"]["coordinate_accuracy_at_5"],
        "disclosure": gate["disclosure"],
        "gate_sha256": digest(gate_path),
        "development_manifest_sha256": digest(dev_manifest_path),
        "blind_labels_used": 0,
        "historical_table_overlap": 0,
    },
    "mapping_memory": {
        "dataset_role": memory["dataset_role"],
        "entry_count": memory["entry_count"],
        "covered_development_rows": memory["covered_development_rows"],
        "collision_key_count": memory["collision_key_count"],
        "key_fields": memory["key_fields"],
        "memory_sha256": digest(memory_path),
        "blind_labels_used": 0,
    },
    "period_probe": {
        "dataset_role": probe["dataset_role"],
        "ready_measurements": probe["ready_measurements"],
        "verified_match_rows": probe["verified_match_rows"],
        "probe_sha256": digest(probe_path),
        "ab_status": period_ab["status"],
        "baseline_ready_measurements": period_ab["baseline_ready_measurements"],
        "candidate_ready_measurements": period_ab["candidate_ready_measurements"],
        "ready_delta": period_ab["ready_delta"],
        "ready_regressions": period_ab["ready_regressions"],
        "period_ab_sha256": digest(period_ab_path),
    },
    "preregistered_new_blind100_thresholds": {
        "item_accuracy_at_5_min": 0.75,
        "coordinate_accuracy_at_5_min": 0.70,
        "eligible_overlap_exact": 100,
        "missing_prediction_packets_max": 0,
    },
    "evaluation_policy": {
        "v33_reuse": False,
        "v61_reuse": False,
        "new_blind100_runs": 1,
        "no_tuning_after_unblind": True,
        "finish_project_after_one_shot_blind_regardless_of_result": True,
    },
    "tests": {"status": "PASS", "scope": "engine/tests"},
}
freeze.joinpath("freeze_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
PY

cp "$FREEZE/freeze_manifest.json" "$FREEZE/engine/freeze_manifest.json"
find "$FREEZE" -type f -exec chmod a-w {} +
find "$FREEZE" -type d -exec chmod a-w {} +
test "$(find "$FREEZE" -type f -perm /222 | wc -l)" -eq 0
test ! -w "$FREEZE"
echo "V64_MAPPING_CANDIDATE_FREEZE_COMPLETE=$FREEZE"
