#!/usr/bin/env python3
"""Lock a URL-disjoint, target-stratified holdout without manual article review."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/archive/검증대상_기사드랍후.csv"
ARTICLES = ROOT / "data/holdout8_stratified_articles.csv"
ASSIGNMENTS = ROOT / "data/holdout8_stratified_assignments.csv"
MANIFEST = ROOT / "data/holdout8_stratified_manifest.json"
START_ROW = 355
QUOTA = 12
SEED = "holdout8-v5-stratified-20260807"
ARTICLE_COLUMNS = ("기사제목", "작성일", "URL", "기사 본문(정제)", "검색 구분 레이블")

EXCLUSION_SOURCES = (
    (ROOT / "data/gold/mcp_full_gold_200.csv", "url"),
    (ROOT / "data/holdout5_articles.csv", "URL"),
    (ROOT / "data/holdout6_articles.csv", "URL"),
    (ROOT / "data/holdout7_disjoint_articles.csv", "URL"),
)

OFFICIAL = re.compile(
    r"통계청|국가데이터처|관세청|산업통상자원부|농림축산식품부|"
    r"고용노동부|국토교통부|보건복지부|한국은행|KOSIS|국가통계포털|"
    r"(?:승인|공식)통계|조사\s*결과|발표",
    re.I,
)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|%p|명|건|대|원|달러|kg|톤)?")
METRIC = {
    "country": re.compile(r"수출|수입|무역|인구|고용|취업|실업|소비|생산"),
    "age": re.compile(r"인구|고용|취업|실업|소득|임금|소비|비율|증가|감소"),
    "gender": re.compile(r"인구|고용|취업|실업|소득|임금|비율|격차|증가|감소"),
    "product": re.compile(r"수출|수입|생산|소비|소비량|판매|출하|재고|가격"),
}
TARGET = {
    "country": re.compile(
        r"미국|중국|일본|베트남|독일|프랑스|영국|인도|러시아|호주|캐나다|"
        r"대만|싱가포르|태국|인도네시아|말레이시아|필리핀"
    ),
    "age": re.compile(
        r"(?:\d{1,2}\s*[~\-]\s*\d{1,2}\s*세|\d{1,2}\s*세\s*(?:이상|이하)|"
        r"청년|고령층|노년층|[1-9]0대)"
    ),
    "gender": re.compile(r"남성|여성|남녀|성별"),
    "product": re.compile(
        r"반도체|자동차|선박|석유|쌀|양곡|소고기|돼지고기|밀|옥수수|"
        r"배터리|의류|화장품|스마트폰|철강|디스플레이|컴퓨터"
    ),
}
NON_KOSIS_SENTENCE = re.compile(
    r"회사채|은행채|한전채|통안채|기업어음|전자단기사채|영업이익|연결\s*기준\s*매출"
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|[\r\n]+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_urls(path: Path, field: str) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        values = {row.get(field, "").strip() for row in csv.DictReader(handle)}
    values.discard("")
    return values


def sentence_candidates(row: dict[str, str], stratum: str) -> list[tuple[int, str]]:
    title = row.get("기사제목", "")
    body = row.get("기사 본문(정제)", "")
    full_text = f"{title} {body}"
    has_official_context = bool(OFFICIAL.search(full_text))
    found: list[tuple[int, str]] = []
    for sentence in SENTENCE_SPLIT.split(full_text):
        if not sentence or NON_KOSIS_SENTENCE.search(sentence):
            continue
        targets = sorted(set(TARGET[stratum].findall(sentence)))
        if not targets or not METRIC[stratum].search(sentence) or not NUMBER.search(sentence):
            continue
        score = 1 + min(len(targets), 3)
        if has_official_context:
            score += 2
        if OFFICIAL.search(sentence):
            score += 3
        found.append((score, "|".join(targets)))
    return found


def stable_tie(url: str) -> str:
    return hashlib.sha256(f"{SEED}|{url}".encode()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    excluded_urls: set[str] = set()
    exclusion_counts: dict[str, int] = {}
    for path, field in EXCLUSION_SOURCES:
        values = read_urls(path, field)
        excluded_urls.update(values)
        exclusion_counts[path.relative_to(ROOT).as_posix()] = len(values)

    pools: dict[str, list[dict[str, object]]] = {name: [] for name in TARGET}
    for source_row, row in enumerate(source_rows[START_ROW - 1 :], start=START_ROW):
        url = row.get("URL", "").strip()
        if not url or url in excluded_urls:
            continue
        for stratum in TARGET:
            candidates = sentence_candidates(row, stratum)
            if not candidates:
                continue
            score, terms = max(candidates)
            pools[stratum].append(
                {
                    "source_row_1_based": source_row,
                    "stratum": stratum,
                    "trigger_terms": terms,
                    "score": score,
                    "url": url,
                    "row": row,
                }
            )

    selected: list[dict[str, object]] = []
    used_urls: set[str] = set()
    # Scarce axes first so cross-stratum articles do not consume their quota.
    for stratum in ("gender", "age", "country", "product"):
        ranked = sorted(
            pools[stratum],
            key=lambda item: (-int(item["score"]), stable_tie(str(item["url"]))),
        )
        chosen = [item for item in ranked if item["url"] not in used_urls][:QUOTA]
        if len(chosen) != QUOTA:
            raise RuntimeError(f"insufficient {stratum} candidates: {len(chosen)}/{QUOTA}")
        selected.extend(chosen)
        used_urls.update(str(item["url"]) for item in chosen)

    article_rows = [dict(item["row"]) for item in selected]
    write_csv(ARTICLES, article_rows, list(ARTICLE_COLUMNS))
    assignment_rows = [
        {
            "holdout_id": f"H8-{index:03d}",
            "stratum": item["stratum"],
            "source_row_1_based": item["source_row_1_based"],
            "trigger_terms": item["trigger_terms"],
            "selection_score": item["score"],
            "URL": item["url"],
        }
        for index, item in enumerate(selected, start=1)
    ]
    write_csv(
        ASSIGNMENTS,
        assignment_rows,
        ["holdout_id", "stratum", "source_row_1_based", "trigger_terms", "selection_score", "URL"],
    )

    selected_urls = {str(item["url"]) for item in selected}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": sha256(SOURCE),
        "selection_start_1_based": START_ROW,
        "seed": SEED,
        "quota_per_stratum": QUOTA,
        "row_count": len(selected),
        "stratum_counts": dict(Counter(str(item["stratum"]) for item in selected)),
        "candidate_pool_counts": {name: len(rows) for name, rows in pools.items()},
        "source_row_numbers_1_based": [item["source_row_1_based"] for item in selected],
        "excluded_url_sources": exclusion_counts,
        "prior_data_url_overlap": len(selected_urls & excluded_urls),
        "unique_url_count": len(selected_urls),
        "articles": ARTICLES.relative_to(ROOT).as_posix(),
        "articles_sha256": sha256(ARTICLES),
        "assignments": ASSIGNMENTS.relative_to(ROOT).as_posix(),
        "assignments_sha256": sha256(ASSIGNMENTS),
        "article_content_printed": False,
        "selection_rules": {
            "same_sentence": "target + metric + numeric token",
            "official_context_bonus": True,
            "non_kosis_sentence_filter": NON_KOSIS_SENTENCE.pattern,
            "priority": ["gender", "age", "country", "product"],
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")
    print(f"locked={len(selected)} strata={manifest['stratum_counts']}")
    print(f"candidate_pools={manifest['candidate_pool_counts']}")
    print(f"overlap={manifest['prior_data_url_overlap']} unique={manifest['unique_url_count']}")
    print(f"articles_sha256={manifest['articles_sha256']}")


if __name__ == "__main__":
    main()
