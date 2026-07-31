#!/usr/bin/env python3
"""검색 비교용 평가 집합을 확정하고 잠근다(lock).

왜 잠그는가
  1차 READY 177 건에는 KOSIS 로 검증할 수 없는 주장이 섞여 있었다(실측).
  그 위에서 잰 recall 은 분모에 정답이 없는 건을 포함하고 있어 해석이 불가능했다.
  집합을 바꿀 때마다 숫자가 흔들리면 A/B 비교 자체가 성립하지 않으므로,
  **어떤 규칙으로 무엇을 뺐는지 manifest 에 박아** 재현 가능하게 만든다.

무엇을 빼는가
  `kosis_scope_gate` 가 REJECT 로 판정한 것만 뺀다. REVIEW 는 남긴다
  (확신 없는 규칙으로 데이터를 버리면 오탐이 생긴다).

manifest 에 남기는 것
  입력 파일 경로·sha256, 출력 sha256, 제외 코드별 건수, 게이트 규칙 스냅샷.
  → 나중에 "이 숫자는 어떤 집합에서 나왔나" 를 파일만 보고 답할 수 있다.

사용법:
  python lock_evaluation_set.py \
    --ready 05_hcx_measurements_kosis_ready.csv \
    --output evaluation_set_v2.csv \
    --manifest evaluation_set_v2_manifest.json \
    --silver silver_coordinates.csv        # (선택) 보고용 교차표
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows
from kosis_scope_gate import (
    DIFFERENCE_HINT,
    FOREIGN_MARKET,
    GLOBAL_AGGREGATE,
    GLOBAL_CONTEXT,
    FORECAST,
    PLAN,
    POLICY_PARAM,
    gate_decision,
)

SCHEMA_VERSION = "kosis-evaluation-set-v2"


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text(value) -> str:
    return str(value or "").strip()


def apply_gate(rows):
    """(유지 행, 제외 행) 으로 가른다. REVIEW 는 유지하되 표시를 남긴다."""
    kept, dropped = [], []
    for row in rows:
        decision = gate_decision(row)
        merged = {**row, **decision}
        (dropped if decision["scope_gate_blocked"] == "Y" else kept).append(merged)
    return kept, dropped


def rule_snapshot() -> dict:
    """어떤 규칙으로 걸렀는지 그대로 박아둔다(규칙이 바뀌면 manifest 가 달라진다)."""
    return {
        "foreign_market": list(FOREIGN_MARKET),
        "global_aggregate": list(GLOBAL_AGGREGATE),
        "global_context": list(GLOBAL_CONTEXT),
        "forecast": list(FORECAST),
        "plan": list(PLAN),
        "policy_parameter": list(POLICY_PARAM),
        "difference_hint": list(DIFFERENCE_HINT),
    }


def build_manifest(ready_path, output_path, kept, dropped, silver_rows=None) -> dict:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_ready_file": str(ready_path),
        "source_ready_sha256": sha256_of(ready_path),
        "output_file": str(output_path),
        "output_sha256": sha256_of(output_path),
        "input_measurements": len(kept) + len(dropped),
        "locked_measurements": len(kept),
        "excluded_measurements": len(dropped),
        "excluded_by_code": dict(Counter(r["scope_gate_code"] for r in dropped).most_common()),
        "review_flagged_but_kept": sum(1 for r in kept if r["scope_gate_severity"] == "REVIEW"),
        "gate_rules": rule_snapshot(),
        "notes": [
            "REJECT 만 제외했다. REVIEW 는 확신이 없어 남긴다(오탐 방지).",
            "게이트는 문장 단위라, 전망 문장에 섞인 실적치가 함께 제외될 수 있다.",
            "이 집합은 '검색 비교'용이다. 판정(verdict) 정확도 평가에는 별도 검토가 필요하다.",
        ],
    }
    if silver_rows:
        tier_of = {text(r.get("claim_measurement_id")): text(r.get("tier")) for r in silver_rows}
        manifest["silver_tier_kept"] = dict(Counter(
            tier_of.get(text(r.get("claim_measurement_id")), "(없음)") for r in kept).most_common())
        manifest["silver_tier_excluded"] = dict(Counter(
            tier_of.get(text(r.get("claim_measurement_id")), "(없음)") for r in dropped).most_common())
        manifest["false_positive_check"] = {
            "silver_unique_excluded": sum(
                1 for r in dropped
                if tier_of.get(text(r.get("claim_measurement_id"))) == "SILVER_UNIQUE"),
            "criterion": "값이 재현된 건을 제외하면 오탐이다. 0이어야 한다.",
        }
    return manifest


def write_csv(path, rows):
    fields = list(rows[0].keys())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ready", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--excluded-output", default="")
    ap.add_argument("--silver", default="")
    args = ap.parse_args()

    rows = read_csv_rows(args.ready)
    kept, dropped = apply_gate(rows)
    if not kept:
        raise SystemExit("평가 집합이 비었다. 게이트 규칙을 확인할 것.")

    write_csv(args.output, kept)
    if args.excluded_output and dropped:
        write_csv(args.excluded_output, dropped)

    silver_rows = read_csv_rows(args.silver) if args.silver else None
    manifest = build_manifest(args.ready, args.output, kept, dropped, silver_rows)
    Path(args.manifest).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"입력 {manifest['input_measurements']} → 확정 {manifest['locked_measurements']} "
          f"(제외 {manifest['excluded_measurements']})")
    print("제외 사유:", manifest["excluded_by_code"])
    print(f"REVIEW 표시 후 유지: {manifest['review_flagged_but_kept']}")
    if "false_positive_check" in manifest:
        n = manifest["false_positive_check"]["silver_unique_excluded"]
        print(f"오탐(값 재현됐는데 제외): {n}건 " + ("← 문제 없음" if n == 0 else "← 규칙을 좁혀야 함"))
        print("유지 집합의 실버 분포:", manifest.get("silver_tier_kept"))
    print(f"\n집합: {args.output}\nmanifest: {args.manifest}")
    print(f"output_sha256={manifest['output_sha256'][:16]}…")


if __name__ == "__main__":
    main()
