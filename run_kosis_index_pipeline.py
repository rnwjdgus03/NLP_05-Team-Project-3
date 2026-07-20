#!/usr/bin/env python3
"""
KOSIS 인덱스 기반 claim 후보 매칭 파이프라인 러너.

실행하면:
1) claim 내용을 보고 필요한 KOSIS 카테고리를 statisticsList API로 동적 조회
2) API 조회 결과로 이번 claim 전용 table index 생성
3) claim별 상위 후보 tbl_id 목록 추출
4) 해당 tbl_id만 KOSIS 메타 API로 조회해 meta index 생성
5) meta index를 붙여 claim ↔ tbl/obj/itm 후보 CSV 재생성

이 스크립트는 KOSIS API 기반 동적 자동매핑 파이프라인이다.
현재 단계는 claim별 tbl_id/메타 후보를 생성하고, 이후 실제값 검증 단계로 확장한다.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path("/Users/gu/myproject/NLP_05-Team-Project-3")
PROJECT_PYTHON = PROJECT_DIR / "venv/bin/python"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TABLE_INDEX = PROJECT_DIR / "data/claims/kosis_table_index.csv"

CATEGORY_PARENT_MAP = {
    "인구": ["A"],
    "출생": ["A"],
    "혼인": ["A"],
    "사망": ["A"],
    "고용": ["D"],
    "노동": ["D"],
    "실업": ["D"],
    "취업": ["D"],
    "임금": ["P1", "D"],
    "최저임금": ["P1", "D"],
    "물가": ["P2"],
    "소비자물가": ["P2"],
    "생산자물가": ["P2"],
    "수입물가": ["P2", "S2"],
    "무역": ["S2"],
    "수출": ["S2"],
    "수입": ["S2"],
    "무역수지": ["S2"],
    "국제수지": ["S2"],
    "소매": ["O"],
    "판매": ["O"],
    "도소매": ["O"],
    "산업": ["J1", "L"],
    "생산": ["J1", "L"],
    "제조": ["L"],
    "건설": ["M1"],
    "교통": ["M2"],
    "항공": ["M2"],
    "GDP": ["Q"],
    "성장률": ["Q", "J1"],
    "국내총생산": ["Q"],
    "복지": ["G"],
    "육아": ["G", "D"],
    "양육": ["G"],
    "보건": ["F"],
    "건강": ["F"],
    "로봇": ["N2", "L"],
    "기술": ["N2"],
    "정보통신": ["N1"],
}

DEFAULT_DYNAMIC_PARENTS = ["S2", "P2", "D", "J1", "O", "Q"]


def run(cmd):
    print("+", " ".join(str(c) for c in cmd))
    completed = subprocess.run([str(c) for c in cmd])
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def infer_api_start_parents(claims_path: Path, max_categories: int = 8):
    rows = read_csv(claims_path)
    found = []
    for row in rows:
        text = " ".join(
            str(row.get(c, ""))
            for c in ["metric_domain", "indicator", "keywords", "industry_or_item", "claim_text"]
        )
        for token, parents in CATEGORY_PARENT_MAP.items():
            if token in text:
                found.extend(parents)
    if not found:
        found = list(DEFAULT_DYNAMIC_PARENTS)
    # 순서 보존 + 과다 API 호출 방지
    deduped = list(dict.fromkeys(found))
    return deduped[:max_categories]


def merge_csvs(paths, out_path: Path):
    seen = set()
    out = []
    fields = [
        "org_id", "tbl_id", "tbl_name", "stat_id", "category_path", "list_id_path",
        "indexed_at", "source", "coverage_scope",
    ]
    for path in paths:
        for row in read_csv(path):
            key = (row.get("org_id") or row.get("ORG_ID"), row.get("tbl_id") or row.get("TBL_ID"))
            if not all(key) or key in seen:
                continue
            seen.add(key)
            out.append({
                "org_id": key[0],
                "tbl_id": key[1],
                "tbl_name": row.get("tbl_name") or row.get("TBL_NM") or "",
                "stat_id": row.get("stat_id") or row.get("STAT_ID") or "",
                "category_path": row.get("category_path") or row.get("path") or "",
                "list_id_path": row.get("list_id_path", ""),
                "indexed_at": row.get("indexed_at", ""),
                "source": row.get("source", "KOSIS statisticsList API"),
                "coverage_scope": row.get("coverage_scope", ""),
            })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    print(f"dynamic_table_index={len(out)} -> {out_path}")


def build_dynamic_table_index(claims_path: Path, out_dir: Path, delay: float, max_calls: int, start_parents):
    if not start_parents:
        start_parents = infer_api_start_parents(claims_path)
    partials = []
    for parent in start_parents:
        out = out_dir / f"{claims_path.stem}_kosis_table_index_api_{parent}.csv"
        run([
            str(PROJECT_PYTHON),
            SCRIPT_DIR / "kosis_build_table_index.py",
            "--start-parent", parent,
            "--out", out,
            "--delay", delay,
            "--max-calls", max_calls,
        ])
        partials.append(out)
    merged = out_dir / f"{claims_path.stem}_kosis_table_index_api.csv"
    merge_csvs(partials, merged)
    return merged


def write_top_tables(candidates_path: Path, out_path: Path, top_rank: int):
    rows = read_csv(candidates_path)
    seen = set()
    out = []
    for r in rows:
        try:
            rank = int(r.get("candidate_rank", "999"))
        except ValueError:
            rank = 999
        if rank > top_rank:
            continue
        key = (r.get("org_id", ""), r.get("tbl_id", ""))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        out.append({
            "org_id": r.get("org_id", ""),
            "tbl_id": r.get("tbl_id", ""),
            "tbl_name": r.get("tbl_name", ""),
            "category_path": r.get("category_path", ""),
            "stat_id": r.get("stat_id", ""),
        })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["org_id", "tbl_id", "tbl_name", "category_path", "stat_id"])
        writer.writeheader()
        writer.writerows(out)
    print(f"top_candidate_tables={len(out)} -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True)
    parser.add_argument("--table-source", choices=["api", "cache"], default="api", help="api=KOSIS 동적 조회. cache는 별도 table-index를 직접 줄 때만 사용")
    parser.add_argument("--table-index", default="", help="--table-source cache일 때 직접 지정할 로컬 인덱스 CSV")
    parser.add_argument("--api-start-parent", action="append", default=[], help="API 조회 시작 카테고리. 예: S2, P2. 여러 번 지정 가능")
    parser.add_argument("--api-max-categories", type=int, default=8)
    parser.add_argument("--api-max-calls-per-category", type=int, default=0, help="0이면 제한 없음")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--top-tables", type=int, default=5)
    parser.add_argument("--top-rank-for-meta", type=int, default=2)
    parser.add_argument("--top-meta", type=int, default=8)
    parser.add_argument("--min-score", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--keep-intermediate", action="store_true", help="중간 CSV(table index/meta/stage1)를 out-dir에 남김. 기본은 최종 파일만 남김")
    args = parser.parse_args()

    claims_path = Path(args.claims).expanduser()
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else claims_path.parent
    stem = claims_path.stem

    work_dir_obj = None
    if args.keep_intermediate:
        work_dir = out_dir
    else:
        work_dir_obj = tempfile.TemporaryDirectory(prefix=f"{stem}_kosis_")
        work_dir = Path(work_dir_obj.name)

    stage1 = work_dir / f"{stem}_kosis_index_candidates.csv"
    top_tables = work_dir / f"{stem}_top_candidate_tables.csv"
    meta_index = work_dir / f"{stem}_kosis_meta_index.csv"
    final_work = work_dir / f"{stem}_kosis_index_candidates_with_meta.csv"
    final = out_dir / f"{stem}_kosis_index_candidates_with_meta.csv"

    if args.table_source == "api":
        start_parents = args.api_start_parent or infer_api_start_parents(
            claims_path, max_categories=args.api_max_categories
        )
        print(f"table_source=api start_parents={','.join(start_parents)}")
        table_index = build_dynamic_table_index(
            claims_path,
            work_dir,
            args.delay,
            args.api_max_calls_per_category,
            start_parents,
        )
    else:
        if not args.table_index:
            raise SystemExit("--table-source cache를 쓰려면 --table-index를 직접 지정해야 합니다. 기본 크롤링 캐시는 삭제되었습니다.")
        table_index = Path(args.table_index).expanduser()
        print(f"table_source=cache table_index={table_index}")

    run([
        sys.executable,
        SCRIPT_DIR / "kosis_match_claims_to_index.py",
        "--claims", claims_path,
        "--table-index", table_index,
        "--out", stage1,
        "--top-tables", args.top_tables,
        "--min-score", args.min_score,
    ])

    write_top_tables(stage1, top_tables, args.top_rank_for_meta)

    run([
        str(PROJECT_PYTHON),
        SCRIPT_DIR / "kosis_build_meta_index.py",
        "--table-index", top_tables,
        "--out", meta_index,
        "--delay", args.delay,
    ])

    run([
        sys.executable,
        SCRIPT_DIR / "kosis_match_claims_to_index.py",
        "--claims", claims_path,
        "--table-index", table_index,
        "--meta-index", meta_index,
        "--out", final_work,
        "--top-tables", args.top_tables,
        "--top-meta", args.top_meta,
        "--min-score", args.min_score,
    ])

    if final_work != final:
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_work, final)

    print("\nDONE")
    if args.keep_intermediate:
        print(stage1)
        print(top_tables)
        print(meta_index)
    else:
        print("intermediate files: cleaned (use --keep-intermediate to keep them)")
    print(final)

    if work_dir_obj is not None:
        work_dir_obj.cleanup()


if __name__ == "__main__":
    main()
