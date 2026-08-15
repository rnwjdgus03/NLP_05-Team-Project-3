#!/usr/bin/env python3
"""Retrieve KOSIS table candidates exactly from the SQLite table catalog.

This is the structured-retrieval complement to BGE.  It searches official
table names and survey/category paths, then returns candidates that can be
unioned with vector results before schema/coordinate resolution.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

from kosis_meta_coordinates import claim_axis_targets
from kosis_semantic_search import survey_hints_from_claim
from kosis_sqlite_metadata import clean


STOPWORDS = {
    "결과", "통계", "조사", "지난해", "작년", "올해", "전년", "대비",
    "증가", "감소", "상승", "하락", "기록", "집계", "가장", "전국",
}
TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")

LEXICAL_EXPANSIONS = (
    (("준공후미분양", "준공후미분양주택"), ("공사완료후", "미분양현황")),
    (("영아돌연사", "영아돌연사증후군"), ("영아사망원인",)),
    (("온라인음식서비스", "음식서비스거래규모"), ("온라인쇼핑", "거래액")),
    (("거래규모",), ("거래액",)),
    (("1인가구", "1인가구수"), ("1인가구",)),
)


def compact(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", clean(value).lower())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def ensure_fts(connection: sqlite3.Connection) -> int:
    """Create or refresh the FTS catalog when the relational catalog changes."""

    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS kosis_tables_fts USING fts5(
            org_id UNINDEXED,
            tbl_id UNINDEXED,
            tbl_name,
            category_path,
            tokenize='unicode61'
        )
        """
    )
    source_count = int(connection.execute("SELECT COUNT(*) FROM kosis_tables").fetchone()[0])
    indexed_count = int(connection.execute("SELECT COUNT(*) FROM kosis_tables_fts").fetchone()[0])
    if source_count != indexed_count:
        connection.execute("DELETE FROM kosis_tables_fts")
        connection.execute(
            """
            INSERT INTO kosis_tables_fts(org_id, tbl_id, tbl_name, category_path)
            SELECT org_id, tbl_id, tbl_name, category_path FROM kosis_tables
            """
        )
        connection.commit()
    return source_count


def focused_terms(claim: Mapping[str, str]) -> tuple[str, ...]:
    """Return high-precision catalog terms without using labels or predictions."""

    values: list[str] = []
    for hint in survey_hints_from_claim(claim):
        values.extend(TOKEN.findall(clean(hint)))
    for field in (
        "measurement_indicator", "indicator", "measurement_item", "industry_or_item",
    ):
        values.extend(TOKEN.findall(clean(claim.get(field))))
    for kind, terms in claim_axis_targets(claim).items():
        if kind in {"region", "country", "age", "gender"}:
            values.extend(clean(term) for term in terms)
    # Claim text is a fallback for named surveys (quoted titles often do not
    # survive HCX into a dedicated survey_name field).
    text = clean(claim.get("claim_text"))
    for match in re.finditer(r"[‘'\"]([^’'\"]{2,30}(?:조사|총조사|통계))[’'\"]", text):
        values.extend(TOKEN.findall(match.group(1)))
    compact_claim = compact(" ".join(
        clean(claim.get(field)) for field in (
            "measurement_indicator", "indicator", "measurement_item",
            "industry_or_item", "claim_text", "title",
        )
    ))
    for triggers, expansions in LEXICAL_EXPANSIONS:
        if any(compact(trigger) in compact_claim for trigger in triggers):
            values.extend(expansions)
    output: list[str] = []
    for value in values:
        value = value.strip()
        if len(value) < 2 or value in STOPWORDS or value in output:
            continue
        output.append(value)
    return tuple(output[:16])


def fts_query(terms: Iterable[str]) -> str:
    # KOSIS titles concatenate Korean compounds (미분양현황, 온라인쇼핑몰),
    # so exact-token FTS misses useful prefixes even though the human terms match.
    escaped = [f'"{clean(term).replace(chr(34), chr(34) * 2)}"*' for term in terms if clean(term)]
    return " OR ".join(escaped)


def exact_boost(claim: Mapping[str, str], table: Mapping[str, str]) -> tuple[float, list[str]]:
    table_name = compact(table.get("tbl_name"))
    table_path = compact(table.get("category_path"))
    reasons: list[str] = []
    score = 0.0
    for hint in survey_hints_from_claim(claim):
        if compact(hint) and compact(hint) in table_path:
            score += 6.0
            reasons.append("SURVEY_PATH_EXACT")
    indicator = clean(claim.get("measurement_indicator") or claim.get("indicator"))
    indicator_tokens = [token for token in TOKEN.findall(indicator) if token not in STOPWORDS]
    if compact(indicator) and compact(indicator) in table_name:
        score += 5.0
        reasons.append("INDICATOR_PHRASE_IN_TITLE")
    else:
        hits = sum(compact(token) in table_name for token in indicator_tokens)
        if hits:
            score += 2.0 * hits / max(1, len(indicator_tokens))
            reasons.append("INDICATOR_TOKEN_IN_TITLE")
    expanded_hits = [
        term for term in focused_terms(claim)
        if compact(term) and compact(term) in table_name
        and compact(term) not in {compact(token) for token in indicator_tokens}
    ]
    if expanded_hits:
        score += min(6.0, 3.0 * len(expanded_hits))
        reasons.append("EXPANDED_TERM_IN_TITLE")

    # A catalog match must be able to cover the requested observation year.
    # KOSIS keeps many census snapshots and archived/pre-adjustment tables whose
    # titles are lexically excellent but cannot answer a current-year claim.
    period_text = clean(
        claim.get("measurement_period") or claim.get("period")
        or claim.get("measurement_year")
    )
    year_match = re.search(r"(?:19|20)\d{2}", period_text)
    target_year = int(year_match.group()) if year_match else None
    raw_path = clean(table.get("category_path"))
    if target_year:
        obsolete = False
        for start, end in re.findall(r"((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})년", raw_path):
            if target_year > int(end):
                obsolete = True
        open_years = {
            int(year) for year in re.findall(
                r"((?:19|20)\d{2})년\s*(?:~|이후|부터)", raw_path
            )
        }
        exact_years = {
            int(year) for year in re.findall(r"((?:19|20)\d{2})년", raw_path)
        } - open_years
        if exact_years and target_year not in exact_years and max(exact_years) < target_year:
            obsolete = True
        if obsolete:
            score -= 10.0
            reasons.append("PERIOD_NOT_COVERED")
        elif open_years and min(open_years) <= target_year:
            score += 1.5
            reasons.append("PERIOD_OPEN_RANGE")
    if any(marker in raw_path for marker in ("시계열 보정 前", "시계열 보정 전", "구자료")):
        score -= 5.0
        reasons.append("ARCHIVED_SERIES")

    # Prefer a table whose visible schema matches the typed target axes.  This
    # prevents an age/sex detail table from beating a total table merely because
    # both contain the same indicator words.
    axes = claim_axis_targets(claim)
    axis_markers = {
        "region": ("시군구", "행정구역", "지역별"),
        "age": ("연령", "연령계층"),
        "gender": ("성별", "남자", "여자"),
        "education": ("교육", "학력"),
        "country": ("국가", "국적"),
    }
    for kind, markers in axis_markers.items():
        visible = any(compact(marker) in table_name for marker in markers)
        requested = bool(axes.get(kind))
        if visible and requested:
            score += 3.0
            reasons.append(f"{kind.upper()}_AXIS_IN_TITLE")
        elif visible and not requested and kind in {"age", "gender", "education", "country"}:
            score -= 2.5
            reasons.append(f"UNREQUESTED_{kind.upper()}_AXIS")

    # Korean KOSIS table titles commonly encode a detail dimension as
    # ``<dimension>별 <metric>``.  If the claim asks only for the total and does
    # not mention that prefix, lower the detail table.  Geography is exempt:
    # nationwide totals are often stored inside an 행정구역별 table.
    if not any(axes.values()):
        visible_title = clean(table.get("tbl_name"))
        prefixes = re.findall(r"([^,/()\s]+)(?:\([^)]*\))?별", visible_title)
        claim_text = compact(" ".join(clean(claim.get(field)) for field in (
            "claim_text", "measurement_indicator", "measurement_item",
        )))
        geographic = ("행정구역", "시군구", "시도", "지역")
        unrequested = [
            prefix for prefix in prefixes
            if not any(marker in prefix for marker in geographic)
            and compact(prefix) not in claim_text
        ]
        if unrequested:
            score -= 2.0
            reasons.append("UNREQUESTED_DETAIL_PREFIX")
    visible_title = compact(table.get("tbl_name"))
    household_scope_text = compact(" ".join(clean(claim.get(field)) for field in (
        "claim_text", "measurement_indicator", "measurement_item",
    )))
    if "전국" in visible_title and not axes.get("region"):
        score += 1.0
        reasons.append("NATIONAL_SCOPE_DEFAULT")
    if "도시" in visible_title and not axes.get("region"):
        score -= 2.0
        reasons.append("UNREQUESTED_URBAN_SCOPE")
    if "2인이상" in visible_title and "2인이상" not in household_scope_text:
        score -= 3.0
        reasons.append("UNREQUESTED_TWO_PLUS_HOUSEHOLD")
    if "1인이상" in visible_title and not any(
        token in household_scope_text for token in ("2인이상", "3인이상", "4인이상")
    ):
        score += 1.0
        reasons.append("ALL_HOUSEHOLD_SCOPE")
    if "표본오차" in visible_title and "표본오차" not in compact(indicator):
        score -= 5.0
        reasons.append("UNREQUESTED_SAMPLING_ERROR")
    if "총괄" in clean(table.get("tbl_name")):
        score += 2.0
        reasons.append("TOTAL_TABLE")
    return score, reasons


def retrieve(
    connection: sqlite3.Connection,
    claim: Mapping[str, str],
    *,
    limit: int = 30,
    fetch_limit: int = 500,
) -> list[dict[str, object]]:
    terms = focused_terms(claim)
    query = fts_query(terms)
    if not query:
        return []
    rows = [dict(row) for row in connection.execute(
        """
        SELECT org_id, tbl_id, tbl_name, category_path,
               bm25(kosis_tables_fts, 0.0, 0.0, 5.0, 2.0) AS fts_bm25
        FROM kosis_tables_fts
        WHERE kosis_tables_fts MATCH ?
        ORDER BY fts_bm25
        LIMIT ?
        """,
        (query, fetch_limit),
    )]
    rescored: list[dict[str, object]] = []
    for row in rows:
        boost, reasons = exact_boost(claim, row)
        rescored.append({
            **row,
            "catalog_exact_boost": boost,
            "catalog_exact_reasons": "|".join(reasons),
            "catalog_query_terms": "|".join(terms),
        })
    rescored.sort(key=lambda row: (
        -float(row["catalog_exact_boost"]),
        float(row["fts_bm25"]),
        clean(row.get("org_id")), clean(row.get("tbl_id")),
    ))
    return rescored[:limit]


def retrieve_all(
    connection: sqlite3.Connection,
    claims: list[dict[str, str]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for claim in claims:
        key = clean(claim.get("gold_id") or claim.get("claim_measurement_id") or claim.get("claim_id"))
        for rank, row in enumerate(retrieve(connection, claim, limit=limit), 1):
            output.append({
                "claim_measurement_id": clean(claim.get("claim_measurement_id")),
                "claim_id": clean(claim.get("claim_id")),
                "article_id": clean(claim.get("article_id")),
                "candidate_rank": rank,
                "retrieval_backend": "sqlite_fts_catalog_v1",
                "candidate_key": key,
                **row,
            })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=30)
    args = parser.parse_args()
    connection = sqlite3.connect(args.metadata_db)
    connection.row_factory = sqlite3.Row
    try:
        table_count = ensure_fts(connection)
        rows = retrieve_all(connection, read_csv(args.claims), limit=args.top_k)
    finally:
        connection.close()
    write_csv(args.output, rows)
    print(f"tables={table_count} claims={len(read_csv(args.claims))} candidates={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
