"""골드 vs 파이프라인 채점기.

make_gold_templates.py로 만든 시트를 사람이 채운 뒤 실행하면 단계별 지표를 출력한다.

사용법:
  python score_gold.py \
    --gold-measurement outputs/gold/gold_measurement.csv \
    --gold-isclaim outputs/gold/gold_is_claim.csv \
    --candidates outputs/runs/hcx_v15_kosis_table_candidates.csv \
    --verified outputs/runs/hcx_v15_kosis_verified.csv
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(2 ** 31 - 1)


def read(path):
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def nz(v):
    s = str(v or "").strip()
    return "" if s in ("", "nan", "None", "-") else s


def pct(a, b):
    return f"{a}/{b} = {a / b:.1%}" if b else f"{a}/0 = n/a"


# ---------- ① is_claim ----------
def score_isclaim(rows):
    labeled = [r for r in rows if nz(r.get("gold_label"))]
    if not labeled:
        print("① is_claim: gold_label 채워진 행 없음"); return
    print(f"\n① is_claim ({len(labeled)}건 라벨됨)")
    for model_col in ("is_claim_007", "is_claim_005"):
        if model_col not in labeled[0]:
            continue
        correct = sum(1 for r in labeled if nz(r[model_col]) == nz(r["gold_label"]))
        print(f"  {model_col} 정확도: {pct(correct, len(labeled))}")


# ---------- ② 게이트 ----------
def score_gate(rows):
    lab = [r for r in rows if nz(r.get("gold_verifiable"))]
    if not lab:
        print("\n② 게이트: gold_verifiable 채워진 행 없음"); return
    ready = [r for r in lab if nz(r.get("in_ready")) == "Y"]
    ver = [r for r in lab if nz(r["gold_verifiable"]).upper() == "Y"]
    tp = sum(1 for r in ready if nz(r["gold_verifiable"]).upper() == "Y")
    print(f"\n② 추출 게이트 ({len(lab)}행 라벨)")
    print(f"  정밀도 P(verifiable | ready): {pct(tp, len(ready))}")
    print(f"  재현율 P(ready | verifiable): {pct(tp, len(ver))}")
    fc = [r for r in ready if nz(r.get("gold_measurement_correct"))]
    if fc:
        ok = sum(1 for r in fc if nz(r["gold_measurement_correct"]).upper() == "Y")
        print(f"  추출 필드 정확도(ready): {pct(ok, len(fc))}")
    # 게이트가 놓친 검증가능값
    missed = [r for r in ver if nz(r.get("in_ready")) != "Y"]
    if missed:
        print(f"  ⚠ 놓친 검증가능값 {len(missed)}건 (게이트가 과도하게 반려):")
        for r in missed[:5]:
            print(f"     {r.get('claim_measurement_id')}: {r.get('measurement_text', '')[:30]}")


# ---------- ③ 검색 recall@k ----------
def retrieval_metrics(gold_rows, cand_rows, ks=(1, 2, 3, 5)):
    gmap = {r["claim_measurement_id"]: nz(r.get("gold_tbl_id"))
            for r in gold_rows if nz(r.get("gold_tbl_id"))}
    rank_of = defaultdict(lambda: 999)
    covered = set()
    for c in cand_rows:
        mid = c.get("claim_measurement_id")
        if mid in gmap:
            covered.add(mid)
        if mid in gmap and nz(c.get("tbl_id")) == gmap[mid]:
            try:
                rank_of[mid] = min(rank_of[mid], int(c.get("candidate_rank", "999")))
            except ValueError:
                pass

    rows = []
    for k in sorted(set(ks)):
        hits = sum(1 for mid in gmap if rank_of[mid] <= k)
        candidate_rows = sum(
            1 for row in cand_rows
            if str(row.get("candidate_rank", "")).isdigit()
            and int(row["candidate_rank"]) <= k
        )
        rows.append({
            "top_k": k,
            "gold_labeled": len(gmap),
            "gold_candidate_covered": len(covered),
            "hits": hits,
            "recall": hits / len(gmap) if gmap else None,
            "covered_recall": hits / len(covered) if covered else None,
            "candidate_rows": candidate_rows,
        })
    return rows


def write_retrieval_metrics(path, rows):
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "top_k", "gold_labeled", "gold_candidate_covered", "hits",
            "recall", "covered_recall", "candidate_rows",
        ])
        writer.writeheader()
        writer.writerows(rows)


def write_candidate_slices(output_dir, cand_rows, ks):
    if not output_dir or not cand_rows:
        return
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(cand_rows[0])
    for k in sorted(set(ks)):
        selected = [
            row for row in cand_rows
            if str(row.get("candidate_rank", "")).isdigit()
            and int(row["candidate_rank"]) <= k
        ]
        with (output_dir / f"kosis_table_candidates_top{k}.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(selected)


def score_retrieval(
    gold_rows,
    cand_rows,
    ks=(1, 2, 3, 5),
    metrics_out="",
    slices_dir="",
):
    gmap = {r["claim_measurement_id"]: nz(r.get("gold_tbl_id"))
            for r in gold_rows if nz(r.get("gold_tbl_id"))}
    if not gmap:
        print("\n③ 검색: gold_tbl_id 채워진 행 없음"); return []
    if not cand_rows:
        print("\n③ 검색: candidate CSV가 없어 채점하지 않음"); return []

    metrics = retrieval_metrics(gold_rows, cand_rows, ks)
    print(f"\n③ 검색 recall@k ({len(gmap)}건 정답표 라벨)")
    for row in metrics:
        print(
            f"  recall@{row['top_k']}: {pct(row['hits'], row['gold_labeled'])}"
            f" | 후보 생성 coverage: {pct(row['gold_candidate_covered'], row['gold_labeled'])}"
            f" | 후보 행: {row['candidate_rows']}"
        )
    write_retrieval_metrics(metrics_out, metrics)
    write_candidate_slices(slices_dir, cand_rows, ks)
    return metrics


# ---------- ④ 판정 ----------
def score_verdict(gold_rows, verified_rows):
    gmap = {r["claim_measurement_id"]: nz(r.get("gold_verdict"))
            for r in gold_rows if nz(r.get("gold_verdict"))}
    if not gmap:
        print("\n④ 판정: gold_verdict 채워진 행 없음"); return
    if not verified_rows:
        print("\n④ 판정: verified CSV가 없어 채점하지 않음"); return
    vmap = {r.get("claim_measurement_id"): nz(r.get("verdict")) for r in verified_rows}
    common = [m for m in gmap if m in vmap]
    correct = sum(1 for m in common if gmap[m] == vmap[m])
    print(f"\n④ 최종 판정 ({len(common)}건 대조)")
    print(f"  verdict 정확도: {pct(correct, len(common))}")
    decisive = [m for m in common if gmap[m] in ("일치", "불일치")]
    dc = sum(1 for m in decisive if gmap[m] == vmap[m])
    print(f"  판정가능 케이스 정확도(판단불가 제외): {pct(dc, len(decisive))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-measurement", default="outputs/gold/gold_measurement.csv")
    ap.add_argument("--gold-isclaim", default="outputs/gold/gold_is_claim.csv")
    ap.add_argument("--candidates", default="")
    ap.add_argument("--verified", default="")
    ap.add_argument("--retrieval-k", type=int, nargs="+", default=[1, 2, 3, 5])
    ap.add_argument("--retrieval-metrics-out", default="")
    ap.add_argument("--retrieval-slices-dir", default="")
    a = ap.parse_args()

    print("=" * 60)
    print("골드 채점 결과")
    print("=" * 60)
    score_isclaim(read(a.gold_isclaim))
    gm = read(a.gold_measurement)
    score_gate(gm)
    score_retrieval(
        gm,
        read(a.candidates),
        ks=a.retrieval_k,
        metrics_out=a.retrieval_metrics_out,
        slices_dir=a.retrieval_slices_dir,
    )
    score_verdict(gm, read(a.verified))
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
