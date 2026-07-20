"""
kosis_metadata_summary.csv에서 단위가 "확인 불가"로 남은 행들만 다시 조회해서 채움.
(get_sample_unit()의 다중 분류축(objL2, objL3...) 버그를 고친 뒤 재실행용)

사용법:
    python fix_units.py
"""

import csv

from kosis_api_test import summarize_meta
from kosis_metadata_summary import get_sample_unit, FIELDS

PATH = "kosis_metadata_summary.csv"


def main():
    with open(PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    fixed = 0
    for r in rows:
        if r.get("단위") != "확인 불가":
            continue
        org_id, tbl_id = r["ORG_ID"], r["TBL_ID"]
        print(f"재조회: {r['TBL_NM']} ({tbl_id})")
        try:
            meta = summarize_meta(org_id, tbl_id)
            unit = get_sample_unit(org_id, tbl_id, meta["classifications"], meta["items"])
        except Exception as e:
            unit = f"조회 실패: {e}"
        if unit != "확인 불가":
            print(f"  -> {unit}")
            r["단위"] = unit
            fixed += 1
        else:
            print("  -> 여전히 확인 불가")

    with open(PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n완료: {fixed}개 단위 업데이트 -> {PATH}")


if __name__ == "__main__":
    main()
