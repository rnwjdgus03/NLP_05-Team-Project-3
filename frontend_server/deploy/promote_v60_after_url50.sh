#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ubuntu/kosis-project
E2E="$ROOT/e2e/v60_chosun_locked_url50_20260824_r1"
CANDIDATE="$ROOT/candidates/v60_final_ui_ea15704/frontend_server"
NODE="$ROOT/tools/node-v22.23.2-linux-x64/bin/node"
PY="$ROOT/.venv/bin/python"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$ROOT/backups/frontend_server_before_v60_$STAMP"
STAGE="$ROOT/.frontend_server_v60_$STAMP"

for path in \
  "$E2E/identity_audit.json" \
  "$E2E/service_readiness.json" \
  "$E2E/evidence_sha256.txt" \
  "$CANDIDATE/server.mjs" \
  "$CANDIDATE/public/index.html" \
  "$CANDIDATE/deploy/kosis-v60-api.service" \
  "$CANDIDATE/deploy/kosis-frontend.service"; do
  [[ -s "$path" ]] || { echo "required artifact missing: $path" >&2; exit 2; }
done

"$PY" - "$E2E/identity_audit.json" "$E2E/service_readiness.json" <<'PY'
import json, sys
for value in sys.argv[1:]:
    payload = json.load(open(value, encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise SystemExit(f"promotion blocked: {value} status={payload.get('status')}")
print("promotion_gates=PASS")
PY

cd "$CANDIDATE"
"$NODE" --check server.mjs
"$NODE" --check public/static/app.js
"$NODE" test_article_extractor.mjs
"$NODE" test_frontend_v60_adapter.mjs
"$PY" test_frontend_url_only.py

mkdir -p "$ROOT/backups" \
  "$ROOT/runs/service_v60_production/jobs" \
  "$ROOT/runs/service_v60_production/state"
cp -a "$CANDIDATE" "$STAGE"

sudo systemctl stop kosis-frontend.service 2>/dev/null || true
tmux kill-session -t v60-bff-eval 2>/dev/null || true
tmux kill-session -t v60-api-eval 2>/dev/null || true

if [[ -d "$ROOT/frontend_server" ]]; then
  mv "$ROOT/frontend_server" "$BACKUP"
fi
mv "$STAGE" "$ROOT/frontend_server"

sudo install -m 0644 "$ROOT/frontend_server/deploy/kosis-v60-api.service" /etc/systemd/system/kosis-v60-api.service
sudo install -m 0644 "$ROOT/frontend_server/deploy/kosis-frontend.service" /etc/systemd/system/kosis-frontend.service
sudo systemctl daemon-reload
sudo systemctl enable --now kosis-v60-api.service

for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8001/readyz > /tmp/kosis-v60-ready.json; then break; fi
  sleep 2
done
"$PY" - /tmp/kosis-v60-ready.json <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "ready", payload
assert payload.get("engine_freeze_id") == "v60_service_candidate_20260824_r1", payload
print("v60_api_ready=PASS")
PY

sudo systemctl enable --now kosis-frontend.service
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3100/healthz > /tmp/kosis-v60-frontend-ready.json; then break; fi
  sleep 1
done
"$PY" - /tmp/kosis-v60-frontend-ready.json <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "ready" and payload.get("api_connected") is True, payload
print("v60_frontend_ready=PASS")
PY

{
  echo "promoted_at=$STAMP"
  echo "source_commit=ea15704"
  sha256sum \
    "$ROOT/frontend_server/server.mjs" \
    "$ROOT/frontend_server/public/index.html" \
    "$ROOT/frontend_server/public/static/app.js" \
    "$ROOT/frontend_server/public/static/styles.css" \
    "$E2E/service_readiness.json" \
    "$E2E/identity_audit.json"
} > "$ROOT/runs/service_v60_production/promotion_manifest.txt"

cat /tmp/kosis-v60-ready.json
cat /tmp/kosis-v60-frontend-ready.json
cat "$ROOT/runs/service_v60_production/promotion_manifest.txt"
echo "V60_SERVICE_PROMOTION_COMPLETE"
