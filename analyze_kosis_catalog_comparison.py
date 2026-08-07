"""Audit two KOSIS catalogs before running a claim-level retrieval benchmark.

The audit intentionally separates catalog structure from retrieval accuracy.
Without claim gold coordinates, retrieval scores are diagnostics rather than
accuracy measurements.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


SUMMARY_COLUMNS = {
    "table_name": ("TBL_NM", "tbl_name"),
    "org_id": ("ORG_ID", "org_id"),
    "tbl_id": ("TBL_ID", "tbl_id"),
    "axes": ("분류축", "axes"),
    "item_examples": ("항목_예시(최대5개)", "item_examples"),
    "item_count": ("항목_전체개수", "item_count"),
    "unit": ("단위", "unit_name", "UNIT_NM"),
    "category_path": ("category_path", "path"),
}


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def first(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def summary_value(row: dict[str, str], field: str) -> str:
    return first(row, SUMMARY_COLUMNS[field])


def table_key(row: dict[str, str]) -> tuple[str, str]:
    return summary_value(row, "org_id"), summary_value(row, "tbl_id")


def raw_index_key(row: dict[str, str]) -> tuple[str, str]:
    return first(row, ("ORG_ID", "org_id")), first(row, ("TBL_ID", "tbl_id"))


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def safe_int(value: str) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0


def axis_count(value: str) -> int:
    return len([part for part in re.split(r"[,|;/\s]+", value.strip()) if part])


def top_category(row: dict[str, str]) -> str:
    path = summary_value(row, "category_path")
    return path.split(">", 1)[0].strip() if path else "(없음)"


def summary_metrics(rows: list[dict[str, str]]) -> dict[str, object]:
    keys = [table_key(row) for row in rows]
    names = [summary_value(row, "table_name") for row in rows]
    organizations = Counter(key[0] for key in keys if key[0])
    categories = Counter(top_category(row) for row in rows)
    item_counts = [safe_int(summary_value(row, "item_count")) for row in rows]
    axis_counts = [axis_count(summary_value(row, "axes")) for row in rows]
    category_depths = [
        len([part for part in summary_value(row, "category_path").split(">") if part.strip()])
        for row in rows
    ]
    total = max(len(rows), 1)
    return {
        "rows": len(rows),
        "unique_table_keys": len(set(keys)),
        "duplicate_table_keys": len(keys) - len(set(keys)),
        "unique_table_names": len(set(names)),
        "duplicate_name_excess": len(names) - len(set(names)),
        "organizations": len(organizations),
        "organization_hhi": round(sum((count / total) ** 2 for count in organizations.values()), 6),
        "top_organizations": [
            {"org_id": org, "tables": count, "share_pct": round(count / total * 100, 2)}
            for org, count in organizations.most_common(10)
        ],
        "categories": dict(categories.most_common()),
        "category_shares_pct": {
            category: round(count / total * 100, 2) for category, count in categories.most_common()
        },
        "item_count": {
            "median": percentile(item_counts, 0.5),
            "mean": round(statistics.mean(item_counts), 3) if item_counts else 0.0,
            "p90": percentile(item_counts, 0.9),
            "max": max(item_counts, default=0),
        },
        "axis_count": {
            "median": percentile(axis_counts, 0.5),
            "mean": round(statistics.mean(axis_counts), 3) if axis_counts else 0.0,
            "p90": percentile(axis_counts, 0.9),
            "max": max(axis_counts, default=0),
        },
        "category_depth": {
            "median": percentile(category_depths, 0.5),
            "mean": round(statistics.mean(category_depths), 3) if category_depths else 0.0,
            "max": max(category_depths, default=0),
        },
        "missing_by_field": {
            field: sum(not summary_value(row, field) for row in rows) for field in SUMMARY_COLUMNS
        },
    }


def index_metrics(rows: list[dict[str, str]], headers: list[str]) -> dict[str, object]:
    keys = [raw_index_key(row) for row in rows]
    coordinate_keys = [
        (
            *raw_index_key(row),
            first(row, ("OBJ_ID", "axis_id", "obj_id")),
            first(row, ("ITM_ID", "code_id", "itm_id")),
        )
        for row in rows
    ]
    lower_headers = Counter(header.lower() for header in headers)
    duplicate_headers = sorted(name for name, count in lower_headers.items() if count > 1)
    return {
        "rows": len(rows),
        "unique_tables": len(set(keys)),
        "unique_coordinate_keys": len(set(coordinate_keys)),
        "duplicate_coordinate_key_excess": len(coordinate_keys) - len(set(coordinate_keys)),
        "blank_org_or_table_key_rows": sum(not org or not table for org, table in keys),
        "blank_obj_id_rows": sum(not first(row, ("OBJ_ID", "axis_id", "obj_id")) for row in rows),
        "blank_itm_id_rows": sum(not first(row, ("ITM_ID", "code_id", "itm_id")) for row in rows),
        "case_insensitive_duplicate_headers": duplicate_headers,
        "headers": headers,
    }


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def build_report(audit: dict[str, object], claims_path: Path | None) -> str:
    old = audit["old_summary"]
    new = audit["expanded_summary"]
    idx = audit["expanded_index"]
    overlap = audit["overlap"]
    coverage = audit["coordinate_coverage"]
    category_lines = "\n".join(
        f"| {row['category']} | {row['summary_tables']} | {row['indexed_tables']} | {row['coverage_pct']:.2f}% |"
        for row in coverage["by_category"]
    )
    claim_status = (
        f"입력 확인: `{claims_path}`. 별도 검색 벤치마크를 실행할 수 있다."
        if claims_path
        else "`kosis_ready_plus_improvable.csv`가 제공되지 않아 142건 검색 정확도·Recall·MRR은 계산하지 않았다."
    )
    return f"""# KOSIS 카탈로그 사전 감사: 37개 vs 4,811개

## 결론

현재 확장판은 원조 카탈로그의 단순 확대본이 아니다. 원조 37개 중 확장 summary와 겹치는 표는 {overlap['shared_tables']}개({overlap['old_retention_pct']:.2f}%)뿐이며, {overlap['old_missing_from_expanded']}개가 빠져 있다. 따라서 같은 claim에 대한 차이는 카탈로그 크기 효과와 주제 교체 효과가 섞인다.

확장 summary는 {new['rows']:,}행이다. 파일의 전체 줄 수(헤더 포함)는 4,812일 수 있지만 통계표 데이터는 4,811개다. 확장 meta index는 {idx['rows']:,}개 좌표와 {idx['unique_tables']:,}개 표만 포함하여 summary의 {coverage['indexed_tables']:,}/{coverage['summary_tables']:,}개({coverage['coverage_pct']:.2f}%)만 구조 검증할 수 있다.

## 핵심 지표

| 지표 | 원조 | 확장 summary |
|---|---:|---:|
| 통계표 | {old['rows']:,} | {new['rows']:,} |
| 기관 | {old['organizations']:,} | {new['organizations']:,} |
| 고유 표명 | {old['unique_table_names']:,} | {new['unique_table_names']:,} |
| 표당 항목 수 중앙값 | {old['item_count']['median']:.1f} | {new['item_count']['median']:.1f} |
| 표당 분류축 수 중앙값 | {old['axis_count']['median']:.1f} | {new['axis_count']['median']:.1f} |
| 기관 집중도 HHI | {old['organization_hhi']:.4f} | {new['organization_hhi']:.4f} |

확장판은 표 수는 크게 늘었지만 항목 수 중앙값은 {old['item_count']['median']:.1f}에서 {new['item_count']['median']:.1f}로 줄었고, 분류축 수도 더 많아지지 않았다. 즉 현재 파일만으로는 “표 내부가 더 세분화됐다”기보다 “특정 분야의 작은 표가 대량 추가됐다”는 해석이 더 적절하다.

## 주제 편향 및 좌표 완전성

| 최상위 분야 | summary 표 | 좌표가 있는 표 | 좌표 커버리지 |
|---|---:|---:|---:|
{category_lines}

확장 summary의 분야는 {', '.join(new['categories'].keys())} 네 개뿐이다. 특히 좌표 index는 금융과 무역ㆍ국제수지에만 있고, 도소매ㆍ서비스와 정부ㆍ재정은 0%다. 그래서 4,811개 표 전부를 ITEM/OBJ 검증에 사용할 수 없다.

meta index 헤더에는 대소문자만 다른 `ORG_ID`/`org_id`, `TBL_ID`/`tbl_id`가 함께 있다. Python `csv`는 읽지만 PowerShell `Import-Csv`는 중복 멤버 오류를 내며, 일부 데이터프레임 도구에서도 충돌 가능성이 있다.

## Claim 벤치마크 상태

{claim_status}

정확한 142건 비교에는 다음이 필요하다.

1. 동일한 `kosis_ready_plus_improvable.csv` 142행
2. 원조 `kosis_meta_index.csv`
3. 가능하면 claim별 정답 `(ORG_ID, TBL_ID)`와 ITEM/OBJ 좌표

정답 표가 없다면 BGE-M3·BM25의 점수나 margin은 후보 검색 진단일 뿐 정확도가 아니다. 이 경우에는 사람 라벨 top-k 적합도, 원조 top-1의 확장판 내 순위 보존율, 좌표 검증 성공률을 분리해 보고해야 한다.

## 판정

현재 파일 상태의 확장판은 **실험 가능하지만 기존 카탈로그 대체용으로는 부적합**하다. 먼저 37개 원조 표를 확장 summary에 합쳐 합집합을 만들고, 4,811개 전체의 좌표 index를 동일 스키마로 재생성한 뒤 142건 A/B 검색을 실행해야 한다.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-summary", type=Path, required=True)
    parser.add_argument("--expanded-summary", type=Path, required=True)
    parser.add_argument("--expanded-index", type=Path, required=True)
    parser.add_argument("--claims", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    old_rows, old_headers = read_csv(args.old_summary)
    new_rows, new_headers = read_csv(args.expanded_summary)
    index_rows, index_headers = read_csv(args.expanded_index)
    old_by_key = {table_key(row): row for row in old_rows}
    new_by_key = {table_key(row): row for row in new_rows}
    index_counts = Counter(raw_index_key(row) for row in index_rows)

    shared = set(old_by_key) & set(new_by_key)
    missing_old = set(old_by_key) - set(new_by_key)
    missing_coordinates = [key for key in new_by_key if not index_counts[key]]

    category_coverage: list[dict[str, object]] = []
    category_tables: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, row in new_by_key.items():
        category_tables[top_category(row)].append(key)
    for category, keys in sorted(category_tables.items(), key=lambda item: (-len(item[1]), item[0])):
        indexed = sum(bool(index_counts[key]) for key in keys)
        category_coverage.append(
            {
                "category": category,
                "summary_tables": len(keys),
                "indexed_tables": indexed,
                "coverage_pct": pct(indexed, len(keys)),
                "coordinate_rows": sum(index_counts[key] for key in keys),
            }
        )

    indexed_tables = sum(bool(index_counts[key]) for key in new_by_key)
    audit: dict[str, object] = {
        "inputs": {
            "old_summary": str(args.old_summary.resolve()),
            "expanded_summary": str(args.expanded_summary.resolve()),
            "expanded_index": str(args.expanded_index.resolve()),
            "claims": str(args.claims.resolve()) if args.claims and args.claims.exists() else None,
        },
        "old_summary": summary_metrics(old_rows),
        "expanded_summary": summary_metrics(new_rows),
        "expanded_index": index_metrics(index_rows, index_headers),
        "overlap": {
            "shared_tables": len(shared),
            "old_missing_from_expanded": len(missing_old),
            "old_retention_pct": pct(len(shared), len(old_by_key)),
            "expanded_new_tables": len(set(new_by_key) - set(old_by_key)),
        },
        "coordinate_coverage": {
            "summary_tables": len(new_by_key),
            "indexed_tables": indexed_tables,
            "missing_tables": len(missing_coordinates),
            "coverage_pct": pct(indexed_tables, len(new_by_key)),
            "by_category": category_coverage,
        },
        "headers": {"old_summary": old_headers, "expanded_summary": new_headers},
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "catalog_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(
        args.output_dir / "old_tables_missing_from_expanded.csv",
        [
            {
                "ORG_ID": key[0],
                "TBL_ID": key[1],
                "TBL_NM": summary_value(old_by_key[key], "table_name"),
                "분류축": summary_value(old_by_key[key], "axes"),
                "단위": summary_value(old_by_key[key], "unit"),
            }
            for key in sorted(missing_old)
        ],
        ["ORG_ID", "TBL_ID", "TBL_NM", "분류축", "단위"],
    )
    write_csv(
        args.output_dir / "expanded_tables_missing_coordinates.csv",
        [
            {
                "ORG_ID": key[0],
                "TBL_ID": key[1],
                "TBL_NM": summary_value(new_by_key[key], "table_name"),
                "category_path": summary_value(new_by_key[key], "category_path"),
            }
            for key in sorted(missing_coordinates)
        ],
        ["ORG_ID", "TBL_ID", "TBL_NM", "category_path"],
    )
    write_csv(
        args.output_dir / "coordinate_coverage_by_category.csv",
        category_coverage,
        ["category", "summary_tables", "indexed_tables", "coverage_pct", "coordinate_rows"],
    )
    report = build_report(audit, args.claims if args.claims and args.claims.exists() else None)
    (args.output_dir / "catalog_comparison_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
