#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
SOURCE=$PROJECT/dev/v27_generalization_20260820
FREEZE=$PROJECT/freezes/v28g_20260820_r1
MANIFEST=$FREEZE/freeze_manifest.json
PY=$PROJECT/.venv/bin/python

test -d "$SOURCE"
test ! -e "$FREEZE"
mkdir -p "$FREEZE"
tar -C "$SOURCE" \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.test-tmp-*' \
  -cf - . | tar -C "$FREEZE" -xf -
find "$FREEZE" -type f \
  ! -name 'code_files_sha256.txt' ! -name 'code_tree_sha256.txt' \
  ! -name 'freeze_manifest.json' -print0 \
  | sort -z | xargs -0 sha256sum > "$FREEZE/code_files_sha256.txt"
sha256sum "$FREEZE/code_files_sha256.txt" > "$FREEZE/code_tree_sha256.txt"

"$PY" - "$MANIFEST" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
freeze = manifest_path.parent
tree = freeze.joinpath("code_tree_sha256.txt").read_text(encoding="utf-8").split()[0]
manifest = {
    "schema_version": "kosis-v28g-freeze-v1",
    "freeze_id": "v28g_20260820_r1",
    "frozen_before_new_blind_selection": True,
    "code_tree_sha256": tree,
    "tests": {"passed": 72, "failed": 0},
    "development_results": {
        "opened30": "/home/ubuntu/kosis-project/runs/v28g_aggregate_target_opened30_dev_20260820",
        "previous30_regression": "/home/ubuntu/kosis-project/runs/v28g_previous30_regression_20260820",
        "old10_regression": "/home/ubuntu/kosis-project/runs/v28g_old10_regression_20260820",
    },
    "development_api_safety": {
        "claim_verified_match": 14,
        "claim_unresolved": 16,
        "claim_value_mismatch": 0,
    },
    "preregistered_blind_thresholds": {
        "stage_a_table_top10_min": 0.80,
        "table_item_top5_min": 0.70,
        "coordinate_top5_min": 0.60,
        "full_top5_min": 0.50,
        "false_value_mismatch_max": 0,
    },
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
PY

find "$FREEZE" -type f -exec chmod a-w {} +
echo V28G_FREEZE_COMPLETE
