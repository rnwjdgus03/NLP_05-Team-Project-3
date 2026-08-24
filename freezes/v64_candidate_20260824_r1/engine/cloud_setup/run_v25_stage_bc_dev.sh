#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=/home/ubuntu/kosis-project
REPO="${KOSIS_V25_REPO:-$PROJECT_ROOT/deploy_v25_range_item_total_r3}"
RUN_ID="${KOSIS_RUN_ID:-v25_dual_top12_stage_bc_dev30_20260820}"
TABLE_POOL="${KOSIS_TABLE_POOL:-$PROJECT_ROOT/runs/v25_stage_a_dual_channel_top12_dev55_20260820/stage_a_table_pool.jsonl}"
GOLD="$PROJECT_ROOT/app/data/gold/stratified_actual_coordinate_gold_v21.csv"
OUT="$PROJECT_ROOT/runs/$RUN_ID"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

mkdir -p "$OUT"
cd "$REPO"
sha256sum "$TABLE_POOL" > "$OUT/table_pool_sha256.txt"

"$PYTHON" -u run_kosis_coordinate_stage_b.py \
  --table-pool "$TABLE_POOL" \
  --postgres-dsn postgresql:///kosis_project \
  --output "$OUT/stage_b_coordinate_beam.jsonl" \
  --device cuda \
  --embedding-batch-size 128 \
  --coordinate-pool-top-k 200 \
  --preserve-table-fallback

"$PYTHON" -u run_kosis_coordinate_stage_c.py \
  --beam-pool "$OUT/stage_b_coordinate_beam.jsonl" \
  --output "$OUT/local_coordinate_top3.jsonl" \
  --fallback-output "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --state-output "$OUT/stage_c_state.jsonl" \
  --device cuda \
  --reranker-batch-size 32 \
  --obj-scope-bonus 0.10 \
  --lock-incumbent-top3

"$PYTHON" -u merge_local_stage_c_candidates.py \
  --primary "$OUT/local_coordinate_top3.jsonl" \
  --fallback "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --output "$OUT/local_api_candidates_top5.jsonl"

"$PYTHON" -u evaluate_coordinate_topk.py \
  --predictions "$OUT/local_api_candidates_top5.jsonl" \
  --gold "$GOLD" \
  --summary "$OUT/coordinate_topk_summary.json" \
  --details "$OUT/coordinate_topk_details.csv" \
  --ks 1,3,5

echo V25_STAGE_BC_COMPLETE
