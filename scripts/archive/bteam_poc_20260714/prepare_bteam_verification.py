"""Resolve the three incomplete review rows and prepare verification inputs."""

import argparse
import csv
from pathlib import Path
import random
import sys


csv.field_size_limit(2_147_483_647)

CRITICAL_FIELDS = ("org_id", "tbl_id", "obj_l1", "itm_id")

MANUAL_DECISIONS = {
    "C13755": (
        "판단불가",
        "수동확인: 선택 통계표 DT_1R11001_FRM101은 품목별 수출액/수입액(천달러) 표임. "
        "주장은 국산 냉장 대형 고등어 소매가격(원/마리)이므로 지표·단위가 달라 obj_l1을 확정하지 않음.",
    ),
    "C13774": (
        "판단불가",
        "수동확인: 선택 통계표 DT_1R11001_FRM101은 품목별 수출액/수입액(천달러) 표이며 "
        "현재 itm_id는 수출액 코드임. 주장은 브라질산 닭고기 수입량(톤)과 국가 비중이므로 "
        "지표·차원이 달라 obj_l1을 확정하지 않음.",
    ),
    "C19540": (
        "판단불가",
        "수동확인: 선택 통계표 DT_1DA7300AS의 분류축은 시간관련 추가취업가능자·잠재경제활동인구·"
        "실업자·경제활동인구 등이며 '쉬었음' 항목이 없음. 주장을 직접 나타내지 않아 obj_l1을 확정하지 않음.",
    ),
}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path, rows, fieldnames):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def select_diverse_sample(rows, sample_size):
    rng = random.Random(20260714)
    shuffled = list(rows)
    rng.shuffle(shuffled)

    selected = []
    seen_tables = set()
    seen_periods = set()

    for row in shuffled:
        table_key = (row.get("org_id"), row.get("tbl_id"))
        period = row.get("prd_se")
        if table_key not in seen_tables or period not in seen_periods:
            selected.append(row)
            seen_tables.add(table_key)
            seen_periods.add(period)
            if len(selected) >= sample_size:
                return selected

    selected_ids = {row.get("claim_id") for row in selected}
    for row in shuffled:
        if row.get("claim_id") in selected_ids:
            continue
        selected.append(row)
        if len(selected) >= sample_size:
            break
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--resolved-output", required=True)
    parser.add_argument("--ready-output", required=True)
    parser.add_argument("--unresolved-output", required=True)
    parser.add_argument("--sample-output", required=True)
    parser.add_argument("--sample-size", type=int, default=24)
    args = parser.parse_args()

    rows, fieldnames = read_csv(args.input)
    missing_before = [
        row for row in rows if any(not (row.get(field) or "").strip() for field in CRITICAL_FIELDS)
    ]
    missing_ids = {row.get("claim_id") for row in missing_before}
    expected_ids = set(MANUAL_DECISIONS)
    if missing_ids != expected_ids:
        raise RuntimeError(
            f"미완성 행이 예상과 다름: expected={sorted(expected_ids)}, actual={sorted(missing_ids)}"
        )

    for row in rows:
        decision = MANUAL_DECISIONS.get(row.get("claim_id"))
        if not decision:
            continue
        status, note = decision
        row["verifiable"] = status
        old_note = (row.get("reviewer_note") or "").strip()
        if note not in old_note:
            row["reviewer_note"] = f"{old_note} | {note}" if old_note else note

    ready = [
        row
        for row in rows
        if all((row.get(field) or "").strip() for field in CRITICAL_FIELDS)
        and row.get("verifiable") != "판단불가"
    ]
    unresolved = [row for row in rows if row.get("verifiable") == "판단불가"]
    sample = select_diverse_sample(ready, args.sample_size)

    if len(rows) != 2001 or len(ready) != 1998 or len(unresolved) != 3:
        raise RuntimeError(
            f"행 수 검증 실패: total={len(rows)}, ready={len(ready)}, unresolved={len(unresolved)}"
        )

    write_csv(args.resolved_output, rows, fieldnames)
    write_csv(args.ready_output, ready, fieldnames)
    write_csv(args.unresolved_output, unresolved, fieldnames)
    write_csv(args.sample_output, sample, fieldnames)

    period_counts = {}
    for row in ready:
        period = row.get("prd_se") or "<blank>"
        period_counts[period] = period_counts.get(period, 0) + 1

    print(f"전체: {len(rows)}건")
    print(f"검증 준비 완료: {len(ready)}건")
    print(f"수동 판단불가: {len(unresolved)}건")
    print(f"표본: {len(sample)}건")
    print(f"주기 분포: {period_counts}")


if __name__ == "__main__":
    main()
