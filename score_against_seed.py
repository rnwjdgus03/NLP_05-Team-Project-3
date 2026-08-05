#!/usr/bin/env python3
"""씨앗 사전을 정답지 삼아 좌표 선택을 채점한다 (2026-08-05).

## 왜 필요한가

**병목이 좌표 선택이라는 것은 네 번 독립으로 쟀다**(홀3 83%, 홀4 80%).
그런데 **고쳤는지 확인할 방법이 없었다.**

지금 골드(`gold_confirmed_v3`)는 우리 후보 중 값이 재현되는 좌표를 골드로 삼은 것이라
"우리가 고른 좌표가 골드와 같은가"는 동어반복이다. 실측 Recall@3 = 100%.
어제 KOSIS 공식 통합검색으로 독립 골드를 만들려다 실패했다 — 정답 0개.

`data/seed_coordinates_verified.csv` 는 다르다.
사람이 KOSIS 메타데이터를 보고 손으로 맞췄고 **우리 임베딩과 무관하다.**
91개 키워드가 전부 KOSIS 조회를 통과했다(2026-08-05 실측).

## **일치하지 않는다고 우리가 틀린 것은 아니다**

이게 이 스크립트를 읽을 때 가장 중요하다.

같은 통계가 여러 표에 실린다. `수출액` 만 해도 씨앗은 `DT_1YL6901`(수출액(시도))
을 가리키지만, 관세청 무역통계 표로도 같은 답이 나온다. **둘 다 맞다.**

그러므로 이 숫자는 **정확도가 아니라 합치도**다. 쓰는 법은 이렇다:

    합치도가 높다   →  좌표 선택이 사람의 선택과 같은 방향이다
    합치도가 낮다   →  **어긋난 건을 사람이 본다.** 자동으로 오답 처리하지 않는다

`disagreements` 출력이 본체고 백분율은 요약일 뿐이다.
오늘 아침에 확정 12건 중 불일치 3건이 **전부 오판**이었다. 숫자만 보면 그걸 못 본다.

## 덮는 범위가 좁다

씨앗은 **국가/시도 총계뿐**이다. 품목축·상대국축이 없다.
홀드아웃4 상위 지표 중 `대미 수출액`·`달걀 물가`·`설비투자`·`원·달러 환율` 은 못 덮고,
**홀드아웃3에서 우리가 틀린 유형(중국 수출·미국 수출)이 정확히 안 덮인다.**

그래서 이건 병목의 해법이 아니라 **부분 정답지**다. 덮이는 만큼만 채점한다.
`--report-uncovered` 로 못 덮는 지표를 함께 뽑아 다음 확장 대상을 정한다.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

FIELDS = ["claim_measurement_id", "indicator", "matched_keyword", "claim_text",
          "seed_tbl_id", "our_tbl_id", "table_agrees",
          "seed_itm_id", "our_itm_id", "item_agrees",
          "seed_obj_l1", "our_obj_l1", "obj_agrees",
          "seed_tbl_name", "our_tbl_name"]


def nz(value) -> str:
    return str(value or "").strip()


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize(text) -> str:
    """공백·중점·괄호를 지워 '원·달러 환율' 과 '원달러환율' 을 같게 본다."""
    return re.sub(r"[\s·・()\[\]]", "", nz(text))


def build_lookup(seed_rows) -> dict[str, dict]:
    """키워드 → 좌표. 긴 키워드가 이기도록 나중에 정렬해 쓴다."""
    return {normalize(row["keyword"]): row for row in seed_rows
            if nz(row.get("check_status")) == "PASS"}


def match_keyword(indicator, lookup, keys) -> str:
    """지표에 대응하는 씨앗 키워드. 없으면 ''.

    완전 일치를 먼저 본다. 그다음 **가장 긴** 부분 일치다 —
    '소비자물가지수' 가 '물가' 보다 먼저 걸려야 한다.
    """
    target = normalize(indicator)
    if not target:
        return ""
    if target in lookup:
        return target
    for key in keys:                      # 길이 내림차순
        if key in target or target in key:
            return key
    return ""


def compare(seed, row) -> dict:
    """씨앗 좌표와 우리가 고른 좌표를 맞춰 본다.

    **표가 다르면 항목·축은 비교하지 않는다.** 표마다 코드 체계가 달라서
    다른 표끼리 대면 우연히 같아진다 — 실측으로 `T10` 은 수출액(DT_1YL6901),
    혼인율(DT_1B83A34), 범죄율(DT_1YL3001) 셋 다에 있다.
    표를 무시하고 세면 셋을 '항목 일치'로 센다.
    """
    record = {
        "seed_tbl_id": nz(seed.get("tbl_id")), "our_tbl_id": nz(row.get("tbl_id")),
        "seed_itm_id": nz(seed.get("itm_id")),
        "our_itm_id": nz(row.get("selected_itm_id")),
        "seed_obj_l1": nz(seed.get("obj_l1")),
        "our_obj_l1": nz(row.get("selected_obj_l1")),
        "seed_tbl_name": nz(seed.get("tbl_name")),
        "our_tbl_name": nz(row.get("tbl_name")),
    }
    same_table = record["seed_tbl_id"] == record["our_tbl_id"] != ""
    record["table_agrees"] = same_table
    record["item_agrees"] = same_table and record["seed_itm_id"] == record["our_itm_id"]
    record["obj_agrees"] = same_table and record["seed_obj_l1"] == record["our_obj_l1"]
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--coordinates", required=True, type=Path,
                        help="chroma_candidates.csv 등 selected_* 를 가진 산출물")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rank", default="1", help="몇 위 후보를 채점할지")
    parser.add_argument("--report-uncovered", action="store_true")
    args = parser.parse_args()

    seed_rows = read(args.seed)
    lookup = build_lookup(seed_rows)
    keys = sorted(lookup, key=len, reverse=True)

    rows = read(args.coordinates)
    # 측정당 한 행만 본다. 지정한 순위(기본 1위)가 우리 시스템의 답이다.
    picked: dict[str, dict] = {}
    for row in rows:
        mid = nz(row.get("claim_measurement_id"))
        rank = nz(row.get("candidate_rank")) or nz(row.get("rank"))
        if mid and rank == args.rank and mid not in picked:
            picked[mid] = row

    out, uncovered = [], Counter()
    for mid, row in picked.items():
        indicator = nz(row.get("indicator")) or nz(row.get("measurement_indicator"))
        key = match_keyword(indicator, lookup, keys)
        if not key:
            uncovered[indicator] += 1
            continue
        seed = lookup[key]
        out.append({
            "claim_measurement_id": mid,
            "indicator": indicator,
            "matched_keyword": seed["keyword"],
            "claim_text": nz(row.get("claim_text"))[:120],
            **compare(seed, row),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out)

    total = len(picked)
    print(f"=== 측정 {total}건 중 씨앗이 덮는 것 {len(out)}건 "
          f"({len(out) / total * 100:.0f}%) ===\n")
    if out:
        for label, field in [("표", "table_agrees"), ("항목", "item_agrees"),
                             ("분류1", "obj_agrees")]:
            hit = sum(1 for r in out if r[field])
            print(f"  {label:4s} 합치 {hit}/{len(out)} = {hit / len(out) * 100:.0f}%")

        print("\n--- 어긋난 건 (자동으로 오답 처리하지 말 것) ---")
        for record in [r for r in out if not r["table_agrees"]][:12]:
            print(f"\n  [{record['matched_keyword']}] {record['claim_text'][:70]}")
            print(f"    씨앗 {record['seed_tbl_id']:20s} {record['seed_tbl_name'][:34]}")
            print(f"    우리 {record['our_tbl_id']:20s} {record['our_tbl_name'][:34]}")

    if args.report_uncovered and uncovered:
        print(f"\n--- 씨앗이 못 덮는 지표 상위 15 (총 {sum(uncovered.values())}건) ---")
        for indicator, number in uncovered.most_common(15):
            print(f"  {number:3d}  {indicator[:50]}")
        print("\n  → 다음에 사전을 넓힐 대상이다. 품목축·상대국축이 여기 몰려 있다.")

    print(f"\n저장: {args.output}")
    print("\n**합치도는 정확도가 아니다.** 같은 통계가 여러 표에 실린다.")
    print("어긋난 건을 사람이 보고 어느 쪽이 맞는지 정해야 비로소 골드가 된다.")


if __name__ == "__main__":
    main()
