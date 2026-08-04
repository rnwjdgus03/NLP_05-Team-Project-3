#!/usr/bin/env python3
"""LLM 라벨링용 근거 시트를 뽑는다 (실버가 자동 확정하지 못한 measurement 대상).

라벨러(사람이든 LLM이든)가 **prior 가 아니라 증거를 보고** 고르게 하는 것이 목적이다.
그래서 measurement 마다 후보 좌표를 KOSIS 메타 이름·단위와 **실제 조회값**까지 붙여 낸다.

원칙
  - 파이프라인이 무엇을 골랐는지는 숨기지 않되 **정렬 기준으로 쓰지 않는다**.
    (후보를 파이프라인 순위대로 보여주면 라벨러가 1위에 끌린다 → 앵커링)
    좌표는 tbl_id/itm_id 사전순으로 섞어 낸다.
  - `pipeline_choice` 컬럼은 별도로 남겨, 라벨 후 '파이프라인과 일치하는가'를
    계산해 상관 오류 위험이 높은 행을 감사 표본에서 과대추출할 수 있게 한다.

사용법:
  python export_labeling_packet.py \
    --silver silver_coordinates.csv \
    --review needs_human_review.csv \
    --measurements 05_hcx_measurements_kosis_ready.csv \
    --output labeling_packet.csv \
    --markdown labeling_packet.md
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

NEEDS_LABEL = {"SILVER_AMBIGUOUS", "NEAR_MISS", "NO_MATCH"}


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def coordinate_label(row) -> str:
    parts = [f"{text(row.get('tbl_id'))}/{text(row.get('selected_itm_id'))}"]
    objs = [text(row.get(f"selected_obj_l{i}")) for i in (1, 2, 3)]
    objs = [o for o in objs if o]
    if objs:
        parts.append("/".join(objs))
    return " ".join(parts)


def describe(row) -> str:
    """사람이 읽고 판단할 수 있는 한 줄. 코드가 아니라 이름과 값이 앞에 온다."""
    bits = [text(row.get("tbl_name")) or text(row.get("tbl_id"))]
    if text(row.get("selected_itm_name")):
        bits.append(f"항목={row['selected_itm_name']}")
    for level in (1, 2, 3):
        name = text(row.get(f"selected_obj_l{level}_name"))
        if name:
            bits.append(f"분류{level}={name}")
    if text(row.get("kosis_actual_value")):
        bits.append(f"KOSIS값={row['kosis_actual_value']}")
    if text(row.get("verdict")):
        bits.append(f"판정={row['verdict']}")
    return " | ".join(bits)


def build_packet(silver_rows, review_rows, claims):
    by_measurement = defaultdict(list)
    for row in review_rows:
        by_measurement[text(row.get("claim_measurement_id"))].append(row)

    packet = []
    for silver in silver_rows:
        tier = text(silver.get("tier"))
        if tier not in NEEDS_LABEL:
            continue
        mid = text(silver.get("claim_measurement_id"))
        claim = claims.get(mid, {})
        candidates = by_measurement.get(mid, [])
        # 앵커링 방지: 파이프라인 순위가 아니라 코드 사전순으로 낸다.
        candidates = sorted(candidates, key=coordinate_label)

        pipeline_choice = ""
        for row in candidates:
            if text(row.get("candidate_rank")) == "1" and "A" in text(row.get("sources")):
                pipeline_choice = coordinate_label(row)
                break

        packet.append({
            "claim_measurement_id": mid,
            "tier": tier,
            "claim_text": text(claim.get("claim_text")),
            "value": text(claim.get("value")),
            "unit": text(claim.get("unit")),
            "period": text(claim.get("measurement_period")) or text(claim.get("period")),
            "prd_se": text(claim.get("measurement_prd_se")),
            "indicator": text(claim.get("measurement_indicator")) or text(claim.get("indicator")),
            "value_type": text(claim.get("value_type")),
            "candidate_count": len(candidates),
            "candidates": " ;; ".join(f"[{i}] {coordinate_label(c)} :: {describe(c)}"
                                      for i, c in enumerate(candidates, 1)),
            "pipeline_choice": pipeline_choice,
            # 라벨러가 채우는 자리
            "label_tbl_id": "", "label_itm_id": "", "label_obj_l1": "",
            "label_confidence": "", "label_evidence": "", "label_by": "",
        })
    return packet


def to_markdown(packet) -> str:
    lines = ["# 라벨링 근거 시트", "",
             "각 measurement 에서 주장을 검증할 수 있는 **좌표 하나**를 고른다.",
             "맞는 좌표가 없으면 `없음`, 판단이 안 서면 `보류` 라고 적는다.",
             "후보는 앵커링을 피하려고 코드 사전순으로 섞어 두었다.", ""]
    for item in packet:
        lines.append(f"## {item['claim_measurement_id']}  ({item['tier']})")
        lines.append(f"- 주장: {item['claim_text']}")
        lines.append(f"- 값: {item['value']} {item['unit']} / 시점 {item['period']} "
                     f"({item['prd_se']}) / 지표 {item['indicator']} / 유형 {item['value_type']}")
        lines.append("- 후보:")
        for chunk in item["candidates"].split(" ;; "):
            if chunk:
                lines.append(f"  - {chunk}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver", required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--markdown", default="")
    args = ap.parse_args()

    silver_rows = read_csv_rows(args.silver)
    review_rows = read_csv_rows(args.review)
    claims = {text(r.get("claim_measurement_id")): r
              for r in read_csv_rows(args.measurements)}

    packet = build_packet(silver_rows, review_rows, claims)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(packet[0].keys()))
        writer.writeheader()
        writer.writerows(packet)

    if args.markdown:
        Path(args.markdown).write_text(to_markdown(packet), encoding="utf-8")

    tiers = defaultdict(int)
    for item in packet:
        tiers[item["tier"]] += 1
    print(f"라벨 필요 measurement={len(packet)} → {args.output}")
    print("tier:", dict(tiers))
    print(f"실버 자동 확정={len(silver_rows) - len(packet)}/{len(silver_rows)}")
    if args.markdown:
        print(f"읽기용 시트: {args.markdown}")


if __name__ == "__main__":
    main()
