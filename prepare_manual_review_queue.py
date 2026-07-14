"""Build prioritized review queues for the 1,998 mapped and 4,403 manual rows."""

import argparse
from collections import Counter
import csv
from pathlib import Path
import re


csv.field_size_limit(2_147_483_647)
CRITICAL_FIELDS = ("org_id", "tbl_id", "obj_l1", "itm_id")


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


def candidate_count(value):
    text = (value or "").strip()
    if not text:
        return 0
    return len([part for part in re.split(r"\s*;\s*", text) if part.strip()])


def manual_priority(row):
    org_tbl = all((row.get(field) or "").strip() for field in ("org_id", "tbl_id"))
    complete = all((row.get(field) or "").strip() for field in CRITICAL_FIELDS)
    obj_count = candidate_count(row.get("obj_l1_candidates"))
    itm_count = candidate_count(row.get("itm_id_candidates"))

    if complete:
        return "P0", "주요 ID 4종이 채워져 있어 매핑 적합성 확인 후 API 검증 가능", obj_count, itm_count
    if org_tbl and 0 < obj_count <= 1 and 0 < itm_count <= 1:
        return "P1", "기관·표 확정, 분류·항목 후보가 각각 1개라 빠른 수동 확정 가능", obj_count, itm_count
    if org_tbl and (obj_count or itm_count):
        return "P2", "기관·표 확정, 분류·항목 후보 중 선택 필요", obj_count, itm_count
    if org_tbl:
        return "P3", "기관·표 확정, KOSIS 메타데이터에서 분류·항목 코드 재조회 필요", obj_count, itm_count
    return "P4", "기관·통계표부터 다시 선택 필요", obj_count, itm_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapped-input", required=True)
    parser.add_argument("--manual-input", required=True)
    parser.add_argument("--sample-verified", required=True)
    parser.add_argument("--mapped-output", required=True)
    parser.add_argument("--manual-output", required=True)
    parser.add_argument("--batch-output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    mapped, mapped_fields = read_csv(args.mapped_input)
    manual, manual_fields = read_csv(args.manual_input)
    sample, _ = read_csv(args.sample_verified)
    sample_by_id = {row.get("claim_id"): row for row in sample}

    mapped_queue = []
    for row in mapped:
        sample_row = sample_by_id.get(row.get("claim_id"))
        notes = row.get("reviewer_note") or ""
        multiple_tables = candidate_count(row.get("candidate_kosis_table")) > 1
        if sample_row and sample_row.get("verdict") != "일치":
            priority = "P0"
            reason = f"표본 검증 {sample_row.get('verdict')}: API/기간/지표·단위 매핑 재확인 필요"
        elif "확인 필요" in notes or multiple_tables:
            priority = "P1"
            reason = "기존 검토 메모 또는 복수 통계표 후보가 있어 매핑 근거 재확인 필요"
        else:
            priority = "P2"
            reason = "주요 ID는 채워졌으나 자동 매핑이므로 지표·단위·기간의 의미 검토 필요"
        enriched = {
            "review_priority": priority,
            "review_reason": reason,
            "sample_verdict": sample_row.get("verdict", "") if sample_row else "",
            "sample_actual_period": sample_row.get("actual_period", "") if sample_row else "",
            **row,
        }
        mapped_queue.append(enriched)

    mapped_queue.sort(key=lambda row: (row["review_priority"], row.get("claim_id") or ""))
    for index, row in enumerate(mapped_queue):
        row["review_batch"] = index // args.batch_size + 1

    manual_queue = []
    for row in manual:
        priority, reason, obj_count, itm_count = manual_priority(row)
        manual_queue.append(
            {
                "review_priority": priority,
                "review_reason": reason,
                "obj_candidate_count": obj_count,
                "itm_candidate_count": itm_count,
                **row,
            }
        )

    manual_queue.sort(
        key=lambda row: (
            row["review_priority"],
            row["obj_candidate_count"] + row["itm_candidate_count"],
            row.get("claim_id") or "",
        )
    )
    for index, row in enumerate(manual_queue):
        row["review_batch"] = index // args.batch_size + 1

    mapped_out_fields = [
        "review_priority", "review_reason", "review_batch",
        "sample_verdict", "sample_actual_period", *mapped_fields,
    ]
    manual_out_fields = [
        "review_priority", "review_reason", "review_batch",
        "obj_candidate_count", "itm_candidate_count", *manual_fields,
    ]
    write_csv(args.mapped_output, mapped_queue, mapped_out_fields)
    write_csv(args.manual_output, manual_queue, manual_out_fields)
    write_csv(args.batch_output, manual_queue[: args.batch_size], manual_out_fields)

    mapped_counts = Counter(row["review_priority"] for row in mapped_queue)
    manual_counts = Counter(row["review_priority"] for row in manual_queue)
    summary_rows = [
        {"대상": "매핑 재검토 1,998건", "우선순위": key, "건수": value}
        for key, value in sorted(mapped_counts.items())
    ] + [
        {"대상": "수동 검토 4,403건", "우선순위": key, "건수": value}
        for key, value in sorted(manual_counts.items())
    ]
    write_csv(args.summary_output, summary_rows, ["대상", "우선순위", "건수"])

    print(f"매핑 재검토 큐: {len(mapped_queue)}건 {dict(mapped_counts)}")
    print(f"수동 검토 큐: {len(manual_queue)}건 {dict(manual_counts)}")
    print(f"1차 수동 검토 배치: {min(args.batch_size, len(manual_queue))}건")


if __name__ == "__main__":
    main()
