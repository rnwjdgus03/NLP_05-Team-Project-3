#!/usr/bin/env bash
set -euo pipefail

CODE=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_ROOT=${PROJECT_ROOT:-/home/ubuntu/kosis-project}
PY=${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}
INPUT=${INPUT:?Set INPUT to a source CSV}
OUT=${OUT:?Set OUT to a new output directory}
MEMORY=${KOSIS_MAPPING_MEMORY:-$CODE/mapping_memory_dev600.json}

# Preserve the complete frozen retrieval/verification cascade, then prepend a
# reusable coordinate only when survey, indicator, official unit and period
# frequency exactly match a collision-free verified mapping.
bash "$CODE/cloud_setup/run_v58_dev300_pipeline_base.sh"

test -s "$MEMORY"
test -s "$OUT/final_candidates_top5.jsonl"
"$PY" -u "$CODE/apply_kosis_mapping_memory.py" \
  --claims "$INPUT" \
  --predictions "$OUT/final_candidates_top5.jsonl" \
  --memory "$MEMORY" \
  --output "$OUT/final_candidates_top5_memory.jsonl" \
  --summary "$OUT/mapping_memory_application_summary.json" \
  --top-k 5
mv "$OUT/final_candidates_top5.jsonl" "$OUT/final_candidates_top5_before_memory.jsonl"
mv "$OUT/final_candidates_top5_memory.jsonl" "$OUT/final_candidates_top5.jsonl"
sha256sum "$MEMORY" "$OUT/final_candidates_top5.jsonl" \
  > "$OUT/mapping_memory_artifact_sha256.txt"
echo V64_MAPPING_MEMORY_APPLIED
