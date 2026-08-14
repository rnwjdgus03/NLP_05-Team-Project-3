"""기존 CSV 파이프라인의 산출물을 SQLite(kosis_pipeline.db)로 옮긴다.

여러 번 실행해도 안전하다 (이미 있는 메타는 덮어쓰지 않고, 카탈로그/검증결과는
최신 값으로 갱신). 하루에 여러 번 돌려도, 실행 순서가 바뀌어도 데이터가 사라지지
않는다 - 오늘 겪었던 "파일명이 겹쳐서 통째로 사라짐" 문제가 구조적으로 없어진다.

사용법:
  python migrate_kosis_csv_to_sqlite.py \
      --db kosis_pipeline.db \
      --table-catalog data/reference/kosis_table_summary.csv \
      --meta-index data/shared_20260802/pipeline_run_v2/05_hcx_measurements_kosis_ready_kosis_meta_index.csv \
      --verified data/shared_20260802/pipeline_run_v2/05_hcx_measurements_kosis_ready_kosis_verified_v4.csv

세 인자 다 선택이다 - 있는 것만 넣어도 되고, 여러 meta-index/verified 파일을
--meta-index/--verified 를 여러 번 줘서 한 번에 다 합칠 수 있다.
"""
import argparse

import kosis_db as db


def run(args):
    conn = db.get_connection(args.db)
    db.ensure_schema(conn)

    if args.table_catalog:
        for path in args.table_catalog:
            rows = db.read_csv(path)
            n = db.upsert_table_catalog(conn, rows)
            print(f"[카탈로그] {path}: {n}행 반영")

    if args.meta_index:
        for path in args.meta_index:
            rows = db.read_csv(path)
            n = db.upsert_meta_rows(conn, rows)
            print(f"[meta-index] {path}: {n}행 시도 (이미 있는 코드는 건너뜀)")

    if args.verified:
        for path in args.verified:
            rows = db.read_csv(path)
            for row in rows:
                db.cache_verified_mapping(conn, row, source_run=path)
            print(f"[검증결과] {path}: {len(rows)}행 캐시에 반영")

    cur = conn.execute("SELECT COUNT(*) AS n FROM kosis_table_catalog")
    print(f"\n현재 DB 상태: 카탈로그 {cur.fetchone()['n']}개 표")
    cur = conn.execute("SELECT COUNT(DISTINCT org_id || ':' || tbl_id) AS n FROM kosis_codes")
    print(f"                메타 코드가 있는 표 {cur.fetchone()['n']}개")
    cur = conn.execute("SELECT COUNT(*) AS n FROM kosis_codes")
    print(f"                메타 코드 총 {cur.fetchone()['n']}행")
    cur = conn.execute("SELECT COUNT(*) AS n FROM verified_mappings")
    print(f"                캐시된 검증 결과 {cur.fetchone()['n']}건")
    conn.close()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="kosis_pipeline.db")
    parser.add_argument("--table-catalog", action="append", default=[])
    parser.add_argument("--meta-index", action="append", default=[])
    parser.add_argument("--verified", action="append", default=[])
    return parser


def main():
    args = build_parser().parse_args()
    run(args)


if __name__ == "__main__":
    main()
