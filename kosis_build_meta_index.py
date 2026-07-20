#!/usr/bin/env python3
"""
KOSIS 메타 인덱스 생성기.

입력
- 통계표 인덱스 CSV: org_id/tbl_id/tbl_name/category_path

출력
- kosis_meta_index.csv: 표별 분류축/항목 코드 long format

왜 필요한가
- tbl_id만으로는 claim 검증이 불가능하다.
- 실제 검증에는 obj_l1/obj_l2/itm_id/unit까지 필요하므로 getMeta 결과를
  검색 가능한 long table로 만들어둔다.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

PROJECT_DIR = Path("/Users/gu/myproject/NLP_05-Team-Project-3")
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import get_meta  # noqa: E402


DEFAULT_TABLE_INDEX = PROJECT_DIR / "data/claims/kosis_table_index.csv"
DEFAULT_OUT = PROJECT_DIR / "data/claims/kosis_meta_index.csv"


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, rows, write_header=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "org_id", "tbl_id", "tbl_name", "category_path",
        "axis_id", "axis_name", "axis_order",
        "code_id", "code_name", "parent_code_id",
        "is_item", "unit_id", "unit_name", "unit_eng_name",
    ]
    mode = "w" if write_header else "a"
    with path.open(mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def norm_table_row(row):
    return {
        "org_id": row.get("org_id") or row.get("ORG_ID") or row.get("OrgId") or "",
        "tbl_id": row.get("tbl_id") or row.get("TBL_ID") or row.get("TblId") or "",
        "tbl_name": row.get("tbl_name") or row.get("TBL_NM") or row.get("TBL_NM_KOR") or "",
        "category_path": row.get("category_path") or row.get("path") or "",
    }


def convert_meta_rows(table, meta_rows):
    out = []
    for r in meta_rows:
        axis_id = r.get("OBJ_ID", "")
        is_item = axis_id == "ITEM"
        out.append({
            "org_id": table["org_id"],
            "tbl_id": table["tbl_id"],
            "tbl_name": table["tbl_name"],
            "category_path": table["category_path"],
            "axis_id": axis_id,
            "axis_name": r.get("OBJ_NM", ""),
            "axis_order": r.get("OBJ_ID_SN", ""),
            "code_id": r.get("ITM_ID", ""),
            "code_name": r.get("ITM_NM", ""),
            "parent_code_id": r.get("UP_ITM_ID", ""),
            "is_item": "Y" if is_item else "N",
            "unit_id": r.get("UNIT_ID", ""),
            "unit_name": r.get("UNIT_NM", ""),
            "unit_eng_name": r.get("UNIT_ENG_NM", ""),
        })
    return out


def load_done(path: Path):
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("org_id") and r.get("tbl_id"):
                done.add((r["org_id"], r["tbl_id"]))
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-index", default=str(DEFAULT_TABLE_INDEX))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=0, help="테스트용 처리 표 수. 0이면 전체")
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keyword", action="append", default=[], help="tbl_name/category_path 필터. 여러 번 가능")
    args = parser.parse_args()

    table_rows = [norm_table_row(r) for r in read_csv(Path(args.table_index).expanduser())]
    table_rows = [r for r in table_rows if r["org_id"] and r["tbl_id"]]
    if args.keyword:
        kws = args.keyword
        table_rows = [
            r for r in table_rows
            if any(k in f"{r['tbl_name']} {r['category_path']}" for k in kws)
        ]

    out = Path(args.out).expanduser()
    done = load_done(out) if args.resume else set()
    todo = [r for r in table_rows if (r["org_id"], r["tbl_id"]) not in done]
    if args.limit:
        todo = todo[:args.limit]

    append_csv(out, [], write_header=not args.resume or not out.exists())
    ok = 0
    fail = 0
    for i, table in enumerate(todo, 1):
        try:
            meta = get_meta(table["org_id"], table["tbl_id"], "ITM")
            rows = convert_meta_rows(table, meta)
            append_csv(out, rows)
            ok += 1
            print(f"\r{i}/{len(todo)} ok={ok} fail={fail} {table['tbl_id']} {table['tbl_name'][:40]}", end="", flush=True)
        except Exception as exc:
            fail += 1
            print(f"\nFAIL {table['org_id']}/{table['tbl_id']} {table['tbl_name']}: {exc}", flush=True)
        time.sleep(args.delay)
    print()
    print(f"saved={out} tables_ok={ok} tables_fail={fail}")


if __name__ == "__main__":
    main()
