#!/usr/bin/env python3
"""KOSIS 공식 통합검색으로 **독립** 표 후보를 만든다 (2026-08-04).

## 왜 필요한가

지금 골드(`gold_confirmed_v3`)는 `build_gold_from_evidence` 가 만들었고,
그것은 **우리 파이프라인 후보 중 값이 재현되는 좌표**를 골드로 삼는다.
그래서 "골드 표가 우리 후보 안에 있는가"는 동어반복이다 — 실측 Recall@3 = 100%.

**우리가 놓친 표는 애초에 골드에 없다. 놓친 것을 못 세는 골드로는 Recall 을 못 잰다.**

그래서 우리 임베딩·BM25 와 **무관한 출처**가 필요하다.
KOSIS 공식 통합검색(`statisticsSearch.do`)이 그 출처다.
여기서 나온 표를 우리 후보와 섞어 사람이 정답을 고르면, 비로소 독립 골드가 된다.

## 질의를 어떻게 만드는가

지표 하나만 던지지 않는다. 팀원 제안대로 **지표 + 대상**을 함께 쓴다.
다만 KOSIS 검색은 긴 질의에 약할 수 있으므로 **둘 다 던지고 합집합**을 만든다.

    q1 = 지표                    '수출액'
    q2 = 지표 + 대상             '수출액 반도체'

어느 질의가 나았는지 `query` 컬럼에 남긴다. 나중에 질의 설계를 고칠 근거가 된다.

## 주의

- **API 키를 로그에 남기지 않는다.** requests 는 예외 메시지에 전체 URL 을 넣는다.
  오늘 그것 때문에 키가 트레이스백에 찍혔다. 여기서는 예외를 잡아 이름만 남긴다.
- `--resume` 로 이어받는다. 중간에 끊겨도 처음부터 다시 하지 않는다.
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

from kosis_api_test import search_tables  # noqa: E402

FIELDS = ["claim_measurement_id", "indicator", "industry_or_item", "claim_text",
          "query", "query_kind", "search_rank", "org_id", "tbl_id", "tbl_name",
          "stat_name", "period_start", "period_end", "source"]


def nz(value) -> str:
    return str(value or "").strip()


def pick(row, *keys) -> str:
    for key in keys:
        value = nz(row.get(key))
        if value:
            return value
    return ""


def queries_for(claim) -> list[tuple[str, str]]:
    """(질의, 종류) 목록. 빈 질의는 만들지 않는다."""
    indicator = nz(claim.get("indicator")) or nz(claim.get("measurement_indicator"))
    item = nz(claim.get("industry_or_item")) or nz(claim.get("measurement_item"))
    out: list[tuple[str, str]] = []
    if indicator:
        out.append((indicator, "indicator"))
        if item and item not in indicator:
            out.append((f"{indicator} {item}", "indicator+item"))
    elif item:
        out.append((item, "item"))
    return out


def convert(claim, query, kind, rows, limit) -> list[dict]:
    out = []
    for rank, row in enumerate(rows[:limit], start=1):
        out.append({
            "claim_measurement_id": nz(claim.get("claim_measurement_id")),
            "indicator": nz(claim.get("indicator")),
            "industry_or_item": nz(claim.get("industry_or_item")),
            "claim_text": nz(claim.get("claim_text"))[:200],
            "query": query,
            "query_kind": kind,
            "search_rank": rank,
            "org_id": pick(row, "ORG_ID", "orgId", "org_id"),
            "tbl_id": pick(row, "TBL_ID", "tblId", "tbl_id"),
            "tbl_name": pick(row, "TBL_NM", "TBL_NM_KOR", "tblNm", "tbl_name"),
            "stat_name": pick(row, "STAT_NM", "statNm", "STAT_NM_KOR"),
            "period_start": pick(row, "PRD_DE_STRT", "STRT_PRD_DE", "prdDeStrt"),
            "period_end": pick(row, "PRD_DE_END", "END_PRD_DE", "prdDeEnd"),
            "source": "official_search",
        })
    return out


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {nz(row.get("claim_measurement_id")) for row in csv.DictReader(handle)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path,
                        help="evaluation_set.csv 등 measurement 단위 CSV")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-query", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    with args.claims.open(encoding="utf-8-sig", newline="") as handle:
        claims = list(csv.DictReader(handle))
    seen_measurement: set[str] = set()
    unique = []
    for claim in claims:
        key = nz(claim.get("claim_measurement_id"))
        if key and key not in seen_measurement:
            seen_measurement.add(key)
            unique.append(claim)

    done = load_done(args.output) if args.resume else set()
    todo = [c for c in unique if nz(c.get("claim_measurement_id")) not in done]
    if args.limit:
        todo = todo[:args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_header = not (args.resume and args.output.exists())
    handle = args.output.open("w" if write_header else "a",
                              encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
    if write_header:
        writer.writeheader()

    total_rows = 0
    failed = 0
    with handle:
        for index, claim in enumerate(todo, start=1):
            rows_for_claim: list[dict] = []
            seen_tbl: set[str] = set()
            for query, kind in queries_for(claim):
                try:
                    hits = search_tables(query, per_page=args.per_query)
                except Exception as exc:      # 키가 URL 에 있으므로 예외 본문을 찍지 않는다
                    failed += 1
                    print(f"\nFAIL {nz(claim.get('claim_measurement_id'))} "
                          f"query={query!r}: {type(exc).__name__}", flush=True)
                    hits = []
                for row in convert(claim, query, kind, hits, args.per_query):
                    if row["tbl_id"] and row["tbl_id"] in seen_tbl:
                        continue          # 두 질의가 같은 표를 주면 한 번만 남긴다
                    seen_tbl.add(row["tbl_id"])
                    rows_for_claim.append(row)
                time.sleep(args.delay)
            writer.writerows(rows_for_claim)
            total_rows += len(rows_for_claim)
            print(f"\r{index}/{len(todo)} rows={total_rows} fail={failed} "
                  f"{nz(claim.get('indicator'))[:24]}", end="", flush=True)

    print()
    print(f"saved={args.output} measurements={len(todo)} rows={total_rows} failed={failed}")
    print("이 후보는 **우리 임베딩과 무관한 출처**다. 라벨링 문제지에 우리 후보와 섞어 쓸 것.")


if __name__ == "__main__":
    main()
