"""
manual_selection_summary.csv (171건) + oversized_candidates_filtered.csv (21건)를 검토해서
Claude가 내린 obj_l1/itm_id 수동 선택 결과를 bteam_kosis_review_manual_todo.csv에 반영하는 스크립트.

사용법:
    python apply_obj_itm_manual_selections.py
"""

import csv
import sys

csv.field_size_limit(sys.maxsize)

PATH = "outputs/bteam_review/bteam_kosis_review_manual_todo.csv"

# claim_id -> {필드: 값} 형태로 반영. prd_se는 비어있을 때만 채움(이미 있으면 안 건드림).
UPDATES = {
    # --- DT_1JH20202: 전산업생산지수 (obj_l1 축) ---
    "C00230": {"obj_l1": "1", "prd_se": "M"},
    "C06498": {"obj_l1": "1", "prd_se": "M"},
    "C06500": {"obj_l1": "1", "prd_se": "M"},
    "C06568": {"obj_l1": "1", "prd_se": "M"},
    "C06569": {"obj_l1": "1", "prd_se": "M"},
    "C09015": {"obj_l1": "1", "prd_se": "M"},

    # --- DT_1F70011: 설비투자지수 (itm_id 축, 전월비이므로 계절조정) ---
    "C00231": {"itm_id": "T5", "prd_se": "M"},
    "C06505": {"itm_id": "T5", "prd_se": "M"},
    "C06506": {"itm_id": "T5", "prd_se": "M"},
    "C06571": {"itm_id": "T5", "prd_se": "M"},
    "C06572": {"itm_id": "T5", "prd_se": "M"},
    "C06573": {"itm_id": "T5", "prd_se": "M"},
    "C09022": {"itm_id": "T5", "prd_se": "M"},
    "C09023": {"itm_id": "T5", "prd_se": "M"},

    # --- DT_1G18004: 건설기성 (obj_l1 축: 0=기성총액) ---
    "C00232": {"obj_l1": "0", "prd_se": "M"},
    "C03635": {"obj_l1": "0", "prd_se": "Q"},
    "C03636": {"obj_l1": "0", "prd_se": "Q"},
    "C03637": {"obj_l1": "0", "prd_se": "Q"},
    "C06507": {"obj_l1": "0", "prd_se": "M"},
    "C06574": {"obj_l1": "0", "prd_se": "M"},
    # C06508: 건축(-4.1%)/토목(-5.2%) 각각 언급 - 단일 obj_l1 코드로 불가, 수동 확인 필요
    "C06508": {"reviewer_note_append": "obj_l1 수동선택 보류: 건축(1)/토목(2) 각각 별도 수치 언급, 단일 코드로 대표 불가"},

    # --- DT_511Y002: 소비자심리지수(CSI) ---
    "C00604": {"obj_l1": "13102134688CSI_CD.FME", "prd_se": "M"},
    "C01992": {"obj_l1": "13102134688CSI_CD.FME", "prd_se": "M"},
    "C05186": {"obj_l1": "13102134688CSI_CD.FME", "prd_se": "M"},
    "C05190": {"obj_l1": "13102134688CSI_CD.FMBA", "prd_se": "M"},  # 생활형편전망CSI
    "C08417": {"obj_l1": "13102134688CSI_CD.FME", "prd_se": "M"},
    "C08418": {"obj_l1": "13102134688CSI_CD.FME", "prd_se": "M"},

    # --- DT_200Y108: 분기 실질GDP (ACC_ITEM 축) ---
    "C02160": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02163": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02164": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02166": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02174": {"obj_l1": "13102136297ACC_ITEM.1020111", "prd_se": "Q"},  # 건설투자
    "C02175": {"obj_l1": "13102136297ACC_ITEM.1010110", "prd_se": "Q"},  # 민간소비
    "C02177": {"obj_l1": "13102136297ACC_ITEM.1020111", "prd_se": "Q"},  # 건설투자
    "C02272": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02274": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02275": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C02283": {"obj_l1": "13102136297ACC_ITEM.1010110", "prd_se": "Q"},  # 민간소비 전망 대비 실제
    "C04021": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},
    "C05652": {"obj_l1": "13102136297ACC_ITEM.10601", "prd_se": "Q"},

    # --- DT_200Y110: 연간 실질GDP ---
    "C02162": {"obj_l1": "13102136261ACC_ITEM.10601", "prd_se": "Y"},
    "C02276": {"obj_l1": "13102136261ACC_ITEM.10601", "prd_se": "Y"},
    "C02295": {"obj_l1": "13102136261ACC_ITEM.10601", "prd_se": "Y"},
    "C03014": {"obj_l1": "13102136261ACC_ITEM.10601", "prd_se": "Y"},
    "C04020": {"obj_l1": "13102136261ACC_ITEM.10601", "prd_se": "Y"},
    "C04071": {"obj_l1": "13102136261ACC_ITEM.10601", "prd_se": "Y",
               "reviewer_note_append": "2008년 4분기 수치는 분기 GDP(DT_200Y108류)에서 별도 확인 필요, 이 표는 연간 계열"},

    # --- DT_1PH2012: 반려동물 양육가구 ---
    "C02838": {"obj_l1": "00", "itm_id": "T20", "prd_se": "Y"},
    "C02839": {"obj_l1": "00", "itm_id": "T20", "prd_se": "Y"},

    # --- DT_1F02001: 광공업생산지수(전국) ---
    "C06501": {"obj_l1": "00", "itm_id": "T20", "prd_se": "M"},  # 전월비 -> 계절조정
    "C06570": {"obj_l1": "00", "itm_id": "T20", "prd_se": "M"},
    "C07048": {"obj_l1": "00", "itm_id": "T10", "prd_se": "M"},  # 전년동월비 -> 원지수
    "C07049": {"obj_l1": "00", "itm_id": "T10", "prd_se": "M"},
    "C07050": {"obj_l1": "00", "itm_id": "T10", "prd_se": "M",
               "reviewer_note_append": "품목별(자동차/고무플라스틱/가구/컴퓨터) 세부수치는 이 표의 업종별 세분류 별도 확인 필요"},
    "C07051": {"obj_l1": "00", "itm_id": "T10", "prd_se": "M"},
    "C07052": {"obj_l1": "00", "itm_id": "T10", "prd_se": "M"},

    # --- DT_1F02016: 출하지수(내수/수출) - 총출하지수 없음, tbl 재검토 권장 ---
    "C07053": {"reviewer_note_append": "obj_l1/itm_id 보류: 이 표는 내수/수출 세부출하만 있고 전체 출하지수는 DT_1F02001(T11)에 있음 - tbl_id 재검토 권장"},
    "C07054": {"reviewer_note_append": "obj_l1/itm_id 보류: 이 표는 내수/수출 세부출하만 있고 전체 출하지수는 DT_1F02001(T11)에 있음 - tbl_id 재검토 권장"},

    # --- DT_133N_A6341: 증여세(세대생략증여) ---
    "C05367": {"itm_id": "D002", "prd_se": "Y",
               "reviewer_note_append": "건당 금액 계산엔 건수(D001)도 별도 필요"},
    "C05368": {"itm_id": "D001", "prd_se": "Y"},

    # --- DT_118N_MON051: 사업체노동력조사 임금(경총 인용) ---
    "C07630": {"itm_id": "13103110311MD_13", "prd_se": "Y"},
    "C07631": {"itm_id": "13103110311MD_14", "prd_se": "Y",
               "reviewer_note_append": "초과급여 제외 임금 = 정액급여+특별급여 조합, 단일 코드로 근사"},
    "C07632": {"itm_id": "13103110311MD_13", "prd_se": "Y"},
    "C07633": {"itm_id": "13103110311MD_13", "prd_se": "Y"},
    "C07635": {"itm_id": "13103110311MD_13", "prd_se": "Y"},
    "C07636": {"itm_id": "13103110311MD_16", "prd_se": "Y"},  # 특별급여
    "C07637": {"itm_id": "13103110311MD_13", "prd_se": "Y",
               "reviewer_note_append": "사업체 규모별(300인미만/이상) 분류축 별도 확인 필요"},
    "C07642": {"itm_id": "13103110311MD_13", "prd_se": "Y",
               "reviewer_note_append": "시간당임금은 MD_13(임금총액)/MD_9(소정실근로시간) 조합 계산값"},
    "C07643": {"itm_id": "13103110311MD_13", "prd_se": "Y",
               "reviewer_note_append": "시간당임금은 MD_13/MD_9 조합 계산값"},

    # --- DT_1B83A08: 초혼부부 연령차 (obj_l1=전국) ---
    "C07964": {"obj_l1": "00", "prd_se": "Y"},
    "C07965": {"obj_l1": "00", "prd_se": "Y"},
    "C07966": {"obj_l1": "00", "prd_se": "Y"},

    # --- DT_121Y002: 예금은행 수신금리(정기적금) ---
    "C04127": {"obj_l1": "13102134588ACC_ITEM.BEABAA212", "prd_se": "M"},

    # --- DT_151Y001: 가계신용 ---
    "C04989": {"obj_l1": "13102134771ACC_ITEM.1000000", "prd_se": "Q"},
    "C04990": {"obj_l1": "13102134771ACC_ITEM.1000000", "prd_se": "Q"},
    "C04991": {"obj_l1": "13102134771ACC_ITEM.1000000", "prd_se": "Q"},
    "C04995": {"obj_l1": "13102134771ACC_ITEM.1000000", "prd_se": "Q"},

    # --- DT_151Y004: 가계신용(주택담보대출) ---
    "C04992": {"obj_l1": "13102134772ACC_ITEM.11000A0", "prd_se": "Q"},

    # --- INH_1B8000F_01: 인구동향조사(출생아수) ---
    "C05551": {"obj_l1": "11", "prd_se": "Y"},

    # --- DT_1KC2020: 서비스업생산지수(음식점업/주점업/숙박음식점업) ---
    "C07180": {"itm_id": "T2", "prd_se": "M"},
    "C07181": {"itm_id": "T2", "prd_se": "M"},
    "C07769": {"itm_id": "T2", "prd_se": "M"},
    "C07770": {"itm_id": "T2", "prd_se": "M"},
    "C09018": {"itm_id": "T2", "prd_se": "M"},

    # --- DT_1K41012: 소매판매액지수 ---
    "C03551": {"itm_id": "T2", "prd_se": "M",
               "reviewer_note_append": "3년 추세 서술 - 불변지수(물량) 기준으로 채움"},
    "C06578": {"itm_id": "T3", "prd_se": "M",
               "reviewer_note_append": "준내구재/비내구재 상품군별 세부 obj_l1 재검토 필요(자동 선택된 합계코드일 수 있음)"},
    "C09021": {"itm_id": "T3", "prd_se": "M",
               "reviewer_note_append": "자동차(상품군) 세부 obj_l1 재검토 필요(자동 선택된 합계코드일 수 있음)"},

    # --- DT_1BPA002: 장래인구추계(65세이상/초고령사회) ---
    "C02285": {"obj_l1": "1", "prd_se": "Y"},
    "C02705": {"obj_l1": "1", "prd_se": "Y"},
    "C02706": {"obj_l1": "1", "prd_se": "Y"},
    "C02710": {"obj_l1": "1", "prd_se": "Y"},
    "C02722": {"obj_l1": "1", "prd_se": "Y"},
    "C05561": {"obj_l1": "1", "prd_se": "Y"},
    "C09032": {"obj_l1": "1", "prd_se": "Y"},

    # --- DT_1R11006_FRM101: 무역통계(수출액/수입액) ---
    "C03202": {"itm_id": "13103103829T1", "prd_se": "M"},  # 수출액

    # --- DT_301Y017: 경상수지 ---
    "C03846": {"obj_l1": "13102134664ACC_CD.SA000", "prd_se": "Y"},

    # --- DT_MLTM_5328: 미분양주택 ---
    "C03897": {"obj_l1": "13102871088A.0001", "prd_se": "M"},  # 전국
    "C05463": {"reviewer_note_append": "obj_l1 보류: 대구+경북 두 지역 합산 필요, 단일 지역코드 아님"},

    # --- TX_38804_A005: 전력거래량(에너지원별) ---
    "C04077": {"itm_id": "16388AAW3", "prd_se": "Y"},
    "C04078": {"itm_id": "T001", "prd_se": "Y"},
    "C04079": {"itm_id": "T001", "prd_se": "Y"},
    "C04082": {"itm_id": "T001", "prd_se": "Y"},
    "C04084": {"itm_id": "T001", "prd_se": "Y"},
    "C04085": {"itm_id": "T001", "prd_se": "Y"},
    "C04086": {"itm_id": "T001", "prd_se": "Y"},
    "C04198": {"itm_id": "T001", "prd_se": "Y"},
    "C04201": {"itm_id": "16388AAW3", "prd_se": "Y"},
    "C04202": {"itm_id": "T001", "prd_se": "Y"},
    "C04203": {"itm_id": "T001", "prd_se": "Y"},
    "C04205": {"itm_id": "T001", "prd_se": "Y"},
    "C04206": {"itm_id": "T001", "prd_se": "Y"},
    "C04207": {"itm_id": "T001", "prd_se": "Y"},
    "C04208": {"itm_id": "T001", "prd_se": "Y"},

    # --- DT_1DA7001S: 경제활동인구조사(실업률) ---
    "C03991": {"itm_id": "T80", "prd_se": "M"},

    # --- DT_1F02016 이미 위에서 처리 ---

    # --- DT_1PH2012 이미 위에서 처리 ---

    # ================= 아래는 oversized 21건 =================

    # 무역통계 SITC 품목별 (org=360)
    "C01163": {"obj_l1": "13102112831A.A", "prd_se": "M"},  # 총액
    "C03193": {"obj_l1": "13102112831A.A", "prd_se": "M"},
    "C04193": {"obj_l1": "13102112831A.A", "prd_se": "M"},
    "C07183": {"obj_l1": "13102112831A.A", "prd_se": "M"},
    "C05005": {"obj_l1": "13102112831A.781", "prd_se": "M",
               "reviewer_note_append": "승용자동차 및 기타의 차량 코드로 근사 - 화물자동차(782) 별도 존재, 확인 필요"},
    "C06796": {"reviewer_note_append": "obj_l1 보류: 컴퓨터/반도체/석유제품 등 복수 품목 개별 수치 언급, 단일 코드 불가"},

    # 인구
    "C03047": {"org_id": "101", "tbl_id": "DT_1BPA002", "obj_l1": "1", "prd_se": "Y",
               "reviewer_note_append": "[Claude 재검토] 원래 DT_1B04006(읍면동단위, obj_l1 후보 과다)에서 DT_1BPA002(장래인구추계)로 표 변경 - 동일 패턴의 다른 행들과 통일"},

    # GDP
    "C03332": {"obj_l1": "13102136275ACC_ITEM.1400", "prd_se": "Y"},  # 국내총생산(시장가격 GDP)

    # 가계동향조사
    "C04947": {"obj_l1": "B4", "prd_se": "Q"},  # 근로소득
    "C08314": {"obj_l1": "W", "prd_se": "Q"},  # 비소비지출
    "C08317": {"obj_l1": "W6", "prd_se": "Q"},  # 이자비용
    "C08318": {"reviewer_note_append": "obj_l1 보류: '교육비' 키워드로 후보 못 찾음, 표 내 정확한 항목명 재확인 필요"},
    "C08319": {"reviewer_note_append": "obj_l1 보류: '교육비' 키워드로 후보 못 찾음, 표 내 정확한 항목명 재확인 필요"},

    # 국세통계 (133) - 00/0E/0F 세 계열 중 00 계열로 채움 (계열 의미 불확실 - 검증 필요)
    "C04952": {"obj_l1": "15133SMB00010102", "prd_se": "Y",
               "reviewer_note_append": "법인세 코드가 00/0E/0F 세 계열로 존재 - 의미 불확실, 우선 00 계열로 채움. 값 검증 시 주의"},
    "C04955": {"obj_l1": "15133SMB00010102", "prd_se": "Y",
               "reviewer_note_append": "법인세 코드 00/0E/0F 계열 중 00으로 채움 - 검증 필요"},
    "C04956": {"obj_l1": "15133SMB000101010204", "prd_se": "Y",
               "reviewer_note_append": "근로소득세(00 계열, 갑종/납세조합 제외 총액으로 추정) - 검증 필요"},
    "C19493": {"reviewer_note_append": "obj_l1 보류: '총국세' 키워드로 후보 못 찾음, 표 내 정확한 항목명 재확인 필요"},
    "C19573": {"obj_l1": "15133SMB00010102", "prd_se": "Y",
               "reviewer_note_append": "법인세 00 계열로 채움 - 검증 필요"},

    # GNI/PGDI
    "C06664": {"obj_l1": "13102136260ACC_ITEM.1600", "prd_se": "Y",
               "reviewer_note_append": "GNI 코드만 채움, PGDI(개인총처분가능소득) 코드는 별도 확인 필요 (비율 계산엔 둘 다 필요)"},

    # 월세지수
    "C16301": {"obj_l1": "a7", "prd_se": "M",
               "reviewer_note_append": "서울(obj_l1=a7) 확정, 아파트 유형(itm_id)은 '아파트' 키워드로 못 찾음 - 재확인 필요"},

    # 1인가구
    "C20422": {"obj_l1": "00", "itm_id": "T1", "prd_se": "Y"},

    # 임대주택 (obj_l1=지역, 전국합계 없음)
    "C16304": {"reviewer_note_append": "obj_l1 보류: 이 표는 시도별 코드만 있고 전국 합계 코드가 없음 - 시도 합산 계산 필요"},
}

with open(PATH, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    fieldnames = list(reader.fieldnames)

assert len(rows) == 4403, f"행 수 이상: {len(rows)}"

applied = 0
notes_only = 0
for r in rows:
    cid = r["claim_id"]
    if cid not in UPDATES:
        continue
    upd = UPDATES[cid]
    changed = False
    for field in ("org_id", "tbl_id", "obj_l1", "itm_id"):
        if field in upd:
            r[field] = upd[field]
            changed = True
    if "prd_se" in upd and not r.get("prd_se", "").strip():
        r["prd_se"] = upd["prd_se"]
        changed = True
    if "reviewer_note_append" in upd:
        existing = r.get("reviewer_note", "").strip()
        addition = upd["reviewer_note_append"]
        r["reviewer_note"] = (existing + " | " + addition).strip(" |") if existing else addition
        changed = True
        if not any(f in upd for f in ("org_id", "tbl_id", "obj_l1", "itm_id")):
            notes_only += 1
    if changed:
        applied += 1

print(f"반영된 행: {applied}건 (그 중 코드 없이 메모만 추가: {notes_only}건)")
print(f"UPDATES에 정의됐지만 파일에서 못 찾은 claim_id: {[c for c in UPDATES if c not in {r['claim_id'] for r in rows}]}")

with open(PATH, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

with open(PATH, encoding="utf-8-sig") as f:
    check = list(csv.DictReader(f))
assert len(check) == 4403, f"쓰기 후 행 수 이상: {len(check)}"
print(f"검증 완료: {len(check)}행")
