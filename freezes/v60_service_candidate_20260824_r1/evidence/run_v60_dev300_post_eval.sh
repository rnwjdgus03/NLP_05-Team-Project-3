#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/development/v60_placeholder_period_20260824/candidate/engine
OUT=$PROJECT/runs/v60_dev300_coordinate_regression_20260824_r1
BASELINE=$PROJECT/runs/v58_dev300_coordinate_regression_20260824_r1/coordinate_topk_multigold_summary.json
GOLD=$PROJECT/runs/v41_primary_tail_metadata_cascade_20260823_r1/dev_coordinate_gold300_api_alternates.csv
PY=$PROJECT/.venv/bin/python

mkdir -p "$OUT"
exec > >(tee -a "$OUT/post_eval.log") 2>&1

echo "waiting_for=kosis-v60-dev300"
while tmux has-session -t kosis-v60-dev300 2>/dev/null; do
  sleep 20
done

grep -q 'V58_DEV300_PIPELINE_COMPLETE' "$OUT/pipeline.log"
test -s "$OUT/final_candidates_top5.jsonl"

cd "$CODE"
"$PY" evaluate_coordinate_topk_multigold.py \
  --predictions "$OUT/final_candidates_top5.jsonl" \
  --gold "$GOLD" \
  --summary "$OUT/coordinate_topk_multigold_summary.json" \
  --details "$OUT/coordinate_topk_multigold_details.csv" \
  --ks 1,3,5

set +e
"$PY" evaluate_v60_dev300_gate.py \
  --candidate-summary "$OUT/coordinate_topk_multigold_summary.json" \
  --baseline-summary "$BASELINE" \
  --output "$OUT/regression_gate.json" \
  --expected-claims 300 \
  --item-top5-min 0.75 \
  --coordinate-top5-min 0.70
gate_status=$?
set -e

sha256sum \
  "$OUT/final_candidates_top5.jsonl" \
  "$OUT/coordinate_topk_multigold_summary.json" \
  "$OUT/coordinate_topk_multigold_details.csv" \
  "$OUT/regression_gate.json" \
  > "$OUT/post_eval_artifact_sha256.txt"

echo "V60_DEV300_EVAL_EXIT=$gate_status"
exit "$gate_status"
