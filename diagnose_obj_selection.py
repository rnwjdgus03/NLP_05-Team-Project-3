#!/usr/bin/env python3
"""OBJ(분류축) 선택이 왜 틀리는지 재고, 고쳤을 때의 이득을 **미리 시뮬레이션**한다.

배경: 골드 12건에서 obj@1 이 A 58.3% / C 50.0% 로 가장 약하다. 표(83.3%)·항목(91.7%)은
잘 찾는데 분류축에서 무너진다. NEAR_MISS 30건 중 약 24건도 좌표 문제였다.

가설: 우리는 "주장이 세부 대상을 말하지 않으면 좌표도 집계값이어야 한다"는 규칙을
      `claim_item_matches_selection` 에 넣어뒀지만, 그건 **READY 확정 게이트에만** 쓰이고
      **후보 순위에는 전혀 반영되지 않는다.** 그래서 검색은 여전히 세부 분류를 1위로 올린다.

이 스크립트는 고치기 전에 두 가지를 잰다.
  1) 현재 rank-1 후보가 '주장은 총계인데 좌표는 세부분류' 인 경우가 얼마나 되는가
  2) 집계 우선 재정렬을 적용하면 골드 기준 obj@1 이 실제로 오르는가 (시뮬레이션)

사용법:
  python diagnose_obj_selection.py \
    --evaluation-set evaluation_set_v2.csv \
    --gold gold_confirmed_v1.csv \
    --candidates-a ..._candidates_with_meta.csv \
    --candidates-c ..._chroma_candidates.csv \
    --output obj_selection_diagnosis.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows
from kosis_validate_mapping_candidates import (
    AGGREGATE_ITEM_TOKENS,
    AGGREGATE_OBJ_NAMES,
    _normalize as _norm_name,
    selection_is_aggregate,
)

OBJ_FIELD = "selected_obj_l1"


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def rank_of(row) -> int:
    try:
        return int(float(text(row.get("candidate_rank")) or "999"))
    except ValueError:
        return 999


def claim_names_a_target(row) -> bool:
    """주장이 세부 대상(품목·업종 등)을 특정했는가."""
    item = text(row.get("industry_or_item")) or text(row.get("measurement_item"))
    return bool(item) and item not in AGGREGATE_ITEM_TOKENS


def gold_values(gold_row) -> set[str]:
    """골드는 파이프로 복수 정답을 담을 수 있다."""
    return {p.strip() for p in text(gold_row.get("gold_obj_l1")).split("|") if p.strip()}


def aggregate_first(candidates, prefer_aggregate: bool):
    """집계 우선 재정렬. 점수는 건드리지 않고 정렬 키의 1순위로만 쓴다.

    (리랭커 로짓은 음수가 될 수 있어 곱셈 감점은 위험하다 — prd_se 강등과 같은 방식.)
    """
    if not prefer_aggregate:
        return sorted(candidates, key=rank_of)
    return sorted(candidates,
                  key=lambda c: (0 if selection_is_aggregate(None, c) else 1, rank_of(c)))


def evaluate_side(label, candidates_by_mid, claims, gold) -> tuple[dict, list[dict]]:
    before = after = 0
    changed: list[dict] = []
    labeled = 0

    for mid, gold_row in gold.items():
        wanted = gold_values(gold_row)
        if not wanted:
            continue
        rows = candidates_by_mid.get(mid) or []
        if not rows:
            continue
        labeled += 1
        claim = claims.get(mid, {})
        prefer = not claim_names_a_target(claim)

        top_now = aggregate_first(rows, prefer_aggregate=False)[0]
        top_fix = aggregate_first(rows, prefer_aggregate=prefer)[0]
        hit_now = text(top_now.get(OBJ_FIELD)) in wanted
        hit_fix = text(top_fix.get(OBJ_FIELD)) in wanted
        before += int(hit_now)
        after += int(hit_fix)

        if hit_now != hit_fix:
            changed.append({
                "side": label,
                "claim_measurement_id": mid,
                "direction": "개선" if hit_fix else "악화",
                "claim_names_target": "Y" if claim_names_a_target(claim) else "N",
                "gold_obj_l1": "|".join(sorted(wanted)),
                "obj_now": text(top_now.get(OBJ_FIELD)),
                "obj_now_name": text(top_now.get("selected_obj_l1_name")),
                "obj_fixed": text(top_fix.get(OBJ_FIELD)),
                "obj_fixed_name": text(top_fix.get("selected_obj_l1_name")),
                "claim_text": text(claim.get("claim_text"))[:100],
            })

    summary = {
        "side": label,
        "labeled": labeled,
        "obj@1_now": round(before / labeled, 4) if labeled else None,
        "obj@1_aggregate_first": round(after / labeled, 4) if labeled else None,
        "improved": sum(1 for c in changed if c["direction"] == "개선"),
        "worsened": sum(1 for c in changed if c["direction"] == "악화"),
    }
    return summary, changed


def scan_rank1_shape(candidates_by_mid, claims) -> Counter:
    """골드와 무관하게, rank-1 후보의 '주장 대상 × 좌표 집계여부' 분포를 센다."""
    shape = Counter()
    for mid, rows in candidates_by_mid.items():
        top = min(rows, key=rank_of) if rows else None
        if top is None:
            continue
        named = claim_names_a_target(claims.get(mid, {}))
        agg = selection_is_aggregate(None, top)
        key = ("주장:세부" if named else "주장:총계") + " / " + ("좌표:집계" if agg else "좌표:세부")
        shape[key] += 1
    return shape


def blocking_axis_name(row) -> tuple[int, str] | None:
    """이 후보를 '집계 아님'으로 만든 **첫 번째** 축의 (레벨, 이름).

    selection_is_aggregate 는 L1~L3 이 **전부** 집계일 때만 True 다.
    그래서 L1='전체' 여도 L2='1차금속 제조업' 이면 집계가 아니다.
    범인을 정확히 지목해야 이름 목록을 넓힐지 판단할 수 있다.
    """
    allowed = {_norm_name(t) for t in AGGREGATE_OBJ_NAMES}
    for level in (1, 2, 3):
        name = text(row.get(f"selected_obj_l{level}_name"))
        if name and _norm_name(name) not in allowed:
            return level, name
    return None


def unrecognised_obj_names(candidates_by_mid, claims, limit=25) -> list[tuple[str, int]]:
    """집계 판정을 막은 축 이름을 '레벨과 함께' 빈도순으로 센다.

    AGGREGATE_OBJ_NAMES 가 좁으면 집계 우선 규칙 자체가 작동하지 않는다.
    실제로 '총지수'(소비자물가 집계축), '전산업생산지수'(전산업 접두)는 목록에 없다.
    이름을 넓힐지는 이 분포를 보고 정한다 — 추측으로 넓히지 않는다.
    """
    names: Counter = Counter()
    for mid, rows in candidates_by_mid.items():
        if claim_names_a_target(claims.get(mid, {})):
            continue  # 주장이 대상을 특정했으면 세부 분류가 정상이다
        for row in rows:
            blocker = blocking_axis_name(row)
            if blocker:
                names[f"L{blocker[0]} {blocker[1]}"] += 1
    return names.most_common(limit)


def group(rows, keys):
    grouped = defaultdict(list)
    for row in rows:
        mid = text(row.get("claim_measurement_id"))
        if mid in keys:
            grouped[mid].append(row)
    return grouped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluation-set", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--candidates-a", required=True)
    ap.add_argument("--candidates-c", default="")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    claims = {text(r.get("claim_measurement_id")): r
              for r in read_csv_rows(args.evaluation_set)}
    gold = {text(r.get("claim_measurement_id")): r for r in read_csv_rows(args.gold)}
    keys = set(claims)

    sides = [("A", group(read_csv_rows(args.candidates_a), keys))]
    if args.candidates_c:
        sides.append(("C", group(read_csv_rows(args.candidates_c), keys)))

    print("=== rank-1 후보의 모양 (골드 무관, 전체 집합) ===")
    print("  '주장:총계 / 좌표:세부' 가 많으면 집계 우선 규칙이 먹힐 여지가 크다\n")
    for label, by_mid in sides:
        print(f"[{label}] measurement {len(by_mid)}")
        for key, n in scan_rank1_shape(by_mid, claims).most_common():
            print(f"    {key:<24} {n:>4}")

    print("\n=== 집계로 인정 못 받은 OBJ 이름 (주장이 대상을 특정하지 않은 건만) ===")
    print("  집계축인데 목록에 없는 이름이 상위에 보이면 AGGREGATE_OBJ_NAMES 를 넓혀야 한다")
    print("  (예: '총지수' 는 소비자물가 집계축인데 현재 목록에 없다)\n")
    for label, by_mid in sides:
        print(f"[{label}]")
        for name, n in unrecognised_obj_names(by_mid, claims):
            print(f"    {name[:30]:<32} {n:>4}")

    all_changed: list[dict] = []
    print("\n=== 집계 우선 재정렬 시뮬레이션 (골드 기준) ===")
    for label, by_mid in sides:
        summary, changed = evaluate_side(label, by_mid, claims, gold)
        all_changed.extend(changed)
        now = summary["obj@1_now"]
        fixed = summary["obj@1_aggregate_first"]
        if now is None:
            print(f"  [{label}] 골드와 겹치는 후보가 없다")
            continue
        print(f"  [{label}] 분모 {summary['labeled']} | "
              f"obj@1 {now:.1%} → {fixed:.1%} "
              f"(개선 {summary['improved']}, 악화 {summary['worsened']})")

    if all_changed:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_changed[0].keys()))
            writer.writeheader()
            writer.writerows(all_changed)
        print(f"\n=== 순위가 바뀐 건 {len(all_changed)} ===")
        for row in all_changed:
            print(f"  [{row['side']}] {row['direction']} | 주장이 대상 특정: {row['claim_names_target']}")
            print(f"    {row['obj_now_name'] or row['obj_now']} → "
                  f"{row['obj_fixed_name'] or row['obj_fixed']} (정답 {row['gold_obj_l1']})")
            print(f"    {row['claim_text']}")
        print(f"\n저장: {args.output}")
    else:
        print("\n순위가 바뀐 건이 없다 — 집계 우선 규칙으로는 obj@1 이 움직이지 않는다.")

    print("\n판단 기준:")
    print("  개선 > 악화 이고 분모가 충분하면 → 검색 단계에 집계 우선 규칙 추가")
    print("  변화 없음/악화 → 원인이 다른 데 있다. 골드를 늘려 다시 볼 것")
    print("  ※ 분모가 10건 안팎이면 1건이 10%p 다. 방향만 보고 결론은 미룰 것")


if __name__ == "__main__":
    main()
