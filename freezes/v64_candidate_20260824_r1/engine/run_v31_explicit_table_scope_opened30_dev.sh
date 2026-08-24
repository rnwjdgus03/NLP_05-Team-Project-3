#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
CODE=$PROJECT/dev/v27_generalization_20260820
INDEX=$PROJECT/indexes/bge_m3_table_v2_complete
PY=$PROJECT/.venv/bin/python
BLIND=$PROJECT/blind/v30_identifiable_unused_coordinate30_20260820
INPUT=$BLIND/blind_input30.csv
GOLD=$BLIND/blind_coordinate_gold30_locked.csv
OUT=$PROJECT/runs/v31b_explicit_table_scope_opened30_dev_20260821
DSN=${KOSIS_POSTGRES_DSN:-postgresql:///kosis_project}

test -f "$INPUT"
test -f "$GOLD"
test ! -e "$OUT"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'
cd "$CODE"

"$PY" -m pytest -q tests
"$PY" -u prepare_kosis_mapping_input.py \
  --input "$INPUT" --output "$OUT/prepared_ready.csv" \
  --rejected-output "$OUT/prepared_rejected.csv" \
  --enrich-output "$OUT/prepared_enrich.csv" \
  --all-output "$OUT/prepared_all.csv"

stage_a() {
  local policy=$1
  local output=$2
  "$PY" -u run_kosis_coordinate_stage_a.py \
    --claims "$OUT/prepared_all.csv" --semantic-index "$INDEX" \
    --postgres-dsn "$DSN" --output "$output" \
    --device cuda --lexical-top-k 300 --dense-top-k 300 \
    --table-rerank-top-k 200 --table-pool-top-k 10 \
    --rerank-family-slots 20 --rerank-survey-groups 20 \
    --item-recall-top-k 300 --item-rerank-slots 100 \
    --item-recall-policy "$policy" --reranker-batch-size 32
}

stage_a legacy "$OUT/stage_a_legacy.jsonl"
stage_a balanced "$OUT/stage_a_balanced.jsonl"
"$PY" -u merge_stage_a_rankings.py \
  --legacy "$OUT/stage_a_legacy.jsonl" --balanced "$OUT/stage_a_balanced.jsonl" \
  --output "$OUT/stage_a_table_pool.jsonl" --legacy-slots 7 --top-k 10
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

set -a
source "$PROJECT/.env"
set +a
"$PY" -u run_kosis_top5_verification.py \
  --claims "$OUT/prepared_all.csv" \
  --candidates "$OUT/local_api_candidates_top5.jsonl" \
  --output "$OUT/verified_candidates.jsonl" \
  --claim-output "$OUT/claim_decisions.jsonl" \
  --postgres-dsn "$DSN" \
  --sqlite-cache "$OUT/kosis_api_cache.sqlite3" --delay 0.4

"$PY" "$PROJECT/blind/summarize_v30_blind.py" \
  --run-dir "$OUT" --freeze-manifest "$PROJECT/freezes/v28g_20260820_r1/freeze_manifest.json" \
  --output "$OUT/dev_final_report.json"
echo V31_OPENED30_DEV_COMPLETE
