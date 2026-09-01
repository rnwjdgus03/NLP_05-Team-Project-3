#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ubuntu/kosis-project
FRONTEND=$ROOT/freezes/v60_service_candidate_20260824_r1/frontend
INPUT=$ROOT/e2e/v66_final_service_url50_20260824_r1/locked_urls50.json
OUT=$ROOT/e2e/v66_final_service_url50_20260824_r1/run

test -s "$INPUT"
curl --fail --silent http://127.0.0.1:3102/healthz >/dev/null
exec "$ROOT/.venv/bin/python" "$FRONTEND/run_real_url_e2e_qa.py" \
  --input "$INPUT" --output-dir "$OUT" \
  --base-url http://127.0.0.1:3102 --poll-seconds 10
