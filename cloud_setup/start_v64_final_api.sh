#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ubuntu/kosis-project
FREEZE=$ROOT/freezes/v64_candidate_20260824_r1
ENGINE=$FREEZE/engine
API=$ROOT/freezes/v60_service_candidate_20260824_r1/api
BLIND_GATE=$ROOT/blind_runs/v65_frozen_v64_blind100_20260824_r1/blind100_gate.json
RUN_ROOT=$ROOT/runs/service_v64_final_url50_20260824_r1
PY=$ROOT/.venv/bin/python
LOG=$RUN_ROOT/api.log

test -s "$ENGINE/freeze_manifest.json"
test -s "$BLIND_GATE"
test ! -w "$ENGINE"
TREE_SHA=$("$PY" -c 'import json,pathlib,sys; f=json.loads(pathlib.Path(sys.argv[1]).read_text()); b=json.loads(pathlib.Path(sys.argv[2]).read_text()); assert f["freeze_id"]=="v64_candidate_20260824_r1"; assert b["promotion_gate"] in {"PASS","FAIL"}; assert b["eligible_overlap"]==100; assert b["missing_prediction_packets"]==0; assert b["candidate_freeze_id"]==f["freeze_id"]; assert b["candidate_engine_tree_sha256"]==f["code_tree_sha256"]; print(f["code_tree_sha256"])' "$ENGINE/freeze_manifest.json" "$BLIND_GATE")

mkdir -p "$RUN_ROOT/state"
set -a
source "$ROOT/.env"
set +a
export KOSIS_PROJECT_ROOT="$ROOT"
export KOSIS_EXPECTED_FREEZE_ID=v64_candidate_20260824_r1
export KOSIS_EXPECTED_CODE_SHA256="$TREE_SHA"
export KOSIS_ENGINE_DIR="$ENGINE"
export KOSIS_INDEX_DIR="$ROOT/indexes/bge_m3_table_v2_complete"
export KOSIS_PYTHON="$PY"
export KOSIS_SERVICE_ROOT="$RUN_ROOT"
export KOSIS_SERVICE_RUNS_DIR="$RUN_ROOT/jobs"
export KOSIS_SERVICE_STATE_DB="$RUN_ROOT/state/jobs.sqlite3"
export KOSIS_POSTGRES_DSN=postgresql:///kosis_project
export KOSIS_DEVICE=cuda
export KOSIS_REQUIRE_READONLY_ENGINE=true
export KOSIS_MAX_ROWS_PER_JOB=20
export KOSIS_CORS_ORIGINS=http://127.0.0.1:3102

cd "$API"
exec >>"$LOG" 2>&1
echo "[$(date -Is)] starting v64 final API on 127.0.0.1:8002"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1
