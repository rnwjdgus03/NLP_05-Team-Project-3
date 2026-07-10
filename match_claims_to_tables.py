"""
A팀의 claim_candidates.csv 가 오면 실행 -> table_claim_mapping.csv 초안 생성.

전제:
- claim_candidates.csv 에 최소한 claim_id, claim_text 컬럼은 있다고 가정.
  metric/time/population/unit 컬럼이 있으면 그것도 활용(더 정확한 키워드 추출 가능).
  없어도 동작은 함 (claim_text에서 대충 키워드를 뽑아서 검색).
- kosis_table_summary.csv 가 이미 있어야 함 (kosis_table_search.py로 미리 크롤링해둔 것).

이 스크립트가 하는 일은 "완전 자동 검증"이 아니라 "1차 초안 생성"임.
사람이 candidate_kosis_table 후보들 중 진짜 맞는 표를 고르고,
calculation(계산식)과 verifiable(일치/불일치/판단불가)은 직접 확인해서 채워야 함.

사용법:
    python match_claims_to_tables.py claim_candidates.csv
    (인자 없이 실행하면 claim_candidates.csv를 찾음)
"""

import csv
import re
import sys

from kosis_api_test import summarize_meta
from kosis_table_search import save_table_summary  # noqa: F401 (참고용 import)


STOPWORDS = {
    "이", "가", "은", "는", "을", "를", "에", "의", "와", "과", "도", "로", "으로",
    "에서", "까지", "부터", "만", "년", "월", "일", "그", "이번", "지난", "올해",
    "것", "등", "위해", "대해", "따르면", "라고", "했다", "밝혔다",
}


def load_table_index(path="kosis_table_summary.csv"):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def search_candidate_tables(keywords, table_index, top_n=5):
    scored = []
    for row in table_index:
        text = f"{row.get('TBL_NM', '')} {row.get('path', '')}"
        score = sum(1 for kw in keywords if kw and kw in text)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:top_n]]


def extract_keywords(claim_row):
    """
    metric/population 같은 컬럼이 있으면 그걸 우선 쓰고,
    없으면 claim_text를 대충 토큰화해서 후보 키워드를 뽑음 (정교한 형태소분석 아님, 1차 필터용).
    """
    keywords = []
    for col in ("population", "metric", "keyword", "keywords"):
        val = claim_row.get(col)
        if val:
            keywords.extend(re.split(r"[,/\s]+", val.strip()))

    if not keywords:
        text = claim_row.get("claim_text", "")
        # 숫자, 조사 등을 대충 걸러내고 2글자 이상 한글 토큰만 후보로
        tokens = re.findall(r"[가-힣]{2,}", text)
        keywords = [t for t in tokens if t not in STOPWORDS]

    # 중복 제거, 너무 흔한 조사류 제거
    return [k for k in dict.fromkeys(keywords) if k and k not in STOPWORDS]


def suggest_api_params(candidate):
    """상위 후보 표 하나에 대해 메타정보(분류/항목)를 조회해서 참고용 힌트를 만듦."""
    org_id, tbl_id = candidate.get("ORG_ID"), candidate.get("TBL_ID")
    try:
        meta = summarize_meta(org_id, tbl_id)
        obj_names = ", ".join(sorted({name for (_id, name) in meta["classifications"].keys()}))
        item_count = len(meta["items"])
        return f"orgId={org_id}, tblId={tbl_id} | 분류: {obj_names} | 항목 {item_count}개 (직접 objL1/itmId 확인 필요)"
    except Exception as e:
        return f"orgId={org_id}, tblId={tbl_id} | 메타 조회 실패: {e}"


def main(claim_csv_path="claim_candidates.csv"):
    with open(claim_csv_path, encoding="utf-8-sig") as f:
        claims = list(csv.DictReader(f))

    table_index = load_table_index()
    print(f"{len(claims)}개 주장, {len(table_index)}개 통계표 인덱스 로드")

    out_rows = []
    for claim in claims:
        claim_id = claim.get("claim_id", "")
        claim_text = claim.get("claim_text", "")
        keywords = extract_keywords(claim)

        candidates = search_candidate_tables(keywords, table_index, top_n=5)
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
    with open("table_claim_mapping.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\n완료 -> table_claim_mapping.csv ({len(out_rows)}행)")
    print("주의: 이건 초안이에요. candidate_kosis_table 중 실제로 맞는 표 고르고,")
    print("calculation/verifiable은 직접 조회해서 채워야 함.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "claim_candidates.csv"
    main(path)
