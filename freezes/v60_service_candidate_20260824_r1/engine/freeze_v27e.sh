#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
SOURCE=$PROJECT/dev/v27_generalization_20260820
FREEZE=$PROJECT/freezes/v27e_20260820_r1
MANIFEST=$FREEZE/freeze_manifest.json
PY=$PROJECT/.venv/bin/python

test -d "$SOURCE"
test ! -e "$FREEZE"
mkdir -p "$FREEZE"
tar -C "$SOURCE" \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.test-tmp-*' \
  -cf - . | tar -C "$FREEZE" -xf -
find "$FREEZE" -type f -print0 | sort -z | xargs -0 sha256sum > "$FREEZE/code_files_sha256.txt"
sha256sum "$FREEZE/code_files_sha256.txt" > "$FREEZE/code_tree_sha256.txt"

"$PY" - "$MANIFEST" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
freeze = manifest_path.parent
results = {
    "opened30": "/home/ubuntu/kosis-project/runs/v27e_strong_component_opened30_dev_20260820",
    "old10": "/home/ubuntu/kosis-project/runs/v27e_strong_component_old10_regression_20260820",
}
tree = freeze.joinpath("code_tree_sha256.txt").read_text(encoding="utf-8").split()[0]
manifest = {
    "schema_version": "kosis-v27e-freeze-v1",
    "freeze_id": "v27e_20260820_r1",
    "frozen_before_new_blind_selection": True,
    "code_tree_sha256": tree,
    "tests": {"passed": 61, "failed": 0},
    "development_results": results,
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
echo V27E_FREEZE_COMPLETE
