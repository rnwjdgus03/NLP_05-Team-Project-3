#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
PY=$PROJECT/.venv/bin/python

run_no_lock() {
  local base=$1
  local out=$2
  local gold=$3
  test ! -e "$out"
  mkdir -p "$out"
  cp "$base/prepared_all.csv" "$base/stage_a_table_pool.jsonl" \
    "$base/stage_b_coordinate_beam.jsonl" "$out/"
  "$PY" -u "$CODE/run_kosis_coordinate_stage_c.py" \
    --beam-pool "$out/stage_b_coordinate_beam.jsonl" \
    --output "$out/local_coordinate_top3.jsonl" \
    --fallback-output "$out/local_coordinate_rank4_5_fallback.jsonl" \
    --state-output "$out/stage_c_state.jsonl" --device cuda \
    --reranker-batch-size 32 --obj-scope-bonus 0.10
  "$PY" -u "$CODE/merge_local_stage_c_candidates.py" \
    --primary "$out/local_coordinate_top3.jsonl" \
    --fallback "$out/local_coordinate_rank4_5_fallback.jsonl" \
    --output "$out/local_api_candidates_top5.jsonl"
  "$PY" -u "$CODE/evaluate_coordinate_topk.py" \
    --predictions "$out/local_api_candidates_top5.jsonl" --gold "$gold" \
    --summary "$out/coordinate_topk_summary.json" \
    --details "$out/coordinate_topk_details.csv" --ks 1,3,5,10
}

run_no_lock \
  "$PROJECT/runs/v27c_multiterm_component_opened30_dev_20260820" \
  "$PROJECT/runs/v27d_new30_stagec_no_lock_20260820" \
  "$PROJECT/blind/v26e_new30_v2_20260820/blind_coordinate_gold30_locked.csv"
run_no_lock \
  "$PROJECT/runs/v27c_old_opened10_regression_20260820" \
  "$PROJECT/runs/v27d_old10_stagec_no_lock_20260820" \
  "$PROJECT/blind/v25/v25_blind_coordinate_gold10_locked.csv"

echo V27_STAGEC_LOCK_AB_COMPLETE
