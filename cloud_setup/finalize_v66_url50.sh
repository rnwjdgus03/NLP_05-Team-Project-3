#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ubuntu/kosis-project
FREEZE=$ROOT/freezes/v64_candidate_20260824_r1
FRONTEND=$ROOT/freezes/v60_service_candidate_20260824_r1/frontend
LOCK_DIR=$ROOT/e2e/v66_final_service_url50_20260824_r1
LOCK=$LOCK_DIR/locked_urls50.json
LOCK_MANIFEST=$LOCK_DIR/lock_manifest.json
E2E=$LOCK_DIR/run
RUNS=$ROOT/runs/service_v64_final_url50_20260824_r1/jobs
PY=$ROOT/.venv/bin/python

test -s "$E2E/qa_state.json"
test -s "$E2E/qa_summary.json"
"$PY" "$ROOT/cloud_setup/verify_frozen_url_run_identity.py" \
  --lock "$LOCK" --lock-manifest "$LOCK_MANIFEST" \
  --engine-manifest "$FREEZE/engine/freeze_manifest.json" \
  --state "$E2E/qa_state.json" --summary "$E2E/qa_summary.json" \
  --output "$E2E/identity_audit.json"
"$PY" "$FRONTEND/audit_real_url_e2e_results.py" \
  --state "$E2E/qa_state.json" --runs-dir "$RUNS" \
  --output "$E2E/funnel_audit.json" --details "$E2E/funnel_details.csv"
set +e
"$PY" "$FRONTEND/assess_real_url_service_readiness.py" \
  --summary "$E2E/qa_summary.json" --audit "$E2E/funnel_audit.json" \
  --details "$E2E/funnel_details.csv" \
  --output "$E2E/service_readiness.json"
readiness_rc=$?
set -e
sha256sum "$LOCK" "$LOCK_MANIFEST" "$FREEZE/freeze_manifest.json" \
  "$E2E/qa_state.json" "$E2E/qa_summary.json" \
  "$E2E/identity_audit.json" "$E2E/funnel_audit.json" \
  "$E2E/funnel_details.csv" "$E2E/service_readiness.json" \
  > "$E2E/evidence_sha256.txt"
cat "$E2E/identity_audit.json"
cat "$E2E/service_readiness.json"
exit "$readiness_rc"
