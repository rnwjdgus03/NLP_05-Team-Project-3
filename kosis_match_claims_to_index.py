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


PROJECT_DIR = Path("/Users/gu/myproject/NLP_05-Team-Project-3")
DEFAULT_TABLE_INDEX_CANDIDATES = [
    PROJECT_DIR / "data/claims/kosis_table_index.csv",
]
DEFAULT_META_INDEX = PROJECT_DIR / "data/claims/kosis_meta_index.csv"

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
    return {
        "claim_id": get_first(row, "claim_id", "claimId", "id"),
        "claim_measurement_id": get_first(row, "claim_measurement_id", "measurement_id"),
        "indicator": get_first(row, "indicator", "지표"),
        "metric_domain": get_first(row, "metric_domain", "도메인", "검색 구분 레이블"),
        "industry_or_item": get_first(row, "industry_or_item", "품목", "산업", "대상"),
        "keywords": get_first(row, "keywords", "키워드"),
        "region": get_first(row, "region", "지역"),
        "age_group": get_first(row, "age_group", "연령"),
        "gender": get_first(row, "gender", "성별"),
        "value": get_first(row, "value", "값", "수치"),
        "unit": get_first(row, "unit", "단위"),
        "period": get_first(row, "period", "작성일", "date"),
        "prd_se": get_first(row, "prd_se", "주기"),
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


def score_table(row, tokens):
    score_name, hits_name = score_text(tokens, row["_compact_tbl_name"])
    score_path, hits_path = score_text(tokens, row["_compact_category_path"])
    score = score_name * 2 + score_path
    return score, list(dict.fromkeys(hits_name + hits_path))


def domain_filter_terms(claim):
    claim = normalized_claim_row(claim)
    text = f"{claim.get('metric_domain','')} {claim.get('indicator','')} {claim.get('keywords','')}"
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
    text = " ".join(str(norm_claim.get(k, "")) for k in ["indicator", "metric_domain", "industry_or_item", "claim_text"])
    ctext = compact(text)
    cname = compact(row.get("code_name") or row.get("ITM_NM", ""))
    caxis = compact(row.get("axis_name") or row.get("OBJ_NM", ""))
    score, hits = score_text(weighted_tokens, compact(f"{row.get('axis_name','')} {row.get('code_name','')} {row.get('unit_name','')}"))

    # 항목(item) 쪽: 수출액/수입액/증감률 같은 값 종류를 강하게 맞춘다.
    if (row.get("is_item") == "Y" or row.get("OBJ_ID") == "ITEM"):
        if "수출" in ctext and "수출" in cname:
            score += 80
        if "수입" in ctext and "수입" in cname:
            score += 80
        if any(k in ctext for k in ["증가율", "상승률", "증감률", "비율", "%", "퍼센트"]):
            if any(k in cname for k in ["증감률", "증가율", "등락률", "비율"]):
                score += 100
            if any(k in cname for k in ["수출액", "수입액", "금액"]):
                score -= 80
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
    if cname in {"계", "전체", "총액", "전국"}:
        score += 5
    return score, hits


def unit_kind(unit):
    """뉴스 단위와 KOSIS 단위의 물리적 성격을 비교한다."""
    u = compact(unit)
    if not u or u == "-":
        return "unknown"
    if "%" in u or "퍼센트" in u or "비율" in u:
        return "rate"
    if any(x in u for x in ("원", "달러", "엔", "유로")):
        return "money"
    if any(x in u for x in ("명", "인", "가구", "세대", "사람")):
        return "people"
    if any(x in u for x in ("시간", "일", "개월", "년", "세")):
        return "time"
    if any(x in u for x in ("개", "대", "건", "톤")):
        return "count"
    return "other"


def unit_candidate_compatible(claim_unit, meta_unit):
    """서로 다른 종류의 항목을 매핑 후보에서 제거한다."""
    ck, mk = unit_kind(claim_unit), unit_kind(meta_unit)
    if ck == "unknown" or mk == "unknown":
        return True
    return ck == mk


def select_structured_meta(meta_rows, norm_claim, weighted_tokens):
    """검증 API가 바로 쓸 수 있게 item 후보와 objL1 후보를 분리해서 고른다."""
    selected = {
        "selected_itm_id": "", "selected_itm_name": "", "selected_itm_unit": "", "selected_itm_score": "",
        "selected_obj_l1_axis_id": "", "selected_obj_l1_axis_name": "",
        "selected_obj_l1": "", "selected_obj_l1_name": "", "selected_obj_l1_score": "",
        "selected_code_status": "meta 없음",
    }
    if not meta_rows:
        return selected

    items = []
    objs = []
    for r in meta_rows:
        # 단위가 명백히 다른 ITEM은 후보에서 제외한다.
        # 예: 뉴스 % claim에 KOSIS 원/천달러 항목을 연결하지 않음.
        meta_unit = r.get("unit_name") or r.get("UNIT_NM", "")
        if (r.get("is_item") == "Y" or r.get("OBJ_ID") == "ITEM") and not unit_candidate_compatible(norm_claim.get("unit", ""), meta_unit):
            continue
        score, hits = score_structured_meta(r, norm_claim, weighted_tokens)
        if (r.get("is_item") == "Y" or r.get("OBJ_ID") == "ITEM"):
            items.append((score, r))
        else:
            objs.append((score, r))
    items.sort(key=lambda x: (-x[0], x[1].get("code_name", "")))
    objs.sort(key=lambda x: (-x[0], x[1].get("axis_id", ""), x[1].get("code_name", "")))

    if items:
        score, r = items[0]
        selected.update({
            "selected_itm_id": r.get("code_id") or r.get("ITM_ID", ""),
            "selected_itm_name": r.get("code_name") or r.get("ITM_NM", ""),
            "selected_itm_unit": r.get("unit_name") or r.get("UNIT_NM", ""),
            "selected_itm_score": score,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True)
    parser.add_argument("--table-index", default=str(default_table_index()))
    parser.add_argument("--meta-index", default=str(DEFAULT_META_INDEX))
    parser.add_argument("--out", default="")
    parser.add_argument("--top-tables", type=int, default=10)
    parser.add_argument("--top-meta", type=int, default=8)
    parser.add_argument("--min-score", type=int, default=2)
    args = parser.parse_args()

    claims_path = Path(args.claims).expanduser()
    table_path = Path(args.table_index).expanduser()
    meta_path = Path(args.meta_index).expanduser()
    out_path = Path(args.out).expanduser() if args.out else claims_path.with_name(f"{claims_path.stem}_kosis_index_candidates.csv")

    claims, _ = read_csv(claims_path)
    table_rows = [norm_table_row(r) for r in read_csv(table_path)[0]]
    table_rows = [r for r in table_rows if r["org_id"] and r["tbl_id"]]
    for r in table_rows:
        r["_compact_tbl_name"] = compact(r["tbl_name"])
        r["_compact_category_path"] = compact(r["category_path"])
    meta_by_table = load_meta_index(meta_path)

    out = []
    for claim in claims:
        norm_claim = normalized_claim_row(claim)
        # 입력 파일 자체가 이미 is_claim=True 100건으로 선별됐다고 가정한다.
        # is_claim/verifiable_kosis 값은 후보 매핑의 필터로 사용하지 않는다.
        tokens = claim_tokens(norm_claim)
        scored = []
        candidate_pool = filtered_tables_for_claim(table_rows, norm_claim)
        for table in candidate_pool:
            score, hits = score_table(table, tokens)
            if score >= args.min_score:
                scored.append((score, hits, table))
        scored.sort(key=lambda x: (-x[0], x[2]["tbl_name"]))
        for rank, (table_score, table_hits, table) in enumerate(scored[:args.top_tables], 1):
            table_meta_rows = meta_by_table.get((table["org_id"], table["tbl_id"]), [])
            structured_meta = select_structured_meta(table_meta_rows, norm_claim, tokens)
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
                "period": norm_claim.get("period", ""),
                "prd_se": norm_claim.get("prd_se", ""),
                "candidate_rank": rank,
                "candidate_score": table_score,
                "candidate_hits": ",".join(list(dict.fromkeys(table_hits))[:20]),
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
        "value", "unit", "period", "prd_se",
        "candidate_rank", "candidate_score", "candidate_hits",
        "org_id", "tbl_id", "tbl_name", "stat_id", "category_path",
        "meta_candidates",
        "selected_itm_id", "selected_itm_name", "selected_itm_unit", "selected_itm_score",
        "selected_obj_l1_axis_id", "selected_obj_l1_axis_name",
        "selected_obj_l1", "selected_obj_l1_name", "selected_obj_l1_score", "selected_code_status",
        "claim_text",
    ]
    write_csv(out_path, out, fields)
    print(f"claims={len(claims)} table_index={len(table_rows)} meta_tables={len(meta_by_table)}")
    print(f"candidates={len(out)} -> {out_path}")
    print("top_indicator_counts", Counter(r["indicator"] for r in out).most_common(10))


if __name__ == "__main__":
    main()
