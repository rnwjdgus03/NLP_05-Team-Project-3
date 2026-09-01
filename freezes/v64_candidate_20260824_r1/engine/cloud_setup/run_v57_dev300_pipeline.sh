#!/usr/bin/env bash
set -euo pipefail

CODE=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_ROOT=${PROJECT_ROOT:-/home/ubuntu/kosis-project}
PY=${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}
INDEX=${KOSIS_SEMANTIC_INDEX:-$PROJECT_ROOT/indexes/bge_m3_table_v2_complete}
DSN=${KOSIS_POSTGRES_DSN:-postgresql:///kosis_project}
INPUT=${INPUT:?Set INPUT to a source CSV}
OUT=${OUT:?Set OUT to a new output directory}
test -f "$INPUT"
test ! -e "$OUT"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pipeline.log") 2>&1
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS='-p no:cacheprovider'
export PYTHONPATH="$CODE"
set -a
source "$PROJECT_ROOT/.env"
set +a
cd "$CODE"

"$PY" -m pytest -q tests
"$PY" -u prepare_kosis_mapping_input.py --input "$INPUT" \
  --output "$OUT/prepared_ready.csv" --rejected-output "$OUT/prepared_rejected.csv" \
  --enrich-output "$OUT/prepared_enrich.csv" --all-output "$OUT/prepared_all.csv"

stage_a() {
  local policy=$1
  local output=$2
  local claims=$3
  shift 3
  "$PY" -u run_kosis_coordinate_stage_a.py \
    --claims "$claims" --semantic-index "$INDEX" --postgres-dsn "$DSN" \
    --output "$output" --device cuda --lexical-top-k 300 --dense-top-k 300 \
    --table-rerank-top-k 200 --table-pool-top-k 10 --rerank-family-slots 20 \
    --rerank-survey-groups 20 --item-recall-top-k 300 --item-rerank-slots 100 \
    --item-recall-policy "$policy" --reranker-batch-size 32 \
    --metadata-recall-top-k 300 --metadata-rerank-slots 100 "$@"
}

# Primary retrieval remains the frozen v39 two-channel blend.
stage_a legacy "$OUT/stage_a_legacy.jsonl" "$OUT/prepared_all.csv"
stage_a balanced "$OUT/stage_a_balanced.jsonl" "$OUT/prepared_all.csv"
"$PY" -u merge_stage_a_raw_scored.py \
  --legacy "$OUT/stage_a_legacy.jsonl" --balanced "$OUT/stage_a_balanced.jsonl" \
  --legacy-raw "$OUT/stage_a_legacy.retrieval.jsonl" \
  --balanced-raw "$OUT/stage_a_balanced.retrieval.jsonl" \
  --legacy-scored "$OUT/stage_a_legacy.jsonl" --balanced-scored "$OUT/stage_a_balanced.jsonl" \
  --output "$OUT/stage_a_pool_top50.jsonl" --legacy-slots 15 --raw-slots 35 --top-k 50
"$PY" -u apply_stage_a_fixed_blend.py --input "$OUT/stage_a_pool_top50.jsonl" \
  --output "$OUT/stage_a_table_pool.jsonl" --top-k 30
"$PY" -u run_kosis_coordinate_stage_b.py --table-pool "$OUT/stage_a_table_pool.jsonl" \
  --postgres-dsn "$DSN" --output "$OUT/stage_b_coordinate_beam.jsonl" --device cuda \
  --embedding-batch-size 128 --item-top-k 10 --axis-top-k 20 --beam-width 400 \
  --coordinate-pool-top-k 400 --preserve-table-fallback
"$PY" -u run_kosis_coordinate_stage_c.py --beam-pool "$OUT/stage_b_coordinate_beam.jsonl" \
  --output "$OUT/local_coordinate_top3.jsonl" \
  --fallback-output "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --state-output "$OUT/stage_c_state.jsonl" --ranked-pool-output "$OUT/stage_c_ranked_pool.jsonl" \
  --device cuda --reranker-batch-size 32 --obj-scope-bonus 0.10 \
  --item-exact-bonus 0.25 --item-exact-slots 2 \
  --stage-a-table-slots 1 --item-component-slots 1
"$PY" -u merge_local_stage_c_candidates.py \
  --primary "$OUT/local_coordinate_top3.jsonl" \
  --fallback "$OUT/local_coordinate_rank4_5_fallback.jsonl" \
  --output "$OUT/primary_top5.jsonl"
"$PY" -u run_kosis_top5_verification.py --claims "$INPUT" \
  --candidates "$OUT/primary_top5.jsonl" \
  --output "$OUT/primary_verified.jsonl" --claim-output "$OUT/primary_decisions.jsonl" \
  --postgres-dsn "$DSN" --sqlite-cache "$OUT/api_cache.sqlite3" --delay 0.0

# Bounded rank 6-10 fallback, only for primary API-unresolved claims.
"$PY" -u build_rank_tail_fallback.py --ranked-pool "$OUT/stage_c_ranked_pool.jsonl" \
  --primary-decisions "$OUT/primary_decisions.jsonl" --claims "$INPUT" \
  --output-primary "$OUT/tail_rank6_8.jsonl" --output-fallback "$OUT/tail_rank9_10.jsonl" \
  --output-claims "$OUT/tail_unresolved_claims.csv" --start-rank 6 --end-rank 10 \
  --item-exact-slots 2 --stage-a-table-slots 1 --item-component-slots 1
"$PY" -u merge_local_stage_c_candidates.py --primary "$OUT/tail_rank6_8.jsonl" \
  --fallback "$OUT/tail_rank9_10.jsonl" --output "$OUT/tail_rank6_10.jsonl"
"$PY" -u run_kosis_top5_verification.py --claims "$OUT/tail_unresolved_claims.csv" \
  --candidates "$OUT/tail_rank6_10.jsonl" --output "$OUT/tail_verified.jsonl" \
  --claim-output "$OUT/tail_decisions.jsonl" --postgres-dsn "$DSN" \
  --sqlite-cache "$OUT/api_cache.sqlite3" --delay 0.0

# Metadata recall is the last fallback and is never an automatic READY signal.
"$PY" -u filter_claims_by_branch_decisions.py --claims "$OUT/prepared_all.csv" \
  --decisions "$OUT/primary_decisions.jsonl" --decisions "$OUT/tail_decisions.jsonl" \
  --output "$OUT/metadata_unresolved_prepared.csv"
stage_a balanced "$OUT/stage_a_balanced_metadata.jsonl" \
  "$OUT/metadata_unresolved_prepared.csv" \
  --metadata-recall-top-k 300 --metadata-rerank-slots 100
"$PY" -u filter_jsonl_by_claims.py --claims "$OUT/metadata_unresolved_prepared.csv" \
  --input "$OUT/stage_a_legacy.jsonl" --output "$OUT/metadata_legacy.jsonl"
"$PY" -u filter_jsonl_by_claims.py --claims "$OUT/metadata_unresolved_prepared.csv" \
  --input "$OUT/stage_a_legacy.retrieval.jsonl" \
  --output "$OUT/metadata_legacy.retrieval.jsonl"
"$PY" -u merge_stage_a_raw_scored.py \
  --legacy "$OUT/metadata_legacy.jsonl" --balanced "$OUT/stage_a_balanced_metadata.jsonl" \
  --legacy-raw "$OUT/metadata_legacy.retrieval.jsonl" \
  --balanced-raw "$OUT/stage_a_balanced_metadata.retrieval.jsonl" \
  --legacy-scored "$OUT/metadata_legacy.jsonl" \
  --balanced-scored "$OUT/stage_a_balanced_metadata.jsonl" \
  --output "$OUT/metadata_stage_a_pool_top50.jsonl" --legacy-slots 15 --raw-slots 35 --top-k 50
"$PY" -u apply_stage_a_fixed_blend.py --input "$OUT/metadata_stage_a_pool_top50.jsonl" \
  --output "$OUT/metadata_stage_a_table_pool.jsonl" --top-k 30
"$PY" -u run_kosis_coordinate_stage_b.py --table-pool "$OUT/metadata_stage_a_table_pool.jsonl" \
  --postgres-dsn "$DSN" --output "$OUT/metadata_stage_b_beam.jsonl" --device cuda \
  --embedding-batch-size 128 --item-top-k 10 --axis-top-k 20 --beam-width 400 \
  --coordinate-pool-top-k 400 --preserve-table-fallback
"$PY" -u run_kosis_coordinate_stage_c.py --beam-pool "$OUT/metadata_stage_b_beam.jsonl" \
  --output "$OUT/metadata_top3.jsonl" --fallback-output "$OUT/metadata_rank4_5.jsonl" \
  --state-output "$OUT/metadata_stage_c_state.jsonl" --device cuda \
  --reranker-batch-size 32 --obj-scope-bonus 0.10 --item-exact-bonus 0.25 \
  --item-exact-slots 2 --stage-a-table-slots 1 --item-component-slots 1
"$PY" -u merge_local_stage_c_candidates.py --primary "$OUT/metadata_top3.jsonl" \
  --fallback "$OUT/metadata_rank4_5.jsonl" --output "$OUT/metadata_top5.jsonl"
"$PY" -u run_kosis_top5_verification.py --claims "$OUT/metadata_unresolved_prepared.csv" \
  --candidates "$OUT/metadata_top5.jsonl" --output "$OUT/metadata_verified.jsonl" \
  --claim-output "$OUT/metadata_decisions.jsonl" --postgres-dsn "$DSN" \
  --sqlite-cache "$OUT/api_cache.sqlite3" --delay 0.0

"$PY" -u build_api_verified_multibranch_cascade.py \
  --primary-candidates "$OUT/primary_top5.jsonl" --primary-decisions "$OUT/primary_decisions.jsonl" \
  --tail-candidates "$OUT/tail_rank6_10.jsonl" --tail-decisions "$OUT/tail_decisions.jsonl" \
  --metadata-candidates "$OUT/metadata_top5.jsonl" \
  --metadata-decisions "$OUT/metadata_decisions.jsonl" \
  --output "$OUT/final_candidates_top5.jsonl" --manifest "$OUT/fallback_manifest.json"

sha256sum "$INPUT" "$INDEX/tables.csv" "$INDEX/embeddings.npy" \
  "$OUT/final_candidates_top5.jsonl" > "$OUT/run_artifact_sha256.txt"
echo V57_DEV300_PIPELINE_COMPLETE
