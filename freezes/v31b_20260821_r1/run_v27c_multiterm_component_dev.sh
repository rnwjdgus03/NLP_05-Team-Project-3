#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
BLIND=$PROJECT/blind/v26e_new30_v2_20260820
INPUT=$BLIND/blind_input30.csv
GOLD=$BLIND/blind_coordinate_gold30_locked.csv
OUT=$PROJECT/runs/v27c_multiterm_component_opened30_dev_20260820
PY=$PROJECT/.venv/bin/python
INDEX=$PROJECT/indexes/bge_m3_table_v2_complete

test ! -e "$OUT"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'

PROJECT="$PROJECT" CODE="$CODE" INDEX="$INDEX" PY="$PY" \
INPUT="$INPUT" GOLD="$GOLD" OUT="$OUT" \
  bash "$CODE/run_v26e_target_contract_dev.sh"

set -a
source "$PROJECT/.env"
set +a
"$PY" -u "$CODE/run_kosis_top5_verification.py" \
  --claims "$OUT/prepared_all.csv" \
  --candidates "$OUT/local_api_candidates_top5.jsonl" \
  --output "$OUT/verified_candidates.jsonl" \
  --claim-output "$OUT/claim_decisions.jsonl" \
  --postgres-dsn postgresql:///kosis_project \
  --sqlite-cache "$OUT/kosis_api_cache.sqlite3" --delay 0.4

echo V27C_MULTITERM_COMPONENT_DEV_COMPLETE
