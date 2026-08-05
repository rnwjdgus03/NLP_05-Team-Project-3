#!/usr/bin/env python3
"""씨앗 좌표를 KOSIS 에 직접 물어 살아 있는 것만 남긴다 (2026-08-05).

## 왜 검증부터 하는가

`build_seed_coordinates.py` 가 가져온 좌표는 **남이 손으로 맞춘 것**이다.
별 8개 개인 프로젝트고 주석은 "2024년 기준" 이다. 표가 폐지됐거나 항목 코드가
바뀌었을 수 있다.

**검증 안 한 좌표를 골드로 삼으면 순환 골드보다 나쁘다.** 순환 골드는 성능을
부풀릴 뿐이지만, 틀린 골드는 맞는 답에 오답 딱지를 붙인다.
오늘 아침에 확정 12건 중 불일치 3건이 **전부 오판**이었던 것과 같은 종류의 사고다.

## 무엇으로 통과를 판정하는가

값이 실제로 오는지만 본다. **값이 맞는지는 여기서 판단하지 않는다** —
그건 우리가 확인하려는 대상이지 전제가 아니다.

    PASS       행이 오고 DT 가 비어 있지 않다
    NO_DATA    err:30 — 좌표는 형식상 맞는데 자료가 없다
    ERR_AXIS   err:20 — **축을 덜 넘겼다.** 데이터 없음이 아니다
    ERR_OTHER  그 밖의 KOSIS 오류
    FAILED     호출 자체가 실패

`err:20` 을 '데이터 없음'으로 읽는 실수를 오늘만 두 번 했다.
한 번은 프로브에서 축 0개로 28건을 조회해놓고 '좌표 오류' 로 셀 뻔했고,
그 전에도 objL2 를 빠뜨려 같은 오해를 했다. **그래서 코드를 따로 센다.**

## 축을 전부 넘긴다

objL1 만 넘기고 objL2 를 빠뜨리면 KOSIS 는 err:20 을 돌려준다.
원본에 objL2 가 있으면 반드시 함께 보낸다.

## 주의

- **API 키를 로그에 남기지 않는다.** requests 는 예외 메시지에 전체 URL 을 넣는다.
  오늘 그것 때문에 키가 트레이스백에 찍혀 폐기해야 했다. 예외는 종류만 남긴다.
- `--resume` 으로 이어받는다.

## 쓰는 법

    python verify_seed_coordinates.py \\
      --input data/seed_coordinates.csv \\
      --output data/seed_coordinates_verified.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import get_stat_data  # noqa: E402

FIELDS = ["keyword", "org_id", "tbl_id", "tbl_name", "itm_id", "obj_l1", "obj_l2",
          "unit", "prd_se_list", "region_scheme", "source",
          "check_status", "check_prd_se", "sample_period", "sample_value",
          "sample_unit", "kosis_err"]


def nz(value) -> str:
    return str(value or "").strip()


def first_periodicity(row) -> str:
    """지원 주기 중 가장 굵은 것으로 확인한다. 자료가 있을 확률이 높다."""
    listed = [p for p in nz(row.get("prd_se_list")).split("|") if p]
    for wanted in ("Y", "Q", "M"):
        if wanted in listed:
            return wanted
    return listed[0] if listed else "Y"


def classify(payload) -> tuple[str, str, list]:
    """KOSIS 응답을 (상태, 에러코드, 행) 으로 가른다."""
    if isinstance(payload, dict):
        code = nz(payload.get("err") or payload.get("errCd"))
        if code == "30":
            return "NO_DATA", code, []
        if code == "20":
            return "ERR_AXIS", code, []
        return "ERR_OTHER", code or "?", []
    rows = [r for r in (payload or []) if isinstance(r, dict)]
    if not rows:
        return "NO_DATA", "", []
    if not any(nz(r.get("DT")) for r in rows):
        return "NO_DATA", "", rows
    return "PASS", "", rows


def check(row, periods) -> dict:
    prd_se = first_periodicity(row)
    extra = {}
    if nz(row.get("obj_l2")):
        extra["objL2"] = nz(row["obj_l2"])
    try:
        payload = get_stat_data(nz(row["org_id"]), nz(row["tbl_id"]),
                                nz(row["obj_l1"]) or None, nz(row["itm_id"]),
                                prd_se=prd_se, new_est_prd_cnt=periods, **extra)
    except Exception as exc:          # 키가 URL 에 있으므로 본문을 찍지 않는다
        return {"check_status": "FAILED", "check_prd_se": prd_se,
                "kosis_err": type(exc).__name__}

    status, code, rows = classify(payload)
    latest = rows[-1] if rows else {}
    return {"check_status": status, "check_prd_se": prd_se, "kosis_err": code,
            "sample_period": nz(latest.get("PRD_DE")),
            "sample_value": nz(latest.get("DT")),
            "sample_unit": nz(latest.get("UNIT_NM"))}


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {nz(r.get("keyword")) for r in csv.DictReader(handle)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--periods", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--unique-tables", action="store_true",
                        help="같은 좌표를 가리키는 동의어는 한 번만 조회한다")
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    done = load_done(args.output) if args.resume else set()
    todo = [r for r in rows if nz(r.get("keyword")) not in done]

    # 동의어가 많다('인구'/'총인구', '실업률' …). 좌표가 같으면 한 번만 물어본다.
    cache: dict[tuple, dict] = {}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    append = args.resume and args.output.exists()
    handle = args.output.open("a" if append else "w", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
    if not append:
        writer.writeheader()

    from collections import Counter
    counts: Counter = Counter()
    with handle:
        for index, row in enumerate(todo, start=1):
            key = (nz(row["org_id"]), nz(row["tbl_id"]), nz(row["itm_id"]),
                   nz(row["obj_l1"]), nz(row["obj_l2"]))
            if args.unique_tables and key in cache:
                result = cache[key]
            else:
                result = check(row, args.periods)
                cache[key] = result
                time.sleep(args.delay)
            counts[result["check_status"]] += 1
            writer.writerow({**row, **result})
            print(f"\r{index}/{len(todo)} {dict(counts)} {nz(row['keyword'])[:14]:16s}",
                  end="", flush=True)

    print()
    print(f"saved={args.output}")
    for status, number in counts.most_common():
        print(f"  {status:10s} {number}")
    print()
    print("**PASS 만 골드 후보다.** ERR_AXIS 가 있으면 축을 덜 넘긴 것이지")
    print("좌표가 틀린 게 아니다 — 원본의 objL2 를 확인할 것.")


if __name__ == "__main__":
    main()
