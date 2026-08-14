"""Run the strict measurement-level KOSIS mapping pipeline.

Unlike the legacy runner, this command never assumes every input row is a
KOSIS target.  It prepares an eligible measurement file first and only sends a
candidate to value verification after table/meta matching marks it READY.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def run(command):
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_top_tables(candidate_path, output_path, max_rank):
    seen = set()
    rows = []
    for row in read_csv(candidate_path):
        try:
            rank = int(row.get("candidate_rank", "999"))
        except ValueError:
            rank = 999
        if rank > max_rank:
            continue
        key = (row.get("org_id", ""), row.get("tbl_id", ""))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "org_id": key[0],
                "tbl_id": key[1],
                "tbl_name": row.get("tbl_name", ""),
                "category_path": row.get("category_path", ""),
                "stat_id": row.get("stat_id", ""),
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["org_id", "tbl_id", "tbl_name", "category_path", "stat_id"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"top_tables={len(rows)} -> {output_path}")


def measurement_key(row):
    return row.get("claim_measurement_id") or row.get("claim_id") or ""


def validate_reusable_candidates(ready_path, candidate_path):
    if not candidate_path.exists():
        raise FileNotFoundError(
            f"재사용할 후보 CSV가 없습니다: {candidate_path}. "
            "먼저 --skip-meta 후보 검색을 실행하세요."
        )
    expected = {measurement_key(row) for row in read_csv(ready_path)}
    candidate_rows = read_csv(candidate_path)
    actual = {measurement_key(row) for row in candidate_rows}
    expected.discard("")
    actual.discard("")
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ValueError(
            "재사용 후보 CSV와 현재 READY 입력의 measurement 집합이 다릅니다. "
            f"missing={missing[:5]} extra={extra[:5]}"
        )
    top1 = [row for row in candidate_rows if row.get("candidate_rank") == "1"]
    if len(top1) != len(expected):
        raise ValueError(
            "재사용 후보 CSV의 1위 후보 수가 READY measurement 수와 다릅니다. "
            f"top1={len(top1)} expected={len(expected)}"
        )
    print(
        f"table_candidates=reused rows={len(candidate_rows)} "
        f"measurements={len(expected)} path={candidate_path}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="v1.5 measurement-first CSV")
    parser.add_argument("--table-index", required=True)
    parser.add_argument("--out-dir", default="outputs/runs")
    parser.add_argument("--top-tables", type=int, default=5)
    parser.add_argument("--top-rank-for-meta", type=int, default=2)
    parser.add_argument("--top-meta", type=int, default=8)
    parser.add_argument("--min-score", type=int, default=10)
    parser.add_argument(
        "--retrieval-mode",
        choices=["auto", "lexical", "hybrid"],
        default="auto",
        help="auto는 임베딩 인덱스가 있으면 hybrid+reranker를 사용",
    )
    parser.add_argument("--semantic-index", default="data/indexes/kosis_bge_m3")
    parser.add_argument("--semantic-top-k", type=int, default=50)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--lexical-reserve-k", type=int, default=0)
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--device", default=None)
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--item-top-k", type=int, default=3)
    parser.add_argument("--obj-top-k", type=int, default=2)
    parser.add_argument("--max-combinations", type=int, default=20)
    parser.add_argument("--skip-meta", action="store_true", help="table-only offline run")
    parser.add_argument(
        "--reuse-table-candidates",
        action="store_true",
        help="기존 table candidates를 검증해 재사용하고 GPU 검색은 건너뜀",
    )
    # --- 여기부터 추가: kosis_match_claims_to_index.py 가 이미 지원하는 override
    # 인자를 오케스트레이터가 그대로 물려주게 한다. 지금까지는 오케스트레이터로
    # 돌리면 이 두 파일이 항상 무시돼서, override를 쓰려면 2차 검색 단계를 손으로
    # 다시 실행해야 했다 (2026-08-11 KOSIS 매핑 점검에서 발견).
    parser.add_argument(
        "--table-overrides",
        default="",
        help="감사 가능한 통계표 검색 override CSV. 빈 문자열이면 사용하지 않음. "
        "1차(표만) 검색과 2차(메타 포함) 검색 모두에 전달된다.",
    )
    parser.add_argument(
        "--mapping-overrides",
        default="",
        help="공식 ITEM/OBJ 코드로 검증되는 매핑 override CSV. 빈 문자열이면 사용하지 않음. "
        "메타 인덱스가 있는 2차 검색에만 전달된다(좌표 확정에 메타가 필요하므로).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    ready = out_dir / f"{stem}_kosis_ready.csv"
    enrich = out_dir / f"{stem}_kosis_enrich.csv"
    rejected = out_dir / f"{stem}_kosis_rejected.csv"
    table_candidates = out_dir / f"{stem}_kosis_table_candidates.csv"
    top_tables = out_dir / f"{stem}_kosis_top_tables.csv"
    meta_index = out_dir / f"{stem}_kosis_meta_index.csv"
    final_candidates = out_dir / f"{stem}_kosis_candidates_with_meta.csv"
    validated_candidates = out_dir / f"{stem}_kosis_validated_mappings.csv"
    verified = out_dir / f"{stem}_kosis_verified.csv"

    run(
        [
            sys.executable,
            SCRIPT_DIR / "prepare_kosis_mapping_input.py",
            "--input",
            input_path,
            "--output",
            ready,
            "--rejected-output",
            rejected,
            "--enrich-output",
            enrich,
        ]
    )
    retrieval_command = [
        sys.executable,
        SCRIPT_DIR / "kosis_match_claims_to_index.py",
        "--claims",
        ready,
        "--table-index",
        args.table_index,
        "--meta-index",
        out_dir / "__no_meta__.csv",
        "--out",
        table_candidates,
        "--top-tables",
        args.top_tables,
        "--min-score",
        args.min_score,
        "--retrieval-mode",
        args.retrieval_mode,
        "--semantic-index",
        args.semantic_index,
        "--semantic-top-k",
        args.semantic_top_k,
        "--rerank-top-k",
        args.rerank_top_k,
        "--lexical-reserve-k",
        args.lexical_reserve_k,
        "--reranker-model",
        args.reranker_model,
    ]
    if args.device:
        retrieval_command.extend(["--device", args.device])
    if args.no_reranker:
        retrieval_command.append("--no-reranker")
    if args.table_overrides:
        retrieval_command.extend(["--table-overrides", args.table_overrides])
    if args.reuse_table_candidates:
        validate_reusable_candidates(ready, table_candidates)
    else:
        run(retrieval_command)

    if args.skip_meta:
        print(f"table_only={table_candidates}")
        return

    write_top_tables(table_candidates, top_tables, args.top_rank_for_meta)
    run(
        [
            sys.executable,
            SCRIPT_DIR / "kosis_build_meta_index.py",
            "--table-index",
            top_tables,
            "--out",
            meta_index,
            "--delay",
            args.delay,
            # 주기를 안 담으면 하류의 주기 가드가 전부 잠든다 (2026-08-04).
            # prd_se_list 가 비면 '모름'으로 읽어 막지 않도록 설계했기 때문이다.
            # 실측: 분기·월 주장 21건 중 18건이 답할 수 없는 표로 가고 있었다.
            # 표당 API 1회가 더 들지만 그만한 값이 있다.
            "--with-periodicity",
        ]
    )
    final_command = [
        sys.executable,
        SCRIPT_DIR / "kosis_match_claims_to_index.py",
        "--claims",
        ready,
        "--table-index",
        args.table_index,
        "--meta-index",
        meta_index,
        "--out",
        final_candidates,
        "--ranking-input",
        table_candidates,
        "--top-tables",
        args.top_tables,
        "--top-meta",
        args.top_meta,
        "--min-score",
        args.min_score,
    ]
    if args.table_overrides:
        final_command.extend(["--table-overrides", args.table_overrides])
    if args.mapping_overrides:
        final_command.extend(["--mapping-overrides", args.mapping_overrides])
    run(final_command)

    if args.verify:
        run(
            [
                sys.executable,
                SCRIPT_DIR / "kosis_validate_mapping_candidates.py",
                "--input",
                final_candidates,
                "--meta-index",
                meta_index,
                "--output",
                validated_candidates,
                "--item-top-k",
                args.item_top_k,
                "--obj-top-k",
                args.obj_top_k,
                "--max-combinations",
                args.max_combinations,
            ]
        )
        run(
            [
                sys.executable,
                SCRIPT_DIR / "kosis_verify_claim_values.py",
                "--input",
                validated_candidates,
                "--output",
                verified,
                "--delay",
                args.delay,
            ]
        )
    else:
        print("verification=skipped (add --verify after reviewing READY candidates)")
    print(f"final_candidates={final_candidates}")
    if args.verify:
        print(f"validated_mappings={validated_candidates}")


if __name__ == "__main__":
    main()