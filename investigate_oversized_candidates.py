"""
manual_selection_summary.csv에서 'oversized'로 표시된 21건 (obj_l1_candidates 또는
itm_id_candidates가 너무 커서 요약 파일에서 잘려나간 행들)을 claim_text/metric 기반
키워드로 필터링해서, Claude가 판단할 수 있는 짧은 후보 목록만 뽑아내는 스크립트.

사용법:
    python investigate_oversized_candidates.py
"""

import csv
import sys

csv.field_size_limit(sys.maxsize)

PATH = "outputs/bteam_review/bteam_kosis_review_manual_todo.csv"
OUT_PATH = "outputs/bteam_review/oversized_candidates_filtered.csv"

# claim_id -> 검색 키워드 목록 (claim 내용 보고 수동으로 골라둔 힌트)
HINTS = {
    "C01163": ["자동차", "반도체", "13개월", "전체", "총"],
    "C03193": ["일평균", "총", "전체"],
    "C04193": ["반도체", "ICT", "전체", "총"],
    "C05005": ["자동차"],
    "C06796": ["컴퓨터", "반도체", "석유제품", "정보기술", "IT"],
    "C07183": ["일평균", "전체", "총"],
    "C03047": ["전국", "65", "계"],
    "C03332": ["국내총생산", "총", "전체"],
    "C04947": ["근로소득", "가계"],
    "C04952": ["법인세", "근로소득세", "총국세", "계"],
    "C04955": ["법인세", "총국세", "계"],
    "C04956": ["근로소득세", "총국세", "계"],
    "C06664": ["GNI", "PGDI", "국민총소득"],
    "C08314": ["비소비지출"],
    "C08317": ["이자비용", "이자"],
    "C08318": ["교육비"],
    "C08319": ["교육비"],
    "C16301": ["서울", "아파트"],
    "C19493": ["총국세", "계"],
    "C19573": ["법인세", "총국세"],
    "C20422": ["전국", "1인"],
}

with open(PATH, encoding="utf-8-sig") as f:
    rows = {r["claim_id"]: r for r in csv.DictReader(f)}

results = []
for cid, keywords in HINTS.items():
    r = rows.get(cid)
    if not r:
        results.append((cid, "ROW NOT FOUND", "", ""))
        continue
    obj_c = r.get("obj_l1_candidates", "")
    itm_c = r.get("itm_id_candidates", "")

    def filter_candidates(field):
        if not field:
            return ""
        items = field.split("; ")
        matched = [it for it in items if any(kw in it for kw in keywords)]
        return "; ".join(matched[:20])  # 최대 20개만

    obj_matched = filter_candidates(obj_c)
    itm_matched = filter_candidates(itm_c)
    results.append((cid, r["claim_text"][:150], obj_matched, itm_matched))

with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["claim_id", "claim_text", "obj_l1_matched", "itm_id_matched"])
    w.writerows(results)

print(f"완료 -> {OUT_PATH}")
for row in results:
    print(row[0], "->", "obj:", row[2][:100] if row[2] else "(no match)",
          "| itm:", row[3][:100] if row[3] else "(no match)")
