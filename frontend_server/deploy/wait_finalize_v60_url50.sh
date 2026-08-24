#!/usr/bin/env bash
set -u

pid="${1:?usage: wait_finalize_v60_url50.sh PID}"
root=/home/ubuntu/kosis-project
out="$root/e2e/v60_chosun_locked_url50_20260824_r1"

while [[ -r "/proc/$pid/stat" ]]; do
  state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
  [[ "$state" == "Z" ]] && break
  sleep 30
done

if [[ -s "$out/service_readiness.json" && -s "$out/finalizer.log" ]]; then
  echo "finalizer artifacts already exist; no rerun"
  exit 0
fi

cd "$root" || exit 90
set +e
./cloud_setup/finalize_v60_url50.sh > "$out/finalizer.log" 2>&1
rc=$?
printf 'FINALIZER_RC=%s\n' "$rc" >> "$out/finalizer.log"
exit "$rc"
