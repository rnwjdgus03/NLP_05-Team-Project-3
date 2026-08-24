#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
INDEX=$PROJECT/indexes/bge_m3_table_v2_complete
PY=$PROJECT/.venv/bin/python
INPUT=$PROJECT/blind/v27e_new_coordinate30_v4_20260820/blind_input30.csv
GOLD=$PROJECT/blind/v27e_new_coordinate30_v4_20260820/blind_coordinate_gold30_locked.csv
OUT=$PROJECT/runs/v28f_period_item_scope_opened30_dev_20260820

test ! -e "$OUT"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'

PROJECT="$PROJECT" CODE="$CODE" INDEX="$INDEX" PY="$PY" \
INPUT="$INPUT" GOLD="$GOLD" OUT="$OUT" \
  bash "$CODE/run_v26e_target_contract_dev.sh"

echo V28F_PERIOD_ITEM_SCOPE_OPENED30_DEV_COMPLETE
