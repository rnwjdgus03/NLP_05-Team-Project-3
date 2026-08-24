#!/usr/bin/env bash
set -euo pipefail
CODE=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_ROOT=${PROJECT_ROOT:-/home/ubuntu/kosis-project}
PY=${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}
INDEX=${KOSIS_SEMANTIC_INDEX:-$PROJECT_ROOT/indexes/bge_m3_table_v2_complete}
DSN=${KOSIS_POSTGRES_DSN:-postgresql:///kosis_project}
INPUT=${INPUT:?Set INPUT to a prepared source CSV}
OUT=${OUT:?Set OUT to a new output directory}
test -f "$INPUT"
test ! -e "$OUT"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'
cd "$CODE"
"$PY" -m pytest -q tests
"$PY" -u prepare_kosis_mapping_input.py --input "$INPUT" \
  --output "$OUT/prepared_ready.csv" --rejected-output "$OUT/prepared_rejected.csv" \
  --enrich-output "$OUT/prepared_enrich.csv" --all-output "$OUT/prepared_all.csv"
stage_a() {
  "$PY" -u run_kosis_coordinate_stage_a.py \
    --claims "$OUT/prepared_all.csv" --semantic-index "$INDEX" --postgres-dsn "$DSN" \
    --output "$2" --device cuda --lexical-top-k 300 --dense-top-k 300 \
    --table-rerank-top-k 200 --table-pool-top-k 10 --rerank-family-slots 20 \
    --rerank-survey-groups 20 --item-recall-top-k 300 --item-rerank-slots 100 \
    --item-recall-policy "$1" --reranker-batch-size 32
}
stage_a legacy "$OUT/stage_a_legacy.jsonl"
stage_a balanced "$OUT/stage_a_balanced.jsonl"
"$PY" -u merge_stage_a_raw_scored.py \
  --legacy "$OUT/stage_a_legacy.jsonl" --balanced "$OUT/stage_a_balanced.jsonl" \
  --legacy-raw "$OUT/stage_a_legacy.retrieval.jsonl" --balanced-raw "$OUT/stage_a_balanced.retrieval.jsonl" \
  --legacy-scored "$OUT/stage_a_legacy.jsonl" --balanced-scored "$OUT/stage_a_balanced.jsonl" \
  --output "$OUT/stage_a_table_pool.jsonl" --legacy-slots 7 --raw-slots 5 --top-k 12
"$PY" -u run_kosis_coordinate_stage_b.py --table-pool "$OUT/stage_a_table_pool.jsonl" \
  --postgres-dsn "$DSN" --output "$OUT/stage_b_coordinate_beam.jsonl" --device cuda \
  --embedding-batch-size 128 --item-top-k 10 --axis-top-k 20 --beam-width 300 \
  --coordinate-pool-top-k 300 --preserve-table-fallback
"$PY" -u run_kosis_coordinate_stage_c.py --beam-pool "$OUT/stage_b_coordinate_beam.jsonl" \
  --output "$OUT/local_coordinate_top3.jsonl" --fallback-output "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --state-output "$OUT/stage_c_state.jsonl" --device cuda --reranker-batch-size 32 \
  --obj-scope-bonus 0.10 --item-exact-bonus 0.25 --item-exact-slots 2
"$PY" -u merge_local_stage_c_candidates.py --primary "$OUT/local_coordinate_top3.jsonl" \
  --fallback "$OUT/local_coordinate_rank4_5_fallback.jsonl" --output "$OUT/local_api_candidates_top5.jsonl"
echo V34_CANDIDATE_RETRIEVAL_COMPLETE
