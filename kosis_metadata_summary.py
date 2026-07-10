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


def main():
    out_rows = []
    for org_id, tbl_id, tbl_nm in CANDIDATE_TABLES:
        print(f"조회 중: {tbl_nm} ({tbl_id})")
        meta = summarize_meta(org_id, tbl_id)
        classifications = meta["classifications"]
        items = meta["items"]

        # 분류축 이름들 (예: "경지규모 영농형태 시도별")
        obj_names = "; ".join(sorted({name for (_id, name) in classifications.keys()}))
        # 항목 예시 (최대 5개만 보여주기)
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

    with open("kosis_metadata_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    print("\n완료 -> kosis_metadata_summary.csv")
    for r in out_rows:
        print(r["TBL_NM"], "|", r["분류축"], "|", r["항목_전체개수"], "개 항목 |", r["단위"])


if __name__ == "__main__":
    main()
