"""
이미 있는 kosis_table_summary.csv(농림=K1 크롤링 결과)에,
다른 카테고리(인구=A, 노동=D 등) 크롤링 결과를 이어붙임 (덮어쓰지 않고 병합).

사용법:
    python crawl_more_categories.py A D
    (인자로 크롤링할 최상위 카테고리 코드를 원하는 만큼 넣기)

여러 명이 동시에 나눠서 크롤링할 때:
    python crawl_more_categories.py --out kosis_table_summary_철수.csv P2 B
    처럼 --out 뒤에 자기 이름 붙인 파일명을 주면, 그 사람 몫만 별도 파일로 저장됨
    (같은 kosis_table_summary.csv를 동시에 건드리면 git push할 때 충돌나서
    각자 다른 파일에 저장 -> 나중에 merge_table_summaries.py로 합치는 방식)

카테고리 코드:
A=인구 B=사회일반 C=범죄ㆍ안전 D=노동 E=소득ㆍ소비ㆍ자산 F=보건 G=복지
H1=교육ㆍ훈련 H2=문화ㆍ여가 I1=주거 I2=국토이용 J1=경제일반ㆍ경기 J2=기업경영
K1=농림 K2=수산 L=광업ㆍ제조업 M1=건설 M2=교통ㆍ물류 N1=정보통신 N2=과학ㆍ기술
O=도소매ㆍ서비스 P1=임금 P2=물가 Q=국민계정 R=정부ㆍ재정 S1=금융 S2=무역ㆍ국제수지
T=환경 U=에너지 V=지역통계
"""

import csv
import os
import sys

from kosis_table_search import crawl_all_tables

FIELDS = ["ORG_ID", "TBL_ID", "TBL_NM", "STAT_ID", "path"]


def load_existing(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_all(rows, path):
    # TBL_ID 기준 중복 제거 (혹시 같은 카테고리 두 번 크롤링해도 안전하게)
    seen = set()
    deduped = []
    for r in rows:
        key = r.get("TBL_ID")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(deduped)
    return len(deduped)


def main(category_codes, out_path):
    existing = load_existing(out_path)
    print(f"기존 {len(existing)}개 통계표 로드 ({out_path})")

    all_rows = list(existing)
    for code in category_codes:
        print(f"\n{code} 카테고리 크롤링 중...")
        new_rows = crawl_all_tables(start_parent=code)
        print(f"  -> {len(new_rows)}개 수집")
        all_rows.extend(new_rows)

    total = save_all(all_rows, out_path)
    print(f"\n완료 -> {out_path} (총 {total}개, 중복 제거 후)")


if __name__ == "__main__":
    args = sys.argv[1:]
    out_path = "kosis_table_summary.csv"
    if args and args[0] == "--out":
        out_path = args[1]
        args = args[2:]
    codes = args if args else ["A", "D"]
    main(codes, out_path)
