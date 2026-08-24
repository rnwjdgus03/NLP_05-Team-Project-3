#!/usr/bin/env bash
set -euo pipefail

PROJECT=/home/ubuntu/kosis-project
FREEZE=$PROJECT/freezes/v64_candidate_20260824_r1
BLIND=$PROJECT/blind/v65_post_v64_table_disjoint_blind100_20260824_r1
INPUT=$BLIND/blind_input100.csv
GOLD=$BLIND/blind_coordinate_gold100_locked.csv
BLIND_MANIFEST=$BLIND/blind_manifest.json
OUT=$PROJECT/blind_runs/v65_frozen_v64_blind100_20260824_r1
PY=$PROJECT/.venv/bin/python

test -f "$FREEZE/freeze_manifest.json"
test ! -w "$FREEZE"
test ! -e "$OUT"

set -a
source "$PROJECT/.env"
set +a

# Gold is generated and locked only after the candidate freeze exists.  The
# candidate pipeline receives INPUT only; GOLD is first passed to code after
# final_candidates_top5.jsonl has been produced.
if test ! -e "$BLIND"; then
  "$PY" "$PROJECT/blind/build_v65_blind100.py"
fi
test -r "$INPUT"
test -r "$GOLD"
test -r "$BLIND_MANIFEST"
test ! -w "$GOLD"

mkdir -p "$OUT"
exec > >(tee -a "$OUT/blind_once.log") 2>&1

"$PY" -c 'import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); m=json.loads(p.read_text()); f=pathlib.Path(sys.argv[2]); z=json.loads(f.read_text()); assert m["blind"] and m["evaluation_only"] and m["no_tuning_after_unblind"]; assert m["candidate_freeze_id"] == z["freeze_id"]; assert m["candidate_code_tree_sha256"] == z["components"]["engine"]["tree_sha256"]; print("BLIND_PREREGISTRATION=PASS")' \
  "$BLIND_MANIFEST" "$FREEZE/freeze_manifest.json"

sha256sum \
  "$FREEZE/freeze_manifest.json" \
  "$PROJECT/blind/build_v65_blind100.py" \
  "$PROJECT/blind/run_v65_blind100_once.sh" \
  > "$OUT/pre_run_code_sha256.txt"
chmod 444 "$OUT/pre_run_code_sha256.txt"

"$PY" -c 'import json,pathlib,sys,datetime; p=pathlib.Path(sys.argv[1]); p.write_text(json.dumps({"schema_version":"kosis-v65-blind100-one-shot-claim-v1","claimed_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"candidate_freeze_id":"v64_candidate_20260824_r1","blind_manifest_sha256":__import__("hashlib").sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest(),"status":"CLAIMED_BEFORE_PREDICTION"},indent=2)+"\n")' \
  "$OUT/one_shot_claim.json" "$BLIND_MANIFEST"
chmod 444 "$OUT/one_shot_claim.json"

INPUT="$INPUT" OUT="$OUT/pipeline" \
  PROJECT_ROOT="$PROJECT" PYTHON_BIN="$PY" \
  KOSIS_SEMANTIC_INDEX="$PROJECT/indexes/bge_m3_table_v2_complete" \
  KOSIS_POSTGRES_DSN="postgresql:///kosis_project" \
  "$FREEZE/engine/cloud_setup/run_v58_dev300_pipeline.sh"

grep -q 'V58_DEV300_PIPELINE_COMPLETE' "$OUT/pipeline/pipeline.log"
test -s "$OUT/pipeline/final_candidates_top5.jsonl"

"$PY" "$FREEZE/engine/evaluate_coordinate_topk_multigold.py" \
  --predictions "$OUT/pipeline/final_candidates_top5.jsonl" \
  --gold "$GOLD" \
  --summary "$OUT/coordinate_topk_multigold_summary.json" \
  --details "$OUT/coordinate_topk_multigold_details.csv" \
  --ks 1,3,5

set +e
"$PY" "$FREEZE/engine/evaluate_v61_blind100_gate.py" \
  --summary "$OUT/coordinate_topk_multigold_summary.json" \
  --blind-manifest "$BLIND_MANIFEST" \
  --freeze-manifest "$FREEZE/freeze_manifest.json" \
  --output "$OUT/blind100_gate.json"
gate_status=$?
set -e

sha256sum \
  "$OUT/one_shot_claim.json" \
  "$OUT/pre_run_code_sha256.txt" \
  "$OUT/pipeline/final_candidates_top5.jsonl" \
  "$OUT/coordinate_topk_multigold_summary.json" \
  "$OUT/coordinate_topk_multigold_details.csv" \
  "$OUT/blind100_gate.json" \
  > "$OUT/blind_artifact_sha256.txt"

chmod 444 \
  "$OUT/coordinate_topk_multigold_summary.json" \
  "$OUT/coordinate_topk_multigold_details.csv" \
  "$OUT/blind100_gate.json" \
  "$OUT/blind_artifact_sha256.txt"

echo "V65_BLIND100_GATE_EXIT=$gate_status"
exit "$gate_status"
