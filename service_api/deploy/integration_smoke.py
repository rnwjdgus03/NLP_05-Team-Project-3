from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def request_json(url: str, *, api_key: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurement-csv", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    api_key = os.getenv("KOSIS_SERVICE_API_KEY")
    if not api_key:
        raise SystemExit("KOSIS_SERVICE_API_KEY is required")
    with args.measurement_csv.open(encoding="utf-8-sig", newline="") as handle:
        measurement = next(csv.DictReader(handle))
    accepted = request_json(
        f"{args.base_url}/v1/verifications",
        api_key=api_key,
        payload={"input_stage": "measurements", "measurements": [measurement]},
    )
    job_id = accepted["job_id"]
    print(f"submitted job_id={job_id}", flush=True)
    deadline = time.monotonic() + args.timeout
    previous = None
    while time.monotonic() < deadline:
        status = request_json(f"{args.base_url}/v1/verifications/{job_id}", api_key=api_key)
        marker = (status["status"], status["progress_step"])
        if marker != previous:
            print(f"status={marker[0]} step={marker[1]}", flush=True)
            previous = marker
        if status["status"] == "SUCCEEDED":
            result = request_json(f"{args.base_url}/v1/verifications/{job_id}/result", api_key=api_key)
            print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
            claim = result["claims"][0]
            print(f"verdict={claim['verdict']} decision_status={claim['decision_status']}")
            return
        if status["status"] == "FAILED":
            raise SystemExit(f"job failed: {status.get('error')}")
        time.sleep(5)
    raise SystemExit("smoke test timed out")


if __name__ == "__main__":
    main()
