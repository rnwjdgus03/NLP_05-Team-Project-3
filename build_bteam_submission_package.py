"""
B팀 2,001건 검증 결과를 제출하기 쉬운 형태로 분리한다.

입력:
- outputs/bteam_review/final_verified_filled_2001_refined_v3.csv

출력:
- outputs/bteam_review/submission_verified_matches.csv
- outputs/bteam_review/submission_recheck_needed.csv
- outputs/bteam_review/submission_unverifiable.csv
- outputs/bteam_review/submission_bteam_status_report.md
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

BASE = Path("outputs/bteam_review")
DEFAULT_INPUT = BASE / "final_verified_filled_2001_refined_v3.csv"


def write_rows(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def compact_row(row):
    return {
        "claim_id": row.get("claim_id", ""),
        "article_id": row.get("article_id", ""),
        "title": row.get("title", ""),
        "date": row.get("date", ""),
        "url": row.get("url", ""),
        "claim_text": row.get("claim_text", ""),
        "metric": row.get("metric", ""),
        "org_id": row.get("org_id", ""),
        "tbl_id": row.get("tbl_id", ""),
        "obj_l1": row.get("obj_l1", ""),
        "itm_id": row.get("itm_id", ""),
        "prd_se": row.get("prd_se", ""),
        "actual_period": row.get("actual_period", ""),
        "actual_prev_period": row.get("actual_prev_period", ""),
        "claim_type": row.get("refined_claim_type", ""),
        "claim_number": row.get("refined_claim_number", ""),
        "actual_number": row.get("refined_actual_number", ""),
        "verdict": row.get("refined_verdict", ""),
        "final_status": row.get("refined_final_status", ""),
        "judge_note": row.get("refined_judge_note", ""),
        "reviewer_note": row.get("reviewer_note", ""),
    }


def main(input_path=DEFAULT_INPUT, output_prefix="submission"):
    input_path = Path(input_path)
    matches_path = BASE / f"{output_prefix}_verified_matches.csv"
    recheck_path = BASE / f"{output_prefix}_recheck_needed.csv"
    unverifiable_path = BASE / f"{output_prefix}_unverifiable.csv"
    report_path = BASE / f"{output_prefix}_bteam_status_report.md"

    with open(input_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    compact = [compact_row(row) for row in rows]
    matches = [row for row in compact if row["final_status"] == "검증완료_일치"]
    unverifiable = [row for row in compact if row["final_status"].startswith("판단불가")]
    recheck = [row for row in compact if row["final_status"].startswith("재검토필요")]

    fields = list(compact[0].keys())
    write_rows(matches_path, matches, fields)
    write_rows(recheck_path, recheck, fields)
    write_rows(unverifiable_path, unverifiable, fields)

    status_counts = Counter(row["final_status"] for row in compact)
    verdict_counts = Counter(row["verdict"] for row in compact)
    metric_counts = Counter(row["metric"] for row in compact)

    report = [
        "# B팀 KOSIS 검증 2,001건 제출 상태 보고",
        "",
        "## 결론",
        "",
        "- 2,001건 전체에 대해 KOSIS API 실제값 조회 및 자동 검증을 수행했다.",
        "- 자동 검증 결과를 그대로 최종 사실판정으로 쓰지 않고, 단위/시점/증감률 오류를 후처리해 제출 큐를 분리했다.",
        f"- 현재 바로 제출 가능한 확정 일치 건은 {len(matches)}건이다.",
        "- 나머지는 뉴스가 틀렸다는 뜻이 아니라, 표/항목/시점/단위 기준 재검토가 필요한 건으로 분리했다.",
        "",
        "## 결과 요약",
        "",
        "| 구분 | 건수 | 의미 |",
        "| --- | ---: | --- |",
    ]
    for key, count in status_counts.most_common():
        if key == "검증완료_일치":
            meaning = "KOSIS 실제값과 뉴스 주장 숫자가 허용오차 안에서 맞음"
        elif key == "재검토필요_증감률불일치":
            meaning = "증감률 claim과 KOSIS 계산값이 다름. 항목/시점/전년대비 기준 재확인 필요"
        elif key == "재검토필요_수준값불일치":
            meaning = "수준값 claim과 KOSIS 값이 다름. 단위/항목/표 매칭 재확인 필요"
        elif key == "판단불가_API조회실패":
            meaning = "API 응답 없음 또는 값 조회 실패"
        elif key == "판단불가_증감계산값없음":
            meaning = "증감률 claim인데 이전 시점 값이 없어 계산 보류"
        elif key == "판단불가_파라미터미확정":
            meaning = "obj_l1/itm_id 등 필수 파라미터 미확정"
        elif key == "판단불가_검증대상아님":
            meaning = "정책/전망/순위/기간 숫자 등 KOSIS 직접 검증 대상이 아님"
        else:
            meaning = "추가 확인 필요"
        report.append(f"| {key} | {count} | {meaning} |")

    report.extend([
        "",
        "## 산출 파일",
        "",
        f"- `{matches_path}`: 바로 제출 가능한 일치 claim",
        f"- `{recheck_path}`: 표/항목/시점/단위 재검토 필요 claim",
        f"- `{unverifiable_path}`: API/파라미터/증감 계산 문제로 판단불가 claim",
        f"- `{input_path}`: 전체 2,001건 상세 검증 결과",
        "",
        "## A팀에 요청할 점",
        "",
        "- 개별 상품 가격, 기업 실적, 전망/목표 문장처럼 KOSIS 공식 통계로 바로 검증하기 어려운 문장은 claim 후보에서 제외하거나 `verifiable=false`로 표시 필요.",
        "- claim마다 실제 검증 대상 숫자(`target_number`)를 별도 컬럼으로 주면 날짜/순위/기간 숫자를 잘못 비교하는 문제가 크게 줄어듦.",
        "- `전년동월 대비`, `전월 대비`, `작년`, `지난달`, `누적`, `1~9월` 같은 시점 기준을 별도 컬럼으로 분리해주면 API 파라미터 매칭 정확도가 올라감.",
        "",
        "## B팀 다음 개선점",
        "",
        "- 무역/물가/고용처럼 반복적으로 나오는 핵심 지표부터 전용 코드북을 만들어 obj_l1/itm_id를 고정한다.",
        "- 품목별 수출(반도체/자동차/화장품 등)은 전체 수출표가 아니라 품목 분류 코드까지 맞춰야 한다.",
        "- 증감률 claim은 KOSIS가 증감률을 직접 주는 표인지, 원자료 두 시점으로 직접 계산해야 하는 표인지 구분한다.",
        "",
        "## 참고 카운트",
        "",
        f"- verdict: {dict(verdict_counts)}",
        f"- metric 상위: {dict(metric_counts.most_common(10))}",
        "",
    ])

    report_path.write_text("\n".join(report), encoding="utf-8")

    print(f"완료 -> {report_path}")
    print(f"일치 제출 가능: {len(matches)}")
    print(f"재검토 필요: {len(recheck)}")
    print(f"판단불가: {len(unverifiable)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="refine_filled_verification.py 결과 CSV")
    parser.add_argument("--prefix", default="submission", help="출력 파일 prefix")
    args = parser.parse_args()
    main(args.input, args.prefix)
