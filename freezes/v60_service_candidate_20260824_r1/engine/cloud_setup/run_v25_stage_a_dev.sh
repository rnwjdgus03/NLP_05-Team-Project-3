#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=/home/ubuntu/kosis-project
REPO="${KOSIS_V25_REPO:-$PROJECT_ROOT/deploy_v25_range_item_total}"
INDEX="$PROJECT_ROOT/indexes/bge_m3_table_v2_complete"
INPUT="$PROJECT_ROOT/runs/hybrid_bge_m3_postgres_mcp_v24b_period_stage_b_slots_20260820/06_in_ready_all_latest_prepared_all.csv"
GOLD="$PROJECT_ROOT/app/data/gold/stratified_actual_coordinate_gold_v21.csv"
RUN_ID="${KOSIS_RUN_ID:-v25_stage_a_item_recall_dev55_20260820}"
OUT="$PROJECT_ROOT/runs/$RUN_ID"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
TABLE_RERANK_TOP_K="${TABLE_RERANK_TOP_K:-100}"
ITEM_RECALL_TOP_K="${ITEM_RECALL_TOP_K:-50}"
ITEM_RERANK_SLOTS="${ITEM_RERANK_SLOTS:-10}"

mkdir -p "$OUT"
cd "$REPO"

find . -type f \( -name '*.py' -o -name '*.sh' -o -name '*.sql' \) \
  ! -path './__pycache__/*' ! -path './.pytest_cache/*' -print0 | \
  sort -z | xargs -0 sha256sum > "$OUT/live_code_files_sha256.txt"
sha256sum "$OUT/live_code_files_sha256.txt" > "$OUT/live_code_tree_sha256.txt"
sha256sum "$INPUT" "$INDEX/tables.csv" "$INDEX/embeddings.npy" "$INDEX/manifest.json" \
  > "$OUT/input_index_sha256.txt"

"$PYTHON" -u run_kosis_coordinate_stage_a.py \
  --claims "$INPUT" \
  --semantic-index "$INDEX" \
  --postgres-dsn postgresql:///kosis_project \
  --output "$OUT/stage_a_table_pool.jsonl" \
  --device cuda \
  --lexical-top-k 300 \
  --dense-top-k 300 \
  --table-rerank-top-k "$TABLE_RERANK_TOP_K" \
  --table-pool-top-k 10 \
  --item-recall-top-k "$ITEM_RECALL_TOP_K" \
  --item-rerank-slots "$ITEM_RERANK_SLOTS" \
  --reranker-batch-size 32

"$PYTHON" -u evaluate_stage_a_table_recall.py \
  --predictions "$OUT/stage_a_table_pool.jsonl" \
  --gold "$GOLD" \
  --summary "$OUT/stage_a_table_recall_summary.json" \
  --details "$OUT/stage_a_table_recall_details.csv" \
  --ks 1,3,5,10

echo V25_STAGE_A_COMPLETE
