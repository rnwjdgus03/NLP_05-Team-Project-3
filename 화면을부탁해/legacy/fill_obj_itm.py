"""
table_claim_mapping_김진성.csv 중 org_id/tbl_id는 확정됐지만
obj_l1/itm_id/prd_se가 비어있는 행에 대해, KOSIS 메타정보 API로 실제 분류축/항목 코드를
조회해서 채워주는 스크립트.

*** 반드시 KOSIS API(kosis.kr)에 접속 가능한 로컬 환경(PowerShell)에서 실행할 것 ***

동작 방식:
  - 분류축(obj_l1)이 1개 코드만 있으면 자동으로 채움
  - 분류축 코드가 여러 개면, "계/전체/총계" 같은 합계 코드를 찾아서 자동으로 채움
    (합계 코드가 없으면 자동 선택 안 하고, 후보 전체를 obj_l1_candidates 컬럼에 저장)
  - 항목(itm_id)도 같은 방식으로 처리 (후보는 itm_id_candidates 컬럼에 저장)
  - 후보가 CSV에 저장되니, 이 파일을 그대로 공유하면 사람이 보고 obj_l1/itm_id 칸에
    후보 중 올바른 code만 옮겨 적으면 됨
  - prd_se(수록주기: Y=연간, Q=분기, M=월별)는 이 스크립트가 채우지 않음 -> claim_text의
    시점 표현(예: "지난달", "1분기")을 보고 직접 채워야 함

재실행해도 안전: 이미 obj_l1/itm_id가 채워진 값은 덮어쓰지 않음.

사용법:
    python fill_obj_itm.py
"""

import csv

from kosis_api_test import summarize_meta

PATH = "table_claim_mapping_김진성.csv"
TOTAL_NAMES = {"계", "전체", "총계", "소계", "총지수", "합계"}
EXTRA_FIELDS = ["obj_l1_candidates", "itm_id_candidates"]


def pick_code(codes):
    """codes: [(code, name), ...]. 합계성 코드를 우선 찾고, 없으면 None."""
    if len(codes) == 1:
        return codes[0][0], None
    total = next((c for c, nm in codes if nm.strip() in TOTAL_NAMES), None)
    if total:
        return total, None
    return None, codes  # 자동 선택 실패 -> 후보 목록 반환


def format_candidates(codes):
    return "; ".join(f"{c}:{nm}" for c, nm in codes)


def main():
    with open(PATH, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        rows = list(r)
        fields = list(r.fieldnames)

    for col in EXTRA_FIELDS:
        if col not in fields:
            fields.append(col)
    for row in rows:
        for col in EXTRA_FIELDS:
            row.setdefault(col, "")

    auto_filled = 0
    need_manual = 0
    skipped = 0

    for row in rows:
        org_id = row.get("org_id", "").strip()
        tbl_id = row.get("tbl_id", "").strip()
        if not org_id or not tbl_id:
            continue

        has_obj = bool(row.get("obj_l1", "").strip())
        has_itm = bool(row.get("itm_id", "").strip())
        if has_obj and has_itm:
            skipped += 1
            continue

        print(f"\n[{row['claim_id']}] {row['claim_text'][:60]}")
        try:
            meta = summarize_meta(org_id, tbl_id)
        except Exception as e:
            print("  메타 조회 실패:", e)
            row["reviewer_note"] = (row.get("reviewer_note", "") + f" | 메타 조회 실패: {e}").strip(" |")
            continue

        classifications = meta["classifications"]
        items = meta["items"]
        notes = []

        if not has_obj and classifications:
            axes = sorted(classifications.keys(), key=lambda k: k[0])
            axis_key = axes[0]
            code, candidates = pick_code(classifications[axis_key])
            if code:
                row["obj_l1"] = code
            else:
                row["obj_l1_candidates"] = format_candidates(candidates)
                notes.append(f"obj_l1 수동 선택 필요({axis_key[1]}, 후보 {len(candidates)}개 -> obj_l1_candidates 컬럼 참고)")
            if len(axes) > 1:
                notes.append(f"분류축이 {len(axes)}개라 obj_l2 이상 추가 필요할 수 있음: " +
                             ", ".join(a[1] for a in axes[1:]))

        if not has_itm and items:
            code, candidates = pick_code(items)
            if code:
                row["itm_id"] = code
            else:
                row["itm_id_candidates"] = format_candidates(candidates)
                notes.append(f"itm_id 수동 선택 필요(후보 {len(candidates)}개 -> itm_id_candidates 컬럼 참고)")

        if row.get("obj_l1", "").strip() and row.get("itm_id", "").strip():
            auto_filled += 1
            print("  -> obj_l1/itm_id 자동 완료")
        else:
            need_manual += 1
            print("  -> 수동 선택 필요 (obj_l1_candidates / itm_id_candidates 컬럼 참고)")

        if notes:
            row["reviewer_note"] = (row.get("reviewer_note", "") + " | " + " / ".join(notes)).strip(" |")

    with open(PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"\n완료 -> {PATH}")
    print(f"obj_l1/itm_id 자동 완료: {auto_filled}건, 수동 선택 필요: {need_manual}건, 이미 완료돼서 건너뜀: {skipped}건")
    print("주의: prd_se(Y/Q/M)는 이 스크립트가 채우지 않음. claim_text 시점 보고 직접 채워야 함.")


if __name__ == "__main__":
    main()
