#!/usr/bin/env python3
"""Analyze KOSIS mapping runs without a gold set.

This script is intentionally diagnostic, not a scorer.  It helps answer three
questions that do not require frozen labels:

1. Why did API_ERROR rows fail?
2. Which NEEDS_CONFIRMATION rows should be sent to human-in-the-loop correction?
3. How different are lexical and hybrid table-retrieval outputs?
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def first(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def measurement_id(row: Mapping[str, Any]) -> str:
    return first(row, "claim_measurement_id", "claim_id")


def table_key(row: Mapping[str, Any]) -> str:
    return f"{first(row, 'org_id')}::{first(row, 'tbl_id')}"


def parse_candidate_combinations(value: str) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def classify_api_error(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return a stable machine code and a short Korean explanation."""
    blob = " ".join(
        [
            first(row, "api_error", "status_reason", "mapping_reason"),
            first(row, "candidate_obj_combinations"),
        ]
    )
    combos = parse_candidate_combinations(first(row, "candidate_obj_combinations"))
    combo_errors = " ".join(str(c.get("api_error", "")) for c in combos)
    text = f"{blob} {combo_errors}"

    if "데이터가 존재하지 않습니다" in text or "데이터가 존재하지 않" in text:
        return "NO_DATA_FOR_COMBINATION", "요청 ITEM/OBJ/기간 조합에 해당하는 KOSIS 데이터 없음"
    if "수록 시점" in text and "숫자만" in text:
        return "INVALID_PERIOD_FORMAT", "KOSIS 기간 파라미터가 숫자 형식이 아님"
    if "잘못된 요청 변수" in text or "잘못된 요청 변수를 호출" in text:
        return "BAD_REQUEST_VARIABLE", "KOSIS가 일부 파라미터 조합을 잘못된 요청 변수로 거절"
    if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in text or "인증" in text or "API key" in text:
        return "AUTH_OR_API_KEY", "API 키/인증 관련 오류"
    if "Timeout" in text or "timed out" in text:
        return "TIMEOUT", "네트워크 또는 KOSIS 응답 지연"
    if "ConnectionError" in text or "Max retries" in text:
        return "NETWORK", "네트워크 연결 오류"
    if re.search(r"HTTP\s*[45]\d\d|status code\s*[45]\d\d", text, re.I):
        return "HTTP_ERROR", "HTTP 4xx/5xx 응답"
    if "JSONDecodeError" in text or "Expecting value" in text:
        return "NON_JSON_RESPONSE", "KOSIS 응답이 JSON 형식이 아님"
    if first(row, "api_error_count") and first(row, "api_error_count") != "0":
        return "UNCLASSIFIED_API_ERROR", "세부 문자열이 부족한 API 오류"
    return "NO_API_ERROR_DETAIL", "행에 API 오류 상세가 없음"


def api_error_report(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if first(row, "mapping_status") != "API_ERROR":
            continue
        code, reason = classify_api_error(row)
        out.append(
            {
                "claim_measurement_id": measurement_id(row),
                "indicator": first(row, "indicator"),
                "tbl_id": first(row, "tbl_id"),
                "tbl_name": first(row, "tbl_name"),
                "candidate_rank": first(row, "candidate_rank"),
                "candidate_status": first(row, "candidate_status"),
                "api_error_type": code,
                "api_error_reason": reason,
                "api_error_count": first(row, "api_error_count"),
                "request_error_count": first(row, "request_error_count"),
                "response_mismatch_count": first(row, "response_mismatch_count"),
                "candidate_obj_combinations": first(row, "candidate_obj_combinations"),
            }
        )
    return out


def hitl_template(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if first(row, "mapping_status") != "NEEDS_CONFIRMATION":
            continue
        out.append(
            {
                "claim_measurement_id": measurement_id(row),
                "claim_text": first(row, "claim_text"),
                "indicator": first(row, "indicator"),
                "industry_or_item": first(row, "industry_or_item"),
                "period": first(row, "period"),
                "comparison_period": first(row, "comparison_period"),
                "mapping_reason": first(row, "mapping_reason"),
                "high_risk_missing": first(row, "high_risk_missing"),
                "candidate_rank": first(row, "candidate_rank"),
                "org_id": first(row, "org_id"),
                "tbl_id": first(row, "tbl_id"),
                "tbl_name": first(row, "tbl_name"),
                "selected_itm_id": first(row, "selected_itm_id"),
                "selected_itm_name": first(row, "selected_itm_name"),
                "selected_obj_l1": first(row, "selected_obj_l1"),
                "selected_obj_l1_name": first(row, "selected_obj_l1_name"),
                "selected_obj_l2": first(row, "selected_obj_l2"),
                "selected_obj_l2_name": first(row, "selected_obj_l2_name"),
                "human_decision": "",
                "correct_tbl_id": "",
                "correct_itm_id": "",
                "correct_obj_l1": "",
                "correct_obj_l2": "",
                "correct_obj_l3": "",
                "correction_note": "",
            }
        )
    return out


def hitl_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        first(row, "claim_measurement_id", "claim_id"),
        first(row, "tbl_id", "correct_tbl_id"),
        first(row, "selected_itm_id", "correct_itm_id"),
        first(row, "selected_obj_l1", "correct_obj_l1"),
        first(row, "selected_obj_l2", "correct_obj_l2"),
        first(row, "selected_obj_l3", "correct_obj_l3"),
    )


def merge_hitl_store(existing: list[dict[str, str]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accumulate HITL rows while preserving human-written correction columns."""
    preserved_columns = {
        "human_decision", "correct_tbl_id", "correct_itm_id", "correct_obj_l1",
        "correct_obj_l2", "correct_obj_l3", "correction_note",
    }
    merged: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {
        hitl_key(row): dict(row) for row in existing
    }
    for row in fresh:
        key = hitl_key(row)
        if key in merged:
            previous = merged[key]
            merged[key] = {**row, **{col: previous.get(col, row.get(col, "")) for col in preserved_columns}}
        else:
            merged[key] = dict(row)
    return list(merged.values())


def top_by_measurement(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = measurement_id(row)
        if key:
            grouped[key].append(row)
    for values in grouped.values():
        values.sort(key=lambda r: int(float(first(r, "candidate_rank") or "999")))
    return grouped


def compare_retrieval(lexical_rows: list[dict[str, str]], hybrid_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    lexical = top_by_measurement(lexical_rows)
    hybrid = top_by_measurement(hybrid_rows)
    out = []
    for key in sorted(set(lexical) | set(hybrid)):
        lex = lexical.get(key, [])
        hyb = hybrid.get(key, [])
        lex_top = lex[0] if lex else {}
        hyb_top = hyb[0] if hyb else {}
        lex_top5 = {table_key(row) for row in lex[:5]}
        hyb_top5 = {table_key(row) for row in hyb[:5]}
        overlap = len(lex_top5 & hyb_top5)
        out.append(
            {
                "claim_measurement_id": key,
                "indicator": first(lex_top, "indicator") or first(hyb_top, "indicator"),
                "lexical_top1_tbl_id": first(lex_top, "tbl_id"),
                "lexical_top1_tbl_name": first(lex_top, "tbl_name"),
                "lexical_top1_score": first(lex_top, "candidate_score"),
                "lexical_top1_status": first(lex_top, "candidate_status"),
                "hybrid_top1_tbl_id": first(hyb_top, "tbl_id"),
                "hybrid_top1_tbl_name": first(hyb_top, "tbl_name"),
                "hybrid_top1_score": first(hyb_top, "candidate_score"),
                "hybrid_top1_status": first(hyb_top, "candidate_status"),
                "top1_same": "Y" if table_key(lex_top) == table_key(hyb_top) else "N",
                "top5_overlap": overlap,
                "top5_overlap_ratio": round(overlap / 5, 3),
            }
        )
    return out


def print_counts(label: str, rows: list[dict[str, Any]], column: str) -> None:
    counter = Counter(str(row.get(column, "")) for row in rows)
    print(f"\n{label}: {len(rows)} rows")
    for value, count in counter.most_common(20):
        print(f"  {value or '(blank)'}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold-free KOSIS mapping run analyzer")
    parser.add_argument("--validated", help="*_kosis_validated_mappings.csv")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--hitl-store",
        help="누적 HITL 보정 CSV. 있으면 사람이 적은 보정값을 보존하며 새 NEEDS_CONFIRMATION을 추가",
    )
    parser.add_argument("--lexical-candidates", help="Lexical *_kosis_table_candidates.csv")
    parser.add_argument("--hybrid-candidates", help="Hybrid *_kosis_table_candidates.csv")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if args.validated:
        rows = read_csv(Path(args.validated))
        api_rows = api_error_report(rows)
        hitl_rows = hitl_template(rows)
        write_csv(out_dir / "api_error_report.csv", api_rows)
        if args.hitl_store:
            store_path = Path(args.hitl_store)
            existing = read_csv(store_path) if store_path.exists() else []
            hitl_rows = merge_hitl_store(existing, hitl_rows)
            write_csv(store_path, hitl_rows)
            hitl_output = store_path
        else:
            hitl_output = out_dir / "hitl_corrections_template.csv"
            write_csv(hitl_output, hitl_rows)
        print_counts("mapping_status", rows, "mapping_status")
        print_counts("api_error_type", api_rows, "api_error_type")
        print_counts("hitl_mapping_reason", hitl_rows, "mapping_reason")
        print(f"\napi_error_report={out_dir / 'api_error_report.csv'}")
        print(f"hitl_corrections={hitl_output}")

    if args.lexical_candidates and args.hybrid_candidates:
        comparison = compare_retrieval(
            read_csv(Path(args.lexical_candidates)),
            read_csv(Path(args.hybrid_candidates)),
        )
        write_csv(out_dir / "lexical_vs_hybrid_comparison.csv", comparison)
        print_counts("retrieval_top1_same", comparison, "top1_same")
        overlaps = Counter(str(row.get("top5_overlap")) for row in comparison)
        print("\ntop5_overlap:")
        for value, count in sorted(overlaps.items()):
            print(f"  {value}: {count}")
        print(f"\nlexical_vs_hybrid_comparison={out_dir / 'lexical_vs_hybrid_comparison.csv'}")


if __name__ == "__main__":
    main()
