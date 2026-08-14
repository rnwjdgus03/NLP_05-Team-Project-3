"""어휘 검색(lexical)을 기본으로 쓰되, 실패한 claim만 벡터 검색(hybrid)으로 보강한다.

배경: README 실측 결과 - 표(TBL) 검색에서 어휘 검색이 BGE-M3/KURE-v1 임베딩보다
전체적으로 나았다(recall@5 62.5% vs 58.3%). 임베딩이 추가로 찾아낸 정답표는
0건이었다. 그래서 이 스크립트는 벡터 검색을 "기본"이 아니라 "어휘 검색이 실패한
claim만을 위한 안전망"으로 좁혀서 쓴다 - 새 인프라를 만들지 않는다.
kosis_match_claims_to_index.py 가 이미 --retrieval-mode hybrid 로 벡터+reranker를
지원하므로, 그걸 그대로 재사용한다.

방법:
  1) 전체 claim을 --retrieval-mode lexical 로 1차 검색
  2) 1위 후보 점수가 --fallback-below-score 미달이거나(또는 candidate_status가
     ALTERNATE/REJECT인) claim만 "실패" 집합으로 뽑음
  3) 그 실패 집합만 --retrieval-mode hybrid 로 재검색 (전체를 다시 돌리지 않음 -
     하이브리드는 임베딩+reranker 로딩이 무거우므로 대상을 최소화하는 게 중요)
  4) 성공(1차) 결과 + 보강(2차) 결과를 합쳐서 하나의 최종 후보 CSV로 저장.
     같은 claim에 대해 2차 결과가 있으면 그걸로 교체, 없으면 1차 결과 유지.

사용법:
  python kosis_lexical_then_vector_fallback.py \
      --claims ready.csv --table-index data/reference/kosis_table_summary.csv \
      --meta-index meta_index.csv --out candidates_final.csv \
      --semantic-index data/indexes/kosis_bge_m3
"""
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


def write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def measurement_key(row):
    return row.get("claim_measurement_id") or row.get("claim_id") or ""


def rank1_by_claim(rows):
    out = {}
    for row in rows:
        if str(row.get("candidate_rank", "")).strip() != "1":
            continue
        out[measurement_key(row)] = row
    return out


def find_lexical_failures(rank1_rows, min_score, weak_statuses):
    failed = set()
    for key, row in rank1_rows.items():
        status = str(row.get("candidate_status", "")).strip()
        try:
            score = float(row.get("candidate_score", "0") or 0)
        except ValueError:
            score = 0.0
        if status in weak_statuses or score < min_score:
            failed.add(key)
    return failed


def write_failed_claims(all_claims, failed_keys, output_path):
    rows = [row for row in all_claims if measurement_key(row) in failed_keys]
    if rows:
        fields = list(rows[0].keys())
    else:
        fields = list(all_claims[0].keys()) if all_claims else []
    write_csv(output_path, rows, fields)
    return len(rows)


def merge_candidates(lexical_rows, fallback_rows, failed_keys):
    """실패했던 claim은 fallback(hybrid) 결과로 통째로 교체, 나머지는 lexical 유지."""
    kept = [row for row in lexical_rows if measurement_key(row) not in failed_keys]
    replaced = [row for row in fallback_rows]
    for row in replaced:
        row["retrieval_backend"] = row.get("retrieval_backend") or "hybrid_fallback"
    return kept + replaced


def run_pipeline(args):
    claims = read_csv(args.claims)
    if not claims:
        raise SystemExit(f"{args.claims} 에 행이 없습니다.")

    lexical_out = Path(args.out).with_suffix(".lexical.csv")
    lexical_command = [
        sys.executable, SCRIPT_DIR / "kosis_match_claims_to_index.py",
        "--claims", args.claims, "--table-index", args.table_index,
        "--meta-index", args.meta_index, "--out", lexical_out,
        "--retrieval-mode", "lexical", "--min-score", args.min_score,
        "--top-tables", args.top_tables,
    ]
    if args.top_meta:
        lexical_command.extend(["--top-meta", args.top_meta])
    if args.table_overrides:
        lexical_command.extend(["--table-overrides", args.table_overrides])
    if args.mapping_overrides:
        lexical_command.extend(["--mapping-overrides", args.mapping_overrides])
    run(lexical_command)

    lexical_rows = read_csv(lexical_out)
    rank1 = rank1_by_claim(lexical_rows)
    weak_statuses = set(args.weak_status)
    failed_keys = find_lexical_failures(rank1, args.fallback_below_score, weak_statuses)

    print(f"\n어휘 검색 1위 확신 부족(안전망 대상): {len(failed_keys)} / {len(rank1)} claim")

    if not failed_keys:
        write_csv(args.out, lexical_rows, list(lexical_rows[0].keys()) if lexical_rows else [])
        print("벡터 검색 안전망 불필요 - 어휘 검색 결과만으로 최종 저장")
        return

    failed_claims_path = Path(args.out).with_suffix(".failed_claims.csv")
    n_failed = write_failed_claims(claims, failed_keys, failed_claims_path)
    print(f"안전망 대상 claim {n_failed}건 -> {failed_claims_path}")

    fallback_out = Path(args.out).with_suffix(".hybrid_fallback.csv")
    hybrid_command = [
        sys.executable, SCRIPT_DIR / "kosis_match_claims_to_index.py",
        "--claims", failed_claims_path, "--table-index", args.table_index,
        "--meta-index", args.meta_index, "--out", fallback_out,
        "--retrieval-mode", "hybrid", "--min-score", args.min_score,
        "--top-tables", args.top_tables,
        "--semantic-index", args.semantic_index,
        "--semantic-top-k", args.semantic_top_k,
        "--rerank-top-k", args.rerank_top_k,
        "--reranker-model", args.reranker_model,
    ]
    if args.top_meta:
        hybrid_command.extend(["--top-meta", args.top_meta])
    if args.device:
        hybrid_command.extend(["--device", args.device])
    if args.table_overrides:
        hybrid_command.extend(["--table-overrides", args.table_overrides])
    if args.mapping_overrides:
        hybrid_command.extend(["--mapping-overrides", args.mapping_overrides])
    run(hybrid_command)

    fallback_rows = read_csv(fallback_out)
    merged = merge_candidates(lexical_rows, fallback_rows, failed_keys)
    fields = list(lexical_rows[0].keys()) if lexical_rows else (list(fallback_rows[0].keys()) if fallback_rows else [])
    for extra in ("retrieval_backend",):
        if extra not in fields:
            fields.append(extra)
    write_csv(args.out, merged, fields)

    fallback_rank1 = rank1_by_claim(fallback_rows)
    rescued = sum(1 for key in failed_keys if key in fallback_rank1
                  and str(fallback_rank1[key].get("candidate_status", "")) not in weak_statuses)
    print(f"\n최종: {args.out}")
    print(f"안전망(hybrid)으로 개선된 claim: {rescued} / {len(failed_keys)}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", required=True)
    parser.add_argument("--table-index", required=True)
    parser.add_argument("--meta-index", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--top-tables", type=int, default=5)
    parser.add_argument("--top-meta", type=int, default=0)
    parser.add_argument("--min-score", type=int, default=10)
    parser.add_argument(
        "--fallback-below-score", type=float, default=15,
        help="1위 후보 점수가 이 값보다 낮으면 벡터 검색 안전망 대상으로 삼음",
    )
    parser.add_argument(
        "--weak-status", action="append", default=["ALTERNATE", "REJECT"],
        help="1위 후보 상태가 이 값들 중 하나면 안전망 대상 (여러 번 지정 가능)",
    )
    parser.add_argument("--table-overrides", default="")
    parser.add_argument("--mapping-overrides", default="")
    parser.add_argument("--semantic-index", default="data/indexes/kosis_bge_m3")
    parser.add_argument("--semantic-top-k", type=int, default=50)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--device", default=None)
    return parser


def main():
    args = build_parser().parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
