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
  mkdir -p "$out"
  PROJECT="$PROJECT" CODE="$CODE" PY="$PY" INDEX="$INDEX" \
    INPUT="$input" GOLD="$gold" OUT="$out" \
    bash "$CODE/run_v26e_target_contract_dev.sh"

  set -a
  source "$PROJECT/.env"
  set +a
  "$PY" -u "$CODE/run_kosis_top5_verification.py" \
    --claims "$out/prepared_all.csv" \
    --candidates "$out/local_api_candidates_top5.jsonl" \
    --output "$out/verified_candidates.jsonl" \
    --claim-output "$out/claim_decisions.jsonl" \
    --postgres-dsn postgresql:///kosis_project \
    --sqlite-cache "$out/kosis_api_cache.sqlite3" --delay 0.4
}

exec > >(tee -a "$PROJECT/runs/v27e_regression_pair_20260820.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'

run_set \
  "$PROJECT/blind/v26e_new30_v2_20260820/blind_input30.csv" \
  "$PROJECT/blind/v26e_new30_v2_20260820/blind_coordinate_gold30_locked.csv" \
  "$PROJECT/runs/v27e_strong_component_opened30_dev_20260820"

run_set \
  "$PROJECT/blind/v25/locked300_v14_mcp_blind30_candidates.csv" \
  "$PROJECT/blind/v25/v25_blind_coordinate_gold10_locked.csv" \
  "$PROJECT/runs/v27e_strong_component_old10_regression_20260820"

echo V27E_REGRESSION_PAIR_COMPLETE
