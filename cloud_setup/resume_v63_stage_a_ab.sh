#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ubuntu/kosis-project
PY="$ROOT/.venv/bin/python"
CODE="$ROOT/development/v63_survey_exact_recall_20260824/candidate/engine"
INPUT="$ROOT/runs/v62_frozen_v60_dev600_baseline_20260824_r1/prepared_all.csv"
GOLD="$ROOT/development/v62_generalization_dev600_20260824_r1/dev_coordinate_gold600.csv"
INDEX="$ROOT/indexes/bge_m3_table_v2_complete"
OUT="$ROOT/runs/v63_survey_exact_stage_a_ab_20260824_r1"
DSN=${KOSIS_POSTGRES_DSN:-postgresql:///kosis_project}

test -f "$INPUT"
test -f "$GOLD"
test -d "$OUT"
test -s "$OUT/stage_a_legacy.retrieval.jsonl"
test ! -e "$OUT/stage_a_summary.json"

exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONPATH="$CODE"
export PYTHONDONTWRITEBYTECODE=1
cd "$CODE"
"$PY" -m pytest -q tests

stage_a() {
  local item_policy=$1
  local output=$2
  "$PY" -u run_kosis_coordinate_stage_a.py \
    --claims "$INPUT" --semantic-index "$INDEX" --postgres-dsn "$DSN" \
    --output "$output" --device cuda --lexical-top-k 300 --dense-top-k 300 \
    --table-rerank-top-k 200 --table-pool-top-k 10 \
    --rerank-family-slots 20 --rerank-survey-groups 20 \
    --item-recall-top-k 300 --item-rerank-slots 100 \
    --item-recall-policy "$item_policy" --reranker-batch-size 32 \
    --metadata-recall-top-k 300 --metadata-rerank-slots 100 \
    --metadata-recall-policy survey_exact
}

stage_a legacy "$OUT/stage_a_legacy.jsonl"
stage_a balanced "$OUT/stage_a_balanced.jsonl"

"$PY" -u merge_stage_a_raw_scored.py \
  --legacy "$OUT/stage_a_legacy.jsonl" \
  --balanced "$OUT/stage_a_balanced.jsonl" \
  --legacy-raw "$OUT/stage_a_legacy.retrieval.jsonl" \
  --balanced-raw "$OUT/stage_a_balanced.retrieval.jsonl" \
  --legacy-scored "$OUT/stage_a_legacy.jsonl" \
  --balanced-scored "$OUT/stage_a_balanced.jsonl" \
  --output "$OUT/stage_a_pool_top50.jsonl" \
  --legacy-slots 15 --raw-slots 35 --top-k 50

"$PY" -u apply_stage_a_fixed_blend.py \
  --input "$OUT/stage_a_pool_top50.jsonl" \
  --output "$OUT/stage_a_table_pool.jsonl" --top-k 30

"$PY" -u evaluate_stage_a_table_recall.py \
  --predictions "$OUT/stage_a_table_pool.jsonl" --gold "$GOLD" \
  --summary "$OUT/stage_a_summary.json" \
  --details "$OUT/stage_a_details.csv" --ks 1,3,5,10,20,30

"$PY" -u "$ROOT/development/audit_v62_stage_a_generalization.py" \
  --gold "$GOLD" --run-dir "$OUT" \
  --summary "$OUT/stage_a_generalization_audit.json" \
  --details "$OUT/stage_a_generalization_audit.csv"

sha256sum \
  "$CODE/run_kosis_coordinate_stage_a.py" \
  "$ROOT/development/v62_generalization_dev600_20260824_r1/dev_manifest.json" \
  "$OUT/stage_a_table_pool.jsonl" "$OUT/stage_a_summary.json" \
  > "$OUT/artifact_sha256.txt"

echo V63_SURVEY_EXACT_STAGE_A_AB_COMPLETE
