"""
fill_obj_itm_manual_todo.py 실행 후 obj_l1_candidates/itm_id_candidates가 채워진 행들을
Claude가 검토하기 쉽도록 요약 파일로 뽑아내는 스크립트.

(Claude 쪽 샌드박스 마운트가 이 큰 CSV의 최신 버전을 아직 못 읽어서,
 로컬에서 직접 요약본을 만들어 전달하는 방식으로 우회함)

사용법:
    python extract_manual_selection_summary.py
"""

import csv
import sys

csv.field_size_limit(sys.maxsize)

PATH = "outputs/bteam_review/bteam_kosis_review_manual_todo.csv"
OUT_PATH = "outputs/bteam_review/manual_selection_summary.csv"
MAX_CANDIDATE_LEN = 1500  # 이보다 길면 "너무 김" 표시만 하고 잘라냄

with open(PATH, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

print(f"전체 행: {len(rows)}")

need_manual = []
oversized = []
for r in rows:
    obj_c = r.get("obj_l1_candidates", "").strip()
    itm_c = r.get("itm_id_candidates", "").strip()
    if obj_c or itm_c:
        need_manual.append(r)
        if len(obj_c) > MAX_CANDIDATE_LEN or len(itm_c) > MAX_CANDIDATE_LEN:
            oversized.append(r["claim_id"])

print(f"수동 선택 필요: {len(need_manual)}건")
print(f"후보 목록이 비정상적으로 큰 행(재검토 필요): {len(oversized)}건 -> {oversized}")

with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["claim_id", "claim_text", "org_id", "tbl_id", "obj_l1_candidates_truncated",
                "itm_id_candidates_truncated", "oversized"])
    for r in need_manual:
        obj_c = r.get("obj_l1_candidates", "").strip()
        itm_c = r.get("itm_id_candidates", "").strip()
        w.writerow([
            r["claim_id"],
            r["claim_text"][:200],
            r.get("org_id", ""),
            r.get("tbl_id", ""),
            obj_c[:MAX_CANDIDATE_LEN],
            itm_c[:MAX_CANDIDATE_LEN],
            "YES" if r["claim_id"] in oversized else "",
        ])

print(f"\n완료 -> {OUT_PATH}")
