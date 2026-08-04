#!/usr/bin/env python3
"""교정 문제지 답안을 채점한다.

이 점수가 라벨링을 믿을 근거다. 낮으면 골드를 늘리지 말아야 한다.
검증 안 된 라벨로 골드를 키우면 평가 전체가 모래 위에 선다.

답안 형식(자유 형식 텍스트도 받는다):
  1=A
  2=C
  3=없음
  4=모름

사용법:
  python score_calibration.py --answer-key calibration_answers.csv \
    --responses my_answers.txt --output calibration_score.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

ABSTAIN = {"모름", "?", "unknown"}
NONE_OF_THEM = {"없음", "none", "-"}


def parse_responses(text: str) -> dict[int, str]:
    """'1=A', '문제 3 = 없음' 같은 줄을 모은다."""
    answers: dict[int, str] = {}
    for match in re.finditer(r"(?:문제\s*)?(\d+)\s*[=:]\s*([A-Ha-h]|없음|모름|none|\?|-)",
                             text):
        answers[int(match.group(1))] = match.group(2).strip().upper()
    return answers


def gold_key(row) -> tuple[str, str, str]:
    return (str(row.get("gold_tbl_id") or "").strip(),
            str(row.get("gold_itm_id") or "").strip(),
            str(row.get("gold_obj_l1") or "").strip())


def option_map(row) -> dict[str, tuple[str, str, str]]:
    options = {}
    for chunk in str(row.get("options") or "").split("|"):
        chunk = chunk.strip()
        if "=" not in chunk:
            continue
        letter, coordinate = chunk.split("=", 1)
        parts = coordinate.split("/")
        while len(parts) < 3:
            parts.append("")
        options[letter.strip().upper()] = tuple(part.strip() for part in parts[:3])
    return options


def matches(chosen, gold) -> bool:
    """골드는 파이프(|)로 복수 정답을 담을 수 있다."""
    for level, value in enumerate(gold):
        alternatives = {part.strip() for part in value.split("|") if part.strip()}
        if not alternatives:
            continue
        if chosen[level] not in alternatives:
            return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer-key", required=True)
    ap.add_argument("--responses", required=True)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    key = {int(row["question"]): row for row in read_csv_rows(args.answer_key)}
    given = parse_responses(Path(args.responses).read_text(encoding="utf-8"))

    rows, correct, wrong, abstained, unanswered = [], 0, 0, 0, 0
    for question, row in sorted(key.items()):
        answer = given.get(question)
        gold = gold_key(row)
        options = option_map(row)
        gold_letter = next((letter for letter, value in options.items()
                            if matches(value, gold)), "")
        if answer is None:
            outcome, unanswered = "미응답", unanswered + 1
        elif answer in ABSTAIN:
            outcome, abstained = "보류", abstained + 1
        elif answer in NONE_OF_THEM:
            outcome = "정답" if not gold_letter else "오답"
            correct, wrong = correct + (outcome == "정답"), wrong + (outcome == "오답")
        elif answer in options and matches(options[answer], gold):
            outcome, correct = "정답", correct + 1
        else:
            outcome, wrong = "오답", wrong + 1
        rows.append({"question": question, "answer": answer or "",
                     "gold_letter": gold_letter, "outcome": outcome,
                     "gold_coordinate": "/".join(gold),
                     "claim_measurement_id": row.get("claim_measurement_id", ""),
                     "gold_grade": row.get("gold_grade", "")})

    answered = correct + wrong
    print(f"문항 {len(key)} | 정답 {correct} · 오답 {wrong} · 보류 {abstained} · 미응답 {unanswered}")
    if answered:
        print(f"응답한 것 중 정확도: {correct}/{answered} = {correct/answered:.1%}")
    print("\n=== 틀린 문항 ===")
    for row in rows:
        if row["outcome"] == "오답":
            print(f"  문제 {row['question']}: 답 {row['answer']} / 정답 "
                  f"{row['gold_letter'] or '(후보에 없음)'} — {row['gold_coordinate']}")

    print("\n판단 기준:")
    print("  정확도 >= 90% 이고 보류가 정직하면 → 이 방식으로 골드를 늘려도 된다")
    print("  정확도 70~90%                     → 확신 있는 건만 라벨. 나머지는 남긴다")
    print("  정확도 < 70%                      → 메타데이터만으로는 부족. 이 방식을 접는다")
    print("\n※ 보류를 정답으로 세지 않는다. 모르는 걸 찍으면 교정이 무의미해진다.")

    if args.output and rows:
        with open(args.output, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
