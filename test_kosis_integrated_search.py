"""KOSIS 통합검색(searchNm) API 테스트 — lexical이 놓친 표를 잡는지 확인.

우리 lexical 검색이 recall@5 62.5%에서 놓친 품목별 표(반도체·바이오·자동차 등)를
KOSIS 자체 통합검색이 찾아주는지 감으로 확인하는 실험용 스크립트다.
골드의 gold_tbl_id를 정답으로 두고, 통합검색 상위 결과에 그 표가 있는지 본다.

엔드포인트: https://kosis.kr/openapi/statisticsSearch.do (method=getList)
필수: searchNm(검색어). 정렬 sort=RANK(정확도순, 기본).

사용법 (로컬, .env에 KOSIS_API_KEY 필요):
  python test_kosis_integrated_search.py                     # 미리 정한 케이스 실행
  python test_kosis_integrated_search.py --query "반도체 수출"  # 단일 검색어
  python test_kosis_integrated_search.py --gold gold_measurement_final.csv  # 골드 정답표 대조
"""
import argparse
import csv
import os

import requests
from dotenv import load_dotenv

from kosis_api_test import _parse_kosis_json

load_dotenv()
SEARCH_URL = "https://kosis.kr/openapi/statisticsSearch.do"

# lexical이 놓친 대표 케이스 (검색어, 참고: 예상 도메인)
DEFAULT_QUERIES = [
    "반도체 수출액",
    "자동차 수출",
    "바이오헬스 수출",
    "석유화학 수출",
    "화장품 수출",
    "항공사별 여객",
    "항공 정비사",
]


def search(query, api_key, count=10):
    params = {
        "method": "getList",
        "apiKey": api_key,
        "searchNm": query,
        "sort": "RANK",
        "startCount": 1,
        "resultCount": count,
        "format": "json",
    }
    r = requests.get(SEARCH_URL, params=params, timeout=15)
    r.raise_for_status()
    try:
        data = _parse_kosis_json(r.text)  # KOSIS 비표준 JSON 대응
    except Exception:
        print(f"  [파싱 실패] {r.text[:150]}")
        return []
    if isinstance(data, dict):
        # 에러 응답 {err:..., errMsg:...}
        if data.get("err"):
            return []
        data = [data]
    return data or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="단일 검색어")
    ap.add_argument("--gold", help="골드 CSV로 정답표 대조 (gold_tbl_id 사용)")
    ap.add_argument("--count", type=int, default=10)
    a = ap.parse_args()

    key = os.environ.get("KOSIS_API_KEY")
    if not key:
        raise SystemExit(".env에 KOSIS_API_KEY를 설정하세요")

    # 골드 대조 모드: 각 measurement의 indicator로 검색해 gold_tbl_id가 상위에 있는지
    if a.gold:
        with open(a.gold, encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f)
                    if (r.get("gold_tbl_id") or "").strip() and (r.get("gold_tbl_id") or "").strip() != "없음"]
        hit1 = hit10 = total = 0
        for r in rows:
            q = (r.get("measurement_indicator") or r.get("indicator") or r.get("claim_text") or "").strip()[:40]
            gt = (r.get("gold_tbl_id") or "").strip()
            if not q:
                continue
            total += 1
            res = search(q, key, a.count)
            tbls = [str(item.get("TBL_ID", "")) for item in res if isinstance(item, dict)]
            rank = tbls.index(gt) + 1 if gt in tbls else 0
            mark = f"@{rank}" if rank else "없음"
            if rank == 1:
                hit1 += 1
            if rank:
                hit10 += 1
            print(f"  [{r.get('claim_measurement_id','')}] '{q}' -> 정답 {gt} {mark}")
        print(f"\n통합검색 정답표 발견: recall@1={hit1}/{total}, recall@{a.count}={hit10}/{total}")
        return

    queries = [a.query] if a.query else DEFAULT_QUERIES
    for q in queries:
        print(f"\n=== '{q}' 통합검색 상위 {a.count} ===")
        res = search(q, key, a.count)
        if not res:
            print("  (결과 없음)")
            continue
        for i, item in enumerate(res, 1):
            if not isinstance(item, dict):
                continue
            print(f"  {i}. [{item.get('ORG_ID','')}/{item.get('TBL_ID','')}] "
                  f"{item.get('TBL_NM','')[:45]}  ({item.get('ORG_NM','')})")


if __name__ == "__main__":
    main()
