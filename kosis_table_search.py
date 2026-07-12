"""
통계목록 API로 후보 통계표 검색하기

중요한 전제: 통계목록 API(statisticsList.do)는 "키워드로 검색"하는 파라미터가 없다.
받는 파라미터는 vwCd(주제별/기관별 구분) 와 parentListId(상위 목록) 뿐이라,
카테고리 트리를 계속 한 단계씩 내려가야만 통계표를 찾을 수 있음.

그래서 "검색"은 2단계로 나눠서 함:
  1) 트리를 미리 재귀적으로 다 돌면서(=크롤링) 로컬 인덱스(csv)로 만들어둔다
     -> 이게 B팀 산출물 kosis_table_summary.csv
  2) A팀이 뽑아온 주장 키워드로, 그 로컬 인덱스에서 문자열 매칭 검색을 한다
     (KOSIS 서버에 매번 검색 요청을 보내는 게 아니라 우리가 만든 캐시에서 찾는 것)

주의: 전체 13개 vwCd(주제별 기준)를 다 돌면 통계표가 수천~수만 개라 오래 걸리고
분당 호출건수 제한에도 걸릴 수 있음. 처음엔 관련 있어 보이는 상위 카테고리 1~2개만
(예: 농가 얘기면 '농림'=K1) 크롤링해서 쓰는 걸 추천.

최상위 카테고리 코드 (vwCd=MT_ZTITLE 기준, 한 번 조회해서 확인한 값):
A=인구 B=사회일반 C=범죄ㆍ안전 D=노동 E=소득ㆍ소비ㆍ자산 F=보건 G=복지
H1=교육ㆍ훈련 H2=문화ㆍ여가 I1=주거 I2=국토이용 J1=경제일반ㆍ경기 J2=기업경영
K1=농림 K2=수산 L=광업ㆍ제조업 M1=건설 M2=교통ㆍ물류 N1=정보통신 N2=과학ㆍ기술
O=도소매ㆍ서비스 P1=임금 P2=물가 Q=국민계정 R=정부ㆍ재정 S1=금융 S2=무역ㆍ국제수지
T=환경 U=에너지 V=지역통계
"""

import csv
import sys
import time

from kosis_api_test import API_KEY, LIST_URL, _parse_kosis_json
import requests


def get_list(vw_cd="MT_ZTITLE", parent_id=""):
    params = {
        "method": "getList",
        "apiKey": API_KEY,
        "vwCd": vw_cd,
        "parentListId": parent_id,  # devGuide엔 parentId라고 나오지만 실제로는 이 이름이어야 동작
        "format": "json",
    }
    res = requests.get(LIST_URL, params=params, timeout=10)
    res.raise_for_status()
    return _parse_kosis_json(res.text)


def crawl_all_tables(start_parent="", vw_cd="MT_ZTITLE", delay=0.3, max_calls=None):
    """
    start_parent 에서부터 재귀적으로 내려가며 leaf(=TBL_ID가 있는 실제 통계표)를 전부 모은다.
    start_parent="" 로 주면 전체 트리(매우 큼), "K1" 처럼 주면 그 카테고리 하위만.
    """
    results = []
    calls = 0
    seen = set()  # 같은 parent_id를 두 번 타는 걸 방지 (무한 재귀/중복 호출 방지)

    def _walk(parent_id, path):
        nonlocal calls
        if max_calls is not None and calls >= max_calls:
            return
        if parent_id in seen:
            return
        seen.add(parent_id)
        calls += 1
        items = get_list(vw_cd=vw_cd, parent_id=parent_id)
        time.sleep(delay)  # 분당 호출건수 제한 대비
        location = " > ".join(path) if path else "(최상위)"
        print(f"\r  [진행] API 호출 {calls}회 | 통계표 {len(results)}개 수집 | 현재: {location}          ",
              end="", flush=True)
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("TBL_ID"):
                results.append({
                    "ORG_ID": item.get("ORG_ID"),
                    "TBL_ID": item.get("TBL_ID"),
                    "TBL_NM": item.get("TBL_NM"),
                    "STAT_ID": item.get("STAT_ID"),
                    "path": " > ".join(path),
                })
            else:
                list_id = item.get("LIST_ID")
                if not list_id:
                    # LIST_ID도 TBL_ID도 없는 이상한 항목이면 더 못 내려가니 건너뜀
                    continue
                name = item.get("LIST_NM") or list_id
                _walk(list_id, path + [name])

    _walk(start_parent, [])
    print()  # 진행 표시 줄 마무리
    return results


def save_table_summary(rows, path="kosis_table_summary.csv"):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["ORG_ID", "TBL_ID", "TBL_NM", "STAT_ID", "path"])
        writer.writeheader()
        writer.writerows(rows)


def search_candidate_tables(keywords, table_index, top_n=10):
    """
    keywords: claim에서 뽑은 단어들 (예: ["농가", "연령", "고령"])
    table_index: crawl_all_tables() 결과 (또는 kosis_table_summary.csv 읽은 것)
    TBL_NM + 카테고리 경로(path)에 키워드가 몇 개 매칭되는지로 점수 매겨 상위 N개 반환
    """
    scored = []
    for row in table_index:
        text = f"{row.get('TBL_NM', '')} {row.get('path', '')}"
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:top_n]]


if __name__ == "__main__":
    # 예시: A팀이 "농가 고령화" 관련 주장을 뽑아왔다고 가정
    # 1) 관련 있어 보이는 상위 카테고리(농림=K1)만 먼저 크롤링해서 캐시 생성
    print("K1(농림) 하위 통계표 크롤링 중...")
    table_index = crawl_all_tables(start_parent="K1_9")
    save_table_summary(table_index)
    print(f"{len(table_index)}개 통계표 저장 완료 -> kosis_table_summary.csv")

    # 2) 로컬 인덱스에서 키워드로 후보 검색 (KOSIS에 다시 요청 안 보냄)
    candidates = search_candidate_tables(["농가", "연령"], table_index)
    print("\n후보 통계표:")
    for c in candidates:
        print(c["TBL_NM"], "|", c["path"], "| orgId=", c["ORG_ID"], "tblId=", c["TBL_ID"])
