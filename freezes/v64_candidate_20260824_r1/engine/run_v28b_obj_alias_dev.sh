#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
PY=$PROJECT/.venv/bin/python
GOLD=$PROJECT/blind/v27e_new_coordinate30_v4_20260820/blind_coordinate_gold30_locked.csv
BASE=$PROJECT/runs/v28_obj_contract_opened30_dev_20260820
OUT=$PROJECT/runs/v28b_obj_alias_opened30_dev_20260820
DSN=postgresql:///kosis_project

test ! -e "$OUT"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'
cd "$CODE"

"$PY" -m pytest -q tests
cp "$BASE"/prepared_*.csv "$OUT"/
cp "$BASE"/stage_a_*.jsonl "$OUT"/

"$PY" -u run_kosis_coordinate_stage_b.py \
  --table-pool "$OUT/stage_a_table_pool.jsonl" --postgres-dsn "$DSN" \
  --output "$OUT/stage_b_coordinate_beam.jsonl" --device cuda \
  --embedding-batch-size 128 --item-top-k 10 --axis-top-k 20 \
  --beam-width 250 --coordinate-pool-top-k 250 --preserve-table-fallback

"$PY" -u run_kosis_coordinate_stage_c.py \
  --beam-pool "$OUT/stage_b_coordinate_beam.jsonl" \
  --output "$OUT/local_coordinate_top3.jsonl" \
  --fallback-output "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --state-output "$OUT/stage_c_state.jsonl" --device cuda \
  --reranker-batch-size 32 --obj-scope-bonus 0.10
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

echo V28B_OBJ_ALIAS_OPENED30_DEV_COMPLETE
