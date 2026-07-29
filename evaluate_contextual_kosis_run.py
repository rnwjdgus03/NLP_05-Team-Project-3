"""Summarize a contextual news-to-KOSIS run with stable denominators."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ARTIFACTS = {
    "sentences": "01_sentences.csv",
    "chunks": "02_chunks.csv",
    "spans": "03_claim_spans.csv",
    "measurements": "05_hcx_measurements.csv",
    "ready": "06_mapping_ready.csv",
    "enrich": "06_mapping_enrich.csv",
    "reject": "06_mapping_reject.csv",
    "validated": "07_mapping/05_hcx_measurements_kosis_validated_mappings.csv",
    "verified": "07_mapping/05_hcx_measurements_kosis_verified.csv",
}

CONCLUSIVE_VERDICTS = {"일치", "불일치", "MATCH", "MISMATCH"}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def measurement_key(row: Mapping[str, Any]) -> str:
    return str(row.get("claim_measurement_id") or row.get("claim_id") or "").strip()


def unique_count(rows: Iterable[Mapping[str, Any]], field: str) -> int:
    return len(
        {
            str(row.get(field, "")).strip()
            for row in rows
            if str(row.get(field, "")).strip()
        }
    )


def rank_value(row: Mapping[str, Any]) -> int:
    try:
        return int(str(row.get("candidate_rank", "999")).strip())
    except ValueError:
        return 999


def final_mapping_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep one final candidate row per measurement instead of counting Top-K rows."""
    selected: dict[str, dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        key = measurement_key(row)
        if not key:
            continue
        current = selected.get(key)
        if current is None or rank_value(row) < rank_value(current):
            selected[key] = row
    return list(selected.values())


def percentage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 3)


def reason_rows(
    stage: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    code_field: str,
    detail_field: str,
    bucket_field: str | None = None,
) -> list[dict[str, Any]]:
    rows = list(rows)
    denominator = len(rows)
    counts = Counter(
        (
            str(row.get(bucket_field, "") or "-") if bucket_field else stage,
            str(row.get(code_field, "") or "-"),
            str(row.get(detail_field, "") or "-"),
        )
        for row in rows
    )
    return [
        {
            "stage": stage,
            "bucket": bucket,
            "reason_code": code,
            "reason_detail": detail,
            "count": count,
            "denominator": denominator,
            "share_pct": percentage(count, denominator),
        }
        for (bucket, code, detail), count in counts.most_common()
    ]


def evaluate_run(run_dir: Path) -> dict[str, Any]:
    paths = {name: run_dir / relative for name, relative in ARTIFACTS.items()}
    rows = {name: read_rows(path) for name, path in paths.items()}
    mapping_rows = final_mapping_rows(rows["validated"])

    measurement_count = len(rows["measurements"])
    ready_count = len(rows["ready"])
    enrich_count = len(rows["enrich"])
    reject_count = len(rows["reject"])
    validated_ready = sum(
        str(row.get("mapping_status", "")).strip().upper() == "READY"
        for row in mapping_rows
    )
    verified_count = len(rows["verified"])
    conclusive_count = sum(
        str(row.get("verdict", "")).strip() in CONCLUSIVE_VERDICTS
        for row in rows["verified"]
    )
    inconclusive_count = verified_count - conclusive_count

    counts = {
        "articles": unique_count(rows["sentences"], "article_id"),
        "sentences": len(rows["sentences"]),
        "chunks": len(rows["chunks"]),
        "claim_spans": len(rows["spans"]),
        "span_claims": unique_count(rows["spans"], "claim_id"),
        "measurements": measurement_count,
        "measurement_claims": unique_count(rows["measurements"], "claim_id"),
        "gate_ready": ready_count,
        "gate_enrich": enrich_count,
        "gate_reject": reject_count,
        "validated_measurements": len(mapping_rows),
        "validated_ready": validated_ready,
        "verified": verified_count,
        "conclusive_verdicts": conclusive_count,
        "inconclusive_verdicts": inconclusive_count,
    }
    rates = {
        "ready_reach_pct": percentage(ready_count, measurement_count),
        "enrich_reach_pct": percentage(enrich_count, measurement_count),
        "reject_reach_pct": percentage(reject_count, measurement_count),
        "mapping_ready_pct": percentage(validated_ready, ready_count),
        "verification_success_pct": percentage(conclusive_count, validated_ready),
        "inconclusive_pct": percentage(inconclusive_count, verified_count),
        "end_to_end_conclusive_pct": percentage(conclusive_count, measurement_count),
    }
    verdicts = Counter(
        str(row.get("verdict", "") or "-") for row in rows["verified"]
    )
    mapping_statuses = Counter(
        str(row.get("mapping_status", "") or "-") for row in mapping_rows
    )

    reasons: list[dict[str, Any]] = []
    reasons.extend(
        reason_rows(
            "gate",
            rows["enrich"],
            code_field="mapping_exclusion_code",
            detail_field="enrichment_actions",
            bucket_field="mapping_gate",
        )
    )
    reasons.extend(
        reason_rows(
            "gate",
            rows["reject"],
            code_field="mapping_exclusion_code",
            detail_field="mapping_gate_reason",
            bucket_field="mapping_gate",
        )
    )
    reasons.extend(
        reason_rows(
            "mapping",
            [
                row
                for row in mapping_rows
                if str(row.get("mapping_status", "")).strip().upper() != "READY"
            ],
            code_field="mapping_reason",
            detail_field="candidate_status_reason",
            bucket_field="mapping_status",
        )
    )
    reasons.extend(
        reason_rows(
            "verification",
            rows["verified"],
            code_field="verdict_code",
            detail_field="verdict_reason",
            bucket_field="verdict",
        )
    )

    return {
        "run_dir": str(run_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {name: str(path) for name, path in paths.items()},
        "counts": counts,
        "rates": rates,
        "mapping_statuses": dict(mapping_statuses),
        "verdicts": dict(verdicts),
        "reasons": reasons,
    }


def metric_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    counts = result["counts"]
    rates = result["rates"]
    rows = [
        ("input", "articles", counts["articles"], "", None, "distinct article_id"),
        ("preprocess", "sentences", counts["sentences"], "", None, "sentence rows"),
        ("context", "chunks", counts["chunks"], "", None, "overlapping chunks"),
        ("claim", "claim_spans", counts["claim_spans"], "", None, "detected span rows"),
        ("measurement", "measurements", counts["measurements"], "", None, "HCX measurement rows"),
        (
            "gate",
            "READY reach",
            counts["gate_ready"],
            counts["measurements"],
            rates["ready_reach_pct"],
            "READY / all measurements",
        ),
        (
            "gate",
            "ENRICH reach",
            counts["gate_enrich"],
            counts["measurements"],
            rates["enrich_reach_pct"],
            "ENRICH / all measurements",
        ),
        (
            "gate",
            "REJECT reach",
            counts["gate_reject"],
            counts["measurements"],
            rates["reject_reach_pct"],
            "REJECT / all measurements",
        ),
        (
            "mapping",
            "validated READY",
            counts["validated_ready"],
            counts["gate_ready"],
            rates["mapping_ready_pct"],
            "mapping READY / gate READY",
        ),
        (
            "verification",
            "conclusive verdict",
            counts["conclusive_verdicts"],
            counts["validated_ready"],
            rates["verification_success_pct"],
            "MATCH or MISMATCH / validated READY",
        ),
        (
            "verification",
            "inconclusive verdict",
            counts["inconclusive_verdicts"],
            counts["verified"],
            rates["inconclusive_pct"],
            "판단불가 / verified rows",
        ),
        (
            "end_to_end",
            "conclusive coverage",
            counts["conclusive_verdicts"],
            counts["measurements"],
            rates["end_to_end_conclusive_pct"],
            "conclusive verdict / all measurements",
        ),
    ]
    return [
        {
            "stage": stage,
            "metric": metric,
            "count": count,
            "denominator": denominator,
            "rate_pct": rate,
            "description": description,
        }
        for stage, metric, count, denominator, rate, description in rows
    ]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def markdown_report(result: Mapping[str, Any], metrics: list[dict[str, Any]]) -> str:
    lines = [
        "# Contextual News-KOSIS Evaluation",
        "",
        f"- Run: `{result['run_dir']}`",
        f"- Generated: `{result['generated_at']}`",
        "",
        "## Funnel",
        "",
        "| Stage | Metric | Count | Denominator | Rate |",
        "|---|---|---:|---:|---:|",
    ]
    for row in metrics:
        rate = "-" if row["rate_pct"] is None else f"{row['rate_pct']:.3f}%"
        denominator = row["denominator"] if row["denominator"] != "" else "-"
        lines.append(
            f"| {row['stage']} | {row['metric']} | {row['count']} | "
            f"{denominator} | {rate} |"
        )
    lines.extend(
        [
            "",
            "## Mapping Status",
            "",
            "| Status | Count |",
            "|---|---:|",
        ]
    )
    for status, count in result["mapping_statuses"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            "| Verdict | Count |",
            "|---|---:|",
        ]
    )
    for verdict, count in result["verdicts"].items():
        lines.append(f"| {verdict} | {count} |")
    lines.extend(
        [
            "",
            "## Reasons",
            "",
            "| Stage | Bucket | Code | Count | Share | Detail |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for row in result["reasons"]:
        share = "-" if row["share_pct"] is None else f"{row['share_pct']:.3f}%"
        detail = str(row["reason_detail"]).replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {row['stage']} | {row['bucket']} | {row['reason_code']} | "
            f"{row['count']} | {share} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate READY, mapping, verification, and reason metrics."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=None,
        help="Default: <run-dir>/08_evaluation",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_dir = args.run_dir.expanduser()
    output_prefix = (args.output_prefix or run_dir / "08_evaluation").expanduser()
    result = evaluate_run(run_dir)
    metrics = metric_rows(result)

    summary_csv = output_prefix.with_name(output_prefix.name + "_summary.csv")
    reasons_csv = output_prefix.with_name(output_prefix.name + "_reasons.csv")
    summary_json = output_prefix.with_name(output_prefix.name + "_summary.json")
    report_md = output_prefix.with_name(output_prefix.name + "_report.md")

    write_csv(
        summary_csv,
        metrics,
        ["stage", "metric", "count", "denominator", "rate_pct", "description"],
    )
    write_csv(
        reasons_csv,
        result["reasons"],
        [
            "stage",
            "bucket",
            "reason_code",
            "reason_detail",
            "count",
            "denominator",
            "share_pct",
        ],
    )
    summary_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_md.write_text(markdown_report(result, metrics), encoding="utf-8")

    print(f"summary={summary_csv}")
    print(f"reasons={reasons_csv}")
    print(f"report={report_md}")
    display_rate = lambda value: "-" if value is None else f"{value:.3f}"
    print(
        "READY={ready}/{measurements} ({ready_rate}%) | "
        "validated_READY={validated}/{ready} ({mapping_rate}%) | "
        "conclusive={conclusive}/{validated} ({verification_rate}%)".format(
            ready=result["counts"]["gate_ready"],
            measurements=result["counts"]["measurements"],
            ready_rate=display_rate(result["rates"]["ready_reach_pct"]),
            validated=result["counts"]["validated_ready"],
            mapping_rate=display_rate(result["rates"]["mapping_ready_pct"]),
            conclusive=result["counts"]["conclusive_verdicts"],
            verification_rate=display_rate(
                result["rates"]["verification_success_pct"]
            ),
        )
    )


if __name__ == "__main__":
    main()
