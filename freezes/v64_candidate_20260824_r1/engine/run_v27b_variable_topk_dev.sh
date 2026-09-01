#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
BASE=$PROJECT/runs/v27_opened_official30_dev_20260820
OUT=$PROJECT/runs/v27b_variable_topk_opened30_dev_20260820
GOLD=$PROJECT/blind/v26e_new30_v2_20260820/blind_coordinate_gold30_locked.csv
PY=$PROJECT/.venv/bin/python

test ! -e "$OUT"
mkdir -p "$OUT"
cp "$BASE/prepared_all.csv" "$BASE/stage_a_table_pool.jsonl" \
  "$BASE/stage_b_coordinate_beam.jsonl" "$OUT/"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'

cd "$CODE"
"$PY" -m pytest -q tests
"$PY" -u run_kosis_coordinate_stage_c.py \
  --beam-pool "$OUT/stage_b_coordinate_beam.jsonl" \
  --output "$OUT/local_coordinate_top3.jsonl" \
  --fallback-output "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --state-output "$OUT/stage_c_state.jsonl" --device cuda \
  --reranker-batch-size 32 --obj-scope-bonus 0.10 --lock-incumbent-top3
"$PY" -u merge_local_stage_c_candidates.py \
  --primary "$OUT/local_coordinate_top3.jsonl" \
  --fallback "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --output "$OUT/local_api_candidates_top5.jsonl"
"$PY" -u evaluate_stage_a_table_recall.py \
  --predictions "$OUT/stage_a_table_pool.jsonl" --gold "$GOLD" \
  --summary "$OUT/stage_a_table_recall_summary.json" \
  --details "$OUT/stage_a_table_recall_details.csv" --ks 1,3,5,10
"$PY" -u evaluate_coordinate_topk.py \
  --predictions "$OUT/local_api_candidates_top5.jsonl" --gold "$GOLD" \
  --summary "$OUT/coordinate_topk_summary.json" \
  --details "$OUT/coordinate_topk_details.csv" --ks 1,3,5,10

set -a
source "$PROJECT/.env"
set +a
"$PY" -u run_kosis_top5_verification.py \
  --claims "$OUT/prepared_all.csv" \
  --candidates "$OUT/local_api_candidates_top5.jsonl" \
  --output "$OUT/verified_candidates.jsonl" \
  --claim-output "$OUT/claim_decisions.jsonl" \
  --postgres-dsn postgresql:///kosis_project \
  --sqlite-cache "$BASE/kosis_api_cache.sqlite3" --delay 0.4

echo V27B_VARIABLE_TOPK_DEV_COMPLETE
