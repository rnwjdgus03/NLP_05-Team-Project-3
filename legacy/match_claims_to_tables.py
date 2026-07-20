"""
A팀의 claim_candidates.csv 가 오면 실행 -> table_claim_mapping.csv 초안 생성.
"""

import csv
import math
import re
import sys

from kosis_api_test import summarize_meta
from kosis_table_search import save_table_summary  # noqa: F401


STOPWORDS = {
    "이", "가", "은", "는", "을", "를", "에", "의", "와", "과", "도", "로", "으로",
    "에서", "까지", "부터", "만", "년", "월", "일", "그", "이번", "지난", "올해",
    "것", "등", "위해", "대해", "따르면", "라고", "했다", "밝혔다",
    "평균", "기간", "수준", "기록", "결과", "증가", "감소", "비율", "대비", "대상",
    "조사", "발표", "관련", "전체", "이상", "이하", "전년", "동월", "동기", "분석",
    "전망", "현황", "동향", "포함", "기준", "이후", "이전", "직전", "직후", "연속",
    "계속", "지난달", "지난해", "올랐다", "내렸다", "늘었다", "줄었다", "나타났다",
    "전망된다", "보인다", "가운데", "가장", "지속", "각각", "같은", "당시",
}


def load_table_index(path="kosis_table_summary.csv"):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def compute_keyword_df(all_keywords, table_index):
    df = {kw: 0 for kw in all_keywords}
    for row in table_index:
        text = f"{row.get('TBL_NM', '')} {row.get('path', '')}"
        for kw in all_keywords:
            if kw in text:
                df[kw] += 1
    return df


def search_candidate_tables(keywords, table_index, df, top_n=10):
    n_total = len(table_index)
    scored = []
    for row in table_index:
        text = f"{row.get('TBL_NM', '')} {row.get('path', '')}"
        score = 0.0
        for kw in keywords:
            if kw and kw in text:
                d = df.get(kw, 0)
                score += math.log(n_total / (1 + d))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:top_n]]


_JOSA_SUFFIXES = sorted(
    ["으로는", "에서는", "에게서", "으로도", "에서도", "까지는",
     "으로", "에서", "에게", "부터", "까지", "만은", "이나", "라도",
     "이", "가", "은", "는", "을", "를", "에", "의", "와", "과", "도", "로", "만"],
    key=len, reverse=True,
)


def _strip_josa(token):
    for suf in _JOSA_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 1:
            return token[: -len(suf)]
    return token


_VERB_SUFFIXES = sorted(
    ["했다", "한다", "된다", "하는", "되는", "였다", "한", "된", "할", "될"],
    key=len, reverse=True,
)


def _is_verb_form_of_stopword(token):
    for suf in _VERB_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 1:
            if token[: -len(suf)] in STOPWORDS:
                return True
    return False


def extract_keywords(claim_row):
    keywords = []
    for col in ("population", "metric", "keyword", "keywords"):
        val = claim_row.get(col)
        if val:
            keywords.extend(re.split(r"[,/\s]+", val.strip()))

    if not keywords:
        text = claim_row.get("claim_text", "")
        tokens = re.findall(r"[가-힣]{2,}", text)
        tokens = [_strip_josa(t) for t in tokens]
        keywords = [t for t in tokens if t not in STOPWORDS and not _is_verb_form_of_stopword(t)]

    return [k for k in dict.fromkeys(keywords) if k and k not in STOPWORDS and not _is_verb_form_of_stopword(k)]


def suggest_api_params(candidate):
    org_id, tbl_id = candidate.get("ORG_ID"), candidate.get("TBL_ID")
    try:
        meta = summarize_meta(org_id, tbl_id)
        obj_names = ", ".join(sorted({name for (_id, name) in meta["classifications"].keys()}))
        item_count = len(meta["items"])
        return f"orgId={org_id}, tblId={tbl_id} | 분류: {obj_names} | 항목 {item_count}개 (직접 objL1/itmId 확인 필요)"
    except Exception as e:
        return f"orgId={org_id}, tblId={tbl_id} | 메타 조회 실패: {type(e).__name__}"


def main(claim_csv_path="claim_candidates.csv", out_path="table_claim_mapping.csv"):
    with open(claim_csv_path, encoding="utf-8-sig") as f:
        claims = list(csv.DictReader(f))

    table_index = load_table_index()
    print(f"{len(claims)}개 주장, {len(table_index)}개 통계표 인덱스 로드")

    claim_keywords_list = [extract_keywords(c) for c in claims]
    all_keywords = set()
    for kws in claim_keywords_list:
        all_keywords.update(kws)
    print(f"고유 키워드 {len(all_keywords)}개 -> 문서빈도(df) 계산 중...")
    df = compute_keyword_df(all_keywords, table_index)

    out_rows = []
    for claim, keywords in zip(claims, claim_keywords_list):
        claim_id = claim.get("claim_id", "")
        claim_text = claim.get("claim_text", "")

        candidates = search_candidate_tables(keywords, table_index, df, top_n=10)
        print(f"\n[{claim_id}] {claim_text}")
        print("  키워드:", keywords)

        if not candidates:
            out_rows.append({
                "claim_id": claim_id, "claim_text": claim_text,
                "metric": claim.get("metric", ""), "time": claim.get("time", ""),
                "population": claim.get("population", ""), "unit": claim.get("unit", ""),
                "candidate_kosis_table": "후보 없음 (해당 카테고리 추가 크롤링 필요)",
                "api_params": "", "calculation": "", "verifiable": "판단불가(후보표 없음)",
            })
            print("  -> 후보 없음. 다른 카테고리 크롤링 필요할 수 있음.")
            continue

        cand_str = "; ".join(f"{c['TBL_NM']}(tblId={c['TBL_ID']})" for c in candidates)
        top = candidates[0]
        api_hint = suggest_api_params(top)
        print("  후보:", cand_str)
        print("  1순위 힌트:", api_hint)

        out_rows.append({
            "claim_id": claim_id, "claim_text": claim_text,
            "metric": claim.get("metric", ""), "time": claim.get("time", ""),
            "population": claim.get("population", ""), "unit": claim.get("unit", ""),
            "candidate_kosis_table": cand_str,
            "api_params": api_hint,
            "calculation": "직접 확인 필요 (원자료가 비율/증감 그대로 나오는지 확인)",
            "verifiable": "검토 필요",
        })

    fieldnames = ["claim_id", "claim_text", "metric", "time", "population", "unit",
                  "candidate_kosis_table", "api_params", "calculation", "verifiable"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\n완료 -> {out_path} ({len(out_rows)}행)")
    print("주의: 이건 초안이에요. candidate_kosis_table 중 실제로 맞는 표 고르고,")
    print("calculation/verifiable은 직접 조회해서 채워야 함.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "claim_candidates.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "table_claim_mapping.csv"
    main(path, out)
