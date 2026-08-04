"""Prepare and audit measurement-first extraction regression batches."""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from extract_hcx import extract_numeric_candidates, measurement_key


CLAIM_COLS = [
    "claim_id", "article_id", "title", "date", "url",
    "claim_text", "prev_sentence", "next_sentence",
]
REQUIRED_MEASUREMENT_FIELDS = (
    "value", "unit", "value_type", "measurement_role",
)
REPORT_COLS = [
    "claim_id", "has_raw_digit", "expected_measurement_count",
    "actual_measurement_count", "missing_expected", "unexpected_actual",
    "missing_required_fields", "ungrounded_actual", "fallback_count",
    "repair_used", "status", "claim_text",
]


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path, rows, fieldnames):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def problem_claims(rows):
    """Return unique baseline claims whose extracted measurement value is missing."""
    selected = {}
    for row in rows:
        if str(row.get("value", "")).strip() != "-":
            continue
        claim_id = str(row.get("claim_id", "")).strip()
        if claim_id and claim_id not in selected:
            selected[claim_id] = {column: row.get(column, "-") for column in CLAIM_COLS}
    return list(selected.values())


def prepare(args):
    claims = problem_claims(read_csv(args.baseline))
    if args.expect_claims and len(claims) != args.expect_claims:
        raise SystemExit(
            f"기준 건수 불일치: expected={args.expect_claims}, actual={len(claims)}"
        )
    write_csv(args.output, claims, CLAIM_COLS)

    digit_claims = sum(bool(re.search(r"\d", row["claim_text"])) for row in claims)
    candidate_counts = [len(extract_numeric_candidates(row["claim_text"])) for row in claims]
    print(f"Created: {args.output}")
    print(
        f"Baseline claims: {len(claims)} | Raw-digit claims: {digit_claims} | "
        f"Candidate claims: {sum(count > 0 for count in candidate_counts)} | "
        f"Candidate measurements: {sum(candidate_counts)}"
    )


def display_key(key):
    return f"{key[0]}{key[1]}"


def audit_claim(claim, actual_rows):
    text = claim.get("claim_text", "")
    expected_candidates = extract_numeric_candidates(text)
    expected = {
        (candidate["value"], candidate["unit"])
        for candidate in expected_candidates
    }
    measurements = [
        row for row in actual_rows
        if row.get("value", "-") != "-" or row.get("unit", "-") != "-"
    ]
    actual = {
        measurement_key(row.get("value", "-"), row.get("unit", "-"))
        for row in measurements
        if row.get("value", "-") != "-" and row.get("unit", "-") != "-"
    }
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)

    missing_required = []
    ungrounded = []
    for index, row in enumerate(measurements, start=1):
        absent = [
            field for field in REQUIRED_MEASUREMENT_FIELDS
            if str(row.get(field, "")).strip() in {"", "-"}
        ]
        if absent:
            missing_required.append(f"m{index}:{','.join(absent)}")
        key = measurement_key(row.get("value", "-"), row.get("unit", "-"))
        measurement_text = str(row.get("measurement_text", "")).strip()
        if key not in expected and (not measurement_text or measurement_text not in text):
            ungrounded.append(display_key(key))

    if missing or missing_required or ungrounded:
        status = "FAIL"
    elif unexpected:
        status = "REVIEW"
    else:
        status = "PASS"

    fallback_count = sum(
        row.get("measurement_source") == "rule_fallback" for row in measurements
    )
    repair_used = any(row.get("measurement_repaired") == "Y" for row in actual_rows)
    return {
        "claim_id": claim["claim_id"],
        "has_raw_digit": "Y" if re.search(r"\d", text) else "N",
        "expected_measurement_count": len(expected),
        "actual_measurement_count": len(measurements),
        "missing_expected": ";".join(map(display_key, missing)) or "-",
        "unexpected_actual": ";".join(map(display_key, unexpected)) or "-",
        "missing_required_fields": ";".join(missing_required) or "-",
        "ungrounded_actual": ";".join(ungrounded) or "-",
        "fallback_count": fallback_count,
        "repair_used": "Y" if repair_used else "N",
        "status": status,
        "claim_text": text,
    }


def audit(args):
    baseline_claims = problem_claims(read_csv(args.baseline))
    actual_by_claim = defaultdict(list)
    for row in read_csv(args.candidate):
        actual_by_claim[row.get("claim_id", "")].append(row)

    report = [
        audit_claim(claim, actual_by_claim.get(claim["claim_id"], []))
        for claim in baseline_claims
    ]
    write_csv(args.report, report, REPORT_COLS)

    expected_claims = sum(row["expected_measurement_count"] > 0 for row in report)
    expected_measurements = sum(row["expected_measurement_count"] for row in report)
    actual_measurements = sum(row["actual_measurement_count"] for row in report)
    fallback_rows = sum(row["fallback_count"] for row in report)
    status_counts = {
        status: sum(row["status"] == status for row in report)
        for status in ("PASS", "REVIEW", "FAIL")
    }
    summary = {
        "baseline_claims": len(report),
        "claims_with_expected_measurements": expected_claims,
        "claims_without_expected_measurements": len(report) - expected_claims,
        "multi_measurement_claims": sum(
            row["expected_measurement_count"] > 1 for row in report
        ),
        "fully_split_multi_measurement_claims": sum(
            row["expected_measurement_count"] > 1
            and row["missing_expected"] == "-"
            and row["actual_measurement_count"] >= row["expected_measurement_count"]
            for row in report
        ),
        "expected_measurements": expected_measurements,
        "actual_measurements": actual_measurements,
        "missing_expected_measurements": sum(
            0 if row["missing_expected"] == "-" else len(row["missing_expected"].split(";"))
            for row in report
        ),
        "claims_with_missing_required_fields": sum(
            row["missing_required_fields"] != "-" for row in report
        ),
        "claims_with_ungrounded_values": sum(
            row["ungrounded_actual"] != "-" for row in report
        ),
        "claims_with_unexpected_values": sum(
            row["unexpected_actual"] != "-" for row in report
        ),
        "claims_repaired": sum(row["repair_used"] == "Y" for row in report),
        "fallback_rows": fallback_rows,
        "fallback_ratio": round(fallback_rows / actual_measurements, 4) if actual_measurements else 0,
        "status": status_counts,
    }
    summary_path = Path(args.summary) if args.summary else Path(args.report).with_suffix(".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Report: {args.report}")
    print(f"Summary: {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="v1.3 누락 claim 회귀 입력 생성")
    prepare_parser.add_argument("--baseline", required=True)
    prepare_parser.add_argument("--output", required=True)
    prepare_parser.add_argument("--expect-claims", type=int, default=0)
    prepare_parser.set_defaults(func=prepare)

    audit_parser = subparsers.add_parser("audit", help="v1.4 재추출 결과 감사")
    audit_parser.add_argument("--baseline", required=True)
    audit_parser.add_argument("--candidate", required=True)
    audit_parser.add_argument("--report", required=True)
    audit_parser.add_argument("--summary")
    audit_parser.set_defaults(func=audit)
    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
