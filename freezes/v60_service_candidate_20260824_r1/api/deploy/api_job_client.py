from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


def request_json(url: str, api_key: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    api_key = os.getenv("KOSIS_SERVICE_API_KEY")
    if not api_key:
        raise SystemExit("KOSIS_SERVICE_API_KEY is required")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    accepted = request_json(f"{args.base_url}/v1/verifications", api_key, payload)
    job_id = accepted["job_id"]
    print(f"submitted job_id={job_id}", flush=True)
    deadline = time.monotonic() + args.timeout
    previous = None
    while time.monotonic() < deadline:
        state = request_json(f"{args.base_url}/v1/verifications/{job_id}", api_key)
        marker = (state["status"], state["progress_step"])
        if marker != previous:
            print(f"status={marker[0]} step={marker[1]}", flush=True)
            previous = marker
        if state["status"] == "SUCCEEDED":
            result = request_json(f"{args.base_url}/v1/verifications/{job_id}/result", api_key)
            output = args.payload.with_name(f"{args.payload.stem}_{job_id}_result.json")
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True), flush=True)
            for claim in result["claims"]:
                selected = claim.get("selected_evidence") or {}
                table = selected.get("table") or {}
                print(
                    f"{claim['claim_measurement_id']} verdict={claim['verdict']} "
                    f"status={claim['decision_status']} table={table.get('tbl_id', '-')}",
                    flush=True,
                )
            print(f"result={output}", flush=True)
            return
        if state["status"] == "FAILED":
            raise SystemExit(f"job failed: {state.get('error')}")
        time.sleep(5)
    raise SystemExit("API job timed out")


if __name__ == "__main__":
    main()
