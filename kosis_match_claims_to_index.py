#!/usr/bin/env python3
"""
claim ↔ KOSIS 통계표/메타 인덱스 후보 매칭.

이 스크립트가 하는 일
- claim CSV의 indicator/keywords/claim_text/value/unit/period를 읽는다.
- kosis_table_index.csv에서 후보 tbl_id를 검색한다.
- kosis_meta_index.csv가 있으면 obj/itm 코드 후보까지 검색한다.
- 최종 판정은 하지 않고, 사람이 검토 가능한 후보 CSV를 만든다.

즉, 코드북/하드코딩 규칙이 아니라 KOSIS API에서 만든 표/메타 인덱스를 이용해
claim별 tbl_id/obj/itm 후보를 생성하는 레이어다.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from prepare_kosis_mapping_input import (
    canonicalize_unit,
    normalize_row as normalize_mapping_row,
    unit_dimension as infer_unit_dimension,
)
from kosis_semantic_search import (
    DEFAULT_RERANKER_MODEL,
    SemanticSearchRuntime,
    build_claim_query,
    file_sha256,
    normalized_rrf_score,
    table_key,
)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_TABLE_INDEX_CANDIDATES = [
    PROJECT_DIR / "data/claims/kosis_table_index.csv",
]
DEFAULT_META_INDEX = PROJECT_DIR / "data/claims/kosis_meta_index.csv"
DEFAULT_SEMANTIC_INDEX = PROJECT_DIR / "data/indexes/kosis_bge_m3"

csv.field_size_limit(sys.maxsize)


DOMAIN_HINTS = {
    "무역": ["무역", "국제수지", "수출", "수입", "품목별", "국가별"],
    "수출": ["무역", "국제수지", "수출", "수입", "품목별"],
    "물가": ["물가", "소비자물가", "생산자물가", "수입물가"],
    "고용": ["고용", "실업", "취업", "경제활동", "노동"],
    "인구": ["인구", "출생", "혼인", "사망"],
    "소매": ["소매", "도소매", "서비스", "판매"],
    "산업": ["산업", "생산", "광업", "제조업", "경기"],
    "GDP": ["국민계정", "국내총생산", "GDP", "성장률"],
    "항공": ["교통", "항공", "여객", "운송"],
    "여객": ["교통", "항공", "여객", "운송"],
    "로봇": ["로봇", "산업", "제조업"],
}

DOMAIN_FILTERS = {
    "무역": ["무역", "국제수지", "수출", "수입"],
    "수출": ["무역", "국제수지", "수출", "수입"],
    "물가": ["물가"],
    "고용": ["고용", "실업", "취업", "경제활동", "노동"],
    "인구": ["인구", "출생", "혼인", "사망"],
    "소매": ["소매", "도소매", "서비스"],
    "산업": ["산업", "생산", "광업", "제조업", "경기"],
    "GDP": ["국민계정", "국내총생산", "GDP"],
    "항공": ["교통", "항공", "여객", "운송"],
    "여객": ["교통", "항공", "여객", "운송"],
    "로봇": ["로봇"],
}

TOKEN_EXPANSIONS = {
    "한국": ["전국", "총액", "전체"],
    "전체": ["총액", "계"],
    "수출": ["수출액", "품목별", "총액"],
    "수입": ["수입액", "품목별", "총액"],
    "무역수지": ["무역", "수출액", "수입액", "국제수지"],
    "흑자": ["무역수지", "수출액", "수입액"],
    "적자": ["무역수지", "수출액", "수입액"],
    "자동차": ["승용자동차", "차량", "자동차"],
    "완성차": ["승용자동차", "차량", "자동차"],
    "선박": ["선박", "보트", "부유구조물"],
    "반도체": ["반도체", "전자집적회로", "메모리", "디바이스"],
    "화장품": ["화장품", "화장용품", "향수"],
    "석유화학": ["석유", "화학", "화학제품"],
    "바이오헬스": ["의약품", "의료용품", "바이오"],
    "농수산식품": ["식품", "농산물", "수산", "어류"],
    "최저임금": ["임금", "노동", "근로"],
}

STOPWORDS = {
    "기록", "전년", "대비", "지난", "올해", "작년", "지난해", "이번", "억원",
    "억달러", "달러", "증가", "감소", "상승", "하락", "최대", "처음",
}

GENERIC_ANCHORS = {
    "수", "액", "금액", "비율", "증감률", "증가율", "감소율", "상승률", "하락률",
    "수출", "수입", "수출액", "수입액", "기업", "현황", "전체", "총액",
}

ITEM_FAMILIES = {
    "반도체": ["반도체", "전자집적회로", "메모리", "초소형조립회로"],
    "자동차": ["자동차", "승용자동차", "차량"],
    "화장품": ["화장품", "화장용품", "K뷰티"],
    "바이오헬스": ["바이오", "의약품", "의료용품"],
    "농수산식품": ["농수산", "농산물", "수산물", "식품", "K푸드"],
    "석유화학": ["석유화학", "화학제품"],
    "선박": ["선박", "보트", "부유구조물"],
}


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        return rows, list(rows[0].keys()) if rows else []


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compact(text):
    return re.sub(r"\s+", "", str(text or "").strip())


def get_first(row, *keys):
    for key in keys:
        value = row.get(key, "")
        if value is not None and str(value).strip() != "":
            return value
    return ""


def normalized_claim_row(row):
    """A팀/HCX 파일마다 다른 컬럼명을 후보 매칭용 표준명으로 맞춘다."""
    if any(key in row for key in ("measurement_indicator", "measurement_period", "measurement_prd_se")):
        row = normalize_mapping_row(row)
    return {
        "claim_id": get_first(row, "claim_id", "claimId", "id"),
        "claim_measurement_id": get_first(row, "claim_measurement_id", "measurement_id"),
        "indicator": get_first(row, "measurement_indicator", "indicator", "지표"),
        "metric_domain": get_first(row, "metric_domain", "도메인", "검색 구분 레이블"),
        "industry_or_item": get_first(row, "measurement_item", "industry_or_item", "품목", "산업", "대상"),
        "keywords": get_first(row, "keywords", "키워드"),
        "region": get_first(row, "region", "지역"),
        "age_group": get_first(row, "age_group", "연령"),
        "gender": get_first(row, "gender", "성별"),
        "value": get_first(row, "value", "값", "수치"),
        "unit": get_first(row, "canonical_unit", "unit", "단위"),
        "raw_unit": get_first(row, "raw_unit", "unit", "단위"),
        "unit_dimension": get_first(row, "unit_dimension"),
        "semantic_type": get_first(row, "semantic_type"),
        "entity_type": get_first(row, "entity_type"),
        "value_type": get_first(row, "value_type"),
        "measurement_role": get_first(row, "measurement_role"),
        "measurement_usage": get_first(row, "measurement_usage"),
        "claim_domain_scope": get_first(row, "claim_domain_scope"),
        "measurement_binding_source": get_first(row, "measurement_binding_source"),
        "mapping_eligible": get_first(row, "mapping_eligible"),
        "mapping_exclusion_code": get_first(row, "mapping_exclusion_code"),
        "mapping_exclusion_reason": get_first(row, "mapping_exclusion_reason"),
        "period": get_first(row, "measurement_period", "period", "작성일", "date"),
        "prd_se": get_first(row, "measurement_prd_se", "prd_se", "주기"),
        "change_base": get_first(row, "change_base"),
        "comparison_period": get_first(row, "comparison_period"),
        "claim_text": get_first(row, "claim_text", "문장", "sentence", "evidence_text"),
    }


def tokens_from_text(text):
    raw = re.findall(r"[가-힣A-Za-z0-9]+", str(text or ""))
    out = []
    joined = compact(text)
    for token in raw:
        if len(token) < 2 or token in STOPWORDS:
            continue
        out.append(token)
        out.extend(TOKEN_EXPANSIONS.get(token, []))
    for k, vals in TOKEN_EXPANSIONS.items():
        if compact(k) in joined:
            out.extend(vals)
    return out


def claim_tokens(row):
    row = normalized_claim_row(row)
    weighted = []
    weights = [
        ("indicator", 5),
        ("industry_or_item", 5),
        ("keywords", 3),
        ("metric_domain", 3),
        ("region", 2),
        ("age_group", 2),
        ("gender", 2),
        # 본문 전체는 너무 많은 잡음을 만들기 때문에 후보 검색에서는 약하게만 쓴다.
        ("claim_text", 1),
    ]
    for col, w in weights:
        toks = tokens_from_text(row.get(col, ""))
        for _ in range(w):
            weighted.extend(toks)
    domain = str(row.get("metric_domain", ""))
    indicator = str(row.get("indicator", ""))
    for key, hints in DOMAIN_HINTS.items():
        if key in domain or key in indicator:
            weighted.extend(hints * 2)
    # 점수 계산량을 줄이기 위해 중복 토큰은 빈도로 가중치만 반영하고,
    # 너무 많은 토큰은 상위 토큰만 사용한다.
    counts = Counter(weighted)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    compact_seen = set()
    out = []
    for tok, weight in ranked:
        ctok = compact(tok)
        if len(ctok) < 2 or ctok in compact_seen:
            continue
        compact_seen.add(ctok)
        out.append((tok, ctok, weight))
        if len(out) >= 30:
            break
    return out


def norm_table_row(row):
    return {
        "org_id": row.get("org_id") or row.get("ORG_ID") or "",
        "tbl_id": row.get("tbl_id") or row.get("TBL_ID") or "",
        "tbl_name": row.get("tbl_name") or row.get("TBL_NM") or "",
        "stat_id": row.get("stat_id") or row.get("STAT_ID") or "",
        "category_path": row.get("category_path") or row.get("path") or "",
    }


def score_text(weighted_tokens, compact_text):
    score = 0
    hits = []
    for tok, ctok, weight in weighted_tokens:
        if not ctok:
            continue
        if ctok in compact_text:
            inc = max(1, min(len(ctok), 8))
            score += inc * max(1, min(weight, 6))
            hits.append(tok)
    return score, hits


def measurement_anchors(claim):
    claim = normalized_claim_row(claim)
    source = f"{claim.get('indicator', '')} {claim.get('industry_or_item', '')}"
    anchors = []
    for token in re.findall(r"[가-힣A-Za-z0-9]+", source):
        compacted = compact(token)
        if len(compacted) >= 2 and compacted not in GENERIC_ANCHORS:
            anchors.append(compacted)
    compact_source = compact(source)
    for canonical, variants in {
        "로봇": ("로봇", "로봇화"),
        "항공": ("항공", "국제선", "LCC", "저비용항공사", "대형항공사"),
        "여객": ("여객", "이용객"),
    }.items():
        if any(compact(variant) in compact_source for variant in variants):
            anchors.append(canonical)
    return list(dict.fromkeys(anchors))


def claim_item_family(claim):
    claim = normalized_claim_row(claim)
    focused = compact(f"{claim.get('industry_or_item', '')} {claim.get('indicator', '')}")
    for family, aliases in ITEM_FAMILIES.items():
        if family in focused or any(compact(alias) in focused for alias in aliases):
            return family
    return ""


def table_year_penalty(table_text, period):
    match = re.search(r"(?:19|20)\d{2}", str(period or ""))
    if not match:
        return 0
    target_year = int(match.group())
    years = [int(year) for year in re.findall(r"(?:19|20)\d{2}", table_text)]
    if years and max(years) < target_year - 1:
        return -300
    if "이전" in table_text and years and max(years) < target_year:
        return -300
    return 0


def score_table(row, tokens, claim):
    score_name, hits_name = score_text(tokens, row["_compact_tbl_name"])
    score_path, hits_path = score_text(tokens, row["_compact_category_path"])
    score = score_name * 2 + score_path
    norm_claim = normalized_claim_row(claim)
    table_text = compact(f"{row['tbl_name']} {row['category_path']}")
    anchors = measurement_anchors(norm_claim)
    family = claim_item_family(norm_claim)

    anchor_hits = [anchor for anchor in anchors if anchor in table_text]
    if anchor_hits:
        score += 120 + 20 * len(anchor_hits)
    elif anchors:
        # Generic product-by-trade tables can legitimately hold an item only in
        # OBJ metadata.  Other domains must expose the measurement subject in
        # the table name/path or they are noise.
        is_trade_item = (
            any(token in compact(norm_claim.get("indicator")) for token in ("수출", "수입", "무역수지"))
            and "품목별" in table_text
            and any(token in table_text for token in ("수출", "수입", "무역"))
        )
        score += 80 if is_trade_item else -160

    if family:
        own_aliases = [compact(alias) for alias in ITEM_FAMILIES[family]]
        if any(alias in table_text for alias in own_aliases):
            score += 140
        for other_family, aliases in ITEM_FAMILIES.items():
            if other_family == family:
                continue
            if any(compact(alias) in table_text for alias in aliases):
                score -= 220
                break

    semantic = norm_claim.get("semantic_type", "")
    indicator_text = compact(norm_claim.get("indicator"))
    focused_text = compact(
        f"{norm_claim.get('indicator', '')} {norm_claim.get('industry_or_item', '')}"
    )
    is_trade_claim = any(
        token in indicator_text for token in ("수출", "수입", "무역수지")
    )

    # Dense retrieval is intentionally broad. These are population/metric
    # mismatches that semantic similarity must never promote to rank 1.
    if is_trade_claim and "기업혁신조사" in table_text:
        return -10**9, []
    if is_trade_claim and "바이오헬스" in focused_text:
        domestic_or_import_only = (
            any(token in table_text for token in ("국내매출", "유지보수매출"))
            or ("수입" in table_text and "수출" not in table_text)
        )
        if domestic_or_import_only:
            return -10**9, []
    if "무역수지" in indicator_text and not any(
        token in table_text
        for token in ("무역수지", "품목별수출액", "품목별수입액", "국제수지")
    ):
        return -10**9, []
    if any(token in indicator_text for token in ("국제선여객", "LCC", "대형항공사")):
        if any(token in table_text for token in ("지역간통행량", "국가교통조사")):
            return -10**9, []
    if "정비사" in indicator_text and any(
        token in table_text for token in ("부족인원", "부족률")
    ):
        return -10**9, []

    period_match = re.search(r"(?:19|20)\d{2}", str(norm_claim.get("period") or ""))
    archived_match = re.search(r"_((?:19|20)\d{2})$", row.get("tbl_id", ""))
    if period_match and archived_match:
        archived_year = int(archived_match.group(1))
        if archived_year < int(period_match.group()):
            return -10**9, []

    if any(token in indicator_text for token in ("수출", "수입", "무역수지")):
        if "품목별수출액,수입액" in table_text or "품목별수출액수입액" in table_text:
            score += 280

    if semantic in {"amount", "rate_change", "absolute_change"}:
        if any(token in table_text for token in ("EBSI", "전망", "경기지수")):
            return -10**9, []
        if any(token in table_text for token in ("감소주요요인", "증가주요요인", "순위")):
            return -10**9, []

    entity = norm_claim.get("entity_type", "")
    if entity == "organization" and any(token in table_text for token in ("인력", "종사자", "피고용자")):
        score -= 240
    if entity == "person" and any(token in table_text for token in ("매출액", "무역수지", "수출입비율")):
        score -= 240

    if "정비사" in indicator_text:
        if "정비사" in table_text:
            score += 180
        elif "항공사별통계" in table_text:
            score += 80
        else:
            score -= 220
    if any(token in indicator_text for token in ("여객", "이용객", "LCC", "대형항공사")):
        if any(token in table_text for token in ("여객", "국제선", "항공사별통계")):
            score += 120
        else:
            score -= 220
    if any(token in indicator_text for token in ("LCC", "대형항공사")) and "항공사별통계" in table_text:
        score += 220
    if "로봇" in compact(f"{norm_claim.get('indicator')} {norm_claim.get('industry_or_item')}"):
        if entity == "organization" and any(token in table_text for token in ("사업체수", "기업수", "업체수")):
            score += 240
        elif entity == "organization" and any(token in table_text for token in ("수입현황", "생산현황", "출하현황", "인력현황")):
            score -= 180

    if "항공" in measurement_anchors(norm_claim):
        if any(token in table_text for token in ("수상여객", "철도여객", "도로여객")):
            return -10**9, []
    score += table_year_penalty(f"{row['tbl_name']} {row['category_path']}", norm_claim.get("period"))
    return score, list(dict.fromkeys(hits_name + hits_path))


def domain_filter_terms(claim):
    claim = normalized_claim_row(claim)
    focused = f"{claim.get('indicator','')} {claim.get('industry_or_item','')}"
    anchors = measurement_anchors(claim)
    if "항공" in anchors:
        return [compact(term) for term in DOMAIN_FILTERS["항공"]]
    if "로봇" in anchors:
        return [compact(term) for term in DOMAIN_FILTERS["로봇"]]
    # Measurement-level meaning wins over a stale claim-level domain label.
    inferred = []
    for key, terms in DOMAIN_FILTERS.items():
        if key in focused:
            inferred.extend(compact(term) for term in terms)
    if inferred:
        return list(dict.fromkeys(term for term in inferred if term))
    text = f"{claim.get('metric_domain','')} {claim.get('indicator','')}"
    out = []
    for key, terms in DOMAIN_FILTERS.items():
        if key in text:
            out.extend(compact(t) for t in terms)
    return list(dict.fromkeys(t for t in out if t))


def filtered_tables_for_claim(table_rows, claim, hard_limit=25000):
    claim = normalized_claim_row(claim)
    terms = domain_filter_terms(claim)
    if not terms:
        return table_rows
    filtered = [
        r for r in table_rows
        if any(t in r["_compact_tbl_name"] or t in r["_compact_category_path"] for t in terms)
    ]
    if not filtered:
        return table_rows
    # 도메인 필터 뒤에도 너무 크면 표명 매칭이 있는 것을 우선한다.
    if len(filtered) > hard_limit:
        name_hits = [
            r for r in filtered
            if any(t in r["_compact_tbl_name"] for t in terms)
        ]
        if name_hits:
            return name_hits[:hard_limit]
        return filtered[:hard_limit]
    return filtered


def load_meta_index(path: Path):
    if not path.exists():
        return defaultdict(list)
    rows, _ = read_csv(path)
    by_table = defaultdict(list)
    for r in rows:
        by_table[(r.get("org_id", ""), r.get("tbl_id", ""))].append(r)
    return by_table


def top_meta_candidates(meta_rows, tokens, limit=8):
    scored = []
    for r in meta_rows:
        text = compact(f"{r.get('axis_name','')} {r.get('code_name','')} {r.get('unit_name','')}")
        score, hits = score_text(tokens, text)
        if score:
            scored.append((score, hits, r))
    scored.sort(key=lambda x: (-x[0], x[2].get("is_item", ""), x[2].get("axis_id", ""), x[2].get("code_name", "")))
    out = []
    for score, hits, r in scored[:limit]:
        out.append({
            "axis_id": r.get("axis_id") or r.get("OBJ_ID", ""),
            "axis_name": r.get("axis_name") or r.get("OBJ_NM", ""),
            "code_id": r.get("code_id") or r.get("ITM_ID", ""),
            "code_name": r.get("code_name") or r.get("ITM_NM", ""),
            "is_item": r.get("is_item", ""),
            "unit_name": r.get("unit_name") or r.get("UNIT_NM", ""),
            "score": score,
            "hits": ",".join(list(dict.fromkeys(hits))[:12]),
        })
    return out


BROAD_OBJ_HINTS = {
    "반도체": {
        "prefer": ["전자집적회로", "초소형", "메모리", "반도체"],
        "avoid": ["감광성", "다이오드", "트랜지스터", "부분품", "액정"],
    },
    "자동차": {
        "prefer": ["자동차", "승용자동차", "차량"],
        "avoid": [],
    },
    "화장품": {
        "prefer": ["화장품", "화장용품"],
        "avoid": ["탈모제", "향수"],
    },
}


def score_structured_meta(row, norm_claim, weighted_tokens):
    """메타 코드 하나를 item/obj 후보로 점수화한다. 너무 세부 품목은 감점한다."""
    text = " ".join(str(norm_claim.get(k, "")) for k in ["indicator", "industry_or_item"])
    ctext = compact(text)
    cname = compact(row.get("code_name") or row.get("ITM_NM", ""))
    caxis = compact(row.get("axis_name") or row.get("OBJ_NM", ""))
    focused_tokens = [
        (token, compact(token), 5)
        for token in tokens_from_text(text)
        if compact(token)
    ]
    score, hits = score_text(
        focused_tokens,
        compact(f"{row.get('axis_name','')} {row.get('code_name','')} {row.get('unit_name','')}"),
    )

    # 항목(item) 쪽: 수출액/수입액/증감률 같은 값 종류를 강하게 맞춘다.
    if (row.get("is_item") == "Y" or row.get("OBJ_ID") == "ITEM"):
        if "수출" in ctext and "수출" in cname:
            score += 80
        if "수입" in ctext and "수입" in cname:
            score += 80
        semantic = norm_claim.get("semantic_type", "")
        if semantic == "rate_change":
            if any(k in cname for k in ["증감률", "증가율", "감소율", "등락률"]):
                score += 100
            elif "비율" in cname or "구성비" in cname:
                score -= 120
            elif any(k in cname for k in ["수출액", "수입액", "사업체수", "기업수", "인원", "여객"]):
                score += 30
        elif semantic == "rate_level":
            if any(k in cname for k in ["비율", "구성비", "점유율"]):
                score += 100
        return score, hits

    # 분류(obj) 쪽: broad claim이면 broad-ish 코드를 선호하고 너무 좁은 코드를 피한다.
    if caxis:
        score += 2
    for broad, cfg in BROAD_OBJ_HINTS.items():
        if broad in ctext:
            if any(compact(p) in cname for p in cfg["prefer"]):
                score += 70
            if any(compact(a) in cname for a in cfg["avoid"]):
                score -= 70
    family = claim_item_family(norm_claim)
    if family:
        own_aliases = [compact(alias) for alias in ITEM_FAMILIES[family]]
        if any(alias in cname for alias in own_aliases):
            score += 120
        for other_family, aliases in ITEM_FAMILIES.items():
            if other_family != family and any(compact(alias) in cname for alias in aliases):
                score -= 240
                break
    if cname in {"계", "전체", "총액", "전국"}:
        score += 5
    return score, hits


def meta_unit_dimension(meta_unit, item_name=""):
    """Infer a KOSIS unit dimension, using the ITEM name only for rate items."""
    dimension = infer_unit_dimension(canonicalize_unit(meta_unit))
    if dimension != "unknown":
        return dimension
    item = compact(item_name)
    if any(token in item for token in ("비율", "증감률", "증가율", "감소율", "등락률", "구성비")):
        return "rate"
    return "unknown"


def item_mapping_type(norm_claim, meta_unit, item_name):
    """Return how an ITEM can produce the claim value, or an incompatibility reason."""
    claim_dimension = norm_claim.get("unit_dimension") or infer_unit_dimension(norm_claim.get("unit", ""))
    item_dimension = meta_unit_dimension(meta_unit, item_name)
    semantic = norm_claim.get("semantic_type", "")
    indicator = compact(norm_claim.get("indicator", ""))
    compact_item = compact(item_name)

    if "정비사" in indicator and not any(
        token in compact_item for token in ("정비사", "정비인력", "종사자", "인력")
    ):
        return "", f"정비사 claim에 다른 ITEM={item_name}"
    if any(token in indicator for token in ("여객", "이용객")) and not any(
        token in compact_item for token in ("여객", "이용객", "승객")
    ):
        return "", f"여객 claim에 다른 ITEM={item_name}"
    if norm_claim.get("entity_type") == "organization" and "로봇" in indicator:
        if not any(token in compact_item for token in ("사업체", "기업", "업체")):
            return "", f"기업 수 claim에 다른 ITEM={item_name}"

    if semantic == "rate_change":
        if item_dimension == "rate" and any(
            token in compact_item for token in ("증감률", "증가율", "감소율", "등락률")
        ):
            return "direct", ""
        if item_dimension == "rate":
            return "", f"증감률 claim에 일반 비율 ITEM={item_name}"
        if item_dimension in {"currency", "person_count", "count", "quantity"}:
            return "rate_from_level", "KOSIS 수준값에서 증감률 계산 필요"
        return "", f"증감률을 계산할 수 없는 KOSIS 단위={meta_unit or '-'}"
    if semantic == "absolute_change":
        if item_dimension == claim_dimension and item_dimension != "unknown":
            return "difference_from_level", "KOSIS 수준값에서 증감량 계산 필요"
        return "", f"증감량과 KOSIS 단위 차원 불일치: {claim_dimension}/{item_dimension}"
    if semantic == "rate_level":
        if item_dimension == "rate":
            return "direct", ""
        return "", f"비율 claim에 비율이 아닌 ITEM={item_name}"
    if claim_dimension == "unknown" or item_dimension == "unknown":
        return "", f"단위 차원을 확정할 수 없음: claim={claim_dimension}, KOSIS={item_dimension}"
    if claim_dimension != item_dimension:
        return "", f"단위 차원 불일치: claim={claim_dimension}, KOSIS={item_dimension}"
    return "direct", ""


def select_structured_meta(meta_rows, norm_claim, weighted_tokens):
    """검증 API가 바로 쓸 수 있게 item 후보와 objL1 후보를 분리해서 고른다."""
    selected = {
        "selected_itm_id": "", "selected_itm_name": "", "selected_itm_unit": "", "selected_itm_score": "",
        "selected_obj_l1_axis_id": "", "selected_obj_l1_axis_name": "",
        "selected_obj_l1": "", "selected_obj_l1_name": "", "selected_obj_l1_score": "",
        "mapping_type": "", "unit_compatibility_reason": "",
        "selected_code_status": "meta 없음",
    }
    if not meta_rows:
        return selected

    items = []
    objs = []
    for r in meta_rows:
        meta_unit = r.get("unit_name") or r.get("UNIT_NM", "")
        score, hits = score_structured_meta(r, norm_claim, weighted_tokens)
        if (r.get("is_item") == "Y" or r.get("OBJ_ID") == "ITEM"):
            mapping_type, unit_reason = item_mapping_type(
                norm_claim,
                meta_unit,
                r.get("code_name") or r.get("ITM_NM", ""),
            )
            if not mapping_type:
                continue
            if mapping_type == "direct":
                score += 30
            items.append((score, r, mapping_type, unit_reason))
        else:
            objs.append((score, r))
    items.sort(key=lambda x: (-x[0], x[1].get("code_name", "")))
    objs.sort(key=lambda x: (-x[0], x[1].get("axis_id", ""), x[1].get("code_name", "")))

    if items:
        score, r, mapping_type, unit_reason = items[0]
        selected.update({
            "selected_itm_id": r.get("code_id") or r.get("ITM_ID", ""),
            "selected_itm_name": r.get("code_name") or r.get("ITM_NM", ""),
            "selected_itm_unit": r.get("unit_name") or r.get("UNIT_NM", ""),
            "selected_itm_score": score,
            "mapping_type": mapping_type,
            "unit_compatibility_reason": unit_reason,
        })
    if objs:
        # 점수가 모두 낮으면 총액/계/전국 같은 안전한 기본값을 우선한다.
        score, r = objs[0]
        selected.update({
            "selected_obj_l1_axis_id": r.get("axis_id") or r.get("OBJ_ID", ""),
            "selected_obj_l1_axis_name": r.get("axis_name") or r.get("OBJ_NM", ""),
            "selected_obj_l1": r.get("code_id") or r.get("ITM_ID", ""),
            "selected_obj_l1_name": r.get("code_name") or r.get("ITM_NM", ""),
            "selected_obj_l1_score": score,
        })
    selected["selected_code_status"] = "itm/obj 후보 선택" if selected["selected_itm_id"] or selected["selected_obj_l1"] else "코드 매칭 없음"
    return selected


def default_table_index():
    for p in DEFAULT_TABLE_INDEX_CANDIDATES:
        if p.exists():
            return p
    return DEFAULT_TABLE_INDEX_CANDIDATES[0]


def candidate_decision(
    rank,
    table_score,
    runner_up_score,
    structured_meta,
    table_meta_rows,
    norm_claim,
    table=None,
):
    """Classify a candidate without pretending that rank 1 means verified."""
    if rank != 1:
        return "ALTERNATE", "NOT_TOP_TABLE", "후순위 통계표 후보"
    if not table_meta_rows:
        return "TABLE_ONLY", "META_NOT_LOADED", "통계표 메타 조회 전 후보"
    if not structured_meta.get("selected_itm_id"):
        return "REJECT", "NO_COMPATIBLE_ITEM", "단위·지표 의미가 맞는 ITEM 없음"
    has_obj_axis = any(
        row.get("is_item") != "Y" and row.get("OBJ_ID") != "ITEM"
        for row in table_meta_rows
    )
    if has_obj_axis and not structured_meta.get("selected_obj_l1"):
        return "REVIEW", "OBJ_UNRESOLVED", "세부 대상 OBJ를 확정하지 못함"

    indicator = compact(norm_claim.get("indicator", ""))
    if "무역수지" in indicator:
        return "REVIEW", "FORMULA_REQUIRED", "수출액-수입액 계산식 매핑이 필요함"

    family = claim_item_family(norm_claim)
    selected_obj_name = compact(structured_meta.get("selected_obj_l1_name", ""))
    if family:
        aliases = {compact(family), *(compact(alias) for alias in ITEM_FAMILIES[family])}
        broad_code = selected_obj_name in aliases or selected_obj_name in {
            compact(f"{family}계"), compact(f"{family}전체")
        }
        if not broad_code:
            return "REVIEW", "CODESET_REQUIRED", f"{family} 집계용 OBJ 코드셋이 필요함"

    focused = compact(f"{norm_claim.get('indicator', '')} {norm_claim.get('industry_or_item', '')}")
    table_text = compact(
        f"{(table or {}).get('tbl_name', '')} {(table or {}).get('category_path', '')}"
    )
    if any(token in focused for token in ("로봇화", "로봇도입")) and "로봇산업실태조사" in table_text:
        return (
            "REVIEW",
            "POPULATION_DEFINITION_MISMATCH",
            "로봇 도입 기업과 로봇산업 사업체는 모집단 정의가 다름",
        )
    if "LCC" in focused or "저비용항공사" in focused:
        if not any(token in selected_obj_name for token in ("LCC", "저비용항공")):
            return "REVIEW", "CODESET_REQUIRED", "LCC 항공사 묶음 OBJ 코드셋이 필요함"
    if "대형항공사" in focused:
        if "대형항공사" not in selected_obj_name:
            return "REVIEW", "CODESET_REQUIRED", "대형 항공사 묶음 OBJ 코드셋이 필요함"

    margin = table_score - runner_up_score if runner_up_score is not None else table_score
    required_margin = max(10, int(table_score * 0.1))
    if runner_up_score is not None and margin < required_margin:
        return (
            "REVIEW",
            "AMBIGUOUS_TABLE",
            f"1·2위 점수 차이 부족: margin={margin}, required={required_margin}",
        )
    return "READY", "READY", "통계표·ITEM·OBJ·단위 의미 확정"


def rank_table_candidates(
    table_rows,
    claim,
    min_score=2,
    top_tables=10,
    semantic_runtime=None,
    semantic_top_k=50,
    rerank_top_k=20,
):
    """Return table candidates using lexical or hybrid retrieval.

    Dense retrieval expands recall, the existing lexical rules preserve domain
    anchors and hard exclusions, and the cross-encoder only reranks the fused
    pool.  Downstream metadata checks remain the final authority.
    """
    norm_claim = normalized_claim_row(claim)
    tokens = claim_tokens(norm_claim)
    candidate_pool = filtered_tables_for_claim(table_rows, norm_claim)
    lexical = []
    for table in candidate_pool:
        score, hits = score_table(table, tokens, norm_claim)
        if score >= min_score:
            lexical.append((score, hits, table))
    lexical.sort(key=lambda item: (-item[0], item[2]["tbl_name"]))

    if semantic_runtime is None:
        return [
            {
                "score": score,
                "hits": hits,
                "table": table,
                "retrieval_backend": "lexical",
                "lexical_score": score,
                "lexical_eligible": True,
                "semantic_score": None,
                "reranker_score": None,
                "fusion_score": None,
            }
            for score, hits, table in lexical[:top_tables]
        ]

    query = build_claim_query(norm_claim)
    semantic_hits = semantic_runtime.search(query, top_k=semantic_top_k)
    table_lookup = {table_key(table): table for table in table_rows}
    lexical_pool_size = max(semantic_top_k, rerank_top_k, top_tables)
    lexical_pool = lexical[:lexical_pool_size]
    lexical_by_key = {
        table_key(table): {"rank": rank, "score": score, "hits": hits}
        for rank, (score, hits, table) in enumerate(lexical_pool, 1)
    }
    semantic_by_key = {
        hit.key: {"rank": hit.rank, "score": hit.score}
        for hit in semantic_hits
        if hit.key in table_lookup
    }

    fused = []
    for key in set(lexical_by_key) | set(semantic_by_key):
        table = table_lookup.get(key)
        if table is None:
            continue
        lexical_evidence = lexical_by_key.get(key)
        if lexical_evidence:
            lexical_score = lexical_evidence["score"]
            hits = lexical_evidence["hits"]
        else:
            lexical_score, hits = score_table(table, tokens, norm_claim)
            # Preserve hard table exclusions even when dense retrieval finds it.
            if lexical_score <= -10**8:
                continue
        semantic_evidence = semantic_by_key.get(key)
        lexical_rank = lexical_evidence["rank"] if lexical_evidence else None
        semantic_rank = semantic_evidence["rank"] if semantic_evidence else None
        fusion = normalized_rrf_score(lexical_rank, semantic_rank)
        fused.append(
            {
                "table": table,
                "hits": hits,
                "lexical_score": lexical_score,
                "lexical_eligible": lexical_score >= min_score,
                "semantic_score": semantic_evidence["score"] if semantic_evidence else None,
                "fusion_score": fusion,
                "reranker_score": None,
            }
        )
    fused.sort(
        key=lambda item: (
            -int(item["lexical_eligible"]),
            -item["fusion_score"],
            -item["lexical_score"],
            item["table"]["tbl_name"],
        )
    )

    rerank_count = min(rerank_top_k, len(fused))
    if rerank_count:
        reranker_scores = semantic_runtime.rerank(
            query,
            [item["table"] for item in fused[:rerank_count]],
        )
        for item, reranker_score in zip(fused[:rerank_count], reranker_scores):
            item["reranker_score"] = reranker_score

    for item in fused:
        if item["reranker_score"] is None:
            final = item["fusion_score"]
            backend = "hybrid"
        else:
            final = 0.35 * item["reranker_score"] + 0.65 * item["fusion_score"]
            backend = "hybrid+reranker"
        item["score"] = int(round(final * 1000))
        item["retrieval_backend"] = backend
    fused.sort(
        key=lambda item: (
            -int(item["lexical_eligible"]),
            -item["score"],
            -item["fusion_score"],
            -item["lexical_score"],
            item["table"]["tbl_name"],
        )
    )
    return fused[:top_tables]


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_precomputed_rankings(path, table_rows):
    """Reuse first-pass table ranking after metadata has been downloaded."""
    table_lookup = {table_key(table): table for table in table_rows}
    rows, _ = read_csv(path)
    grouped = defaultdict(list)
    for row in rows:
        measurement_key = row.get("claim_measurement_id") or row.get("claim_id") or ""
        table = table_lookup.get((row.get("org_id", ""), row.get("tbl_id", "")))
        if not measurement_key or table is None:
            continue
        lexical_score = _float_or_none(row.get("lexical_score"))
        raw_eligible = str(row.get("lexical_eligible", "")).upper()
        lexical_eligible = (
            raw_eligible not in {"N", "FALSE", "0"}
            if raw_eligible
            else lexical_score is not None and lexical_score >= 2
        )
        grouped[measurement_key].append(
            {
                "score": int(float(row.get("candidate_score") or 0)),
                "hits": [hit for hit in row.get("candidate_hits", "").split(",") if hit],
                "table": table,
                "retrieval_backend": row.get("retrieval_backend") or "lexical",
                "lexical_score": lexical_score,
                "lexical_eligible": lexical_eligible,
                "semantic_score": _float_or_none(row.get("semantic_score")),
                "reranker_score": _float_or_none(row.get("reranker_score")),
                "fusion_score": _float_or_none(row.get("fusion_score")),
            }
        )
    for candidates in grouped.values():
        candidates.sort(
            key=lambda item: (-int(item["lexical_eligible"]), -item["score"])
        )
    return grouped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True)
    parser.add_argument("--table-index", default=str(default_table_index()))
    parser.add_argument("--meta-index", default=str(DEFAULT_META_INDEX))
    parser.add_argument("--out", default="")
    parser.add_argument("--top-tables", type=int, default=10)
    parser.add_argument("--top-meta", type=int, default=8)
    parser.add_argument("--min-score", type=int, default=2)
    parser.add_argument(
        "--retrieval-mode",
        choices=["auto", "lexical", "hybrid"],
        default="auto",
        help="auto는 임베딩 인덱스가 있으면 hybrid, 없으면 lexical 사용",
    )
    parser.add_argument("--semantic-index", default=str(DEFAULT_SEMANTIC_INDEX))
    parser.add_argument("--semantic-top-k", type=int, default=50)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--device", default=None, help="임베딩/리랭커 장치: cuda 또는 cpu")
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument(
        "--ranking-input",
        default="",
        help="첫 패스 후보 CSV를 재사용해 모델 재로딩 없이 메타만 결합",
    )
    parser.add_argument(
        "--allow-legacy",
        action="store_true",
        help="measurement 계약이 없는 구형 CSV 허용. 기본은 mapping_eligible=Y만 처리",
    )
    args = parser.parse_args()

    claims_path = Path(args.claims).expanduser()
    table_path = Path(args.table_index).expanduser()
    meta_path = Path(args.meta_index).expanduser()
    out_path = Path(args.out).expanduser() if args.out else claims_path.with_name(f"{claims_path.stem}_kosis_index_candidates.csv")

    input_claims, _ = read_csv(claims_path)
    claims = []
    excluded = Counter()
    for claim in input_claims:
        normalized = normalized_claim_row(claim)
        eligible = normalized.get("mapping_eligible") == "Y"
        legacy = "measurement_usage" not in claim and "mapping_eligible" not in claim
        if eligible or (args.allow_legacy and legacy):
            claims.append(claim)
        else:
            code = normalized.get("mapping_exclusion_code") or "INPUT_CONTRACT_MISSING"
            excluded[code] += 1
    table_rows = [norm_table_row(r) for r in read_csv(table_path)[0]]
    table_rows = [r for r in table_rows if r["org_id"] and r["tbl_id"]]
    for r in table_rows:
        r["_compact_tbl_name"] = compact(r["tbl_name"])
        r["_compact_category_path"] = compact(r["category_path"])
    meta_by_table = load_meta_index(meta_path)

    precomputed = None
    semantic_runtime = None
    retrieval_mode = args.retrieval_mode
    if args.ranking_input:
        precomputed = load_precomputed_rankings(Path(args.ranking_input), table_rows)
        retrieval_mode = "precomputed"
    elif retrieval_mode != "lexical":
        semantic_index = Path(args.semantic_index)
        try:
            semantic_runtime = SemanticSearchRuntime(
                semantic_index,
                reranker_model=args.reranker_model,
                use_reranker=not args.no_reranker,
                device=args.device,
            )
            expected_hash = semantic_runtime.index.manifest.get("source_sha256")
            if expected_hash and expected_hash != file_sha256(table_path):
                raise ValueError(
                    "임베딩 인덱스가 현재 --table-index와 다릅니다. 인덱스를 다시 생성하세요."
                )
            retrieval_mode = "hybrid"
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            if args.retrieval_mode == "hybrid":
                raise
            retrieval_mode = "lexical"
            print(f"semantic_retrieval=disabled ({exc})")

    out = []
    for claim in claims:
        norm_claim = normalized_claim_row(claim)
        # 입력 파일 자체가 이미 is_claim=True 100건으로 선별됐다고 가정한다.
        # is_claim/verifiable_kosis 값은 후보 매핑의 필터로 사용하지 않는다.
        tokens = claim_tokens(norm_claim)
        measurement_key = norm_claim.get("claim_measurement_id") or norm_claim.get("claim_id")
        if precomputed is not None:
            ranked = precomputed.get(measurement_key, [])[: args.top_tables]
        else:
            ranked = rank_table_candidates(
                table_rows,
                norm_claim,
                min_score=args.min_score,
                top_tables=args.top_tables,
                semantic_runtime=semantic_runtime,
                semantic_top_k=args.semantic_top_k,
                rerank_top_k=args.rerank_top_k,
            )
        for rank, candidate in enumerate(ranked, 1):
            table_score = candidate["score"]
            table_hits = candidate["hits"]
            table = candidate["table"]
            runner_up_score = ranked[1]["score"] if rank == 1 and len(ranked) > 1 else None
            table_meta_rows = meta_by_table.get((table["org_id"], table["tbl_id"]), [])
            structured_meta = select_structured_meta(table_meta_rows, norm_claim, tokens)
            candidate_status, candidate_status_code, candidate_status_reason = candidate_decision(
                rank,
                table_score,
                runner_up_score,
                structured_meta,
                table_meta_rows,
                norm_claim,
                table,
            )
            meta_candidates = top_meta_candidates(table_meta_rows, tokens, args.top_meta)
            if meta_candidates:
                meta_summary = " | ".join(
                    f"{m['axis_name']}:{m['code_name']}[{m['code_id']}]/item={m['is_item']}/score={m['score']}"
                    for m in meta_candidates
                )
            else:
                meta_summary = "meta_index 없음 또는 코드명 매칭 없음"
            out.append({
                "claim_id": norm_claim.get("claim_id", ""),
                "claim_measurement_id": norm_claim.get("claim_measurement_id", ""),
                "indicator": norm_claim.get("indicator", ""),
                "metric_domain": norm_claim.get("metric_domain", ""),
                "industry_or_item": norm_claim.get("industry_or_item", ""),
                "value": norm_claim.get("value", ""),
                "unit": norm_claim.get("unit", ""),
                "raw_unit": norm_claim.get("raw_unit", ""),
                "unit_dimension": norm_claim.get("unit_dimension", ""),
                "semantic_type": norm_claim.get("semantic_type", ""),
                "entity_type": norm_claim.get("entity_type", ""),
                "value_type": norm_claim.get("value_type", ""),
                "measurement_role": norm_claim.get("measurement_role", ""),
                "measurement_usage": norm_claim.get("measurement_usage", ""),
                "period": norm_claim.get("period", ""),
                "prd_se": norm_claim.get("prd_se", ""),
                "change_base": norm_claim.get("change_base", ""),
                "comparison_period": norm_claim.get("comparison_period", ""),
                "candidate_rank": rank,
                "candidate_score": table_score,
                "candidate_runner_up_score": runner_up_score if runner_up_score is not None else "",
                "candidate_status": candidate_status,
                "candidate_status_code": candidate_status_code,
                "candidate_status_reason": candidate_status_reason,
                "candidate_hits": ",".join(list(dict.fromkeys(table_hits))[:20]),
                "retrieval_backend": candidate.get("retrieval_backend", retrieval_mode),
                "lexical_score": candidate.get("lexical_score") if candidate.get("lexical_score") is not None else "",
                "lexical_eligible": "Y" if candidate.get("lexical_eligible", True) else "N",
                "semantic_score": candidate.get("semantic_score") if candidate.get("semantic_score") is not None else "",
                "reranker_score": candidate.get("reranker_score") if candidate.get("reranker_score") is not None else "",
                "fusion_score": candidate.get("fusion_score") if candidate.get("fusion_score") is not None else "",
                "org_id": table["org_id"],
                "tbl_id": table["tbl_id"],
                "tbl_name": table["tbl_name"],
                "stat_id": table["stat_id"],
                "category_path": table["category_path"],
                "meta_candidates": meta_summary,
                **structured_meta,
                "claim_text": norm_claim.get("claim_text", ""),
            })

    fields = [
        "claim_id", "claim_measurement_id", "indicator", "metric_domain", "industry_or_item",
        "value", "unit", "raw_unit", "unit_dimension", "semantic_type", "entity_type",
        "value_type", "measurement_role", "measurement_usage", "period", "prd_se", "change_base", "comparison_period",
        "candidate_rank", "candidate_score", "candidate_runner_up_score",
        "candidate_status", "candidate_status_code", "candidate_status_reason", "candidate_hits",
        "retrieval_backend", "lexical_score", "lexical_eligible", "semantic_score", "reranker_score", "fusion_score",
        "org_id", "tbl_id", "tbl_name", "stat_id", "category_path",
        "meta_candidates",
        "selected_itm_id", "selected_itm_name", "selected_itm_unit", "selected_itm_score",
        "selected_obj_l1_axis_id", "selected_obj_l1_axis_name",
        "selected_obj_l1", "selected_obj_l1_name", "selected_obj_l1_score", "selected_code_status",
        "mapping_type", "unit_compatibility_reason",
        "claim_text",
    ]
    write_csv(out_path, out, fields)
    print(
        f"input_rows={len(input_claims)} eligible_measurements={len(claims)} "
        f"excluded={len(input_claims) - len(claims)} table_index={len(table_rows)} "
        f"meta_tables={len(meta_by_table)} retrieval={retrieval_mode}"
    )
    if excluded:
        print("excluded_reasons", excluded.most_common())
    print(f"candidates={len(out)} -> {out_path}")
    print("top_indicator_counts", Counter(r["indicator"] for r in out).most_common(10))
    print("candidate_status_counts", Counter(r["candidate_status"] for r in out).most_common())


if __name__ == "__main__":
    main()
