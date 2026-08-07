"""Build lexical KOSIS table candidates for MCP full gold 200 inputs.

This is a local fallback when ChromaDB/BGE dependencies or indexes are not
available.  It does not read gold coordinates; it only uses the gold-free input
fixture and the public KOSIS table summary CSV.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from search_mcp_gold_200_chroma_bge import infer_table_search_profile, select_claim_unit


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "gold" / "mcp_full_gold_200_inputs.csv"
DEFAULT_TABLES = ROOT / "data" / "reference" / "kosis_table_summary.csv"
DEFAULT_OUTPUT = ROOT / "outputs" / "runs" / "mcp_gold_200_lexical_table_search" / "table_candidates.csv"
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
STOPWORDS = {
    "기록",
    "지난",
    "올해",
    "전년",
    "대비",
    "증가",
    "감소",
    "상승",
    "하락",
    "최대",
    "최소",
    "역대",
    "처음",
    "지난해",
    "올",
    "지난달",
    "기준",
    "기록했다",
    "밝혔다",
}
DOMAIN_HINTS = {
    "수출": ("무역", "국제수지", "수출", "수입", "품목별"),
    "수입": ("무역", "국제수지", "수출", "수입", "품목별"),
    "무역": ("무역", "국제수지", "수출", "수입"),
    "소비자물가": ("물가", "소비자물가", "품목성질별"),
    "물가": ("물가", "소비자물가", "생산자물가"),
    "고용": ("고용", "취업", "실업", "경제활동인구"),
    "실업": ("고용", "실업", "경제활동인구"),
    "취업": ("고용", "취업", "경제활동인구"),
    "인구": ("인구", "주민등록", "장래인구", "시군구"),
    "출생": ("인구", "출생", "인구동향"),
    "혼인": ("인구", "혼인", "인구동향"),
    "가구": ("가구", "가계", "가구원"),
    "GDP": ("국민계정", "국내총생산", "GDP"),
    "국내총생산": ("국민계정", "국내총생산", "GDP"),
    "항공": ("교통", "항공", "여객", "운송"),
    "여객": ("교통", "항공", "여객", "운송"),
}
CANONICAL_ALIASES = {
    "품목별 수출액 수입액": ("품목별", "수출액", "수입액"),
    "국가별 수출액 수입액": ("국가별", "수출액", "수입액"),
    "출생아수 합계출산율 자연증가": ("출생아수", "합계출산율", "자연증가"),
    "행정구역 시군구별 농가 농가인구": ("행정구역", "농가", "농가인구"),
}


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_table(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "org_id": clean(row.get("org_id") or row.get("ORG_ID")),
        "tbl_id": clean(row.get("tbl_id") or row.get("TBL_ID")),
        "tbl_name": clean(row.get("tbl_name") or row.get("TBL_NM")),
        "stat_id": clean(row.get("stat_id") or row.get("STAT_ID")),
        "category_path": clean(row.get("category_path") or row.get("path")),
    }


def base_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text):
        token = token.strip()
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token.lower())
        if re.search(r"[가-힣]", token) and len(token) >= 4:
            tokens.extend(token[i : i + 2].lower() for i in range(len(token) - 1))
    return tokens


def table_document(row: Mapping[str, Any]) -> str:
    return " ".join(
        clean(row.get(key))
        for key in ("tbl_name", "category_path", "stat_id")
        if clean(row.get(key))
    )


def query_text(row: Mapping[str, Any]) -> str:
    text = " ".join(
        clean(row.get(key))
        for key in ("title", "claim_text", "claim_type")
        if clean(row.get(key))
    )
    selected_unit = select_claim_unit(dict(row))
    if selected_unit:
        text += " " + selected_unit
    compact = text.replace(" ", "")
    hints = []
    for trigger, values in DOMAIN_HINTS.items():
        if trigger in compact:
            hints.extend(values)
    profile = infer_table_search_profile(dict(row))
    return text + " " + " ".join([*hints, *profile["aliases"]])


def build_index(tables: list[dict[str, str]]) -> tuple[dict[str, list[int]], list[Counter[str]], dict[str, float]]:
    inverted: dict[str, list[int]] = defaultdict(list)
    doc_tokens: list[Counter[str]] = []
    doc_freq: Counter[str] = Counter()
    for index, table in enumerate(tables):
        counts = Counter(base_tokens(table_document(table)))
        doc_tokens.append(counts)
        for token in counts:
            inverted[token].append(index)
            doc_freq[token] += 1
    total = max(len(tables), 1)
    idf = {token: math.log((1 + total) / (1 + freq)) + 1.0 for token, freq in doc_freq.items()}
    return inverted, doc_tokens, idf


def build_canonical_index(tables: list[dict[str, str]]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = defaultdict(list)
    for table_index, table in enumerate(tables):
        compact = re.sub(r"[^0-9A-Za-z가-힣]", "", table["tbl_name"])
        for alias, required_terms in CANONICAL_ALIASES.items():
            if all(term in compact for term in required_terms):
                index[alias].append(table_index)
    return dict(index)


def search_tables(
    claim: Mapping[str, Any],
    tables: list[dict[str, str]],
    inverted: Mapping[str, list[int]],
    doc_tokens: list[Counter[str]],
    idf: Mapping[str, float],
    canonical_index: Mapping[str, list[int]],
    *,
    top_k: int,
    pool_limit: int,
) -> list[dict[str, Any]]:
    query_counts = Counter(base_tokens(query_text(claim)))
    scores: Counter[int] = Counter()
    hits: dict[int, set[str]] = defaultdict(set)
    for token, q_count in query_counts.items():
        postings = inverted.get(token, [])
        if len(postings) > pool_limit:
            continue
        weight = idf.get(token, 1.0) * min(q_count, 3)
        for index in postings:
            scores[index] += weight * min(doc_tokens[index].get(token, 0), 3)
            hits[index].add(token)

    compact_claim = (clean(claim.get("title")) + " " + clean(claim.get("claim_text"))).replace(" ", "")
    profile = infer_table_search_profile(dict(claim))
    profile_bonus: Counter[int] = Counter()
    profile_reasons: dict[int, list[str]] = defaultdict(list)
    for alias in profile["aliases"]:
        for index in canonical_index.get(alias, []):
            scores[index] += 120.0
            profile_bonus[index] += 120.0
            profile_reasons[index].append(f"canonical:{alias}")

    for index in list(scores):
        table = tables[index]
        name = table["tbl_name"].replace(" ", "")
        path = table["category_path"].replace(" ", "")
        if name and name in compact_claim:
            scores[index] += 25
        for trigger, values in DOMAIN_HINTS.items():
            if trigger in compact_claim and any(value in name or value in path for value in values):
                scores[index] += 8
        negative_hits = [
            term for term in profile["negative_terms"] if term.replace(" ", "") in name or term.replace(" ", "") in path
        ]
        if negative_hits:
            penalty = 80.0 * len(negative_hits)
            scores[index] -= penalty
            profile_bonus[index] -= penalty
            profile_reasons[index].extend(f"penalty:{term}" for term in negative_hits)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], tables[item[0]]["tbl_name"]))[:top_k]
    results: list[dict[str, Any]] = []
    for rank, (index, score) in enumerate(ranked, 1):
        table = tables[index]
        results.append(
            {
                "gold_id": claim.get("gold_id", ""),
                "claim_id": claim.get("claim_id", ""),
                "article_id": claim.get("article_id", ""),
                "title": claim.get("title", ""),
                "claim_text": claim.get("claim_text", ""),
                "claim_type": claim.get("claim_type", ""),
                "claim_value": claim.get("claim_value", ""),
                "input_quality_status": claim.get("input_quality_status", ""),
                "input_quality_reason": claim.get("input_quality_reason", ""),
                "org_id": table["org_id"],
                "tbl_id": table["tbl_id"],
                "tbl_name": table["tbl_name"],
                "category_path": table["category_path"],
                "stat_id": table["stat_id"],
                "candidate_rank": rank,
                "candidate_score": round(float(score), 6),
                "candidate_hits": "|".join(sorted(hits[index])[:40]),
                "candidate_profile_bonus": round(float(profile_bonus[index]), 6),
                "candidate_profile_reasons": "|".join(profile_reasons[index]),
                "retrieval_backend": "local_lexical_baseline",
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--table-index", type=Path, default=DEFAULT_TABLES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--pool-limit", type=int, default=25000)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    claims = read_csv(args.input.expanduser())
    tables = [
        row for row in (normalize_table(row) for row in read_csv(args.table_index.expanduser()))
        if row["org_id"] and row["tbl_id"]
    ]
    inverted, doc_tokens, idf = build_index(tables)
    canonical_index = build_canonical_index(tables)
    rows: list[dict[str, Any]] = []
    for claim in claims:
        rows.extend(
            search_tables(
                claim,
                tables,
                inverted,
                doc_tokens,
                idf,
                canonical_index,
                top_k=args.top_k,
                pool_limit=args.pool_limit,
            )
        )
    fields = [
        "gold_id",
        "claim_id",
        "article_id",
        "title",
        "claim_text",
        "claim_type",
        "claim_value",
        "input_quality_status",
        "input_quality_reason",
        "org_id",
        "tbl_id",
        "tbl_name",
        "category_path",
        "stat_id",
        "candidate_rank",
        "candidate_score",
        "candidate_hits",
        "candidate_profile_bonus",
        "candidate_profile_reasons",
        "retrieval_backend",
    ]
    write_csv(args.output.expanduser(), rows, fields)
    print(f"claims={len(claims)} tables={len(tables)} candidate_rows={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
