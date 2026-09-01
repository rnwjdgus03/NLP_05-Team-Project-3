#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
PY=$PROJECT/.venv/bin/python
OUT=$PROJECT/runs/v28g_aggregate_target_opened30_dev_20260820

exec > >(tee -a "$OUT/api_verification.log") 2>&1
set -a
source "$PROJECT/.env"
set +a
cd "$CODE"
"$PY" -u run_kosis_top5_verification.py \
  --claims "$OUT/prepared_all.csv" \
  --candidates "$OUT/local_api_candidates_top5.jsonl" \
  --output "$OUT/verified_candidates.jsonl" \
  --claim-output "$OUT/claim_decisions.jsonl" \
  --postgres-dsn postgresql:///kosis_project \
  --sqlite-cache "$OUT/kosis_api_cache.sqlite3" --delay 0.4

echo V28G_API_SAFETY_COMPLETE
