#!/usr/bin/env python3
"""단계별 검색 성능을 잰다 (2026-08-04).

## 왜 필요한가

**구조는 단계별인데 평가가 단계별이 아니었다.** 최종 확정률만 보고 있었다.
그래서 병목이 좌표 선택이라는 것을 홀드아웃 세 묶음을 돌리고서야 알았다.

**표 후보에 정답이 없으면 재랭커를 아무리 잘 만들어도 못 맞힌다.**
그러므로 순서는 이렇다:

    표 Recall@K  →  표 TOP1  →  ITEM  →  OBJ  →  전체 좌표

앞 단계가 낮으면 뒤를 고쳐도 소용없다. 어디를 고칠지는 이 숫자가 정한다.

## 골드가 복수 정답을 가질 수 있다

같은 통계가 여러 표에 수록된 경우 `gold_tbl_id` 가 `A|B` 형태다.
하나라도 맞으면 정답으로 센다.

## **경고 — 지금 골드로는 Recall 을 잴 수 없다**

`gold_confirmed_v3.csv` 는 `build_gold_from_evidence` 가 만들었고,
그것은 **우리 파이프라인 후보 중 값이 재현되는 좌표**를 골드로 삼는다.
그러므로 "골드 표가 후보 안에 있는가"는 **동어반복이다.**

실측: Recall@3 = 100%. 이 숫자는 검색 성능이 아니라 골드 생성 방식을 반영한다.
2026-08-04 아침에 '확정된 것의 얇은 마진 0%' 로 같은 실수를 했다.

**Recall 을 재려면 후보와 무관하게 만든 골드가 필요하다.**
KOSIS 공식 통합검색이나 사람이 고른 정답 표로 라벨해야 한다.
그때까지 이 스크립트의 ① 은 **TOP1 만** 의미가 있다
(후보 안에서 1위를 맞히는가 — 이건 순환이 아니다).

## 표본이 작다

골드 12건이다. **1건이 8.3%p 다.** 숫자를 소수점까지 믿지 말 것.
방향(어느 단계가 확연히 낮은가)만 읽는다.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def nz(value) -> str:
    return str(value or "").strip()


def gold_set(value) -> set[str]:
    """'A|B' 를 {A, B} 로. 빈 값은 빈 집합(=채점 제외)."""
    return {part.strip() for part in nz(value).split("|") if part.strip()}


def rank_of(row) -> int:
    for key in ("candidate_rank", "table_rank", "rank", "retrieval_rank"):
        raw = nz(row.get(key))
        if raw.isdigit():
            return int(raw)
    return 10**6


def by_measurement(rows) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = nz(row.get("claim_measurement_id"))
        if key:
            grouped.setdefault(key, []).append(row)
    for items in grouped.values():
        items.sort(key=rank_of)
    return grouped


def pct(hit: int, total: int) -> str:
    return f"{hit}/{total} = {hit / total * 100:.1f}%" if total else f"{hit}/0 = -"


def evaluate(gold_rows, table_rows, coord_rows, ks) -> None:
    tables = by_measurement(table_rows)
    coords = by_measurement(coord_rows) if coord_rows else {}

    print(f"=== 골드 {len(gold_rows)}건 ===\n")

    # ------------------------------------------------------------------
    # 1. 표 후보에 정답이 들어 있는가
    # ------------------------------------------------------------------
    print("① 표 검색 — 정답 표가 후보 안에 있는가")
    scored = [row for row in gold_rows if gold_set(row.get("gold_tbl_id"))]
    for k in ks:
        hit = 0
        for row in scored:
            want = gold_set(row.get("gold_tbl_id"))
            got = {nz(c.get("tbl_id")) for c in
                   tables.get(nz(row.get("claim_measurement_id")), [])[:k]}
            hit += bool(want & got)
        print(f"   Recall@{k:<3} {pct(hit, len(scored))}")

    top1 = 0
    for row in scored:
        candidates = tables.get(nz(row.get("claim_measurement_id")), [])
        if candidates and nz(candidates[0].get("tbl_id")) in gold_set(row.get("gold_tbl_id")):
            top1 += 1
    print(f"   TOP1      {pct(top1, len(scored))}")
    print("   [경고] 골드가 파이프라인 후보에서 만들어졌다면 Recall 은 동어반복이다.")
    print("          독립 골드가 생기기 전까지는 TOP1 만 읽을 것.\n")

    if not coords:
        print("② 좌표 — 좌표 후보 파일(--coordinates)이 없어 건너뛴다.")
        return

    # ------------------------------------------------------------------
    # 2. 표를 맞힌 건에서 좌표를 맞히는가
    # ------------------------------------------------------------------
    print("② 좌표 — 표가 맞은 건에서만 잰다 (표를 틀리면 좌표는 볼 것도 없다)")
    axes = [("ITEM", "gold_itm_id", "selected_itm_id"),
            ("OBJ_L1", "gold_obj_l1", "selected_obj_l1"),
            ("OBJ_L2", "gold_obj_l2", "selected_obj_l2")]
    denom = 0
    axis_hit = {name: 0 for name, _, _ in axes}
    axis_den = {name: 0 for name, _, _ in axes}
    whole = 0
    for row in scored:
        mid = nz(row.get("claim_measurement_id"))
        chosen = next((c for c in coords.get(mid, [])
                       if nz(c.get("tbl_id")) in gold_set(row.get("gold_tbl_id"))), None)
        if chosen is None:
            continue
        denom += 1
        ok_all = True
        for name, gold_col, sel_col in axes:
            want = gold_set(row.get(gold_col))
            if not want:
                continue          # 그 축이 없는 표다. 채점하지 않는다
            axis_den[name] += 1
            if nz(chosen.get(sel_col)) in want:
                axis_hit[name] += 1
            else:
                ok_all = False
        whole += ok_all
    print(f"   표를 맞힌 건 {denom}")
    for name, _, _ in axes:
        print(f"   {name:<7} {pct(axis_hit[name], axis_den[name])}")
    print(f"   전체 좌표 {pct(whole, denom)}")
    print("\n   → ITEM 이 낮으면 항목 매칭을, OBJ 가 낮으면 분류축 매칭을 고친다.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--table-candidates", required=True, type=Path)
    parser.add_argument("--coordinates", type=Path,
                        help="chroma_validated.csv 등 좌표가 선택된 산출물")
    parser.add_argument("--k", default="1,3,5,10,20")
    args = parser.parse_args()

    ks = [int(part) for part in args.k.split(",") if part.strip().isdigit()]
    evaluate(read(args.gold), read(args.table_candidates),
             read(args.coordinates) if args.coordinates else None, ks)


if __name__ == "__main__":
    main()
