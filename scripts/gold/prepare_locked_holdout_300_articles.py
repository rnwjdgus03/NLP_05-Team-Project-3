#!/usr/bin/env python3
"""Lock 300 URL-disjoint news articles for final KOSIS evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/archive/검증대상_기사드랍후.csv"
ARTICLE_MAP = ROOT / "data/archive/claim_candidates_from_xlsx.csv"
OUTPUT = ROOT / "data/locked_holdout_300_articles.csv"
ASSIGNMENTS = ROOT / "data/locked_holdout_300_assignments.csv"
MANIFEST = ROOT / "data/locked_holdout_300_manifest.json"
SEED = "locked-holdout-300-articles-v1-20260810"

TITLE = "기사제목"
DATE = "작성일"
URL = "URL"
BODY = "기사 본문(정제)"
LABEL = "검색 구분 레이블"
CLAIMS = "claim_문장"

OFFICIAL = re.compile(
    r"통계청|국가데이터처|국가통계포털|KOSIS|관세청|산업통상자원부|산업부|"
    r"고용노동부|농림축산식품부|국토교통부|보건복지부|한국은행|조사\s*결과|통계\s*발표"
)
NUMBER = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:%p|%포인트|%|억\s*달러|만\s*달러|달러|억원|조원|"
    r"천명|만명|명|건|가구|대|지수)"
)
NON_KOSIS = re.compile(
    r"회사채|은행채|기업어음|영업이익|순이익|시가총액|CEO스코어|국제로봇연맹|IFR|"
    r"미국\s*(?:노동부|상무부)|중국\s*국가통계국|전망|예상|목표|계획"
)
METRIC = re.compile(
    r"수출|수입|무역|소비자물가|물가지수|가격|고용률|실업률|취업자|경제활동인구|"
    r"출생아|출산율|혼인|사망|인구|소매판매|서비스업생산|산업생산|생산지수|"
    r"국내총생산|GDP|성장률|농가|가구|소득|임금"
)
TARGETS = {
    "gender": re.compile(r"남성|여성|남자|여자|성별|남녀"),
    "age": re.compile(r"청년|고령|노년|20대|30대|40대|50대|60대|70대|\d{1,2}\s*[~∼-]\s*\d{1,2}\s*세"),
    "country": re.compile(r"미국|중국|일본|베트남|독일|프랑스|영국|인도|대만|홍콩|캐나다|호주|러시아|유럽연합|EU|대미|대중|대일"),
    "product": re.compile(r"반도체|자동차|승용차|화장품|선박|철강|석유|배터리|의약품|바이오|농산물|수산물|식품|쌀|배추|사과|라면|커피"),
    "region": re.compile(r"서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|시군구|지역별"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_article_id(value: str) -> str:
    raw = str(value or "").strip()
    return f"A{int(raw):04d}" if re.fullmatch(r"\d+", raw) else raw.upper()


def normalize_date(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.0+)?", raw):
        return (datetime(1899, 12, 30) + timedelta(days=float(raw))).strftime("%Y-%m-%d")
    return raw[:10]


def excluded_urls() -> tuple[set[str], dict[str, int]]:
    sources = [
        (ROOT / "data/gold/mcp_full_gold_250.csv", "url"),
        (ROOT / "data/holdout5_articles.csv", "URL"),
        (ROOT / "data/holdout6_articles.csv", "URL"),
        (ROOT / "data/holdout7_disjoint_articles.csv", "URL"),
        (ROOT / "data/holdout8_stratified_articles.csv", "URL"),
    ]
    blocked: set[str] = set()
    counts = {}
    for path, field in sources:
        if not path.exists():
            continue
        values = {row.get(field, "").strip() for row in read_csv(path) if row.get(field, "").strip()}
        blocked.update(values)
        counts[path.relative_to(ROOT).as_posix()] = len(values)
    return blocked, counts


def candidate(row: dict[str, str], source_row: int) -> dict[str, object] | None:
    text = f"{row.get(TITLE, '')} {row.get(CLAIMS, '')}"
    body = row.get(BODY, "")
    if not row.get(URL, "").strip() or NON_KOSIS.search(text):
        return None
    if not NUMBER.search(text) or not METRIC.search(text):
        return None
    official = bool(OFFICIAL.search(text) or OFFICIAL.search(body))
    strata = [name for name, pattern in TARGETS.items() if pattern.search(text)]
    stratum = strata[0] if strata else "general"
    score = 2 + int(official) * 4 + min(len(strata), 2)
    if OFFICIAL.search(text):
        score += 2
    if stratum != "general":
        score += 1
    return {
        "source_row_1_based": source_row,
        "stratum": stratum,
        "all_strata": "|".join(strata) if strata else "general",
        "selection_score": score,
        "official_context": "Y" if official else "N",
        "url": row[URL].strip(),
        "row": row,
    }


def main() -> None:
    blocked, exclusion_counts = excluded_urls()
    url_to_article = {
        row.get("url", "").strip(): canonical_article_id(row.get("article_id", ""))
        for row in read_csv(ARTICLE_MAP)
        if row.get("url", "").strip()
    }
    pool = []
    for source_row, row in enumerate(read_csv(SOURCE), start=1):
        if row.get(URL, "").strip() in blocked:
            continue
        item = candidate(row, source_row)
        if item:
            pool.append(item)

    def rank(item: dict[str, object]) -> tuple[object, ...]:
        tie = hashlib.sha256(f"{SEED}|{item['url']}".encode()).hexdigest()
        return (-int(item["selection_score"]), tie)

    quotas = {"gender": 12, "age": 45, "country": 75, "product": 75, "region": 35, "general": 58}
    selected = []
    used: set[str] = set()
    for stratum in ("gender", "age", "region", "country", "product", "general"):
        available = sorted((item for item in pool if item["stratum"] == stratum and item["url"] not in used), key=rank)
        chosen = []
        chosen_urls: set[str] = set()
        for item in available:
            url = str(item["url"])
            if url in chosen_urls:
                continue
            chosen.append(item)
            chosen_urls.add(url)
            if len(chosen) >= quotas[stratum]:
                break
        selected.extend(chosen)
        used.update(str(item["url"]) for item in chosen)
    if len(selected) < 300:
        reserve = sorted((item for item in pool if item["url"] not in used), key=rank)
        for item in reserve:
            url = str(item["url"])
            if url in used:
                continue
            selected.append(item)
            used.add(url)
            if len(selected) >= 300:
                break
    if len(selected) != 300:
        raise RuntimeError(f"only {len(selected)} disjoint articles available")

    article_rows = []
    assignment_rows = []
    for index, item in enumerate(selected, start=1):
        row = dict(item["row"])
        url = str(item["url"])
        # The archive's 1-based source row is the canonical article number when
        # the URL is absent from the auxiliary article map.
        article_id = url_to_article.get(url) or f"A{int(item['source_row_1_based']):04d}"
        row.update(
            holdout_id=f"LH300-{index:03d}",
            article_id=article_id,
            date_iso=normalize_date(row.get(DATE, "")),
            lock_status="LOCKED_DO_NOT_TUNE",
            selection_stratum=item["stratum"],
        )
        article_rows.append(row)
        assignment_rows.append({
            "holdout_id": f"LH300-{index:03d}",
            "article_id": article_id,
            "stratum": item["stratum"],
            "all_strata": item["all_strata"],
            "selection_score": item["selection_score"],
            "official_context": item["official_context"],
            "source_row_1_based": item["source_row_1_based"],
            "date": normalize_date(row.get(DATE, "")),
            "title": row.get(TITLE, ""),
            "url": url,
        })

    article_fields = ["holdout_id", "article_id", "date_iso", "lock_status", "selection_stratum", TITLE, DATE, URL, BODY, LABEL, CLAIMS]
    write_csv(OUTPUT, article_rows, article_fields)
    write_csv(ASSIGNMENTS, assignment_rows, list(assignment_rows[0]))
    selected_urls = {str(item["url"]) for item in selected}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "lock_status": "LOCKED_DO_NOT_TUNE",
        "selection_seed": SEED,
        "evaluation_unit": "article",
        "row_count": 300,
        "unique_url_count": len(selected_urls),
        "unique_article_id_count": len({row["article_id"] for row in article_rows}),
        "stratum_counts": dict(Counter(str(item["stratum"]) for item in selected)),
        "official_context_counts": dict(Counter(str(item["official_context"]) for item in selected)),
        "candidate_pool_count": len(pool),
        "candidate_pool_stratum_counts": dict(Counter(str(item["stratum"]) for item in pool)),
        "prior_url_overlap": len(selected_urls & blocked),
        "excluded_url_sources": exclusion_counts,
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": sha256(SOURCE),
        "articles": OUTPUT.relative_to(ROOT).as_posix(),
        "articles_sha256": sha256(OUTPUT),
        "assignments": ASSIGNMENTS.relative_to(ROOT).as_posix(),
        "assignments_sha256": sha256(ASSIGNMENTS),
        "label_status": "UNSEEN_LOCKED_INPUT_NOT_YET_MCP_GOLD",
        "human_reviewed": False,
        "selection_rules": {
            "same_article": "numeric token + KOSIS-compatible metric",
            "official_context_bonus": True,
            "non_kosis_filter": NON_KOSIS.pattern,
            "article_disjoint": True,
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
