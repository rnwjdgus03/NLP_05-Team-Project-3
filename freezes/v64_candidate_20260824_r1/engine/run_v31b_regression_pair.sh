#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
PY=$PROJECT/.venv/bin/python
INDEX=$PROJECT/indexes/bge_m3_table_v2_complete

run_set() {
  local input=$1
  local gold=$2
  local out=$3
  test ! -e "$out"
  PROJECT="$PROJECT" CODE="$CODE" PY="$PY" INDEX="$INDEX" \
    INPUT="$input" GOLD="$gold" OUT="$out" \
    bash "$CODE/run_v26e_target_contract_dev.sh"
}

exec > >(tee -a "$PROJECT/runs/v31b_regression_pair_20260821.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'

run_set \
  "$PROJECT/blind/v26e_new30_v2_20260820/blind_input30.csv" \
  "$PROJECT/blind/v26e_new30_v2_20260820/blind_coordinate_gold30_locked.csv" \
  "$PROJECT/runs/v31b_previous30_regression_20260821"

run_set \
  "$PROJECT/blind/v25/locked300_v14_mcp_blind30_candidates.csv" \
  "$PROJECT/blind/v25/v25_blind_coordinate_gold10_locked.csv" \
  "$PROJECT/runs/v31b_old10_regression_20260821"

echo V31B_REGRESSION_PAIR_COMPLETE
