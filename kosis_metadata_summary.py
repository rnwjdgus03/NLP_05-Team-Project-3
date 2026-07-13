"""
후보 통계표들의 분류축/항목/단위를 실제로 조회해서 kosis_metadata_summary.csv 로 정리.

방법: "통계표설명"(메타정보) API 사용 - method=getMeta&type=ITM
  https://kosis.kr/openapi/statisticsData.do?method=getMeta&type=ITM&apiKey=...&orgId=..&tblId=..&format=json

이 API는 orgId/tblId만 있으면 되고, objL1/itmId를 몰라도 그 표에 있는
분류 코드 전체 + 항목 코드 전체를 한번에 알려줌 (실제 수치 데이터는 안 가져옴, 그래서 빠름).

응답 안에서:
  - OBJ_ID == "ITEM" 인 행들 -> 그 표의 "항목"(itmId로 쓸 수 있는 값들)
  - 그 외 OBJ_ID(A, B ...) 인 행들 -> 그 표의 "분류"(objL1, objL2 ...로 쓸 수 있는 값들),
    OBJ_NM이 분류축 이름 (예: "경지규모 영농형태 시도별")

단위(UNIT_NM)는 이 메타 API엔 안 나와서, 실제 데이터 1건만 조회해서 확인함
(get_stat_data에 objL1/itmId 아무 코드 하나씩만 넣어서 1행만 받아옴).
"""

import csv
import sys

from kosis_api_test import summarize_meta, get_stat_data

# 지금까지 xlsx에 "미확인"으로 남겨둔 후보 표들
CANDIDATE_TABLES = [
    ("101", "DT_1EA1019", "경영주 연령별 농가"),
    ("101", "DT_1EA1013", "전겸업별 농가"),
    ("101", "DT_1EA1015", "경지규모별 농가"),
    ("101", "DT_1EA1017", "밭경영규모별 농가"),
    ("101", "DT_1EA1020", "가구원수별 농가"),
    ("101", "DT_1EA1018", "영농형태별 농가"),
    ("101", "DT_1EA1038", "과수 재배 작물별 농가"),
    # 2026.07.13 추가: 뉴스 주장 후보 5개 분야(출생아/물가/고용률/수출/GDP) 대응 표
    ("101", "INH_1B8000F_01", "출생아수, 합계출산율, 자연증가 등"),
    ("101", "DT_1J22003", "소비자물가지수(2020=100)"),
    ("101", "DT_1J22042", "월별 소비자물가 등락률"),
    ("101", "DT_1ES3D11J", "전국 연령별/교육분류(영역)별 취업자 및 고용률"),
    ("360", "DT_1R11006_FRM101", "국가별 수출액, 수입액"),
    ("301", "DT_200Y113", "국내총생산과 지출(명목, 연간)"),
]

# 팀원과 나눠서 "카테고리별 대표표 1개씩" 조회할 때는 아래 리스트에
# (orgId, tblId, 표이름) 을 본인이 담당한 카테고리 것만 채워서 쓰면 됨.
# 담당: 인구(A)/사회일반(B)/범죄안전(C)/노동(D)/소득소비자산(E)/보건(F)/복지(G)/
#       교육훈련(H1)/문화여가(H2)/주거(I1)/국토이용(I2)/경제일반경기(J1)/기업경영(J2)/농림(K1)/수산(K2)
MY_CATEGORY_TABLES = [
    ("101", "INH_1B8000F_01", "[인구] 출생아수, 합계출산율, 자연증가 등"),
    ("101", "DT_1SSSP020R", "[사회일반] 주관적 만족도(13세 이상 인구)"),
    ("110", "DT_A11001_2009_1604", "[범죄안전] 범죄발생 및 검거"),
    ("101", "DT_1ES3D11J", "[노동] 전국 연령별/교육분류별 취업자 및 고용률"),
    ("101", "DT_1L9U101", "[소득소비자산] 가구당 월평균 가계수지(전국,1인이상)"),
    ("101", "INH_1B8000F_02", "[보건] 사망자수, 조사망률, 기대수명"),
    ("110", "DT_110001_A045", "[복지] 국민기초생활보장수급자 및 등록장애인"),
    ("101", "DT_1PE003", "[교육훈련] 학교급별 사교육비 총액"),
    ("113", "DT_113_STBL_1028353", "[문화여가] 여가활동 유형(문화예술관람활동)"),
    ("408", "DT_304N_04_00001", "[주거] 유형별 주택매매가격지수(2011.6=100)"),
    ("110", "DT_110001_A006", "[국토이용] 지목별 토지현황"),
    ("340", "DT_D10100A", "[경제일반경기] 총괄표 실적 SBHI"),
    ("301", "DT_501Y005", "[기업경영] 성장성 지표"),
    # 농림(K1)은 CANDIDATE_TABLES의 "경영주 연령별 농가"로 이미 커버됨 (중복 방지로 생략)
    ("101", "DT_1EW0001", "[수산] 어업생산동향 총괄표"),
]


def get_sample_unit(org_id, tbl_id, classifications, items):
    """분류/항목 코드 중 하나씩 골라 실제 데이터 1건만 조회해서 단위(UNIT_NM)를 확인."""
    if not classifications or not items:
        return "확인 불가 (분류/항목 코드 없음)"
    any_obj_id = next(iter(classifications))[0]  # 예: "A"
    any_code = classifications[next(iter(classifications))][0][0]  # 그 분류의 첫 코드
    any_item_id = items[0][0]
    try:
        rows = get_stat_data(
            org_id, tbl_id,
            obj_l1=any_code, itm_id=any_item_id,
            prd_se="Y", new_est_prd_cnt=1,
        )
        if rows:
            return rows[0].get("UNIT_NM", "확인 불가")
    except Exception as e:
        return f"조회 실패: {e}"
    return "확인 불가"


FIELDS = ["TBL_NM", "ORG_ID", "TBL_ID", "분류축", "항목_예시(최대5개)", "항목_전체개수", "단위"]


def load_existing(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def main(out_path):
    existing = load_existing(out_path)
    seen_ids = {r["TBL_ID"] for r in existing}
    print(f"기존 {len(existing)}개 로드 ({out_path})")

    todo = []
    for t in CANDIDATE_TABLES + MY_CATEGORY_TABLES:
        if t[1] in seen_ids:
            continue
        seen_ids.add(t[1])  # 이번 실행 내에서도 중복 방지
        todo.append(t)
    if not todo:
        print("새로 조회할 표가 없음 (CANDIDATE_TABLES / MY_CATEGORY_TABLES 확인)")
        return

    out_rows = list(existing)
    for org_id, tbl_id, tbl_nm in todo:
        print(f"조회 중: {tbl_nm} ({tbl_id})")
        meta = summarize_meta(org_id, tbl_id)
        classifications = meta["classifications"]
        items = meta["items"]

        obj_names = "; ".join(sorted({name for (_id, name) in classifications.keys()}))
        item_sample = ", ".join(f"{nm}({cd})" for cd, nm in items[:5])
        item_count = len(items)

        unit = get_sample_unit(org_id, tbl_id, classifications, items)

        out_rows.append({
            "TBL_NM": tbl_nm,
            "ORG_ID": org_id,
            "TBL_ID": tbl_id,
            "분류축": obj_names,
            "항목_예시(최대5개)": item_sample,
            "항목_전체개수": item_count,
            "단위": unit,
        })

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\n완료 -> {out_path} (총 {len(out_rows)}개)")
    for r in out_rows[-len(todo):]:
        print(r["TBL_NM"], "|", r["분류축"], "|", r["항목_전체개수"], "개 항목 |", r["단위"])


if __name__ == "__main__":
    args = sys.argv[1:]
    out_path = "kosis_metadata_summary.csv"
    if args and args[0] == "--out":
        out_path = args[1]
    main(out_path)
