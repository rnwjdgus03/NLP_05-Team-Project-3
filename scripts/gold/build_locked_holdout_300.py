#!/usr/bin/env python3
"""Build a URL-disjoint 300-row KOSIS holdout candidate set.

The selector is deliberately conservative.  It only emits claim shapes whose
official KOSIS coordinate is represented in the locked MCP development gold.
Numeric evidence is not trusted at selection time: the final ``build`` stage
requires a KOSIS MCP evidence JSONL file and drops every row that cannot be
recomputed from the connector response.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    ROOT / "data/archive/claim_candidates_filtered.csv",
    ROOT / "data/archive/claim_candidates_from_xlsx.csv",
    ROOT / "data/archive/검증대상_기사드랍후.csv",
)
DEV_GOLD = ROOT / "data/gold/mcp_full_gold_250.csv"
CANDIDATES = ROOT / "data/gold/locked_holdout_300_candidates.json"
EVIDENCE = ROOT / "data/gold/locked_holdout_300_mcp_evidence.jsonl"
OUTPUT = ROOT / "data/gold/locked_holdout_300.csv"
MANIFEST = ROOT / "data/gold/locked_holdout_300_manifest.json"

PARTIAL_PERIOD = re.compile(
    r"(?:\d{1,2}\s*[~∼～-]\s*\d{1,2}\s*일)|(?:일평균|하루\s*평균|조업일수|조업\s*일수)"
)
FORECAST = re.compile(r"전망|예상|목표|추정|계획|전망치|예측")
NON_KOSIS = re.compile(
    r"CEO스코어|기업\s*매출|회사채|영업이익|순이익|시가총액|증권사|리서치센터|"
    r"국제로봇연맹|IFR|미국\s*(?:노동부|상무부)|중국\s*국가통계국"
)

SERIES = {
    "trade_total_export": dict(domain="trade", org_id="360", tbl_id="DT_1R11001_FRM101", tbl_name="품목별 수출액 수입액", obj_l1="13102112831A.A", obj_l1_name="총액", itm_id="13103112831T1", itm_name="수출액", source_unit="천달러"),
    "trade_total_import": dict(domain="trade", org_id="360", tbl_id="DT_1R11001_FRM101", tbl_name="품목별 수출액 수입액", obj_l1="13102112831A.A", obj_l1_name="총액", itm_id="13103112831T2", itm_name="수입액", source_unit="천달러"),
    "trade_semiconductor_export": dict(domain="product", org_id="360", tbl_id="DT_1R11001_FRM101", tbl_name="품목별 수출액 수입액", obj_l1="13102112831A.7763", obj_l1_name="반도체", itm_id="13103112831T1", itm_name="수출액", source_unit="천달러"),
    "trade_auto_export": dict(domain="product", org_id="360", tbl_id="DT_1R11001_FRM101", tbl_name="품목별 수출액 수입액", obj_l1="13102112831A.781", obj_l1_name="승용자동차 및 기타의 차량", itm_id="13103112831T1", itm_name="수출액", source_unit="천달러"),
    "trade_cosmetics_export": dict(domain="product", org_id="360", tbl_id="DT_1R11001_FRM101", tbl_name="품목별 수출액 수입액", obj_l1="13102112831A.553", obj_l1_name="향수 및 화장품화장용품(비누제외)", itm_id="13103112831T1", itm_name="수출액", source_unit="천달러"),
    "trade_ship_export": dict(domain="product", org_id="360", tbl_id="DT_1R11001_FRM101", tbl_name="품목별 수출액 수입액", obj_l1="13102112831A.793", obj_l1_name="선박보트 및 부유구조물", itm_id="13103112831T1", itm_name="수출액", source_unit="천달러"),
    "trade_us_export": dict(domain="country", org_id="360", tbl_id="DT_1R11006_FRM101", tbl_name="국가별 수출액 수입액", obj_l1="13102103829E.US", obj_l1_name="미국", itm_id="13103103829T1", itm_name="수출액", source_unit="천달러"),
    "trade_us_import": dict(domain="country", org_id="360", tbl_id="DT_1R11006_FRM101", tbl_name="국가별 수출액 수입액", obj_l1="13102103829E.US", obj_l1_name="미국", itm_id="13103103829T2", itm_name="수입액", source_unit="천달러"),
    "trade_cn_export": dict(domain="country", org_id="360", tbl_id="DT_1R11006_FRM101", tbl_name="국가별 수출액 수입액", obj_l1="13102103829E.CN", obj_l1_name="중국", itm_id="13103103829T1", itm_name="수출액", source_unit="천달러"),
    "trade_cn_import": dict(domain="country", org_id="360", tbl_id="DT_1R11006_FRM101", tbl_name="국가별 수출액 수입액", obj_l1="13102103829E.CN", obj_l1_name="중국", itm_id="13103103829T2", itm_name="수입액", source_unit="천달러"),
    "cpi_yoy_total": dict(domain="cpi", org_id="101", tbl_id="DT_1J22042", tbl_name="월별 소비자물가 등락률", obj_l1="0", obj_l1_name="총지수", itm_id="T03", itm_name="전년동월비(%)", source_unit="%"),
    "cpi_mom_total": dict(domain="cpi", org_id="101", tbl_id="DT_1J22042", tbl_name="월별 소비자물가 등락률", obj_l1="0", obj_l1_name="총지수", itm_id="T02", itm_name="전월비", source_unit="%"),
    "cpi_yoy_living": dict(domain="cpi", org_id="101", tbl_id="DT_1J22042", tbl_name="월별 소비자물가 등락률", obj_l1="1", obj_l1_name="생활물가지수", itm_id="T03", itm_name="전년동월비(%)", source_unit="%"),
    "cpi_yoy_core": dict(domain="cpi", org_id="101", tbl_id="DT_1J22042", tbl_name="월별 소비자물가 등락률", obj_l1="3", obj_l1_name="농산물및석유류제외지수", itm_id="T03", itm_name="전년동월비(%)", source_unit="%"),
    "cpi_index": dict(domain="cpi", org_id="101", tbl_id="DT_1J22003", tbl_name="소비자물가지수(2020=100)", obj_l1="T10", obj_l1_name="전국", itm_id="T", itm_name="소비자물가지수(총지수)", source_unit="지수"),
    "employment_total": dict(domain="employment", org_id="101", tbl_id="DT_1DA7001S", tbl_name="성별 경제활동인구 총괄", obj_l1="0", obj_l1_name="계", itm_id="T30", itm_name="취업자", source_unit="천명"),
    "unemployment_rate": dict(domain="employment", org_id="101", tbl_id="DT_1DA7001S", tbl_name="성별 경제활동인구 총괄", obj_l1="0", obj_l1_name="계", itm_id="T80", itm_name="실업률", source_unit="%"),
    "employment_rate": dict(domain="employment", org_id="101", tbl_id="DT_1DA7001S", tbl_name="성별 경제활동인구 총괄", obj_l1="0", obj_l1_name="계", itm_id="T90", itm_name="고용률", source_unit="%"),
    "youth_employment": dict(domain="age", org_id="101", tbl_id="DT_1DA7002S", tbl_name="연령별 경제활동인구 총괄", obj_l1="75", obj_l1_name="15 - 29세", itm_id="T30", itm_name="취업자", source_unit="천명"),
    "youth_unemployment_rate": dict(domain="age", org_id="101", tbl_id="DT_1DA7002S", tbl_name="연령별 경제활동인구 총괄", obj_l1="75", obj_l1_name="15 - 29세", itm_id="T80", itm_name="실업률", source_unit="%"),
    "youth_employment_rate": dict(domain="age", org_id="101", tbl_id="DT_1DA7002S", tbl_name="연령별 경제활동인구 총괄", obj_l1="75", obj_l1_name="15 - 29세", itm_id="T90", itm_name="고용률", source_unit="%"),
    "birth_count": dict(domain="population", org_id="101", tbl_id="INH_1B8000F_01", tbl_name="출생아수 합계출산율 자연증가 등", obj_l1="11", obj_l1_name="출생아수(명)", itm_id="T1", itm_name="인구동태건수 및 동태율 추이", source_unit="명"),
    "fertility_rate": dict(domain="population", org_id="101", tbl_id="INH_1B8000F_01", tbl_name="출생아수 합계출산율 자연증가 등", obj_l1="30", obj_l1_name="합계출산율(명)", itm_id="T1", itm_name="인구동태건수 및 동태율 추이", source_unit="명"),
    "retail_total": dict(domain="retail", org_id="101", tbl_id="DT_1K41012", tbl_name="재별 및 상품군별 소매판매액지수", obj_l1="G0", obj_l1_name="총지수", itm_id="T2", itm_name="불변지수", source_unit="지수"),
}

CPI_ITEM_CODES = {
    "쌀": "A01A01101", "현미": "A01A01102", "찹쌀": "A01A01103", "보리쌀": "A01A01104",
    "땅콩": "A01A01106", "배추": "A02A01701", "상추": "A02A01702", "시금치": "A02A01703",
    "양배추": "A02A01704", "미나리": "A02A01705", "깻잎": "A02A01706", "부추": "A02A01707",
    "열무": "A02A01709", "당근": "A02A01710", "감자": "A02A01711", "고구마": "A02A01712",
    "도라지": "A02A01713", "콩나물": "A02A01714", "버섯": "A02A01715", "오이": "A02A01716",
    "풋고추": "A02A01717", "호박": "A02A01718", "토마토": "A02A01720", "양파": "A02A01722",
    "마늘": "A02A01723", "브로콜리": "A02A01724", "고사리": "A02A01725", "파프리카": "A02A01726",
    "생강": "A02A01903", "사과": "A03A01601", "복숭아": "A03A01603", "포도": "A03A01604",
    "참기름": "B01A01501", "식용유": "B01A01502", "초콜릿": "B01A01801", "사탕": "B01A01802",
    "아이스크림": "B01A01804", "비스킷": "B01A01805", "스낵과자": "B01A01806", "설탕": "B01A01808",
    "소금": "B01A01904", "간장": "B01A01905", "된장": "B01A01906", "고추장": "B01A01908",
    "김치": "B01A01915", "커피": "B01A02101", "주스": "B01A02201", "두유": "B01A02202",
    "생수": "B01A02203", "탄산음료": "B01A02205", "소주": "B01B01101", "맥주": "B01B01103",
    "막걸리": "B01B01104",
}
for _item_name, _item_code in CPI_ITEM_CODES.items():
    SERIES[f"cpi_item_{_item_code}"] = dict(
        domain="item", org_id="101", tbl_id="DT_1J22112",
        tbl_name="품목별 소비자물가지수(품목성질별: 2020=100)",
        obj_l1="T10", obj_l1_name="전국", obj_l2=_item_code,
        obj_l2_name=_item_name, itm_id="T", itm_name="소비자물가지수",
        source_unit="지수",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalized_source_rows(path: Path, url_to_article: dict[str, str]) -> list[dict[str, str]]:
    rows = read_csv(path)
    if not rows or "claim_문장" not in rows[0]:
        return rows
    normalized = []
    number_unit = re.compile(
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(%p|%|억\s*달러|만\s*달러|달러|천\s*명|만\s*명|명|지수)"
    )
    for article_no, row in enumerate(rows, start=1):
        url = row.get("URL", "").strip()
        body = row.get("기사 본문(정제)", "")
        source_hint = "국가데이터처 소비자물가" if re.search(r"(?:통계청|국가데이터처).{0,80}소비자물가|소비자물가.{0,80}(?:통계청|국가데이터처)", body) else ""
        for sentence_no, sentence in enumerate(row.get("claim_문장", "").split("||"), start=1):
            sentence = sentence.strip()
            if not sentence:
                continue
            matches = number_unit.findall(sentence)
            if not matches:
                continue
            normalized.append({
                "claim_id": f"R{article_no:04d}S{sentence_no:02d}",
                "article_id": url_to_article.get(url, str(article_no)),
                "title": row.get("기사제목", ""),
                "date": row.get("작성일", ""),
                "url": url,
                "claim_text": sentence,
                "prev_sentence": source_hint,
                "next_sentence": "",
                "numbers": ";".join(number.replace(",", "") for number, _ in matches),
                "units": ";".join(re.sub(r"\s+", "", unit) for _, unit in matches),
            })
    return normalized


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canon_article(value: Any) -> str:
    raw = str(value or "").strip()
    return f"A{int(raw):04d}" if re.fullmatch(r"\d+", raw) else raw.upper()


def month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    absolute = year * 12 + month - 1 + delta
    return absolute // 12, absolute % 12 + 1


def infer_period(text: str, published: str, prefer_annual: bool = False) -> tuple[str, str] | None:
    try:
        date = datetime.strptime(published[:10], "%Y-%m-%d")
    except ValueError:
        return None
    explicit_month = re.search(r"((?:19|20)\d{2})년\s*(1[0-2]|0?[1-9])월", text)
    if explicit_month:
        return "M", f"{explicit_month.group(1)}{int(explicit_month.group(2)):02d}"
    explicit_year = re.search(r"((?:19|20)\d{2})년", text)
    month = re.search(r"(?<!\d)(1[0-2]|0?[1-9])월", text)
    if month and not prefer_annual:
        m = int(month.group(1))
        y = int(explicit_year.group(1)) if explicit_year else date.year
        if not explicit_year and m > date.month:
            y -= 1
        return "M", f"{y}{m:02d}"
    if re.search(r"지난달|전월", text):
        y, m = month_shift(date.year, date.month, -1)
        return "M", f"{y}{m:02d}"
    if explicit_year:
        return "Y", explicit_year.group(1)
    if re.search(r"지난해|작년", text):
        return "Y", str(date.year - 1)
    if prefer_annual and re.search(r"올해|연간|한\s*해", text):
        return "Y", str(date.year)
    return None


def numeric_pairs(row: dict[str, str]) -> list[tuple[float, str]]:
    try:
        numbers = list(ast.literal_eval(row.get("numbers") or "[]"))
        units = list(ast.literal_eval(row.get("units") or "[]"))
    except (SyntaxError, ValueError, TypeError):
        numbers = [part.strip() for part in re.split(r"[;,|]", row.get("numbers", "")) if part.strip()]
        units = [part.strip() for part in re.split(r"[;,|]", row.get("units", "")) if part.strip()]
    pairs = []
    for index, value in enumerate(numbers):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        unit = str(units[index]) if index < len(units) else ""
        pairs.append((number, unit))
    return pairs


def select_value(row: dict[str, str], mode: str) -> tuple[float, str] | None:
    pairs = numeric_pairs(row)
    if mode == "rate":
        candidates = [(n, u) for n, u in pairs if "%" in u]
    elif mode == "person":
        candidates = [(n, u) for n, u in pairs if any(x in u for x in ("명", "만명", "천명"))]
    elif mode == "currency":
        candidates = [(n, u) for n, u in pairs if any(x in u for x in ("달러", "불"))]
    elif mode == "index":
        candidates = [(n, u) for n, u in pairs if n < 1000 and not (1900 <= n <= 2100)]
    else:
        candidates = [(n, u) for n, u in pairs if not (1900 <= n <= 2100)]
    if not candidates:
        return None
    # The asserted statistic is normally the final compatible number after
    # dates, comparison bases and ranges have been mentioned.
    return candidates[-1]


def previous_period(prd_se: str, period: str, text: str) -> str:
    if prd_se == "Y":
        return str(int(period) - 1)
    year, month = int(period[:4]), int(period[4:])
    if re.search(r"전월|지난달\s*대비", text):
        y, m = month_shift(year, month, -1)
    else:
        y, m = year - 1, month
    return f"{y}{m:02d}"


def fallback_release_period(series_key: str, published: str) -> tuple[str, str] | None:
    try:
        date = datetime.strptime(published[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if series_key == "fertility_rate":
        return "Y", str(date.year - 1)
    lag = -2 if series_key == "birth_count" else -1
    year, month = month_shift(date.year, date.month, lag)
    return "M", f"{year}{month:02d}"


def classify(row: dict[str, str]) -> dict[str, Any] | None:
    claim = row.get("claim_text", "")
    context = " ".join(row.get(k, "") for k in ("title", "prev_sentence", "claim_text", "next_sentence"))
    if FORECAST.search(context) or NON_KOSIS.search(context):
        return None
    series_key = ""
    value_mode = "rate"
    claim_type = "LEVEL"
    prefer_annual = False

    item_hits = [name for name in CPI_ITEM_CODES if name in claim]
    official_cpi_context = bool(re.search(r"소비자물가|통계청|국가데이터처", context))
    if len(item_hits) == 1 and official_cpi_context and "%" in claim and re.search(r"가격|물가|오르|상승|하락|내리|뛰|급등|급락|비싸|저렴", claim):
        item_code = CPI_ITEM_CODES[item_hits[0]]
        series_key, value_mode, claim_type = f"cpi_item_{item_code}", "rate", "CHANGE_RATE"
    elif re.search(r"출생아", claim):
        series_key = "birth_count"
        value_mode = "rate" if "%" in claim and re.search(r"증가|감소|늘|줄", claim) else "person"
        claim_type = "CHANGE_RATE" if value_mode == "rate" else "LEVEL"
    elif re.search(r"합계출산율", claim):
        series_key, value_mode, claim_type, prefer_annual = "fertility_rate", "index", "LEVEL", True
    elif re.search(r"소매판매|판매액지수", claim):
        series_key = "retail_total"
        value_mode = "rate" if "%" in claim and re.search(r"증가|감소|상승|하락|늘|줄", claim) else "index"
        claim_type = "CHANGE_RATE" if value_mode == "rate" else "LEVEL"
    elif re.search(r"소비자물가|물가지수|생활물가|근원물가", claim):
        if re.search(r"생활물가", claim):
            series_key = "cpi_yoy_living"
        elif re.search(r"근원물가|농산물.*석유류.*제외", claim):
            series_key = "cpi_yoy_core"
        elif re.search(r"전월\s*대비", claim):
            series_key = "cpi_mom_total"
        elif "%" in claim:
            series_key = "cpi_yoy_total"
        else:
            series_key, value_mode = "cpi_index", "index"
    elif re.search(r"실업률|고용률|취업자", claim):
        youth = bool(re.search(r"청년|15\s*[~∼-]\s*29|15세.*29세", claim))
        if re.search(r"실업률", claim):
            series_key = "youth_unemployment_rate" if youth else "unemployment_rate"
            value_mode = "rate"
        elif re.search(r"고용률", claim):
            series_key = "youth_employment_rate" if youth else "employment_rate"
            value_mode = "rate"
        else:
            series_key = "youth_employment" if youth else "employment_total"
            value_mode = "rate" if "%" in claim and re.search(r"증가|감소|늘|줄", claim) else "person"
            claim_type = "CHANGE_RATE" if value_mode == "rate" else "LEVEL"
    elif re.search(r"수출|수입", claim):
        if PARTIAL_PERIOD.search(context):
            return None
        direction = "export" if "수출" in claim else "import"
        country = "us" if "미국" in claim or "대미" in claim else "cn" if "중국" in claim or "대중" in claim else ""
        product = "semiconductor" if "반도체" in claim else "auto" if re.search(r"자동차|승용차", claim) else "cosmetics" if re.search(r"화장품|K뷰티", claim) else "ship" if re.search(r"선박|조선", claim) else ""
        if country:
            series_key = f"trade_{country}_{direction}"
        elif product and direction == "export":
            series_key = f"trade_{product}_export"
        else:
            series_key = f"trade_total_{direction}"
        value_mode = "rate" if "%" in claim and re.search(r"증가|감소|늘|줄|급증|급감", claim) else "currency"
        claim_type = "CHANGE_RATE" if value_mode == "rate" else "LEVEL"
        prefer_annual = bool(re.search(r"연간|지난해|작년|한\s*해|\d{4}년\s*(?:수출|수입)", claim))
    else:
        return None

    if series_key not in SERIES:
        return None
    period = infer_period(context, row.get("date", ""), prefer_annual=prefer_annual)
    if not period and re.search(r"통계청|국가데이터처|산업통상자원부|산업부|관세청", context):
        period = fallback_release_period(series_key, row.get("date", ""))
    value = select_value(row, value_mode)
    if not period or not value:
        return None
    prd_se, current = period
    # CPI, employment rates and fertility are published as direct rate levels.
    if series_key.startswith("cpi_") or series_key in {"unemployment_rate", "employment_rate", "youth_unemployment_rate", "youth_employment_rate", "fertility_rate"}:
        claim_type = "LEVEL"
    previous = previous_period(prd_se, current, context) if claim_type == "CHANGE_RATE" else ""
    series = dict(SERIES[series_key])
    if prd_se == "Y" and series_key.startswith("cpi_yoy_"):
        return None
    return {
        **series,
        "series_key": series_key,
        "claim_id": row["claim_id"],
        "claim_measurement_id": f"{row['claim_id']}-m1",
        "article_id": canon_article(row.get("article_id")),
        "title": row.get("title", ""),
        "date": row.get("date", ""),
        "url": row.get("url", ""),
        "claim_text": claim,
        "claim_type": claim_type,
        "claim_value": value[0],
        "claim_unit": value[1],
        "prd_se": prd_se,
        "period": current,
        "previous_period": previous,
    }


def excluded_urls() -> tuple[set[str], dict[str, int]]:
    sources = [
        (DEV_GOLD, "url"),
        (ROOT / "data/holdout5_articles.csv", "URL"),
        (ROOT / "data/holdout6_articles.csv", "URL"),
        (ROOT / "data/holdout7_disjoint_articles.csv", "URL"),
        (ROOT / "data/holdout8_stratified_articles.csv", "URL"),
    ]
    urls: set[str] = set()
    counts = {}
    for path, field in sources:
        if not path.exists():
            continue
        values = {row.get(field, "").strip() for row in read_csv(path) if row.get(field, "").strip()}
        urls.update(values)
        counts[path.relative_to(ROOT).as_posix()] = len(values)
    return urls, counts


def select(target_count: int = 300) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocked, exclusion_counts = excluded_urls()
    candidates = []
    seen_claim_text: set[tuple[str, str]] = set()
    source_counts: dict[str, int] = {}
    url_to_article = {
        row.get("url", "").strip(): row.get("article_id", "").strip()
        for row in read_csv(ROOT / "data/archive/claim_candidates_from_xlsx.csv")
        if row.get("url", "").strip() and row.get("article_id", "").strip()
    }
    for source_priority, source in enumerate(SOURCES):
        count = 0
        for row in normalized_source_rows(source, url_to_article):
            if not row.get("url") or row["url"] in blocked:
                continue
            key = (row["url"], row.get("claim_text", ""))
            if key in seen_claim_text:
                continue
            raw_date = str(row.get("date", "")).strip()
            if re.fullmatch(r"\d+(?:\.0+)?", raw_date):
                excel_date = datetime(1899, 12, 30) + timedelta(days=float(raw_date))
                row["date"] = excel_date.strftime("%Y-%m-%d")
            mapped = classify(row)
            if mapped:
                seen_claim_text.add(key)
                mapped["source_priority"] = source_priority
                candidates.append(mapped)
                count += 1
        source_counts[source.relative_to(ROOT).as_posix()] = count

    # Deterministic, domain-balanced article-first selection.  Repeated rows
    # from one article are allowed only after every available article has had
    # one chance to enter the holdout and are capped at two.
    candidates.sort(key=lambda r: (r["source_priority"], r["date"], r["article_id"], r["claim_id"]))
    by_article: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_article[row["url"]].append(row)
    domain_order = ("country", "age", "population", "product", "item", "employment", "cpi", "retail", "trade")
    selected: list[dict[str, Any]] = []
    used_claims: set[str] = set()
    for pass_no in (0, 1):
        for domain in domain_order:
            for url in sorted(by_article, key=lambda u: hashlib.sha256(f"locked-holdout-300-v1|{u}".encode()).hexdigest()):
                rows = [r for r in by_article[url] if r["domain"] == domain]
                if len(rows) <= pass_no:
                    continue
                row = rows[pass_no]
                if row["claim_id"] in used_claims:
                    continue
                selected.append(row)
                used_claims.add(row["claim_id"])
                if len(selected) >= target_count:
                    break
            if len(selected) >= target_count:
                break
        if len(selected) >= target_count:
            break
    if len(selected) < target_count:
        raise RuntimeError(
            f"only {len(selected)} selected from {len(candidates)} conservative candidates "
            f"across {len(by_article)} articles for target {target_count}"
        )
    for index, row in enumerate(selected, start=1):
        row["candidate_no"] = index
    manifest = {
        "schema_version": 1,
        "selection_seed": "locked-holdout-300-v1",
        "candidate_count": len(selected),
        "unique_article_count": len({r["url"] for r in selected}),
        "domain_counts": dict(Counter(r["domain"] for r in selected)),
        "series_counts": dict(Counter(r["series_key"] for r in selected)),
        "excluded_url_source_counts": exclusion_counts,
        "prior_url_overlap": len({r["url"] for r in selected} & blocked),
        "sources": [path.relative_to(ROOT).as_posix() for path in SOURCES],
        "source_sha256": {path.relative_to(ROOT).as_posix(): sha256(path) for path in SOURCES},
        "eligible_source_counts": source_counts,
    }
    return selected, manifest


def write_candidates(target_count: int) -> None:
    rows, manifest = select(target_count)
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest.update(candidate_file=CANDIDATES.relative_to(ROOT).as_posix(), candidate_sha256=sha256(CANDIDATES))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def load_evidence() -> dict[int, dict[str, Any]]:
    evidence = {}
    if not EVIDENCE.exists():
        return evidence
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        evidence[int(row["candidate_no"])] = row
    return evidence


def value_for_period(rows: list[dict[str, Any]], period: str) -> float | None:
    for row in rows:
        row_period = str(row.get("PRD_DE") or row.get("prdDe") or row.get("period") or "")
        if row_period != period:
            continue
        raw = row.get("DT") if row.get("DT") is not None else row.get("value")
        try:
            value = float(str(raw).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None


def compute_actual(candidate: dict[str, Any], current: float, previous: float | None) -> tuple[float, str]:
    if candidate["claim_type"] == "CHANGE_RATE":
        if previous in (None, 0):
            raise ValueError("missing previous value")
        return (current - previous) / abs(previous) * 100, "(current-previous)/abs(previous)*100"
    unit = candidate["claim_unit"]
    scale = 1.0
    if candidate["source_unit"] == "천달러":
        if "억" in unit and ("달러" in unit or "불" in unit):
            scale = 1e-5
        elif "만" in unit and ("달러" in unit or "불" in unit):
            scale = 1e-1
    elif candidate["source_unit"] == "천명" and "만명" in unit:
        scale = 0.1
    return current * scale, f"current*{scale:g}"


def label(claim: float, actual: float) -> str:
    tolerance = max(0.15 if abs(actual) < 10 else 0.5, abs(actual) * 0.015)
    return "SUPPORTS" if abs(claim - actual) <= tolerance else "REFUTES"


def build(target_count: int = 300) -> None:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    evidence = load_evidence()
    accepted = []
    rejected = []
    for candidate in candidates:
        audit = evidence.get(int(candidate["candidate_no"]))
        if not audit or not audit.get("ok"):
            rejected.append({"candidate_no": candidate["candidate_no"], "reason": "missing_or_failed_mcp_evidence"})
            continue
        rows = audit.get("rows") or []
        current = value_for_period(rows, candidate["period"])
        previous = value_for_period(rows, candidate["previous_period"]) if candidate["previous_period"] else None
        if current is None or (candidate["previous_period"] and previous is None):
            rejected.append({"candidate_no": candidate["candidate_no"], "reason": "requested_period_not_in_mcp_response"})
            continue
        try:
            actual, derivation = compute_actual(candidate, current, previous)
        except ValueError:
            rejected.append({"candidate_no": candidate["candidate_no"], "reason": "cannot_compute_actual"})
            continue
        accepted.append({
            "gold_id": f"H300-{len(accepted)+1:03d}",
            "claim_id": candidate["claim_id"],
            "claim_measurement_id": candidate["claim_measurement_id"],
            "article_id": candidate["article_id"],
            "title": candidate["title"],
            "date": candidate["date"],
            "url": candidate["url"],
            "claim_text": candidate["claim_text"],
            "claim_type": candidate["claim_type"],
            "claim_value": candidate["claim_value"],
            "claim_unit": candidate["claim_unit"],
            "gold_label": label(float(candidate["claim_value"]), actual),
            "gold_label_tier": "LOCKED_HOLDOUT_KOSIS_MCP",
            "gold_verifiable": "Y",
            "gold_ready": "Y",
            "human_reviewed": "N",
            "gold_org_id": candidate["org_id"],
            "gold_tbl_id": candidate["tbl_id"],
            "gold_tbl_name": candidate["tbl_name"],
            "gold_obj_l1": candidate["obj_l1"],
            "gold_obj_l1_name": candidate["obj_l1_name"],
            "gold_obj_l2": candidate.get("obj_l2") or "N/A",
            "gold_obj_l2_name": candidate.get("obj_l2_name") or "N/A",
            "gold_itm_id": candidate["itm_id"],
            "gold_item_name": candidate["itm_name"],
            "gold_category_name": candidate["obj_l1_name"],
            "gold_prd_se": candidate["prd_se"],
            "gold_period": candidate["period"],
            "gold_previous_period": candidate["previous_period"] or "N/A",
            "gold_source_value": current,
            "gold_previous_source_value": previous if previous is not None else "N/A",
            "gold_source_unit": candidate["source_unit"],
            "gold_actual_value": actual,
            "gold_derivation_method": derivation,
            "gold_coordinate_status": "MCP_ACTUAL_VALUE_CONFIRMED",
            "gold_label_source": "KOSIS_MCP_GET_DATA",
            "gold_evidence_url": audit.get("evidence_url", ""),
            "gold_retrieved_at": audit.get("retrieved_at", ""),
            "selection_domain": candidate["domain"],
            "selection_series": candidate["series_key"],
        })
        if len(accepted) >= target_count:
            break
    if len(accepted) != target_count:
        raise RuntimeError(f"expected {target_count} accepted rows, got {len(accepted)}; rejected={len(rejected)}")
    fields = list(accepted[0])
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(accepted)
    dev_urls = {r["url"] for r in read_csv(DEV_GOLD)}
    output_urls = {r["url"] for r in accepted}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lock_status": "LOCKED_DO_NOT_TUNE",
        "row_count": len(accepted),
        "unique_article_count": len(output_urls),
        "label_counts": dict(Counter(r["gold_label"] for r in accepted)),
        "domain_counts": dict(Counter(r["selection_domain"] for r in accepted)),
        "table_counts": dict(Counter(r["gold_tbl_id"] for r in accepted)),
        "claim_type_counts": dict(Counter(r["claim_type"] for r in accepted)),
        "dev_gold_url_overlap": len(output_urls & dev_urls),
        "blank_required_count": sum(not str(r.get(k, "")).strip() for r in accepted for k in ("article_id", "title", "url", "claim_text", "gold_tbl_id", "gold_obj_l1", "gold_itm_id", "gold_period", "gold_actual_value")),
        "human_reviewed": False,
        "candidate_file": CANDIDATES.relative_to(ROOT).as_posix(),
        "candidate_sha256": sha256(CANDIDATES),
        "evidence_file": EVIDENCE.relative_to(ROOT).as_posix(),
        "evidence_sha256": sha256(EVIDENCE),
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "output_sha256": sha256(OUTPUT),
        "rejected_before_target": rejected,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    select_parser = sub.add_parser("select")
    select_parser.add_argument("--target-count", type=int, default=300)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--target-count", type=int, default=300)
    args = parser.parse_args()
    if args.command == "select":
        write_candidates(args.target_count)
    else:
        build(args.target_count)


if __name__ == "__main__":
    main()
