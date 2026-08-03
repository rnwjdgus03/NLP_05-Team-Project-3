#!/usr/bin/env python3
"""빈 응답이 온 좌표를 **다른 기간으로** 다시 조회해 원인을 가른다.

가르려는 것
-----------
  다른 기간에는 값이 있다  → 좌표는 맞고 그 시점 데이터만 없다 → **확인 불가**
  어느 기간에도 없다       → 좌표가 틀렸다                     → **시스템 한계**

이 구분이 커버리지 숫자의 의미를 바꾼다. 확인 불가를 시스템 한계로 세면
시스템이 실제보다 못해 보이고, 반대로 세면 성능을 부풀린다.

**요청은 반드시 build_kosis_request 로 만든다.**
2026-08-02 에 같은 검사를 손으로 두 번 짰다가 두 번 다 틀렸다.
  1차 — validate 출력의 selected_* 컬럼을 썼는데, 실패한 행은 그 칸이 비어 있다.
        좌표 없이 조회해놓고 '데이터가 없다'고 결론 낼 뻔했다.
  2차 — 후보 파일에서 좌표를 가져왔지만 objL1 만 넘기고 objL2 를 빠뜨렸다.
        KOSIS 가 err:20(세부항목 누락)을 돌려줬고 그걸 파이프라인 버그로 오해했다.
두 번 다 '좌표를 손으로 재구성'하다 생긴 일이다. 그래서 여기서는 재구성하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from kosis_api_test import get_stat_data
from kosis_meta_coordinates import read_csv_rows
from kosis_validate_mapping_candidates import build_kosis_request

MAX_AXIS = 8


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def combination_from(row) -> dict:
    """후보 행을 build_kosis_request 가 받는 조합 형태로 옮긴다.

    축을 하나라도 빠뜨리면 KOSIS 가 err:20 을 돌려주고, 그걸 '데이터 없음'으로
    오해하게 된다. 그래서 objL1~objL8 을 전부 옮긴다.
    """
    combination = {"itm_id": text(row.get("selected_itm_id")), "metadata_valid": True}
    for level in range(1, MAX_AXIS + 1):
        code = text(row.get(f"selected_obj_l{level}"))
        if code:
            combination[f"objL{level}"] = code
    return combination


def axes_used(combination) -> int:
    return sum(1 for level in range(1, MAX_AXIS + 1) if combination.get(f"objL{level}"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", required=True, help="report_coverage.py 출력")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--bucket", default="NO_DATA_AT_COORDINATE")
    ap.add_argument("--output", required=True)
    ap.add_argument("--periods", type=int, default=20)
    ap.add_argument("--delay", type=float, default=0.12)
    args = ap.parse_args()

    targets = {text(r.get("claim_measurement_id"))
               for r in read_csv_rows(args.coverage)
               if text(r.get("bucket")) == args.bucket}

    top: dict[str, dict] = {}
    for row in read_csv_rows(args.candidates):
        mid = text(row.get("claim_measurement_id"))
        if mid not in targets:
            continue
        try:
            rank = int(float(text(row.get("candidate_rank")) or "999"))
        except ValueError:
            rank = 999
        current = top.get(mid)
        if current is None or rank < current["_rank"]:
            top[mid] = {**row, "_rank": rank}

    results = []
    for mid, row in sorted(top.items()):
        combination = combination_from(row)
        note = ""
        try:
            params = build_kosis_request(
                text(row.get("org_id")) or "101", text(row.get("tbl_id")), combination,
                prd_se=text(row.get("coordinate_prd_se")) or text(row.get("prd_se")) or "Y",
                new_est_prd_cnt=args.periods)
            extra = {f"obj_l{level}": params[f"objL{level}"]
                     for level in range(2, MAX_AXIS + 1) if params.get(f"objL{level}")}
            response = get_stat_data(
                org_id=params["orgId"], tbl_id=params["tblId"],
                obj_l1=params.get("objL1"), itm_id=params["itmId"],
                prd_se=params.get("prdSe", "Y"), new_est_prd_cnt=args.periods, **extra)
            values = sum(1 for r in response
                         if text(r.get("DT")) and not text(r.get("err")))
            errors = sorted({text(r.get("err")) for r in response if text(r.get("err"))})
            note = ",".join(errors)
        except Exception as exc:
            values, note = -1, f"{type(exc).__name__}: {exc}"[:80]

        results.append({
            "claim_measurement_id": mid,
            "tbl_id": text(row.get("tbl_id")),
            "tbl_name": text(row.get("tbl_name"))[:40],
            "itm_id": combination["itm_id"],
            "axes_used": axes_used(combination),
            "values_found": values,
            "kosis_err": note,
            "claim_text": text(row.get("claim_text"))[:70],
        })
        time.sleep(args.delay)

    valid = sum(1 for r in results if r["values_found"] > 0)
    empty = sum(1 for r in results if r["values_found"] == 0)
    failed = sum(1 for r in results if r["values_found"] < 0)

    print(f"=== {args.bucket} {len(results)}건 재조회 ===\n")
    print(f"  다른 기간에 값 있음 (좌표 유효 → 확인 불가):   {valid}")
    print(f"  어느 기간에도 없음 (좌표 오류 → 시스템 한계): {empty}")
    print(f"  조회 실패:                                  {failed}")

    axis_counts = {}
    for row in results:
        axis_counts[row["axes_used"]] = axis_counts.get(row["axes_used"], 0) + 1
    print(f"\n  사용한 분류축 수 분포: {dict(sorted(axis_counts.items()))}")
    errs = {}
    for row in results:
        if row["kosis_err"]:
            errs[row["kosis_err"]] = errs.get(row["kosis_err"], 0) + 1
    if errs:
        print(f"  KOSIS 에러코드: {errs}")
        print("  ※ err:20 이 나오면 축을 덜 넘긴 것이다 — 데이터 없음이 아니다")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
