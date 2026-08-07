"""Build a 200-row auto gold set whose numeric evidence is re-fetched via KOSIS MCP.

The script has two stages:
1. ``select`` creates a deterministic reserve pool from the existing news mapping output.
2. ``build`` consumes MCP evidence JSONL files and emits the final CSV and manifest.

MCP calls themselves are intentionally orchestrated outside this script so every accepted
row can be traced to a KOSIS connector response rather than a direct HTTP/API call.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs" / "bteam_review" / "final_verified_filled_2001_audited_v4.csv"
CANDIDATES = ROOT / "data" / "gold" / "mcp_full_gold_200_candidates.json"
EVIDENCE_DIR = ROOT / "data" / "gold" / "mcp_full_gold_evidence"
OUTPUT = ROOT / "data" / "gold" / "mcp_full_gold_200.csv"
MANIFEST = ROOT / "data" / "gold" / "mcp_full_gold_200_manifest.json"

SEMANTIC_KEYWORDS = {
    "DT_1R11001_FRM101": ("수출", "수입", "무역"),
    "DT_1R11006_FRM101": ("수출", "수입", "무역", "대미", "대중", "중국", "미국"),
    "DT_1J22042": ("물가", "가격", "소비자물가", "인플레이션"),
    "DT_1J22003": ("물가", "가격", "소비자물가", "인플레이션"),
    "DT_1K41012": ("소매판매", "소비", "판매"),
    "DT_1DA7001S": ("취업", "고용", "실업", "경제활동", "구직"),
    "DT_1DA7002S": ("취업", "고용", "실업", "경제활동", "구직", "청년", "고령"),
    "INH_1B8000F_01": ("출생", "출생아", "사망", "인구", "혼인", "이혼", "자연증가"),
    "INH_1B8000F_02": ("출생", "출생아", "사망", "인구", "혼인", "이혼", "자연증가"),
    "DT_1L9U101": ("소득", "가계", "처분가능", "흑자", "소비지출"),
    "DT_1KC2020": ("서비스업", "생산"),
    "DT_1EA1011": ("농가", "농업"),
}

TABLE_QUOTAS = {
    "DT_1R11001_FRM101": 45,
    "DT_1R11006_FRM101": 35,
    "DT_1J22042": 25,
    "DT_1J22003": 25,
    "DT_1DA7001S": 20,
    "DT_1DA7002S": 15,
    "INH_1B8000F_01": 12,
    "INH_1B8000F_02": 3,
    "DT_1K41012": 10,
    "DT_1L9U101": 4,
    "DT_1KC2020": 4,
    "DT_1EA1011": 2,
}

TABLE_NAMES = {
    "DT_1R11001_FRM101": "품목별 수출액 수입액",
    "DT_1R11006_FRM101": "국가별 수출액 수입액",
    "DT_1J22042": "월별 소비자물가 등락률",
    "DT_1J22003": "소비자물가지수(2020＝100)",
    "DT_1DA7001S": "성별 경제활동인구 총괄",
    "DT_1DA7002S": "연령별 경제활동인구 총괄",
    "INH_1B8000F_01": "출생아수 합계출산율 자연증가 등",
    "INH_1B8000F_02": "시도별 인구동태건수 및 동태율",
    "DT_1K41012": "재별 및 상품군별 소매판매액지수(2020＝100.0)",
    "DT_1L9U101": "가구당 월평균 가계수지",
    "DT_1KC2020": "산업별 서비스업생산지수(2020＝100.0)",
    "DT_1EA1011": "행정구역(시군구)별 농가 농가인구",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kosis_url(org_id: str, tbl_id: str) -> str:
    return (
        "https://kosis.kr/statHtml/statHtml.do?"
        f"orgId={org_id}&tblId={tbl_id}&vw_cd=MT_ZTITLE"
    )


def valid_period(prd_se: str, period: str) -> bool:
    if prd_se == "Y":
        return bool(re.fullmatch(r"\d{4}", period))
    if prd_se in {"M", "Q"}:
        return bool(re.fullmatch(r"\d{6}", period))
    return False


def period_key(prd_se: str, period: str) -> int:
    if prd_se == "Y":
        return int(period) * 100 + 12
    if prd_se == "M":
        return int(period)
    year, quarter = int(period[:4]), int(period[-2:])
    return year * 100 + quarter * 3


def to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def select_candidates() -> list[dict[str, Any]]:
    rows = read_csv(SOURCE)
    eligible: list[dict[str, str]] = []
    for row in rows:
        required = ("claim_id", "title", "url", "date", "claim_text", "org_id", "tbl_id", "obj_l1", "itm_id", "prd_se", "actual_period", "actual_value")
        if not all((row.get(field) or "").strip() for field in required):
            continue
        if row.get("claim_type") not in {"LEVEL", "CHANGE_RATE", "CHANGE_POINT"}:
            continue
        if (row.get("api_error") or "").strip():
            continue
        if row.get("audit_future_period") == "Y" or row.get("audit_forecast_or_target") == "Y" or row.get("audit_mapping_unconfirmed") == "Y":
            continue
        if row["tbl_id"] not in SEMANTIC_KEYWORDS:
            continue
        if not any(keyword in row["claim_text"] for keyword in SEMANTIC_KEYWORDS[row["tbl_id"]]):
            continue
        if not valid_period(row["prd_se"], row["actual_period"]):
            continue
        if row["claim_type"] != "LEVEL":
            if not (row.get("actual_prev_period") and row.get("actual_prev_value")):
                continue
            if not valid_period(row["prd_se"], row["actual_prev_period"]):
                continue
        try:
            article_date = datetime.strptime(row["date"][:10], "%Y-%m-%d")
        except ValueError:
            continue
        if period_key(row["prd_se"], row["actual_period"]) > article_date.year * 100 + article_date.month:
            continue
        if to_float(row.get("refined_claim_number") or row.get("claim_number")) is None:
            continue
        if to_float(row.get("refined_actual_number")) is None:
            continue
        eligible.append(row)

    def rank(row: dict[str, str]) -> tuple[Any, ...]:
        exact = 0 if row.get("refined_final_status") == "검증완료_일치" else 1
        article = row.get("article_id") or row.get("url")
        return (exact, row["date"], article, row["claim_id"])

    eligible.sort(key=rank)
    by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_coordinate_period: set[tuple[str, ...]] = set()
    for row in eligible:
        key = (
            row["org_id"], row["tbl_id"], row["obj_l1"], row.get("obj_l2", ""),
            row["itm_id"], row["prd_se"], row["actual_period"], row.get("actual_prev_period", ""),
        )
        if key in seen_coordinate_period:
            continue
        seen_coordinate_period.add(key)
        by_table[row["tbl_id"]].append(row)

    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    for table, quota in TABLE_QUOTAS.items():
        for row in by_table[table][:quota]:
            selected.append(row)
            selected_ids.add(row["claim_id"])

    if len(selected) < 240:
        for row in eligible:
            if row["claim_id"] in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(row["claim_id"])
            if len(selected) >= 240:
                break

    if len(selected) < 200:
        raise ValueError(f"only {len(selected)} eligible MCP candidates found")

    output: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        current = row["actual_period"]
        previous = row.get("actual_prev_period", "") if row["claim_type"] != "LEVEL" else ""
        query_start = min(filter(None, (current, previous)))
        query_end = max(filter(None, (current, previous)))
        scale = 1.0
        if row["claim_type"] == "LEVEL":
            source_actual = to_float(row["actual_value"])
            refined_actual = to_float(row["refined_actual_number"])
            if source_actual and refined_actual is not None:
                scale = refined_actual / source_actual
        output.append({
            "candidate_no": index,
            "claim_id": row["claim_id"],
            "article_id": row.get("article_id", ""),
            "title": row["title"],
            "date": row["date"],
            "url": row["url"],
            "claim_text": row["claim_text"],
            "claim_type": row["claim_type"],
            "claim_value": to_float(row.get("refined_claim_number") or row.get("claim_number")),
            "claim_unit": row.get("target_unit") or row.get("units") or "",
            "org_id": row["org_id"],
            "tbl_id": row["tbl_id"],
            "obj_l1": row["obj_l1"],
            "obj_l2": row.get("obj_l2", ""),
            "itm_id": row["itm_id"],
            "prd_se": row["prd_se"],
            "period": current,
            "previous_period": previous,
            "query_start": query_start,
            "query_end": query_end,
            "level_scale": scale,
            "source_actual_value": to_float(row["actual_value"]),
            "source_previous_value": to_float(row.get("actual_prev_value")),
            "source_refined_actual": to_float(row["refined_actual_number"]),
            "source_refined_verdict": row.get("refined_verdict", ""),
            "source_final_status": row.get("refined_final_status", ""),
        })
    return output


def write_candidates() -> None:
    candidates = select_candidates()
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_count": len(candidates),
        "first_200_table_counts": Counter(row["tbl_id"] for row in candidates[:200]),
        "reserve_count": len(candidates) - 200,
        "output": str(CANDIDATES.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2, default=dict))


def append_support_candidates(limit: int = 40) -> None:
    candidates: list[dict[str, Any]] = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    used_claim_ids = {row["claim_id"] for row in candidates}
    rows = read_csv(SOURCE)
    supports: list[dict[str, str]] = []
    for row in rows:
        if row.get("refined_final_status") != "검증완료_일치":
            continue
        if row.get("claim_type") not in {"LEVEL", "CHANGE_RATE", "POINT_CHANGE"}:
            continue
        required = ("claim_id", "title", "url", "date", "claim_text", "org_id", "tbl_id", "obj_l1", "itm_id", "prd_se", "actual_period", "actual_value", "refined_actual_number")
        if not all((row.get(field) or "").strip() for field in required):
            continue
        if row["claim_id"] in used_claim_ids or row["tbl_id"] not in SEMANTIC_KEYWORDS:
            continue
        if not any(keyword in row["claim_text"] for keyword in SEMANTIC_KEYWORDS[row["tbl_id"]]):
            continue
        if row.get("audit_future_period") == "Y" or row.get("audit_forecast_or_target") == "Y":
            continue
        if not valid_period(row["prd_se"], row["actual_period"]):
            continue
        normalized_type = "CHANGE_POINT" if row["claim_type"] == "POINT_CHANGE" else row["claim_type"]
        if normalized_type != "LEVEL":
            if not (row.get("actual_prev_period") and row.get("actual_prev_value")):
                continue
            if not valid_period(row["prd_se"], row["actual_prev_period"]):
                continue
        try:
            article_date = datetime.strptime(row["date"][:10], "%Y-%m-%d")
        except ValueError:
            continue
        if period_key(row["prd_se"], row["actual_period"]) > article_date.year * 100 + article_date.month:
            continue
        if to_float(row.get("refined_claim_number") or row.get("claim_number")) is None or to_float(row.get("refined_actual_number")) is None:
            continue
        row = dict(row)
        row["claim_type"] = normalized_type
        supports.append(row)

    supports.sort(key=lambda row: (row["date"], row["claim_id"]))
    for row in supports[:limit]:
        current = row["actual_period"]
        previous = row.get("actual_prev_period", "") if row["claim_type"] != "LEVEL" else ""
        scale = 1.0
        if row["claim_type"] == "LEVEL":
            source_actual = to_float(row["actual_value"])
            refined_actual = to_float(row["refined_actual_number"])
            if source_actual and refined_actual is not None:
                scale = refined_actual / source_actual
        candidates.append({
            "candidate_no": len(candidates) + 1,
            "claim_id": row["claim_id"],
            "article_id": row.get("article_id", ""),
            "title": row["title"],
            "date": row["date"],
            "url": row["url"],
            "claim_text": row["claim_text"],
            "claim_type": row["claim_type"],
            "claim_value": to_float(row.get("refined_claim_number") or row.get("claim_number")),
            "claim_unit": row.get("target_unit") or row.get("units") or "",
            "org_id": row["org_id"],
            "tbl_id": row["tbl_id"],
            "obj_l1": row["obj_l1"],
            "obj_l2": row.get("obj_l2", ""),
            "itm_id": row["itm_id"],
            "prd_se": row["prd_se"],
            "period": current,
            "previous_period": previous,
            "query_start": min(filter(None, (current, previous))),
            "query_end": max(filter(None, (current, previous))),
            "level_scale": scale,
            "source_actual_value": to_float(row["actual_value"]),
            "source_previous_value": to_float(row.get("actual_prev_value")),
            "source_refined_actual": to_float(row["refined_actual_number"]),
            "source_refined_verdict": "일치",
            "source_final_status": row.get("refined_final_status", ""),
        })
    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "appended_support_candidates": min(limit, len(supports)),
        "candidate_count": len(candidates),
        "new_candidate_range": [241, len(candidates)],
    }, ensure_ascii=False, indent=2))


def load_evidence() -> dict[int, dict[str, Any]]:
    evidence: dict[int, dict[str, Any]] = {}
    for path in sorted(EVIDENCE_DIR.glob("batch_*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                evidence[int(item["candidate_no"])] = item
    return evidence


def normalize_verdict(value: str) -> str:
    return "SUPPORTS" if value == "일치" else "REFUTES"


def infer_unit(point: dict[str, Any], candidate: dict[str, Any]) -> str:
    unit = str(point.get("unit") or "").strip()
    if unit:
        return unit
    label = f"{point.get('item_name', '')} {point.get('category_name', '')}"
    if "%" in label:
        return "%"
    match = re.search(r"\(([^()]+)\)", label)
    if match:
        return match.group(1)
    if candidate["tbl_id"] == "DT_1J22042":
        return "%"
    return "원응답 단위 미표기"


def build_output() -> None:
    candidates: list[dict[str, Any]] = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates.sort(key=lambda row: (0 if row.get("source_refined_verdict") == "일치" else 1, int(row["candidate_no"])))
    evidence = load_evidence()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for candidate in candidates:
        ev = evidence.get(int(candidate["candidate_no"]))
        if not ev or not ev.get("success"):
            rejected.append({"candidate_no": candidate["candidate_no"], "reason": "missing_or_failed_mcp_evidence"})
            continue
        expected_table_name = TABLE_NAMES.get(candidate["tbl_id"], "")
        response_table_name = str(ev.get("table_name") or "").strip()
        if response_table_name and expected_table_name and response_table_name != expected_table_name:
            rejected.append({
                "candidate_no": candidate["candidate_no"],
                "reason": "mcp_response_table_mismatch",
                "expected_table_name": expected_table_name,
                "response_table_name": response_table_name,
            })
            continue
        points = {str(point["period"]): point for point in ev.get("data_points", [])}
        current_point = points.get(candidate["period"])
        previous_point = points.get(candidate["previous_period"]) if candidate["previous_period"] else None
        if not current_point or (candidate["previous_period"] and not previous_point):
            rejected.append({"candidate_no": candidate["candidate_no"], "reason": "requested_period_not_in_mcp_response"})
            continue
        current = to_float(current_point.get("value"))
        previous = to_float(previous_point.get("value")) if previous_point else None
        if current is None or (candidate["previous_period"] and previous is None):
            rejected.append({"candidate_no": candidate["candidate_no"], "reason": "non_numeric_mcp_value"})
            continue
        if candidate["claim_type"] == "LEVEL":
            actual = current * float(candidate["level_scale"])
            derivation = f"MCP current value × source unit scale ({candidate['level_scale']:.12g})"
        elif candidate["claim_type"] == "CHANGE_RATE":
            if previous == 0:
                rejected.append({"candidate_no": candidate["candidate_no"], "reason": "zero_previous_value"})
                continue
            actual = (current - previous) / abs(previous) * 100.0
            derivation = "(MCP current − MCP previous) / |MCP previous| × 100"
        else:
            actual = current - float(previous)
            derivation = "MCP current − MCP previous"

        source_actual = float(candidate["source_refined_actual"])
        if not math.isclose(actual, source_actual, rel_tol=1e-8, abs_tol=1e-8):
            rejected.append({
                "candidate_no": candidate["candidate_no"],
                "reason": "mcp_value_changed_from_mapping_source",
                "mcp_actual": actual,
                "source_actual": source_actual,
            })
            continue
        accepted.append({
            "gold_id": f"MCPG-{len(accepted) + 1:03d}",
            "claim_id": candidate["claim_id"],
            "article_id": candidate["article_id"],
            "title": candidate["title"],
            "date": candidate["date"],
            "url": candidate["url"],
            "claim_text": candidate["claim_text"],
            "claim_type": candidate["claim_type"],
            "claim_value": candidate["claim_value"],
            "claim_unit": candidate["claim_unit"],
            "gold_label": normalize_verdict(candidate["source_refined_verdict"]),
            "gold_label_tier": "FULL_KOSIS_MCP",
            "gold_verifiable": "Y",
            "gold_ready": "Y",
            "human_reviewed": "N",
            "gold_org_id": candidate["org_id"],
            "gold_tbl_id": candidate["tbl_id"],
            "gold_tbl_name": response_table_name or expected_table_name,
            "gold_obj_l1": candidate["obj_l1"],
            "gold_obj_l2": candidate["obj_l2"] or "N/A",
            "gold_itm_id": candidate["itm_id"],
            "gold_item_name": current_point.get("item_name", ""),
            "gold_category_name": current_point.get("category_name", ""),
            "gold_prd_se": candidate["prd_se"],
            "gold_period": candidate["period"],
            "gold_previous_period": candidate["previous_period"] or "N/A",
            "gold_source_value": current,
            "gold_previous_source_value": previous if previous is not None else "N/A",
            "gold_source_unit": infer_unit(current_point, candidate),
            "gold_actual_value": actual,
            "gold_derivation_method": derivation,
            "gold_coordinate_status": "MCP_ACTUAL_VALUE_CONFIRMED",
            "gold_label_source": "KOSIS_MCP_GET_DATA",
            "gold_evidence_url": ev.get("source_url") or kosis_url(candidate["org_id"], candidate["tbl_id"]),
            "gold_evidence_batch": ev.get("batch", ""),
            "gold_retrieved_at": ev.get("retrieved_at", now),
        })
        if len(accepted) == 200:
            break

    if len(accepted) != 200:
        raise ValueError(f"expected 200 accepted MCP rows, got {len(accepted)}; rejected={len(rejected)}")
    fields = list(accepted[0])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(accepted)

    blank_required = []
    required = [
        "gold_id", "claim_id", "title", "url", "claim_text", "gold_label", "gold_org_id",
        "gold_tbl_id", "gold_tbl_name", "gold_obj_l1", "gold_itm_id", "gold_item_name",
        "gold_prd_se", "gold_period", "gold_source_value", "gold_source_unit",
        "gold_actual_value", "gold_evidence_url", "gold_retrieved_at",
    ]
    for row in accepted:
        for field in required:
            if row[field] in ("", None):
                blank_required.append((row["gold_id"], field))
    if blank_required:
        raise ValueError(f"blank required fields: {blank_required[:10]}")

    manifest = {
        "dataset": "mcp_full_gold_200",
        "created_at": now,
        "row_count": len(accepted),
        "all_rows_mcp_actual_value": True,
        "human_reviewed": False,
        "label_tier_counts": dict(Counter(row["gold_label_tier"] for row in accepted)),
        "label_counts": dict(Counter(row["gold_label"] for row in accepted)),
        "table_counts": dict(Counter(row["gold_tbl_id"] for row in accepted)),
        "unique_claim_count": len({row["claim_id"] for row in accepted}),
        "unique_coordinate_period_count": len({
            (row["gold_org_id"], row["gold_tbl_id"], row["gold_obj_l1"], row["gold_obj_l2"], row["gold_itm_id"], row["gold_prd_se"], row["gold_period"], row["gold_previous_period"])
            for row in accepted
        }),
        "blank_required_count": len(blank_required),
        "rejected_candidate_count_before_200": len(rejected),
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": sha256(SOURCE),
        "candidate_file": str(CANDIDATES.relative_to(ROOT)).replace("\\", "/"),
        "candidate_sha256": sha256(CANDIDATES),
        "evidence_files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in sorted(EVIDENCE_DIR.glob("batch_*.jsonl"))],
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(OUTPUT),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def print_batch(start: int, size: int) -> None:
    candidates: list[dict[str, Any]] = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    print(json.dumps(candidates[start - 1:start - 1 + size], ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("select")
    sub.add_parser("append-supports")
    batch = sub.add_parser("batch")
    batch.add_argument("--start", type=int, required=True)
    batch.add_argument("--size", type=int, default=10)
    sub.add_parser("build")
    args = parser.parse_args()
    if args.command == "select":
        write_candidates()
    elif args.command == "append-supports":
        append_support_candidates()
    elif args.command == "batch":
        print_batch(args.start, args.size)
    else:
        build_output()


if __name__ == "__main__":
    main()
