#!/usr/bin/env python3
"""상류 표 검색이 1위와 2위를 구분하고 있는가.

배경: '후보 비결정' 24건을 조회해보니 맞는 매핑 3건이 **전부 점수 마진**에 걸려 있었다.
      625/621, 653/647, 546/544 — 모두 1% 미만 차이다.
      그런데 그건 3건짜리 근거다. 표 검색 전반이 그런지는 재본 적이 없다.

이 스크립트가 답하는 것:
  (1) 얇은 마진이 흔한가, 아니면 그 3건이 예외인가
  (2) 얇은 마진이 실제로 나쁜 결과와 이어지는가

(2)가 핵심이다. 마진이 얇아도 1위가 맞는 표라면 문제가 아니다.
'구분을 못 한다'와 '구분할 필요가 없다'는 다르다.

사용법:
  python diagnose_table_margin.py \
    --table-candidates ..._kosis_table_candidates.csv \
    --evaluation-set evaluation_set_v3.csv \
    --coverage coverage_report_v2.csv \
    --output table_margin_diagnosis.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

# recover_downstream_validated._margin_ok 와 같은 기준을 쓴다.
# 진단이 게이트와 다른 잣대를 쓰면 결론이 어긋난다.
MIN_ABSOLUTE = 5.0
MIN_RELATIVE = 0.01


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def number(value):
    try:
        return float(text(value))
    except ValueError:
        return None


def margin_of(row) -> tuple[float | None, float | None]:
    """(절대 차이, 상대 차이). 점수가 없으면 (None, None)."""
    score = number(row.get("candidate_score"))
    runner_up = number(row.get("candidate_runner_up_score"))
    if score is None or runner_up is None:
        return None, None
    absolute = score - runner_up
    return absolute, (absolute / score if score else None)


def is_thin(absolute, score) -> bool:
    """게이트가 '결정적이지 않다'고 보는 기준."""
    if absolute is None or score is None:
        return False
    return absolute < max(MIN_ABSOLUTE, score * MIN_RELATIVE)


def bucket_label(absolute) -> str:
    if absolute is None:
        return "점수 없음"
    for edge, label in ((0.5, "거의 동점 (<0.5)"), (2, "0.5~2"), (5, "2~5"),
                        (20, "5~20"), (100, "20~100")):
        if absolute < edge:
            return label
    return "100 이상"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table-candidates", required=True)
    ap.add_argument("--evaluation-set", required=True)
    ap.add_argument("--coverage", default="")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    keys = {text(r.get("claim_measurement_id")) for r in read_csv_rows(args.evaluation_set)}
    outcome = {text(r.get("claim_measurement_id")): text(r.get("bucket"))
               for r in read_csv_rows(args.coverage)} if args.coverage else {}

    top: dict[str, dict] = {}
    for row in read_csv_rows(args.table_candidates):
        mid = text(row.get("claim_measurement_id"))
        if mid not in keys:
            continue
        rank = number(row.get("candidate_rank")) or 999
        if mid not in top or rank < top[mid]["_rank"]:
            top[mid] = {**row, "_rank": rank}

    rows, spread, thin_count = [], Counter(), 0
    by_outcome: dict[str, list[bool]] = defaultdict(list)
    for mid, row in sorted(top.items()):
        absolute, relative = margin_of(row)
        score = number(row.get("candidate_score"))
        thin = is_thin(absolute, score)
        thin_count += thin
        spread[bucket_label(absolute)] += 1
        bucket = outcome.get(mid, "(미상)")
        by_outcome[bucket].append(thin)
        rows.append({
            "claim_measurement_id": mid,
            "tbl_id": text(row.get("tbl_id")),
            "score": text(row.get("candidate_score")),
            "runner_up": text(row.get("candidate_runner_up_score")),
            "margin": "" if absolute is None else round(absolute, 2),
            "margin_pct": "" if relative is None else round(relative * 100, 2),
            "thin": "Y" if thin else "N",
            "candidate_status": text(row.get("candidate_status")),
            "outcome": bucket,
            "claim_text": text(row.get("claim_text"))[:80],
        })

    total = len(rows)
    print(f"=== 표 후보 1위의 마진 (measurement {total}) ===\n")
    order = ["거의 동점 (<0.5)", "0.5~2", "2~5", "5~20", "20~100", "100 이상", "점수 없음"]
    for label in order:
        n = spread.get(label, 0)
        if n:
            print(f"  {label:<18} {n:>4}  ({n/total:.0%})")
    print(f"\n  게이트가 '결정적이지 않다'고 보는 것: {thin_count}/{total} ({thin_count/total:.0%})")

    if outcome:
        print("\n=== 결과별 얇은 마진 비율 ===")
        print("  (얇은 마진이 나쁜 결과와 이어지는지 — 이게 핵심이다)")
        for bucket, flags in sorted(by_outcome.items(), key=lambda kv: -len(kv[1])):
            share = sum(flags) / len(flags)
            print(f"    {bucket:<28} {sum(flags):>3}/{len(flags):<3} ({share:.0%})")

        confirmed = by_outcome.get("CONFIRMED", [])
        if confirmed:
            confirmed_share = sum(confirmed) / len(confirmed)
            others = [f for b, fs in by_outcome.items() if b != "CONFIRMED" for f in fs]
            other_share = sum(others) / len(others) if others else 0
            print(f"\n  확정된 것의 얇은 마진 {confirmed_share:.0%} vs 나머지 {other_share:.0%}")
            print("  → 차이가 크면 마진이 실제 신호다. 비슷하면 마진은 결과와 무관하고")
            print("     '구분을 못 한다'가 아니라 '구분할 필요가 없다'는 뜻이다.")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
