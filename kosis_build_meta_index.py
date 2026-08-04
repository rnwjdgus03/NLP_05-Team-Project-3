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

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import get_meta  # noqa: E402
from kosis_meta_coordinates import normalize_periodicity  # noqa: E402


DEFAULT_TABLE_INDEX = PROJECT_DIR / "data/claims/kosis_table_index.csv"
DEFAULT_OUT = PROJECT_DIR / "data/claims/kosis_meta_index.csv"


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# extrasaction="ignore" 라서 여기 없는 키는 **조용히 버려진다.**
# 2026-08-04: convert_meta_rows 에 prd_se_list 를 넣었는데 이 목록을 안 고쳐서
# 520개 표를 다 수집하고도 컬럼이 없었다. 사전만 검사하는 테스트는 이걸 못 잡는다.
FIELDS = [
    "org_id", "tbl_id", "tbl_name", "category_path",
    "axis_id", "axis_name", "axis_order",
    "code_id", "code_name", "parent_code_id",
    "is_item", "unit_id", "unit_name", "unit_eng_name",
    "prd_se_list", "prd_ranges",
]


def append_csv(path: Path, rows, write_header=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = FIELDS
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


def collect_periodicity(org_id, tbl_id):
    """표가 어떤 주기를 제공하는가 (2026-08-04 추가).

    이걸 몰라서 **분기 주장에 연간을 물어봤다.** 홀드아웃1 의 거짓 불일치 하나가
    그 때문이다 — '소매판매액지수 2022년 2분기 -0.2%' 를 2022년 연간 +5.88% 와 대조했다.

    KOSIS 는 없는 주기를 물어도 **에러를 내지 않는다.** 실측(DT_127005_005):
    prdSe=M 으로 물으면 PRD_DE=['2019'..'2024'] 인 연간 행이 그대로 온다.
    그래서 조회 전에 표가 무엇을 줄 수 있는지 알아야 한다.

    반환: ('Y|Q|M', '1970~2025') 형태. 실패하면 ('', '') — 수집을 멈추지 않는다.
    """
    try:
        rows = get_meta(org_id, tbl_id, "PRD")
    except Exception:
        return "", ""
    codes, spans = [], []
    for row in rows or []:
        code = normalize_periodicity(row.get("PRD_SE"))
        if code and code not in codes:
            codes.append(code)
        start = str(row.get("STRT_PRD_DE") or "").strip()
        end = str(row.get("END_PRD_DE") or "").strip()
        if start or end:
            spans.append(f"{code}:{start}~{end}")
    return "|".join(codes), ";".join(spans)


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
            # 표 단위 값이라 행마다 같다. 하류가 표를 고를 때 이것만 보면 되도록 붙여둔다.
            "prd_se_list": table.get("prd_se_list", ""),
            "prd_ranges": table.get("prd_ranges", ""),
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
    parser.add_argument("--with-periodicity", action="store_true",
                        help="표별 수록 주기를 함께 수집한다 (표당 API 1회 추가)")
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
            if args.with_periodicity:
                table["prd_se_list"], table["prd_ranges"] = collect_periodicity(
                    table["org_id"], table["tbl_id"])
                time.sleep(args.delay)
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
