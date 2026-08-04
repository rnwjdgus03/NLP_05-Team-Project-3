"""Summarize KOSIS fetch and automated claim verification outputs."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path


csv.field_size_limit(2_147_483_647)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def normalized_error(value):
    text = (value or "").strip()
    if not text:
        return "없음"
    if "데이터 없음" in text:
        return "데이터 없음"
    if "HTTPSConnectionPool" in text or "Connection" in text:
        return "네트워크 오류"
    if "Invalid" in text or "invalid" in text:
        return "잘못된 코드/요청"
    return text[:120]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--verified", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--show-rows", type=int, default=0)
    args = parser.parse_args()

    mapping = read_csv(args.mapping)
    verified = read_csv(args.verified)
    verdict_counts = Counter((row.get("verdict") or "<blank>") for row in verified)
    period_counts = Counter((row.get("prd_se") or "<blank>") for row in verified)
    fetch_status = Counter(
        "성공" if (row.get("actual_value") or "").strip() else "실패/미매칭"
        for row in mapping
    )
    error_counts = Counter(normalized_error(row.get("api_error")) for row in mapping)

    summary_rows = [
        {"구분": "전체", "항목": "행 수", "건수": len(verified)},
        *(
            {"구분": "KOSIS 조회", "항목": key, "건수": value}
            for key, value in sorted(fetch_status.items())
        ),
        *(
            {"구분": "자동 판정", "항목": key, "건수": value}
            for key, value in sorted(verdict_counts.items())
        ),
        *(
            {"구분": "수록주기", "항목": key, "건수": value}
            for key, value in sorted(period_counts.items())
        ),
        *(
            {"구분": "API 오류", "항목": key, "건수": value}
            for key, value in error_counts.most_common()
        ),
    ]

    output_path = Path(args.summary_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["구분", "항목", "건수"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    print(
        json.dumps(
            {
                "rows": len(verified),
                "fetch_status": dict(fetch_status),
                "verdicts": dict(verdict_counts),
                "periods": dict(period_counts),
                "errors": dict(error_counts),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    for row in verified[: args.show_rows]:
        compact = {
            "claim_id": row.get("claim_id"),
            "claim_text": (row.get("claim_text") or "")[:100],
            "prd_se": row.get("prd_se"),
            "tbl_id": row.get("tbl_id"),
            "actual_period": row.get("actual_period"),
            "actual_value": row.get("actual_value"),
            "claim_type": row.get("claim_type"),
            "claim_number": row.get("claim_number"),
            "verdict": row.get("verdict"),
            "api_error": normalized_error(row.get("api_error")),
        }
        print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
