#!/usr/bin/env python3
"""라벨러(사람이든 LLM이든)를 **채점하기 위한** 문제지를 만든다.

왜 필요한가
-----------
실버(값 재현)로 만들 수 있는 골드는 12건에서 멈췄다. 원리상 그렇다 —
실버는 '기사 숫자를 재현하는 좌표'를 찾으므로 **기사 숫자가 맞는 건만** 라벨한다.
그런데 기사 숫자가 틀렸는지 밝히는 것이 이 프로젝트의 목적이다.
따라서 남은 건들은 값과 무관하게 '이 주장에 맞는 좌표인가'로 판단해야 한다.

그 판단을 믿어도 되는지 먼저 재야 한다. 이미 정답을 아는 12건을 정답 없이 내주고,
메타데이터만으로 맞히는지 본다. 못 맞히면 이 방식으로 골드를 늘리면 안 된다.

누출 방지
---------
- 실제 조회값·판정·매핑 상태를 넣지 않는다 (값을 보면 답이 보인다)
- 파이프라인 순위를 넣지 않고 좌표 코드 사전순으로 낸다 (앵커링 방지)
- 정답 표시를 넣지 않는다. 정답은 --answer-key 로 따로 저장한다

사용법:
  python export_calibration_packet.py \
    --gold gold_confirmed_v2.csv \
    --candidates ..._chroma_validated.csv \
    --measurements evaluation_set_v3.csv \
    --output calibration_packet.md \
    --answer-key calibration_answers.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

# 정답이 새는 컬럼. 문제지에 절대 넣지 않는다.
LEAKY = ("kosis_actual_value", "kosis_actual_raw", "verdict", "verdict_code",
         "mapping_status", "mapping_reason", "value_diff", "candidate_rank",
         "response_code_valid", "api_valid", "matching_rows", "silver_tbl_id",
         "gold_tbl_id", "candidate_score", "final_confidence", "ranking_score")


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def coordinate_key(row) -> tuple[str, str, str]:
    return (text(row.get("tbl_id")),
            text(row.get("selected_itm_id")),
            text(row.get("selected_obj_l1")))


def describe(row) -> str:
    """좌표를 메타데이터로만 설명한다."""
    parts = [f"표 `{text(row.get('tbl_id'))}` {text(row.get('tbl_name'))}"]
    item = text(row.get("selected_itm_name")) or text(row.get("selected_itm_id"))
    if item:
        unit = text(row.get("selected_itm_unit"))
        parts.append(f"항목 {item}" + (f" [{unit}]" if unit else " [단위 미상]"))
    for level in (1, 2, 3):
        name = text(row.get(f"selected_obj_l{level}_name"))
        if name:
            axis = text(row.get(f"selected_obj_l{level}_axis_name")) or f"분류{level}"
            parts.append(f"{axis}={name}")
    prd = text(row.get("coordinate_prd_se")) or text(row.get("prd_se"))
    if prd:
        parts.append(f"주기 {prd}")
    return " · ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--answer-key", default="")
    ap.add_argument("--max-options", type=int, default=8)
    ap.add_argument("--unlabeled", action="store_true",
                    help="골드에 **없는** measurement 로 문제지를 만든다(실제 라벨링용). "
                         "이때는 정답이 없으므로 answer-key 를 쓰지 않는다.")
    ap.add_argument("--limit", type=int, default=0, help="한 번에 낼 문항 수(배치)")
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    gold = {text(r.get("claim_measurement_id")): r for r in read_csv_rows(args.gold)}
    claims = {text(r.get("claim_measurement_id")): r
              for r in read_csv_rows(args.measurements)}
    if not args.unlabeled and not args.answer_key:
        raise SystemExit("교정 모드에서는 --answer-key 가 필요하다")

    targets = set(claims) - set(gold) if args.unlabeled else set(gold)
    by_measurement: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for row in read_csv_rows(args.candidates):
        mid = text(row.get("claim_measurement_id"))
        if mid in targets:
            by_measurement[mid].setdefault(coordinate_key(row), row)

    lines = [
        "# 좌표 라벨링 교정 문제지",
        "",
        "각 주장에 대해 **KOSIS 좌표 후보** 중 맞는 것을 고른다.",
        "실제 조회값·판정은 일부러 넣지 않았다 — 메타데이터만으로 판단해야 한다.",
        "후보는 파이프라인 순위가 아니라 좌표 코드 사전순이다(앵커링 방지).",
        "",
        "맞는 후보가 없으면 `없음`, 판단이 불가능하면 `모름`으로 답한다.",
        "**모르는 걸 찍으면 교정의 의미가 없다.**",
        "",
        "---",
        "",
    ]
    answers = []
    selected = sorted(by_measurement.items())
    if args.limit:
        selected = selected[args.offset:args.offset + args.limit]
    for index, (mid, options) in enumerate(selected, start=args.offset + 1):
        claim = claims.get(mid, {})
        ordered = [options[key] for key in sorted(options)][:args.max_options]
        if len(ordered) < 2:
            continue
        lines += [
            f"## 문제 {index}",
            "",
            f"> {text(claim.get('claim_text'))}",
            "",
            f"- 지표: {text(claim.get('indicator')) or '-'}",
            f"- 대상: {text(claim.get('industry_or_item')) or '(없음 — 총계로 봐야 함)'}",
            f"- 값: {text(claim.get('value'))} {text(claim.get('unit'))}",
            f"- 기간: {text(claim.get('period'))} ({text(claim.get('prd_se')) or '?'})"
            + (f", 비교 {text(claim.get('comparison_period'))}"
               if text(claim.get('comparison_period')) else ""),
            "",
            "후보:",
            "",
        ]
        for letter, row in zip("ABCDEFGH", ordered):
            lines.append(f"- **{letter}.** {describe(row)}")
        lines += ["", f"답: `문제 {index} = ?`", "", "---", ""]

        entry = {
            "question": index,
            "claim_measurement_id": mid,
            "options": " | ".join(
                f"{letter}={'/'.join(coordinate_key(row))}"
                for letter, row in zip("ABCDEFGH", ordered)),
        }
        if not args.unlabeled:
            entry.update({
                "gold_tbl_id": text(gold[mid].get("gold_tbl_id")),
                "gold_itm_id": text(gold[mid].get("gold_itm_id")),
                "gold_obj_l1": text(gold[mid].get("gold_obj_l1")),
                "gold_grade": text(gold[mid].get("gold_grade")),
            })
        answers.append(entry)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    key_path = args.answer_key or (str(Path(args.output).with_suffix("")) + "_key.csv")
    with open(key_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(answers[0].keys()))
        writer.writeheader()
        writer.writerows(answers)

    leaked = [name for name in LEAKY
              if any(name in line for line in lines)]
    print(f"문제 {len(answers)}개 → {args.output}")
    print(f"{'선택지 매핑' if args.unlabeled else '정답'} → {key_path}")
    if args.unlabeled:
        print(f"라벨 대상 {len(by_measurement)}건 중 {len(answers)}건 출제 "
              f"(offset={args.offset}, limit={args.limit or '전체'})")
    print(f"누출 검사: {'통과' if not leaked else '실패 ' + str(leaked)}")
    if leaked:
        raise SystemExit("문제지에 정답이 새는 항목이 있다")


if __name__ == "__main__":
    main()
