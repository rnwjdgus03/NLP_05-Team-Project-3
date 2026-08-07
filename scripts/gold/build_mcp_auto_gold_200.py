"""Expand the fully populated automatic KOSIS gold set to 200 rows."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "gold" / "mcp_auto_gold_v3.csv"
CODEBOOK = ROOT / "data" / "gold" / "context_top50_common_gold_v1.csv"
CODEBOOK_MANIFEST = ROOT / "data" / "gold" / "context_top50_common_gold_v1_manifest.json"
NEWS = ROOT / "outputs" / "runs" / "is_claim_news_10000_true.csv"
NEWS_CONTEXT = ROOT / "data" / "inputs" / "news_top50_sentences_context_v2.csv"
OUTPUT = ROOT / "data" / "gold" / "mcp_auto_gold_200.csv"
MANIFEST = ROOT / "data" / "gold" / "mcp_auto_gold_200_manifest.json"
NA = "N/A"


TABLES = {
    "DT_1R11001_FRM101": ("360", "품목별 수출액, 수입액"),
    "DT_115_2012_AA001": ("115", "산업별(중분류) 현재인원(성별, 고용형태별 등)"),
    "DT_444002_N2023A006": ("444", "직무별 종사자 현황"),
    "DT_1K41012": ("101", "재별 및 상품군별 소매판매액지수(2020=100.0)"),
    "DT_920005_B008": ("381", "항공사별 통계"),
    "DT_1J22041": ("101", "연도별 소비자물가 등락률"),
}


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number_key(value: str) -> float | str:
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return (value or "").strip()


def semantic_key(row: dict[str, str]) -> tuple[object, ...]:
    return (
        row.get("article_id", ""),
        row.get("claim_text", ""),
        number_key(row.get("value", "")),
        row.get("unit", ""),
        row.get("measurement_period", ""),
    )


def kosis_url(org_id: str, tbl_id: str) -> str:
    return (
        "https://kosis.kr/statHtml/statHtml.do?"
        f"orgId={org_id}&tblId={tbl_id}&vw_cd=MT_ZTITLE"
    )


def select_additions(
    base_rows: list[dict[str, str]], codebook_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    base_keys = {semantic_key(row) for row in base_rows}
    positives = sorted(
        (
            row for row in codebook_rows
            if row["gold_ready"] == "Y" and semantic_key(row) not in base_keys
        ),
        key=lambda row: row["candidate_id"],
    )
    if len(positives) != 82:
        raise ValueError(f"expected 82 new CODEBOOK_KOSIS rows, got {len(positives)}")

    used_keys = base_keys | {semantic_key(row) for row in positives}
    measurement_errors = sorted(
        (
            row for row in codebook_rows
            if row["gold_ready"] == "N"
            and row["gold_measurement_correct"] == "N"
            and semantic_key(row) not in used_keys
        ),
        key=lambda row: row["candidate_id"],
    )[:3]
    used_keys.update(semantic_key(row) for row in measurement_errors)
    out_of_scope = sorted(
        (
            row for row in codebook_rows
            if row["gold_ready"] == "N"
            and row["gold_measurement_correct"] == "Y"
            and row["gold_verifiable"] == "N"
            and semantic_key(row) not in used_keys
        ),
        key=lambda row: row["candidate_id"],
    )[:3]
    additions = positives + measurement_errors + out_of_scope
    if len(additions) != 88:
        raise ValueError(f"expected 88 additions, got {len(additions)}")
    return additions


def build_news_index(news_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in news_rows:
        key = row["article_id"]
        existing = index.get(key)
        if existing and any(
            existing.get(field, "") != row.get(field, "")
            for field in ("title", "date", "url")
        ):
            raise ValueError(f"conflicting news metadata for {key}")
        index[key] = row
    return index


def make_row(
    source: dict[str, str], fields: list[str], news_index: dict[str, dict[str, str]], now: str
) -> dict[str, object]:
    row: dict[str, object] = {field: NA for field in fields}
    news = news_index.get(source["article_id"])
    if not news:
        raise ValueError(f"news metadata not found for {source['candidate_id']}")

    row.update(
        claim_id=f"{source['article_id']}-{source['candidate_id']}",
        claim_measurement_id=f"{source['article_id']}-{source['candidate_id']}-m1",
        article_id=source["article_id"],
        title=source["title"] or news["title"],
        date=source["date"] or news["date"],
        url=news["url"],
        claim_text=source["claim_text"],
        measurement_text=source["measurement_text"] or NA,
        measurement_usage="KOSIS_VALUE",
        claim_domain_scope="국내공식통계",
        measurement_binding_source="codex_common_codebook",
        measurement_role=source["measurement_role"] or NA,
        measurement_indicator=source["measurement_indicator"] or NA,
        measurement_item=source["measurement_item"] or source["measurement_indicator"],
        value=source["value"] or NA,
        unit=source["unit"] or NA,
        measurement_period=source["measurement_period"] or NA,
        measurement_prd_se=source["measurement_prd_se"] or NA,
        gold_verifiable=source["gold_verifiable"],
        gold_measurement_correct=source["gold_measurement_correct"],
        gold_ready=source["gold_ready"],
        gold_retrieved_at=now,
        human_reviewed="N",
    )

    if source["gold_ready"] == "Y":
        tbl_id = source["gold_candidate_tbl_id"]
        if tbl_id not in TABLES:
            raise ValueError(f"unconfirmed table in selected positive: {tbl_id}")
        org_id, tbl_name = TABLES[tbl_id]
        row.update(
            gold_label_tier="CODEBOOK_KOSIS",
            gold_org_id=org_id,
            gold_tbl_id=tbl_id,
            gold_tbl_name=tbl_name,
            gold_prd_se=source["measurement_prd_se"],
            gold_period=source["measurement_period"],
            gold_value_type=source["measurement_role"],
            gold_derivation_method="TABLE_SERIES_LABEL",
            gold_claim_signed_value=source["value"],
            gold_verdict="값검증대기",
            gold_coordinate_status="TABLE_ONLY",
            gold_confidence="HIGH",
            gold_reason=(
                f"{source['gold_reason']}; 잠긴 Codex 공통 골드에서 측정·검증 가능 판정, "
                "KOSIS MCP로 통계표명 재확인, 세부 항목·분류·실제값은 미확정."
            ),
            gold_evidence_url=kosis_url(org_id, tbl_id),
            gold_label_source="CODEX_COMMON_GOLD_V1+KOSIS_MCP_TABLE_INFO_200",
        )
    else:
        is_error = source["gold_measurement_correct"] == "N"
        row.update(
            gold_label_tier="MEASUREMENT_ERROR" if is_error else "MCP_NOT_VERIFIABLE",
            gold_verdict="판단불가",
            gold_coordinate_status="NOT_APPLICABLE",
            gold_confidence="HIGH",
            gold_reason=(
                f"{source['gold_reason']}; {source['measurement_correct_reason']}; "
                "잠긴 Codex 공통 골드의 제외 판정을 유지함."
            ),
            gold_label_source="CODEX_COMMON_GOLD_V1_200",
        )
    return row


def main() -> None:
    fields, base_rows = read_rows(BASE)
    _, codebook_rows = read_rows(CODEBOOK)
    _, news_rows = read_rows(NEWS)
    _, context_rows = read_rows(NEWS_CONTEXT)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    additions = select_additions(base_rows, codebook_rows)
    news_index = build_news_index(news_rows + context_rows)
    new_rows = [make_row(row, fields, news_index, now) for row in additions]
    rows: list[dict[str, object]] = [dict(row) for row in base_rows] + new_rows
    rows.sort(key=lambda row: str(row["claim_measurement_id"]))

    if len(rows) != 200:
        raise ValueError(f"expected 200 rows, got {len(rows)}")
    if len({row["claim_measurement_id"] for row in rows}) != 200:
        raise ValueError("claim_measurement_id is not unique")
    blanks = [
        (row["claim_measurement_id"], field)
        for row in rows for field in fields
        if row.get(field, "") in ("", None)
    ]
    if blanks:
        raise ValueError(f"blank fields remain: {blanks[:20]}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    tier_counts: dict[str, int] = {}
    for row in rows:
        tier = str(row["gold_label_tier"])
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    manifest = {
        "dataset": "mcp_auto_gold_200",
        "created_at": now,
        "row_count": len(rows),
        "unique_measurement_count": len({row["claim_measurement_id"] for row in rows}),
        "tier_counts": tier_counts,
        "gold_verifiable_counts": {
            "Y": sum(row["gold_verifiable"] == "Y" for row in rows),
            "N": sum(row["gold_verifiable"] == "N" for row in rows),
        },
        "added_rows": {
            "total": len(new_rows),
            "CODEBOOK_KOSIS": sum(row["gold_label_tier"] == "CODEBOOK_KOSIS" for row in new_rows),
            "MCP_NOT_VERIFIABLE": sum(row["gold_label_tier"] == "MCP_NOT_VERIFIABLE" for row in new_rows),
            "MEASUREMENT_ERROR": sum(row["gold_label_tier"] == "MEASUREMENT_ERROR" for row in new_rows),
            "candidate_ids": [row["candidate_id"] for row in additions],
        },
        "blank_field_count": 0,
        "human_reviewed": False,
        "sources": {
            str(BASE.relative_to(ROOT)).replace("\\", "/"): sha256(BASE),
            str(CODEBOOK.relative_to(ROOT)).replace("\\", "/"): sha256(CODEBOOK),
            str(CODEBOOK_MANIFEST.relative_to(ROOT)).replace("\\", "/"): sha256(CODEBOOK_MANIFEST),
            str(NEWS.relative_to(ROOT)).replace("\\", "/"): sha256(NEWS),
            str(NEWS_CONTEXT.relative_to(ROOT)).replace("\\", "/"): sha256(NEWS_CONTEXT),
        },
        "kosis_mcp_table_info_checked": [
            {"org_id": org_id, "tbl_id": tbl_id, "tbl_name": tbl_name}
            for tbl_id, (org_id, tbl_name) in TABLES.items()
        ],
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(OUTPUT),
        "tier_meaning": {
            "FULL_KOSIS": "KOSIS 세부 좌표와 실제값까지 확정",
            "CODEBOOK_KOSIS": "잠긴 Codex 골드에서 검증 가능 판정 및 KOSIS 표명 확인, 세부 좌표·값은 대기",
            "MCP_NOT_VERIFIABLE": "KOSIS 직접 검증 범위 밖",
            "MEASUREMENT_ERROR": "기사 문맥에서 측정값 추출이 잘못됨",
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
