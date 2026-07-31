#!/usr/bin/env python3
"""후보 좌표를 KOSIS 실제값으로 대조해 **실버(silver) 좌표 라벨**을 만든다.

■ 이것은 골드가 아니다 ─────────────────────────────────────────────────
  사람이 만든 정답이 아니라 "기사 숫자를 재현하는 좌표"를 기계적으로 찾은 것이다.
  따라서 다음 한계가 **구조적으로** 있다.

  1) 기사 숫자가 틀린 주장(=우리가 잡아내야 할 대상)에서는 어떤 좌표도 값을 재현하지
     못하므로 라벨이 생기지 않는다. 즉 실버는 **참인 주장 쪽으로 편향**된다.
  2) 그러므로 이 라벨로 **판정(verdict) 정확도를 측정하면 순환 논증**이다.
     "기사가 맞다"고 가정해 좌표를 정하고, 그 좌표로 기사를 채점하게 된다.
  3) 쓸 수 있는 용도는 하나다 — **검색(retrieval) 비교**.
     "정답 좌표를 후보 Top-K 안에 넣었는가"는 좌표가 정해지면 독립적으로 측정된다.
     그것도 편향된 부분집합 위에서의 비교임을 항상 함께 보고해야 한다.

  최종 골드(A팀 사람 라벨)를 대체하지 않는다. 골드가 오면 실버와 대조해
  실버가 얼마나 맞았는지부터 보고할 것.

■ 방법 ──────────────────────────────────────────────────────────────
  measurement 마다 A/C 양쪽 후보 좌표를 모아 중복 제거하고, 각 좌표를
  `kosis_verify_claim_values.verify_row(use_pinned_item=True)` 로 **좌표를 고정한 채**
  실제값을 조회해 기사 값과 비교한다. `일치` 가 나온 좌표만 실버 후보로 본다.

  tier
    SILVER_UNIQUE     정확히 한 좌표만 값을 재현 → 실버 라벨 채택
    SILVER_AMBIGUOUS  두 개 이상이 재현 → 채택하지 않음(사람 판단 필요)
    NEAR_MISS         '판정보류'만 있음(오차밴드 안) → 사람 판단 필요
    NO_MATCH          재현 좌표 없음 → 기사가 틀렸거나 좌표를 못 찾은 것. 라벨 불가

사용법:
  python build_silver_coordinates.py \
    --measurements 05_hcx_measurements_kosis_ready.csv \
    --candidates-a 05_hcx_measurements_kosis_validated_mappings.csv \
    --candidates-c chroma_hybrid/05_hcx_measurements_kosis_chroma_validated.csv \
    --output silver_coordinates.csv \
    --review-output needs_human_review.csv \
    --delay 0.12
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from kosis_meta_coordinates import MAX_AXIS, read_csv_rows
from kosis_verify_claim_values import parse_number, verify_row

OBJ_FIELDS = [f"selected_obj_l{i}" for i in range(1, MAX_AXIS + 1)]
CLAIM_CONTEXT = ("claim_id", "claim_text", "date", "indicator", "measurement_indicator",
                 "value", "unit", "period", "measurement_period", "prd_se",
                 "measurement_prd_se", "comparison_period", "value_type",
                 "semantic_type", "unit_dimension", "measurement_role")


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def coordinate_key(row) -> tuple:
    return (text(row.get("org_id")), text(row.get("tbl_id")),
            text(row.get("selected_itm_id"))) + tuple(text(row.get(f)) for f in OBJ_FIELDS)


def resolve_mapping_type(row, claim) -> str:
    """비어 있으면 (주장, 좌표) 쌍에서 계산한다. C 경로는 이 값이 비어 있다."""
    existing = text(row.get("mapping_type"))
    if existing:
        return existing
    try:
        from kosis_match_claims_to_index import item_mapping_type
    except ImportError:
        return "direct"
    mapping_type, _reason = item_mapping_type(
        claim, text(row.get("selected_itm_unit")), text(row.get("selected_itm_name")))
    return mapping_type or "direct"


def collect_candidates(sources, keys):
    """measurement -> {coordinate_key: (row, {출처})}. 같은 좌표는 한 번만 조회한다."""
    grouped: dict[str, dict] = defaultdict(dict)
    for label, rows in sources:
        for row in rows:
            mid = text(row.get("claim_measurement_id"))
            if mid not in keys or not text(row.get("tbl_id")):
                continue
            key = coordinate_key(row)
            if key in grouped[mid]:
                grouped[mid][key][1].add(label)
            else:
                grouped[mid][key] = (dict(row), {label})
    return grouped


def build_probe_row(row, claim):
    """좌표를 고정해 검증하기 위한 입력 행. 상태 게이트는 의도적으로 우회한다."""
    probe = dict(row)
    for field in CLAIM_CONTEXT:
        if not text(probe.get(field)) and text(claim.get(field)):
            probe[field] = claim[field]
    probe["period"] = text(probe.get("period")) or text(probe.get("measurement_period"))
    probe["prd_se"] = text(probe.get("prd_se")) or text(probe.get("measurement_prd_se"))
    probe["mapping_type"] = resolve_mapping_type(row, claim)
    # 좌표 자체를 시험하는 것이 목적이므로 상류 상태 게이트는 통과시킨다.
    probe["mapping_status"] = "READY"
    probe["candidate_status"] = "READY"
    probe["candidate_rank"] = "1"
    return probe


def classify(results) -> tuple[str, list]:
    matched = [r for r in results if r["verdict"] == "일치"]
    unique_coords = {r["coordinate_key"] for r in matched}
    if len(unique_coords) == 1:
        return "SILVER_UNIQUE", matched
    if len(unique_coords) > 1:
        return "SILVER_AMBIGUOUS", matched
    near = [r for r in results if r["verdict"] == "판정보류"]
    if near:
        return "NEAR_MISS", near
    return "NO_MATCH", []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--candidates-a", required=True)
    ap.add_argument("--candidates-c", default="")
    ap.add_argument("--output", required=True)
    ap.add_argument("--review-output", default="")
    ap.add_argument("--delay", type=float, default=0.12)
    ap.add_argument("--max-coordinates-per-measurement", type=int, default=12,
                    help="API 호출 상한. 후보 순위 상위부터 자른다")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    claims = {text(r.get("claim_measurement_id")): r
              for r in read_csv_rows(args.measurements)}
    keys = set(claims)
    sources = [("A", read_csv_rows(args.candidates_a))]
    if args.candidates_c:
        sources.append(("C", read_csv_rows(args.candidates_c)))

    grouped = collect_candidates(sources, keys)
    measurement_ids = sorted(grouped)
    if args.limit:
        measurement_ids = measurement_ids[:args.limit]

    meta_cache: dict = {}
    silver_rows, review_rows = [], []
    tier_counts: Counter = Counter()
    api_calls = 0

    for index, mid in enumerate(measurement_ids, 1):
        claim = claims.get(mid, {})
        claim_value = parse_number(claim.get("value"))
        entries = list(grouped[mid].items())

        def rank_of(item):
            try:
                return int(float(text(item[1][0].get("candidate_rank")) or "999"))
            except ValueError:
                return 999

        entries.sort(key=rank_of)
        entries = entries[:args.max_coordinates_per_measurement]

        results = []
        for key, (row, labels) in entries:
            probe = build_probe_row(row, claim)
            try:
                verified = verify_row(probe, meta_cache, args.delay, use_pinned_item=True)
            except Exception as exc:                       # 한 좌표 실패가 전체를 막지 않는다
                verified = {"verdict": "판단불가", "verdict_code": "PROBE_ERROR",
                            "verdict_reason": f"{type(exc).__name__}: {exc}"}
            api_calls += 1
            results.append({
                "coordinate_key": key,
                "sources": "+".join(sorted(labels)),
                "candidate_rank": text(row.get("candidate_rank")),
                "tbl_id": text(row.get("tbl_id")),
                "tbl_name": text(row.get("tbl_name")),
                "selected_itm_id": text(row.get("selected_itm_id")),
                "selected_itm_name": text(row.get("selected_itm_name")),
                "selected_obj_l1": text(row.get("selected_obj_l1")),
                "selected_obj_l2": text(row.get("selected_obj_l2")),
                "selected_obj_l3": text(row.get("selected_obj_l3")),
                "mapping_type": text(probe.get("mapping_type")),
                "verdict": text(verified.get("verdict")),
                "verdict_code": text(verified.get("verdict_code")),
                "kosis_actual_value": text(verified.get("kosis_actual_value")),
                "verdict_reason": text(verified.get("verdict_reason"))[:300],
            })

        tier, winners = classify(results)
        tier_counts[tier] += 1
        best = winners[0] if winners else None

        silver_rows.append({
            "claim_measurement_id": mid,
            "tier": tier,
            "usable_for_retrieval_eval": tier == "SILVER_UNIQUE",
            "silver_org_id": text((best or {}).get("org_id")) or text(claim.get("org_id")),
            "silver_tbl_id": (best or {}).get("tbl_id", ""),
            "silver_itm_id": (best or {}).get("selected_itm_id", ""),
            "silver_obj_l1": (best or {}).get("selected_obj_l1", ""),
            "silver_obj_l2": (best or {}).get("selected_obj_l2", ""),
            "silver_obj_l3": (best or {}).get("selected_obj_l3", ""),
            "silver_source": (best or {}).get("sources", ""),
            "claim_value": claim_value if claim_value is not None else "",
            "kosis_actual_value": (best or {}).get("kosis_actual_value", ""),
            "coordinates_tried": len(results),
            "matched_coordinates": len({r["coordinate_key"] for r in results
                                        if r["verdict"] == "일치"}),
            "claim_text": text(claim.get("claim_text"))[:160],
            # 골드 컬럼은 비워 둔다 — 사람이 채우는 자리이며 실버로 채우지 않는다.
            "gold_tbl_id": "", "gold_itm_id": "", "gold_obj_l1": "",
            "gold_confirmed_by": "", "gold_note": "",
        })

        if tier != "SILVER_UNIQUE":
            for r in results:
                review_rows.append({"claim_measurement_id": mid, "tier": tier,
                                    "claim_text": text(claim.get("claim_text"))[:160],
                                    "claim_value": claim_value if claim_value is not None else "",
                                    **{k: v for k, v in r.items() if k != "coordinate_key"}})

        if index % 20 == 0:
            print(f"  {index}/{len(measurement_ids)} 처리, API 호출 {api_calls}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(silver_rows[0].keys()))
        writer.writeheader()
        writer.writerows(silver_rows)

    if args.review_output and review_rows:
        with open(args.review_output, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(review_rows[0].keys()))
            writer.writeheader()
            writer.writerows(review_rows)

    total = len(silver_rows)
    unique = tier_counts["SILVER_UNIQUE"]
    print(f"\nmeasurement={total} | KOSIS 조회 좌표={api_calls} → {args.output}")
    print("tier:", dict(tier_counts.most_common()))
    print(f"검색 평가에 쓸 수 있는 실버 = {unique}/{total} ({unique / max(total, 1):.1%})")
    print("\n[경고] 실버는 '기사 숫자를 재현하는 좌표'라서 참인 주장 쪽으로 편향돼 있다.")
    print("       검색 비교에만 쓰고, 판정(verdict) 정확도 측정에는 쓰지 말 것.")
    if args.review_output and review_rows:
        print(f"사람 판단 필요 목록: {args.review_output} ({len(review_rows)}행)")


if __name__ == "__main__":
    main()
