#!/usr/bin/env bash
set -euo pipefail

PROJECT=${PROJECT:-/home/ubuntu/kosis-project}
CODE=${CODE:-$PROJECT/app_v26_20260820}
INDEX=${INDEX:-$PROJECT/indexes/bge_m3_table_v2_complete}
PY=${PY:-$PROJECT/.venv/bin/python}
INPUT=${INPUT:-$PROJECT/blind/v25/locked300_v14_mcp_blind30_candidates.csv}
GOLD=${GOLD:-$PROJECT/blind/v25/v25_blind_coordinate_gold10_locked.csv}
OUT=${OUT:-$PROJECT/runs/v26e_target_contract_dev_20260820}
DSN=${KOSIS_POSTGRES_DSN:-postgresql:///kosis_project}

mkdir -p "$OUT"
cd "$CODE"

echo '[0/7] regression tests'
"$PY" -m pytest -q tests

echo '[1/7] rebuild prepared claims with evidence-grounded OBJ targets'
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

echo '[2/7] dual-channel Stage A'
stage_a legacy "$OUT/stage_a_legacy.jsonl"
stage_a balanced "$OUT/stage_a_balanced.jsonl"
"$PY" -u merge_stage_a_rankings.py \
  --legacy "$OUT/stage_a_legacy.jsonl" \
  --balanced "$OUT/stage_a_balanced.jsonl" \
  --output "$OUT/stage_a_table_pool.jsonl" \
  --legacy-slots 7 --top-k 10

echo '[3/7] Stage B exact coordinate assembly'
"$PY" -u run_kosis_coordinate_stage_b.py \
  --table-pool "$OUT/stage_a_table_pool.jsonl" --postgres-dsn "$DSN" \
  --output "$OUT/stage_b_coordinate_beam.jsonl" --device cuda \
  --embedding-batch-size 128 --item-top-k 10 --axis-top-k 20 \
  --beam-width 250 --coordinate-pool-top-k 250 --preserve-table-fallback

echo '[4/7] Stage C OBJ contract and Top-5'
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

echo '[5/7] opened-development retrieval evaluation'
"$PY" -u evaluate_stage_a_table_recall.py \
  --predictions "$OUT/stage_a_table_pool.jsonl" --gold "$GOLD" \
  --summary "$OUT/stage_a_table_recall_summary.json" \
  --details "$OUT/stage_a_table_recall_details.csv" --ks 1,3,5,10
"$PY" -u evaluate_coordinate_topk.py \
  --predictions "$OUT/local_api_candidates_top5.jsonl" --gold "$GOLD" \
  --summary "$OUT/coordinate_topk_summary.json" \
  --details "$OUT/coordinate_topk_details.csv" --ks 1,3,5,10

echo '[6/7] immutable evidence'
sha256sum "$INPUT" "$GOLD" "$INDEX/tables.csv" \
  "$INDEX/embeddings.npy" "$INDEX/manifest.json" > "$OUT/inputs_sha256.txt"
find . -type f -not -path './.pytest_cache/*' -not -path './.test-tmp-*/*' \
  -not -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha256sum \
  > "$OUT/code_files_sha256.txt"
sha256sum "$OUT/code_files_sha256.txt" > "$OUT/code_tree_sha256.txt"

echo '[7/7] complete'
cat "$OUT/stage_a_table_recall_summary.json"
cat "$OUT/coordinate_topk_summary.json"
echo V26E_TARGET_CONTRACT_DEV_COMPLETE
