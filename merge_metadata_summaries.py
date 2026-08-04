"""
팀원별로 나눠서 조회한 kosis_metadata_summary_*.csv 여러 개를
하나의 kosis_metadata_summary.csv 로 합침 (TBL_ID 기준 중복 제거).

사용법:
    python merge_metadata_summaries.py kosis_metadata_summary.csv kosis_metadata_summary.csv kosis_metadata_summary_철수.csv
    (첫번째 인자가 최종 결과 파일명, 나머지는 합칠 파일들)
"""

import csv
import sys

FIELDS = ["TBL_NM", "ORG_ID", "TBL_ID", "분류축", "항목_예시(최대5개)", "항목_전체개수", "단위"]


def main(out_path, in_paths):
    seen = set()
    merged = []
    for path in in_paths:
        try:
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError:
            print(f"(없음, 건너뜀) {path}")
            continue
        added = 0
        for r in rows:
            key = r.get("TBL_ID")
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)
            added += 1
        print(f"{path}: {len(rows)}개 중 {added}개 새로 추가")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(merged)
    print(f"\n완료 -> {out_path} (총 {len(merged)}개)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python merge_metadata_summaries.py 결과파일.csv 합칠파일1.csv [합칠파일2.csv ...]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2:])
