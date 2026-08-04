#!/usr/bin/env python3
"""Build manual labeling files for a new news holdout batch.

This adapter deliberately stops before the KOSIS first-ready gate.  It only
normalizes article IDs, preserves raw/clean article text, reshapes existing
is_claim / HCX measurement outputs, and appends empty gold-label columns.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from preprocess_news import clean_article_body


ARTICLE_COLUMNS = [
    "article_id",
    "article_order",
    "article_title",
    "article_date",
    "article_url",
    "article_text_raw",
    "article_text_clean",
    "search_label_original",
]

CLAIM_COLUMNS = [
    "article_id",
    "claim_id",
    "article_date",
    "article_title",
    "article_url",
    "claim_text",
    "prev_sentence",
    "next_sentence",
    "is_claim",
    "is_claim_reason",
]

MEASUREMENT_GOLD_COLUMNS = [
    "gold_measurement_exists",
    "gold_measurement_correct",
    "gold_indicator",
    "gold_value",
    "gold_unit",
    "gold_period_current",
    "gold_period_base",
    "gold_periodicity",
    "gold_measurement_role",
    "gold_change_type",
    "gold_measurement_observation_type",
    "gold_source_scope",
    "gold_source_org",
    "gold_measurement_note",
    "gold_first_ready",
    "gold_front_gate_status",
    "gold_front_gate_reason",
    "gold_kosis_verifiable_2025",
    "gold_verifiability_reason",
    "gold_org_id",
    "gold_tbl_id",
    "gold_tbl_name",
    "gold_itm_ids",
    "gold_itm_names",
    "gold_obj_codes",
    "gold_obj_names",
    "gold_mapping_feasibility",
    "gold_formula_type",
    "gold_formula_expression",
    "gold_period_query",
    "gold_actual_value",
    "gold_actual_unit",
    "gold_claim_true",
    "gold_verdict",
    "gold_final_status",
    "evidence_url",
    "evidence_note",
    "annotator",
    "annotation_date",
    "second_reviewer",
    "adjudication_status",
    "adjudication_note",
    "leakage_check",
]

COVERAGE_GOLD_COLUMNS = [
    "gold_should_have_measurement",
    "gold_expected_measurement_count",
    "gold_missing_measurement_note",
    "reviewer",
]


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def remove_leading_article_number(text: str) -> str:
    """Remove only a crawler/media count at the very beginning."""
    return re.sub(r"^\s*\d+\s+", "", str(text or ""), count=1)


def build_clean_articles(input_path: Path, output_path: Path, start_number: int) -> list[dict[str, str]]:
    rows, fieldnames = read_csv(input_path)
    required = ["기사제목", "작성일", "URL", "기사 본문(정제)"]
    missing = [column for column in required if column not in fieldnames]
    if missing:
        raise SystemExit(f"입력 CSV 필수 컬럼이 없습니다: {missing}; 실제 컬럼={fieldnames}")

    clean_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        article_number = start_number + index
        raw_text = str(row.get("기사 본문(정제)", "") or "")
        text_without_prefix = remove_leading_article_number(raw_text)
        clean_text = clean_article_body(text_without_prefix, title=str(row.get("기사제목", "") or ""))
        clean_rows.append(
            {
                "article_id": f"HOLDOUT-A{article_number:03d}",
                "article_order": str(article_number),
                "article_title": str(row.get("기사제목", "") or "").strip(),
                "article_date": str(row.get("작성일", "") or "").strip(),
                "article_url": str(row.get("URL", "") or "").strip(),
                "article_text_raw": raw_text,
                "article_text_clean": clean_text,
                "search_label_original": str(row.get("검색 구분 레이블", "") or "").strip(),
            }
        )

    write_csv(output_path, clean_rows, ARTICLE_COLUMNS)
    return clean_rows


def reshape_claims(is_claim_path: Path, output_path: Path) -> list[dict[str, str]]:
    rows, _ = read_csv(is_claim_path)
    claim_rows: list[dict[str, str]] = []
    for row in rows:
        is_claim = str(row.get("is_claim", "") or "").strip()
        if is_claim.lower() != "true":
            continue
        claim_rows.append(
            {
                "article_id": row.get("article_id", ""),
                "claim_id": row.get("claim_id", ""),
                "article_date": row.get("date", ""),
                "article_title": row.get("title", ""),
                "article_url": row.get("url", ""),
                "claim_text": row.get("claim_text", ""),
                "prev_sentence": row.get("prev_sentence", ""),
                "next_sentence": row.get("next_sentence", ""),
                "is_claim": is_claim,
                "is_claim_reason": row.get("is_claim_reason", ""),
            }
        )
    write_csv(output_path, claim_rows, CLAIM_COLUMNS)
    return claim_rows


def _measurement_aliases(row: dict[str, str]) -> dict[str, str]:
    return {
        "article_date": row.get("date", ""),
        "article_title": row.get("title", ""),
        "article_url": row.get("url", ""),
        "measurement_value": row.get("value", ""),
        "measurement_unit": row.get("unit", ""),
        "measurement_periodicity": row.get("measurement_prd_se", ""),
        "change_type": row.get("change_base", ""),
        "approximate": row.get("value_approximate", ""),
        "formula_expression": "",
        "hcx_model": row.get("hcx_model") or row.get("extraction_model", ""),
    }


def build_gold_labeling(measurements_path: Path, output_path: Path) -> list[dict[str, str]]:
    rows, fieldnames = read_csv(measurements_path)
    output_rows: list[dict[str, str]] = []
    alias_fields = [
        "article_date",
        "article_title",
        "article_url",
        "measurement_value",
        "measurement_unit",
        "measurement_periodicity",
        "change_type",
        "approximate",
        "formula_expression",
    ]
    out_fields = list(fieldnames)
    for field in alias_fields:
        if field not in out_fields:
            out_fields.append(field)
    for field in MEASUREMENT_GOLD_COLUMNS:
        if field not in out_fields:
            out_fields.append(field)

    for row in rows:
        out = dict(row)
        out.update(_measurement_aliases(row))
        for field in MEASUREMENT_GOLD_COLUMNS:
            out[field] = ""
        output_rows.append(out)

    write_csv(output_path, output_rows, out_fields)
    return output_rows


def build_coverage_review(
    claims_path: Path,
    measurements_path: Path,
    output_path: Path,
) -> list[dict[str, str]]:
    claims, _ = read_csv(claims_path)
    measurements, _ = read_csv(measurements_path)
    by_claim: dict[str, list[dict[str, str]]] = defaultdict(list)
    parse_success_by_claim: dict[str, str] = {}
    error_by_claim: dict[str, str] = {}
    for row in measurements:
        claim_id = row.get("claim_id", "")
        if not claim_id:
            continue
        if row.get("claim_measurement_id", "") not in {"", "-"}:
            by_claim[claim_id].append(row)
        parse_success_by_claim[claim_id] = row.get("hcx_parse_success", "")
        error_by_claim[claim_id] = row.get("hcx_error", "")

    out_rows: list[dict[str, str]] = []
    for claim in claims:
        claim_id = claim.get("claim_id", "")
        claim_measurements = by_claim.get(claim_id, [])
        out = {
            "article_id": claim.get("article_id", ""),
            "claim_id": claim_id,
            "claim_text": claim.get("claim_text", ""),
            "prev_sentence": claim.get("prev_sentence", ""),
            "next_sentence": claim.get("next_sentence", ""),
            "hcx_measurement_count": str(len(claim_measurements)),
            "hcx_measurement_ids": "|".join(row.get("claim_measurement_id", "") for row in claim_measurements),
            "hcx_parse_success": parse_success_by_claim.get(claim_id, ""),
            "hcx_error": error_by_claim.get(claim_id, ""),
        }
        for field in COVERAGE_GOLD_COLUMNS:
            out[field] = ""
        out_rows.append(out)

    fieldnames = [
        "article_id",
        "claim_id",
        "claim_text",
        "prev_sentence",
        "next_sentence",
        "hcx_measurement_count",
        "hcx_measurement_ids",
        "hcx_parse_success",
        "hcx_error",
        *COVERAGE_GOLD_COLUMNS,
    ]
    write_csv(output_path, out_rows, fieldnames)
    return out_rows


def build_summary(
    output_path: Path,
    articles: list[dict[str, str]],
    sentence_path: Path,
    is_claim_path: Path,
    claim_rows: list[dict[str, str]],
    measurement_rows: list[dict[str, str]],
    coverage_rows: list[dict[str, str]],
) -> dict[str, object]:
    sentences, _ = read_csv(sentence_path)
    is_claim_rows, _ = read_csv(is_claim_path)
    measurement_ids = [
        row.get("claim_measurement_id", "")
        for row in measurement_rows
        if row.get("claim_measurement_id", "") not in {"", "-"}
    ]
    claims_with_measurements = {
        row.get("claim_id", "")
        for row in measurement_rows
        if row.get("claim_measurement_id", "") not in {"", "-"}
    }
    count_by_claim = Counter(
        row.get("claim_id", "")
        for row in measurement_rows
        if row.get("claim_measurement_id", "") not in {"", "-"}
    )
    summary = {
        "input_articles": len(articles),
        "clean_articles": len(articles),
        "sentences": len(sentences),
        "claim_candidates": len(is_claim_rows),
        "is_claim_true": sum(1 for row in is_claim_rows if str(row.get("is_claim", "")).strip().lower() == "true"),
        "unique_claims": len({row.get("claim_id", "") for row in claim_rows}),
        "measurement_rows": len(measurement_ids),
        "claims_with_measurements": len(claims_with_measurements),
        "claims_without_measurements": sum(1 for row in coverage_rows if row.get("hcx_measurement_count") == "0"),
        "multi_measurement_claims": sum(1 for count in count_by_claim.values() if count > 1),
        "hcx_parse_success": Counter(row.get("hcx_parse_success", "") for row in measurement_rows),
        "hcx_parse_failure": sum(1 for row in measurement_rows if row.get("hcx_parse_success") == "N"),
        "observation_type_distribution": Counter(row.get("measurement_observation_type", "") for row in measurement_rows),
        "source_scope_distribution": Counter(row.get("source_scope", "") for row in measurement_rows),
    }
    serializable = {
        key: dict(value) if isinstance(value, Counter) else value
        for key, value in summary.items()
    }
    output_path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return serializable


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    clean = subparsers.add_parser("clean-articles")
    clean.add_argument("--input", required=True, type=Path)
    clean.add_argument("--output", required=True, type=Path)
    clean.add_argument("--start-number", type=int, default=51)

    claims = subparsers.add_parser("claims")
    claims.add_argument("--is-claim", required=True, type=Path)
    claims.add_argument("--output", required=True, type=Path)

    gold = subparsers.add_parser("gold-labeling")
    gold.add_argument("--measurements", required=True, type=Path)
    gold.add_argument("--output", required=True, type=Path)

    coverage = subparsers.add_parser("coverage")
    coverage.add_argument("--claims", required=True, type=Path)
    coverage.add_argument("--measurements", required=True, type=Path)
    coverage.add_argument("--output", required=True, type=Path)

    summary = subparsers.add_parser("summary")
    summary.add_argument("--articles", required=True, type=Path)
    summary.add_argument("--sentences", required=True, type=Path)
    summary.add_argument("--is-claim", required=True, type=Path)
    summary.add_argument("--claims", required=True, type=Path)
    summary.add_argument("--measurements", required=True, type=Path)
    summary.add_argument("--coverage", required=True, type=Path)
    summary.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()

    if args.command == "clean-articles":
        rows = build_clean_articles(args.input, args.output, args.start_number)
        print(f"saved={args.output} rows={len(rows)}")
    elif args.command == "claims":
        rows = reshape_claims(args.is_claim, args.output)
        print(f"saved={args.output} rows={len(rows)}")
    elif args.command == "gold-labeling":
        rows = build_gold_labeling(args.measurements, args.output)
        print(f"saved={args.output} rows={len(rows)}")
    elif args.command == "coverage":
        rows = build_coverage_review(args.claims, args.measurements, args.output)
        print(f"saved={args.output} rows={len(rows)}")
    elif args.command == "summary":
        articles, _ = read_csv(args.articles)
        claims_rows, _ = read_csv(args.claims)
        measurement_rows, _ = read_csv(args.measurements)
        coverage_rows, _ = read_csv(args.coverage)
        data = build_summary(
            args.output,
            articles,
            args.sentences,
            args.is_claim,
            claims_rows,
            measurement_rows,
            coverage_rows,
        )
        print(f"saved={args.output}")
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
