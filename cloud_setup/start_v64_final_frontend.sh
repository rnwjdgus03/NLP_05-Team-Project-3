#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ubuntu/kosis-project
FRONTEND=$ROOT/freezes/v60_service_candidate_20260824_r1/frontend
BLIND_GATE=$ROOT/blind_runs/v65_frozen_v64_blind100_20260824_r1/blind100_gate.json
RUN_ROOT=$ROOT/runs/service_v64_final_url50_20260824_r1
PY=$ROOT/.venv/bin/python
LOG=$RUN_ROOT/frontend.log

test -s "$BLIND_GATE"
"$PY" -c 'import json,pathlib,sys; x=json.loads(pathlib.Path(sys.argv[1]).read_text()); assert x["promotion_gate"] in {"PASS","FAIL"} and x["eligible_overlap"]==100 and x["missing_prediction_packets"]==0 and x["candidate_freeze_id"]=="v64_candidate_20260824_r1"' "$BLIND_GATE"
mkdir -p "$RUN_ROOT"
set -a
source "$ROOT/.env"
set +a
export KOSIS_FRONTEND_HOST=127.0.0.1
export KOSIS_FRONTEND_PORT=3102
export KOSIS_API_BASE_URL=http://127.0.0.1:8002
export KOSIS_MAX_ARTICLE_CLAIMS=4

cd "$FRONTEND"
exec >>"$LOG" 2>&1
echo "[$(date -Is)] starting v64 final BFF on 127.0.0.1:3102"
exec "$ROOT/tools/node-v22.23.2-linux-x64/bin/node" server.mjs
