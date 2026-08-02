#!/usr/bin/env python3
"""세부 좌표가 1위로 뽑힐 때, 그 표에 애초에 '총계'가 있었는가를 잰다.

diagnose_obj_selection.py 로 확인된 것:
  대상을 특정하지 않은 주장 46건 중 41건(C)이 세부 분류 좌표를 1위로 받았다.

그 41건은 원인이 둘로 갈리고, 처방이 완전히 다르다.

  (a) 같은 표·같은 축에 집계 코드가 **있는데도** 세부를 골랐다
      → 순위 문제. 집계 우선 규칙을 검색 단계에 넣으면 회수된다.
  (b) 그 표·축에 집계 코드가 **아예 없다**
      → 표 선택 문제. 순위를 고쳐도 안 나온다. 다른 표를 찾아야 한다.

메타에서 실제로 확인된 사례들:
  '722783.2항의 것' — DT_1R11001_FRM101(품목별 수출액,수입액)의 정상 HS 세번.
                      표는 맞고 총액 대신 세부 품목을 고른 것 → (a)
  '잘 모름'/'0%'   — 하도급·대출 설문표의 응답 보기. 거시 주장에 쓰일 수 없다 → (b)
  '매출액별'        — 자식 5개를 가진 계층 부모 노드(축 이름 유출 아님)

사용법:
  python diagnose_coordinate_space.py \
    --meta-index ..._kosis_meta_index.csv \
    --evaluation-set evaluation_set_v2.csv \
    --candidates ..._chroma_candidates.csv --label C \
    --output coordinate_space_diagnosis.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from diagnose_obj_selection import claim_names_a_target, rank_of, text
from kosis_meta_coordinates import read_csv_rows
from kosis_validate_mapping_candidates import AGGREGATE_OBJ_NAMES, _normalize as _norm

# 실패 사례에서 확인된 집계 축 이름을 더한다. 두 모듈에 목록이 갈라져 있어
# (kosis_meta_coordinates.AGGREGATE_NAMES / validate.AGGREGATE_OBJ_NAMES)
# 여기서는 진단 목적으로만 합집합을 쓴다. 통합은 별도 작업.
EXTRA_AGGREGATE = ("총지수", "전산업생산지수")
ALL_AGGREGATE = {_norm(n) for n in (*AGGREGATE_OBJ_NAMES, *EXTRA_AGGREGATE)}


def is_item_row(row) -> bool:
    return text(row.get("is_item")).upper() in {"Y", "TRUE", "1"}


def load_axis_index(meta_rows):
    """(tbl_id, axis_id) -> {codes, aggregate_codes, parent_codes} 로 정리한다."""
    by_axis: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"names": {}, "aggregate": set(), "parents": set()})
    child_count: Counter = Counter()

    rows = [r for r in meta_rows if not is_item_row(r)]
    for row in rows:
        key = (text(row.get("tbl_id")), text(row.get("axis_id")))
        parent = text(row.get("parent_code_id"))
        if parent:
            child_count[(key, parent)] += 1

    for row in rows:
        key = (text(row.get("tbl_id")), text(row.get("axis_id")))
        code = text(row.get("code_id"))
        name = text(row.get("code_name"))
        axis = by_axis[key]
        axis["names"][code] = name
        if _norm(name) in ALL_AGGREGATE:
            axis["aggregate"].add(code)
        if child_count[(key, code)] > 0:
            axis["parents"].add(code)
    return by_axis


def classify(candidate, by_axis) -> tuple[str, str]:
    """rank-1 세부 좌표 한 건을 (원인, 근거) 로 분류한다."""
    tbl = text(candidate.get("tbl_id"))
    axis_id = text(candidate.get("selected_obj_l1_axis_id"))
    axis = by_axis.get((tbl, axis_id))
    if axis is None:
        return "AXIS_NOT_IN_META", "메타에서 축을 못 찾음 (표/축 식별자 불일치)"
    if axis["aggregate"]:
        sample = sorted(axis["names"][c] for c in axis["aggregate"])[:3]
        return "AGGREGATE_AVAILABLE", f"같은 축에 집계 코드 있음: {', '.join(sample)}"
    return "NO_AGGREGATE_IN_AXIS", f"축 '{text(candidate.get('selected_obj_l1_axis_name'))}' 에 집계 코드 없음"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-index", required=True)
    ap.add_argument("--evaluation-set", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--label", default="C")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    by_axis = load_axis_index(read_csv_rows(args.meta_index))
    claims = {text(r.get("claim_measurement_id")): r
              for r in read_csv_rows(args.evaluation_set)}

    top_by_mid: dict[str, dict] = {}
    for row in read_csv_rows(args.candidates):
        mid = text(row.get("claim_measurement_id"))
        if mid not in claims:
            continue
        current = top_by_mid.get(mid)
        if current is None or rank_of(row) < rank_of(current):
            top_by_mid[mid] = row

    causes: Counter = Counter()
    detail: list[dict] = []
    for mid, top in top_by_mid.items():
        claim = claims[mid]
        if claim_names_a_target(claim):
            continue  # 주장이 대상을 특정했으면 세부 분류가 정상이다
        name = text(top.get("selected_obj_l1_name"))
        if not name or _norm(name) in ALL_AGGREGATE:
            causes["ALREADY_AGGREGATE"] += 1
            continue
        cause, why = classify(top, by_axis)
        causes[cause] += 1
        detail.append({
            "label": args.label,
            "claim_measurement_id": mid,
            "cause": cause,
            "why": why,
            "tbl_id": text(top.get("tbl_id")),
            "tbl_name": text(top.get("tbl_name"))[:60],
            "obj_l1_name": name,
            "axis_name": text(top.get("selected_obj_l1_axis_name")),
            "claim_text": text(claim.get("claim_text"))[:100],
        })

    total = sum(causes.values())
    print(f"=== [{args.label}] 대상 미특정 주장의 rank-1 좌표 {total}건 ===\n")
    labels = {
        "ALREADY_AGGREGATE": "이미 집계 좌표 (문제 없음)",
        "AGGREGATE_AVAILABLE": "집계가 있는데 세부를 고름 → 순위 문제",
        "NO_AGGREGATE_IN_AXIS": "축에 집계가 없음 → 표 선택 문제",
        "AXIS_NOT_IN_META": "축을 메타에서 못 찾음 → 식별자 문제",
    }
    for cause, n in causes.most_common():
        share = n / total if total else 0
        print(f"  {labels.get(cause, cause):<36} {n:>4}  ({share:.0%})")

    fixable = causes["AGGREGATE_AVAILABLE"]
    other = causes["NO_AGGREGATE_IN_AXIS"] + causes["AXIS_NOT_IN_META"]
    print("\n판단:")
    if fixable > other:
        print(f"  집계가 있는데 놓친 게 {fixable}건 > 표/식별자 문제 {other}건")
        print("  → 검색 단계 집계 우선 규칙이 실제로 겨냥할 대상이 있다")
    elif other > fixable:
        print(f"  표/식별자 문제 {other}건 > 순위 문제 {fixable}건")
        print("  → 순위를 고쳐도 대부분 안 나온다. 표 선택으로 방향을 틀 것")
    else:
        print("  두 원인이 비슷하다. 둘 다 손봐야 한다")

    if detail:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
            writer.writeheader()
            writer.writerows(detail)
        print(f"\n저장: {args.output}")

        print("\n--- 축에 집계가 없는 표 (표 선택이 잘못됐을 가능성) ---")
        bad = Counter(d["tbl_name"] for d in detail
                      if d["cause"] == "NO_AGGREGATE_IN_AXIS")
        for tbl, n in bad.most_common(12):
            print(f"    {n:>3}  {tbl}")


if __name__ == "__main__":
    main()
