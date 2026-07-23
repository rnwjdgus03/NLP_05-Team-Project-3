"""Run one retrieval mode and compare Mapping-end at Top-1/2/3/5.

The expensive table retrieval and row-level KOSIS combination validation are
performed once at max(K). Each Top-K branch then reapplies the cross-table
ambiguity rule and verifies only mappings that remain READY.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

from kosis_validate_mapping_candidates import resolve_table_ambiguity
from score_gold import nz, retrieval_metrics


ROOT = Path(__file__).resolve().parent


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(command: list[object]) -> None:
    rendered = [str(value) for value in command]
    print("+ " + " ".join(rendered), flush=True)
    subprocess.run(rendered, check=True)


def candidate_rank(row: dict[str, str]) -> int:
    try:
        return int(row.get("candidate_rank", "999"))
    except (TypeError, ValueError):
        return 999


def gold_map(gold_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        nz(row.get("claim_measurement_id")): row
        for row in gold_rows
        if nz(row.get("claim_measurement_id"))
    }


def accuracy(rows, gold, predicted_key, gold_key):
    comparable = [
        row for row in rows
        if nz(gold.get(nz(row.get("claim_measurement_id")), {}).get(gold_key))
    ]
    correct = sum(
        nz(row.get(predicted_key))
        == nz(gold[nz(row.get("claim_measurement_id"))].get(gold_key))
        for row in comparable
    )
    return correct, len(comparable)


def summarize(
    k: int,
    gold_rows: list[dict[str, str]],
    candidates: list[dict[str, str]],
    validated: list[dict[str, str]],
    verified: list[dict[str, str]],
) -> dict[str, object]:
    retrieval = retrieval_metrics(gold_rows, candidates, ks=(k,))[0]
    gold = gold_map(gold_rows)
    ready = [row for row in validated if row.get("mapping_status") == "READY"]
    technical_valid = [
        row for row in validated
        if str(row.get("response_code_valid", "")).lower() == "true"
        and str(row.get("unit_valid", "")).lower() == "true"
        and str(row.get("period_valid", "")).lower() == "true"
    ]
    statuses = Counter(row.get("mapping_status") or "EMPTY" for row in validated)
    reasons = Counter(row.get("mapping_reason") or "EMPTY" for row in validated)
    item_ok, item_n = accuracy(ready, gold, "selected_itm_id", "gold_itm_id")
    obj_ok, obj_n = accuracy(ready, gold, "selected_obj_l1", "gold_obj_l1")
    joint_rows = [
        row for row in ready
        if nz(gold.get(nz(row.get("claim_measurement_id")), {}).get("gold_itm_id"))
        and nz(gold.get(nz(row.get("claim_measurement_id")), {}).get("gold_obj_l1"))
    ]
    joint_ok = sum(
        nz(row.get("selected_itm_id"))
        == nz(gold[nz(row.get("claim_measurement_id"))].get("gold_itm_id"))
        and nz(row.get("selected_obj_l1"))
        == nz(gold[nz(row.get("claim_measurement_id"))].get("gold_obj_l1"))
        for row in joint_rows
    )
    joint_gold = {
        measurement_id: row for measurement_id, row in gold.items()
        if nz(row.get("gold_itm_id")) and nz(row.get("gold_obj_l1"))
    }
    technical_joint_hits = sum(
        any(
            nz(candidate.get("claim_measurement_id")) == measurement_id
            and nz(candidate.get("selected_itm_id")) == nz(gold_row.get("gold_itm_id"))
            and nz(candidate.get("selected_obj_l1")) == nz(gold_row.get("gold_obj_l1"))
            for candidate in technical_valid
        )
        for measurement_id, gold_row in joint_gold.items()
    )
    verdict_rows = [
        row for row in verified
        if nz(gold.get(nz(row.get("claim_measurement_id")), {}).get("gold_verdict"))
    ]
    verdict_ok = sum(
        nz(row.get("verdict"))
        == nz(gold[nz(row.get("claim_measurement_id"))].get("gold_verdict"))
        for row in verdict_rows
    )
    return {
        "top_k": k,
        "candidate_rows": len(candidates),
        "retrieval_hits": retrieval["hits"],
        "retrieval_gold": retrieval["gold_labeled"],
        "retrieval_recall": retrieval["recall"],
        "retrieval_coverage": (
            retrieval["gold_candidate_covered"] / retrieval["gold_labeled"]
            if retrieval["gold_labeled"] else ""
        ),
        "ready_rows": len(ready),
        "technical_valid_rows": len(technical_valid),
        "needs_confirmation_rows": statuses["NEEDS_CONFIRMATION"],
        "api_error_rows": statuses["API_ERROR"],
        "not_evaluated_rows": statuses["NOT_EVALUATED"],
        "top_mapping_reasons": " | ".join(
            f"{reason}:{count}" for reason, count in reasons.most_common(5)
        ),
        "item_correct": item_ok,
        "item_labeled": item_n,
        "obj_correct": obj_ok,
        "obj_labeled": obj_n,
        "item_obj_correct": joint_ok,
        "item_obj_labeled": len(joint_rows),
        "technical_item_obj_hits": technical_joint_hits,
        "technical_item_obj_gold": len(joint_gold),
        "verified_rows": len(verified),
        "verdict_correct": verdict_ok,
        "verdict_labeled": len(verdict_rows),
    }


def write_report(
    path: Path,
    summary: list[dict[str, object]],
    retrieval_knee: int,
    recommended: int | None,
    retrieval_mode: str = "hybrid",
) -> None:
    title = "BGE-M3 hybrid" if retrieval_mode == "hybrid" else "lexical"
    lines = [
        f"# KOSIS {title} Top-K 정식 비교",
        "",
        "| K | TBL recall | 후보 row | 기술 유효 | READY | 기술 ITEM/OBJ hit | READY ITEM/OBJ 정답 | verdict 정답 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['top_k']} | {row['retrieval_hits']}/{row['retrieval_gold']} "
            f"({float(row['retrieval_recall']):.1%}) | {row['candidate_rows']} | "
            f"{row['technical_valid_rows']} | {row['ready_rows']} | "
            f"{row['technical_item_obj_hits']}/{row['technical_item_obj_gold']} | "
            f"{row['item_obj_correct']}/{row['item_obj_labeled']} | "
            f"{row['verdict_correct']}/{row['verdict_labeled']} |"
        )
    recommendation = f"Top-{recommended}" if recommended is not None else "보류(READY 0)"
    lines.extend([
        "",
        f"검색 기준 최소 최적값: **Top-{retrieval_knee}**",
        f"최종 권장 설정: **{recommendation}**",
        "",
        "선정 규칙은 최고 TBL recall을 달성한 설정 중 가장 작은 K이다. "
        "ITEM/OBJ와 verdict 지표는 정확도 저하 여부를 확인하는 안전장치로 함께 본다.",
        "READY가 0이면 검색 설정만 판단하고 최종 설정은 보류한다.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="READY 39 measurement CSV")
    parser.add_argument("--gold", required=True, help="locked gold measurement CSV")
    parser.add_argument("--table-index", required=True)
    parser.add_argument("--retrieval-mode", choices=["lexical", "hybrid"], default="hybrid")
    parser.add_argument("--semantic-index", default="")
    parser.add_argument("--out-dir", default="outputs/runs/bge_topk_sweep")
    parser.add_argument("--ks", type=int, nargs="+", default=[1, 2, 3, 5])
    parser.add_argument("--semantic-top-k", type=int, default=50)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--item-top-k", type=int, default=3)
    parser.add_argument("--obj-top-k", type=int, default=2)
    parser.add_argument("--max-combinations", type=int, default=20)
    parser.add_argument("--reuse-base", action="store_true")
    parser.add_argument(
        "--reuse-validation",
        action="store_true",
        help="기존 기술 검증 CSV까지 재사용; 기본은 검색만 재사용하고 매핑/API는 재검증",
    )
    args = parser.parse_args()

    if args.retrieval_mode == "hybrid" and not args.semantic_index:
        parser.error("--semantic-index is required when --retrieval-mode=hybrid")

    ks = sorted(set(args.ks))
    if not ks or ks[0] < 1:
        parser.error("--ks에는 1 이상의 정수가 필요합니다")
    input_path = Path(args.input).resolve()
    gold_path = Path(args.gold).resolve()
    out_dir = Path(args.out_dir).resolve()
    base_dir = out_dir / f"base_top{max(ks)}"
    stem = input_path.stem
    max_k = max(ks)

    base_candidates = base_dir / f"{stem}_kosis_candidates_with_meta.csv"
    meta_index = base_dir / f"{stem}_kosis_meta_index.csv"
    if not args.reuse_base:
        pipeline_command = [
            sys.executable, ROOT / "run_kosis_measurement_pipeline.py",
            "--input", input_path,
            "--table-index", Path(args.table_index).resolve(),
            "--out-dir", base_dir,
            "--top-tables", max_k,
            "--top-rank-for-meta", max_k,
            "--retrieval-mode", args.retrieval_mode,
            "--delay", args.delay,
        ]
        if args.retrieval_mode == "hybrid":
            pipeline_command.extend([
                "--semantic-index", Path(args.semantic_index).resolve(),
                "--semantic-top-k", args.semantic_top_k,
                "--rerank-top-k", args.rerank_top_k,
                "--device", args.device,
            ])
        run(pipeline_command)
    for required in (base_candidates, meta_index):
        if not required.exists():
            raise FileNotFoundError(f"필수 base 산출물이 없습니다: {required}")

    all_candidates = read_csv(base_candidates)
    technical_path = out_dir / f"{stem}_top{max_k}_technical_validated.csv"
    if not args.reuse_validation or not technical_path.exists():
        run([
            sys.executable, ROOT / "kosis_validate_mapping_candidates.py",
            "--input", base_candidates,
            "--meta-index", meta_index,
            "--output", technical_path,
            "--item-top-k", args.item_top_k,
            "--obj-top-k", args.obj_top_k,
            "--max-combinations", args.max_combinations,
            "--skip-table-ambiguity",
            "--evaluate-all-ranks",
        ])
    technical = read_csv(technical_path)
    gold_rows = read_csv(gold_path)
    summary = []

    for k in ks:
        branch = out_dir / f"top{k}"
        candidates = [row for row in all_candidates if candidate_rank(row) <= k]
        validated = resolve_table_ambiguity(
            [row for row in technical if candidate_rank(row) <= k]
        )
        candidate_path = branch / f"{stem}_top{k}_candidates.csv"
        validated_path = branch / f"{stem}_top{k}_validated.csv"
        verified_path = branch / f"{stem}_top{k}_verified.csv"
        write_csv(candidate_path, candidates)
        write_csv(validated_path, validated)
        run([
            sys.executable, ROOT / "kosis_verify_claim_values.py",
            "--input", validated_path,
            "--output", verified_path,
            "--delay", args.delay,
        ])
        verified = read_csv(verified_path)
        row = summarize(k, gold_rows, candidates, validated, verified)
        row = {"retrieval_mode": args.retrieval_mode, **row}
        summary.append(row)

    max_hits = max(row["retrieval_hits"] for row in summary)
    retrieval_knee = min(
        int(row["top_k"]) for row in summary if row["retrieval_hits"] == max_hits
    )
    viable = [row for row in summary if int(row["ready_rows"]) > 0]
    if viable:
        viable_max_hits = max(row["retrieval_hits"] for row in viable)
        recommended = min(
            int(row["top_k"])
            for row in viable
            if row["retrieval_hits"] == viable_max_hits
        )
    else:
        recommended = None
    write_csv(out_dir / "topk_summary.csv", summary)
    write_report(
        out_dir / "topk_report.md", summary, retrieval_knee, recommended,
        retrieval_mode=args.retrieval_mode,
    )
    print(f"summary={out_dir / 'topk_summary.csv'}")
    print(f"report={out_dir / 'topk_report.md'}")
    print(f"retrieval_knee_top_k={retrieval_knee}")
    print(f"recommended_top_k={recommended if recommended is not None else 'PENDING'}")


if __name__ == "__main__":
    main()
