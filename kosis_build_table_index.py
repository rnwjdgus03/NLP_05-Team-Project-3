#!/usr/bin/env python3
"""
KOSIS 통계표 목록 인덱스 생성기.

역할
- KOSIS statisticsList API를 재귀 호출해서 org_id/tbl_id/tbl_name/category_path를 CSV로 저장한다.
- KOSIS statisticsList API를 호출해 필요한 카테고리의 table index를 만든다.

주의
- 전체 트리 조회는 오래 걸릴 수 있다.
- 실무 흐름에서는 claim 도메인에 맞는 카테고리만 동적으로 조회한다.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path("/Users/gu/myproject/NLP_05-Team-Project-3")
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import get_list  # noqa: E402


DEFAULT_OUT = PROJECT_DIR / "data/claims/kosis_table_index.csv"


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "org_id", "tbl_id", "tbl_name", "stat_id", "category_path", "list_id_path",
        "indexed_at", "source", "coverage_scope",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def normalize_row(item, category_path, list_id_path, coverage_scope):
    return {
        "org_id": item.get("ORG_ID", ""),
        "tbl_id": item.get("TBL_ID", ""),
        "tbl_name": item.get("TBL_NM", ""),
        "stat_id": item.get("STAT_ID", ""),
        "category_path": " > ".join(category_path),
        "list_id_path": " > ".join(list_id_path),
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "KOSIS statisticsList API",
        "coverage_scope": coverage_scope,
    }


def crawl_tables(start_parent="", vw_cd="MT_ZTITLE", delay=0.15, max_calls=0):
    rows = []
    calls = 0
    seen = set()
    coverage_scope = f"{vw_cd}:{start_parent or 'ROOT'}"

    def walk(parent_id, category_path, list_id_path):
        nonlocal calls
        if max_calls and calls >= max_calls:
            return
        key = (vw_cd, parent_id)
        if key in seen:
            return
        seen.add(key)
        calls += 1
        items = get_list(vw_cd=vw_cd, parent_id=parent_id)
        time.sleep(delay)
        print(
            f"\rAPI calls={calls} tables={len(rows)} current={' > '.join(category_path) or '(root)'}",
            end="",
            flush=True,
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("TBL_ID"):
                rows.append(normalize_row(item, category_path, list_id_path, coverage_scope))
            else:
                child_id = item.get("LIST_ID", "")
                if not child_id:
                    continue
                child_name = item.get("LIST_NM") or child_id
                walk(child_id, category_path + [child_name], list_id_path + [child_id])

    walk(start_parent, [], [start_parent] if start_parent else [])
    print()
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--start-parent", default="", help="예: S2=무역ㆍ국제수지, P2=물가. 비우면 전체")
    parser.add_argument("--vw-cd", default="MT_ZTITLE")
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--max-calls", type=int, default=0, help="테스트용 API 호출 제한. 0이면 제한 없음")
    args = parser.parse_args()

    rows = crawl_tables(args.start_parent, args.vw_cd, args.delay, args.max_calls)
    out = Path(args.out).expanduser()
    write_csv(out, rows)
    print(f"saved={out} rows={len(rows)}")


if __name__ == "__main__":
    main()
