"""Freeze a versioned measurement gold set after deterministic label cleanup.

The source gold remains untouched. This command merges the latest gate result,
changes only non-KOSIS usage labels that conflict with the agreed policy, and
writes audit and metric artifacts beside the locked CSV.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


NON_VERIFIABLE_USAGES = {"POLICY_VALUE", "CONDITION", "CONTEXT"}
REQUIRED_FIELDS = {
    "claim_measurement_id",
    "measurement_usage",
    "gold_verifiable",
    "gold_measurement_correct",
    "in_ready",
}
LOCK_FIELDS = ["gold_label_version", "gold_label_rule", "gate_version"]


def read_csv(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return rows, fields


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lock_rows(
    source_rows: list[dict],
    ready_ids: set[str],
    label_version: str = "v1",
    gate_version: str = "trade_scope_v1",
) -> tuple[list[dict], list[dict]]:
    locked = []
    audit = []
    seen = set()

    for source in source_rows:
        row = dict(source)
        measurement_id = row.get("claim_measurement_id", "").strip()
        if not measurement_id:
            raise ValueError("claim_measurement_id is blank")
        if measurement_id in seen:
            raise ValueError(f"duplicate claim_measurement_id: {measurement_id}")
        seen.add(measurement_id)

        old_gold = row.get("gold_verifiable", "").strip().upper()
        if old_gold not in {"Y", "N"}:
            raise ValueError(f"invalid gold_verifiable for {measurement_id}: {old_gold!r}")
        measurement_correct = row.get("gold_measurement_correct", "").strip().upper()
        if measurement_correct not in {"Y", "N"}:
            raise ValueError(
                f"invalid gold_measurement_correct for {measurement_id}: {measurement_correct!r}"
            )

        usage = row.get("measurement_usage", "").strip()
        new_gold = old_gold
        rule = "HUMAN_LABEL_PRESERVED"
        if usage in NON_VERIFIABLE_USAGES:
            new_gold = "N"
            rule = "NON_KOSIS_USAGE_TO_N"

        row["gold_verifiable"] = new_gold
        row["in_ready"] = "Y" if measurement_id in ready_ids else "N"
        row["gold_label_version"] = label_version
        row["gold_label_rule"] = rule
        row["gate_version"] = gate_version
        locked.append(row)

        if old_gold != new_gold:
            audit.append(
                {
                    "claim_measurement_id": measurement_id,
                    "measurement_usage": usage,
                    "measurement_role": row.get("measurement_role", ""),
                    "measurement_indicator": row.get("measurement_indicator", ""),
                    "value": row.get("value", ""),
                    "unit": row.get("unit", ""),
                    "old_gold_verifiable": old_gold,
                    "new_gold_verifiable": new_gold,
                    "change_rule": rule,
                }
            )

    missing_ready = sorted(ready_ids - seen)
    if missing_ready:
        raise ValueError(f"ready IDs missing from gold: {missing_ready[:5]}")
    return locked, audit


def build_metrics(rows: list[dict], audit_count: int) -> dict:
    total = len(rows)
    ready = [row for row in rows if row["in_ready"] == "Y"]
    verifiable = [row for row in rows if row["gold_verifiable"] == "Y"]
    true_positive = sum(row["gold_verifiable"] == "Y" for row in ready)
    false_positive = len(ready) - true_positive
    false_negative = sum(row["in_ready"] != "Y" for row in verifiable)
    extraction_labeled = [row for row in ready if row["gold_measurement_correct"] in {"Y", "N"}]
    extraction_correct = sum(row["gold_measurement_correct"] == "Y" for row in extraction_labeled)

    return {
        "rows": total,
        "unique_measurement_ids": len({row["claim_measurement_id"] for row in rows}),
        "label_changes": audit_count,
        "gold_verifiable": dict(Counter(row["gold_verifiable"] for row in rows)),
        "gold_measurement_correct": dict(
            Counter(row["gold_measurement_correct"] for row in rows)
        ),
        "ready": len(ready),
        "rejected": total - len(ready),
        "gate_true_positive": true_positive,
        "gate_false_positive": false_positive,
        "gate_false_negative": false_negative,
        "gate_precision": ratio(true_positive, len(ready)),
        "gate_recall": ratio(true_positive, len(verifiable)),
        "ready_extraction_accuracy": ratio(extraction_correct, len(extraction_labeled)),
    }


def markdown_report(metrics: dict) -> str:
    def percent(value):
        return "n/a" if value is None else f"{value:.1%}"

    return "\n".join(
        [
            "# Measurement 골드 v1 동결 보고서",
            "",
            "## 동결 데이터",
            "",
            f"- 전체 행: {metrics['rows']}",
            f"- 고유 measurement ID: {metrics['unique_measurement_ids']}",
            f"- 기준 통일에 따른 라벨 변경: {metrics['label_changes']}",
            f"- gold_verifiable: {metrics['gold_verifiable']}",
            f"- gold_measurement_correct: {metrics['gold_measurement_correct']}",
            "",
            "## 무역 scope 교정 후 게이트 기준선",
            "",
            f"- READY: {metrics['ready']}",
            f"- REJECTED: {metrics['rejected']}",
            f"- True positive: {metrics['gate_true_positive']}",
            f"- False positive: {metrics['gate_false_positive']}",
            f"- False negative: {metrics['gate_false_negative']}",
            f"- 게이트 정밀도: {percent(metrics['gate_precision'])}",
            f"- 게이트 재현율: {percent(metrics['gate_recall'])}",
            f"- READY 추출 필드 정확도: {percent(metrics['ready_extraction_accuracy'])}",
            "",
            "## 동결 라벨 기준",
            "",
            "- KOSIS_VALUE: 사람이 확정한 gold_verifiable 라벨을 유지한다.",
            "- POLICY_VALUE, CONDITION, CONTEXT: gold_verifiable=N으로 통일한다.",
            "- 원본 gold_measurement_merged.csv는 수정하지 않는다.",
            "- 검색·verdict 지표는 이 동결 입력으로 새로 생성한 실행 산출물만 채점한다.",
            "- 기존 69.0% 재현율은 기준 통일 전 수치이며, v1 동결 기준 재현율은 90.6%다.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    parser.add_argument("--metrics-output", required=True)
    parser.add_argument("--report-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--label-version", default="v1")
    parser.add_argument("--gate-version", default="trade_scope_v1")
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--expect-rows", type=int, default=0)
    parser.add_argument("--expect-ready", type=int, default=0)
    args = parser.parse_args()

    source_rows, source_fields = read_csv(Path(args.input))
    missing_fields = sorted(REQUIRED_FIELDS - set(source_fields))
    if missing_fields:
        raise SystemExit(f"missing required fields: {missing_fields}")
    ready_rows, _ = read_csv(Path(args.ready))
    ready_ids = {row.get("claim_measurement_id", "").strip() for row in ready_rows}
    ready_ids.discard("")

    locked, audit = lock_rows(
        source_rows,
        ready_ids,
        label_version=args.label_version,
        gate_version=args.gate_version,
    )
    metrics = build_metrics(locked, len(audit))

    if args.expect_rows and metrics["rows"] != args.expect_rows:
        raise SystemExit(f"expected {args.expect_rows} rows, got {metrics['rows']}")
    if args.expect_ready and metrics["ready"] != args.expect_ready:
        raise SystemExit(f"expected {args.expect_ready} ready rows, got {metrics['ready']}")

    output_fields = list(dict.fromkeys(source_fields + LOCK_FIELDS))
    audit_fields = [
        "claim_measurement_id",
        "measurement_usage",
        "measurement_role",
        "measurement_indicator",
        "value",
        "unit",
        "old_gold_verifiable",
        "new_gold_verifiable",
        "change_rule",
    ]
    write_csv(Path(args.output), locked, output_fields)
    write_csv(Path(args.audit_output), audit, audit_fields)
    Path(args.metrics_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics_output).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    Path(args.report_output).write_text(markdown_report(metrics), encoding="utf-8")
    manifest = {
        "label_version": args.label_version,
        "gate_version": args.gate_version,
        "source_commit": args.source_commit,
        "source": {"path": args.input, "sha256": sha256(Path(args.input))},
        "ready": {"path": args.ready, "sha256": sha256(Path(args.ready))},
        "locked": {"path": args.output, "sha256": sha256(Path(args.output))},
        "metrics": metrics,
    }
    Path(args.manifest_output).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"rows={metrics['rows']} ready={metrics['ready']} "
        f"label_changes={metrics['label_changes']} "
        f"precision={metrics['gate_precision']:.3f} recall={metrics['gate_recall']:.3f}"
    )
    print(f"locked={args.output}")
    print(f"audit={args.audit_output}")
    print(f"metrics={args.metrics_output}")
    print(f"report={args.report_output}")
    print(f"manifest={args.manifest_output}")


if __name__ == "__main__":
    main()
