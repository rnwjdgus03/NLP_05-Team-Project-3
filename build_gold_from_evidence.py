#!/usr/bin/env python3
"""이미 확보된 근거를 골드 좌표 파일로 굳힌다 (새 판단 없이 기록만 정리).

우리는 이미 좌표까지 확인된 건을 여러 갈래로 갖고 있는데 흩어져 있어서 recall 계산에
못 쓰고 있었다. 이 스크립트는 **새로 판단하지 않고** 기존 근거를 한 파일로 모은다.

근거 등급 (강한 순)
  VALUE_REPRODUCED      실버가 그 좌표로 조회해 기사 숫자를 재현했고 그런 좌표가 유일
  VALUE_REPRODUCED_ALT  여러 좌표가 재현 — 정답이 하나가 아니다(표가 중복 수록된 경우)
  VERDICT_MATCH         검증기가 그 좌표로 '일치' 판정 (좌표 + 값 모두 확인)
  COORD_PLAUSIBLE       좌표로 데이터가 나왔고 차이가 개정으로 설명되는 수준
                        → 좌표는 맞을 가능성이 높지만 값 확인은 아니다. 사람 확인 대기.

정답이 여럿인 경우
  타 팀은 정답 tblId 를 하나로 두고 `TABLE_ID_OVERRIDES` 로 카탈로그 실재값에 맞췄다.
  우리는 그 대신 **복수 정답을 그대로 기록**한다(`A|B` 파이프 구분). 수출액이
  DT_1R11006_FRM101 과 DT_1R11001_FRM101 양쪽에 있는 것은 오류가 아니라 사실이고,
  둘 중 아무거나 찾아도 검색은 성공한 것이기 때문이다.

사용법:
  python build_gold_from_evidence.py \
    --silver silver_coordinates.csv \
    --verified 05_hcx_measurements_kosis_verified_released.csv \
    --evaluation-set evaluation_set_v2.csv \
    --output gold_coordinates_v1.csv \
    --manifest gold_coordinates_v1_manifest.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

SCHEMA_VERSION = "kosis-gold-coordinates-v1"

# 사람/LLM 검수에서 좌표에 의문이 남은 건. docs/검수_자동확정_20260731.md 근거.
# 근거를 코드에 박아두면 나중에 "왜 뺐지?" 를 다시 묻지 않아도 된다.
REVIEW_EXCLUSIONS: dict[str, str] = {
    "A0006-SP454B0C203E-m3":
        "주장은 WTO 1~9월 누적 기준인데 조회는 연간 — 기간 정의가 달라 좌표 확정 불가",
    "A0006-SP454B0C203E-m4":
        "같은 문장의 순위 주장 — 기간 정의 문제 동일",
}

STRENGTH = {
    "VALUE_REPRODUCED": 0,
    "VALUE_REPRODUCED_ALT": 1,
    "VERDICT_MATCH": 2,
    "COORD_PLAUSIBLE": 3,
}
# 값까지 확인된 등급만 '확정'으로 본다. 나머지는 사람 확인 대기.
CONFIRMED = {"VALUE_REPRODUCED", "VALUE_REPRODUCED_ALT", "VERDICT_MATCH"}

OBJ_LEVELS = (1, 2, 3)


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def coordinate_of(row, prefix="selected_") -> dict[str, str]:
    return {
        "tbl_id": text(row.get("tbl_id")),
        "itm_id": text(row.get(f"{prefix}itm_id")) or text(row.get("itm_id")),
        **{f"obj_l{n}": text(row.get(f"{prefix}obj_l{n}")) for n in OBJ_LEVELS},
    }


def _merge_alternates(entries: list[dict]) -> dict[str, str]:
    """같은 measurement 에 좌표가 여럿이면 파이프로 묶는다(둘 다 정답)."""
    merged: dict[str, str] = {}
    for field in ("tbl_id", "itm_id", *[f"obj_l{n}" for n in OBJ_LEVELS]):
        seen, values = set(), []
        for entry in entries:
            value = entry["coordinate"].get(field, "")
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        merged[field] = "|".join(values)
    return merged


def collect(silver_rows, verified_rows, keys: set[str]) -> dict[str, list[dict]]:
    """measurement 별 근거 후보를 모은다. 새 판단은 하지 않는다."""
    found: dict[str, list[dict]] = defaultdict(list)

    for row in silver_rows:
        mid = text(row.get("claim_measurement_id"))
        if mid not in keys:
            continue
        tier = text(row.get("tier"))
        if tier == "SILVER_UNIQUE":
            grade = "VALUE_REPRODUCED"
        elif tier == "SILVER_AMBIGUOUS":
            grade = "VALUE_REPRODUCED_ALT"
        else:
            continue
        coordinate = {
            "tbl_id": text(row.get("silver_tbl_id")),
            "itm_id": text(row.get("silver_itm_id")),
            **{f"obj_l{n}": text(row.get(f"silver_obj_l{n}")) for n in OBJ_LEVELS},
        }
        if not coordinate["tbl_id"]:
            continue
        found[mid].append({
            "grade": grade, "coordinate": coordinate,
            "evidence": f"실버 {tier} (KOSIS 값 재현, 후보 {text(row.get('coordinates_tried'))}개 조회)",
            "claim_text": text(row.get("claim_text")),
        })

    for row in verified_rows:
        mid = text(row.get("claim_measurement_id"))
        if mid not in keys:
            continue
        code = text(row.get("verdict_code"))
        if code == "MATCH":
            grade = "VERDICT_MATCH"
            evidence = f"검증기 '일치' (차이율 {text(row.get('value_diff'))[:12]})"
        elif code == "REVISION_VINTAGE_RISK":
            grade = "COORD_PLAUSIBLE"
            evidence = "검증기 '판정보류' — 좌표로 데이터가 나왔고 차이가 개정으로 설명되는 수준"
        else:
            continue
        coordinate = coordinate_of(row)
        if not coordinate["tbl_id"]:
            continue
        found[mid].append({
            "grade": grade, "coordinate": coordinate, "evidence": evidence,
            "claim_text": text(row.get("claim_text")),
        })

    return found


def build_rows(found: dict[str, list[dict]], claims: dict[str, dict]) -> list[dict]:
    rows = []
    for mid in sorted(found):
        entries = found[mid]
        if mid in REVIEW_EXCLUSIONS:
            continue
        entries.sort(key=lambda e: STRENGTH.get(e["grade"], 9))
        best_grade = entries[0]["grade"]
        same = [e for e in entries if e["grade"] == best_grade]
        merged = _merge_alternates(same)
        claim = claims.get(mid, {})
        rows.append({
            "claim_measurement_id": mid,
            "gold_tbl_id": merged["tbl_id"],
            "gold_itm_id": merged["itm_id"],
            "gold_obj_l1": merged["obj_l1"],
            "gold_obj_l2": merged["obj_l2"],
            "gold_obj_l3": merged["obj_l3"],
            "gold_grade": best_grade,
            "gold_confirmed": "Y" if best_grade in CONFIRMED else "N",
            "gold_evidence": " / ".join(dict.fromkeys(e["evidence"] for e in same)),
            "alternate_count": len(merged["tbl_id"].split("|")) if merged["tbl_id"] else 0,
            "gold_confirmed_by": "",          # 사람이 확인하면 이름을 적는다
            "gold_note": "",
            "claim_text": (entries[0]["claim_text"] or text(claim.get("claim_text")))[:160],
            "value": text(claim.get("value")),
            "unit": text(claim.get("unit")),
            "period": text(claim.get("measurement_period")) or text(claim.get("period")),
        })
    return rows


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver", required=True)
    ap.add_argument("--verified", required=True)
    ap.add_argument("--evaluation-set", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--manifest", default="")
    args = ap.parse_args()

    claims = {text(r.get("claim_measurement_id")): r
              for r in read_csv_rows(args.evaluation_set)}
    found = collect(read_csv_rows(args.silver), read_csv_rows(args.verified), set(claims))
    rows = build_rows(found, claims)
    if not rows:
        raise SystemExit("골드로 굳힐 근거가 없다. 입력 파일을 확인할 것.")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    grades = Counter(r["gold_grade"] for r in rows)
    confirmed = sum(1 for r in rows if r["gold_confirmed"] == "Y")
    print(f"평가 집합 {len(claims)} → 골드 {len(rows)}건 (확정 {confirmed}, 확인대기 {len(rows)-confirmed})")
    print("근거 등급:", dict(grades.most_common()))
    print(f"복수 정답(표가 중복 수록): {sum(1 for r in rows if r['alternate_count'] > 1)}건")
    if REVIEW_EXCLUSIONS:
        print(f"검수에서 제외: {len(REVIEW_EXCLUSIONS)}건")
        for mid, why in REVIEW_EXCLUSIONS.items():
            print(f"  {mid}: {why}")

    if args.manifest:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_file": str(args.output),
            "output_sha256": sha256_of(args.output),
            "evaluation_set": str(args.evaluation_set),
            "gold_measurements": len(rows),
            "confirmed": confirmed,
            "pending_human_check": len(rows) - confirmed,
            "by_grade": dict(grades),
            "review_exclusions": REVIEW_EXCLUSIONS,
            "notes": [
                "새 판단 없이 기존 근거(실버 값 재현 · 검증기 판정)를 모은 것이다.",
                "COORD_PLAUSIBLE 은 값 확인이 아니라 '좌표로 데이터가 나왔다' 수준이다.",
                "복수 정답은 파이프(|)로 기록한다 — 같은 통계가 여러 표에 수록된 경우.",
                "recall 을 보고할 때 반드시 이 등급 분포를 함께 적을 것.",
            ],
        }
        Path(args.manifest).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nmanifest: {args.manifest}")
    print(f"골드: {args.output}")


if __name__ == "__main__":
    main()
