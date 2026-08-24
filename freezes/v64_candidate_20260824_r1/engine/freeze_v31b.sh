#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
SOURCE=$PROJECT/dev/v27_generalization_20260820
FREEZE=$PROJECT/freezes/v31b_20260821_r1
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
    "schema_version": "kosis-v31b-freeze-v1",
    "freeze_id": "v31b_20260821_r1",
    "frozen_before_new_blind_selection": True,
    "code_tree_sha256": tree,
    "tests": {"passed": 75, "failed": 0},
    "development_results": {
        "opened_v30_30": "/home/ubuntu/kosis-project/runs/v31b_explicit_table_scope_opened30_dev_20260821",
        "previous30_regression": "/home/ubuntu/kosis-project/runs/v31b_previous30_regression_20260821",
        "old10_regression": "/home/ubuntu/kosis-project/runs/v31b_old10_regression_20260821",
    },
    "opened_v30_metrics": {
        "stage_a_table_top10": 0.80,
        "table_item_top5": 0.80,
        "coordinate_top5": 0.7666666666666667,
        "full_top5": 0.7666666666666667,
        "false_value_mismatch": 0,
        "uncertain_is_unresolved": True,
    },
    "preregistered_blind_thresholds": {
        "stage_a_table_top10_min": 0.80,
        "table_item_top5_min": 0.70,
        "coordinate_top5_min": 0.60,
        "full_top5_min": 0.50,
        "false_value_mismatch_max": 0,
        "uncertain_must_be_unresolved": True,
    },
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
PY

find "$FREEZE" -type f -exec chmod a-w {} +
test "$(find "$FREEZE" -type f -perm /222 | wc -l)" -eq 0
echo V31B_FREEZE_COMPLETE
