"""
B팀 2,001건 검증 결과를 제출하기 쉬운 형태로 분리한다.

입력:
- outputs/bteam_review/final_verified_filled_2001_audited_v4.csv

출력:
- outputs/bteam_review/submission_match_candidates.csv
- outputs/bteam_review/submission_recheck_needed.csv
- outputs/bteam_review/submission_unverifiable.csv
- outputs/bteam_review/submission_bteam_status_report.md
"""

import csv
from collections import Counter
from pathlib import Path

BASE = Path("outputs/bteam_review")
INPUT = BASE / "final_verified_filled_2001_audited_v4.csv"
CANDIDATES = BASE / "submission_match_candidates.csv"
RECHECK = BASE / "submission_recheck_needed.csv"
UNVERIFIABLE = BASE / "submission_unverifiable.csv"
REPORT = BASE / "submission_bteam_status_report.md"


def write_rows(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def verdict_summary(counter):
    return ", ".join(f"{key} {counter.get(key, 0)}건" for key in ("일치", "불일치", "판단불가"))


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
        "final_status": row.get("audit_status") or row.get("refined_final_status", ""),
        "audit_reason": row.get("audit_reason", ""),
        "rerun_verdict": row.get("rerun_verdict", ""),
        "judge_note": row.get("refined_judge_note", ""),
        "reviewer_note": row.get("reviewer_note", ""),
    }


def main():
    with open(INPUT, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    compact = [compact_row(row) for row in rows]
    candidates = [row for row in compact if row["final_status"].startswith("수동확인필요")]
    unverifiable = [row for row in compact if row["final_status"].startswith("판단불가")]
    recheck = [row for row in compact if row["final_status"].startswith("재검토필요")]

    fields = list(compact[0].keys())
    write_rows(CANDIDATES, candidates, fields)
    write_rows(RECHECK, recheck, fields)
    write_rows(UNVERIFIABLE, unverifiable, fields)

    status_counts = Counter(row["final_status"] for row in compact)
    verdict_counts = Counter(row["verdict"] for row in compact)
    rerun_counts = Counter(row["rerun_verdict"] for row in compact if row["rerun_verdict"])
    metric_counts = Counter(row["metric"] for row in compact)

    report = [
        "# B팀 KOSIS 검증 2,001건 제출 상태 보고",
        "",
        "## 결론",
        "",
        "- 원격의 2,001건 자동 실행 결과는 최종 사실판정이 아닌 단위/시점/증감률 오류 진단 자료로 사용했다.",
        "- 24건 표본의 의미 매핑 품질 게이트가 실패해 1,998건 전체를 새 로직으로 재실행하지 않았다.",
        "- 기존 자동 일치 70건을 다시 감사해 미래시점·전망문장·수동확인 후보로 재분류했다.",
        f"- 70건 정확시점 재실행 자동 판정: {verdict_summary(rerun_counts)}.",
        "- 현재 표·항목·단위·의미 매핑까지 확정된 최종 일치는 0건이다.",
        "- 나머지는 뉴스가 틀렸다는 뜻이 아니라, 표/항목/시점/단위 기준 재검토가 필요한 건으로 분리했다.",
        "",
        "## 결과 요약",
        "",
        "| 구분 | 건수 | 의미 |",
        "| --- | ---: | --- |",
    ]
    for key, count in status_counts.most_common():
        if key == "수동확인필요_일치후보":
            meaning = "수치 오차는 범위 이내지만 표/항목/단위/의미 매핑 수동 확정 필요"
        elif key == "재검토필요_미래시점":
            meaning = "기사일 이후 통계 시점을 사용한 기존 자동 일치"
        elif key == "재검토필요_정확시점불일치":
            meaning = "정확한 목표 시점으로 재조회한 KOSIS 값과 주장 수치가 다름"
        elif key == "판단불가_전망문장":
            meaning = "전망/예상/목표 문장으로 현재 실적값 검증 대상이 아님"
        elif key == "판단불가_정확시점조회실패":
            meaning = "정확한 목표 시점의 KOSIS 값을 조회하거나 증감을 계산하지 못함"
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
        else:
            meaning = "추가 확인 필요"
        report.append(f"| {key} | {count} | {meaning} |")

    report.extend([
        "",
        "## 산출 파일",
        "",
        f"- `{CANDIDATES.as_posix()}`: 수치상 일치하지만 매핑 수동 확정이 남은 claim",
        f"- `{RECHECK.as_posix()}`: 표/항목/시점/단위 재검토 필요 claim",
        f"- `{UNVERIFIABLE.as_posix()}`: API/파라미터/증감 계산 문제로 판단불가 claim",
        f"- `{INPUT.as_posix()}`: 전체 2,001건 상세 검증 결과",
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
        f"- 기존 원격 자동 verdict(진단용): {dict(verdict_counts)}",
        f"- 70건 정확시점 재실행 verdict: {verdict_summary(rerun_counts)}",
        f"- metric 상위: {dict(metric_counts.most_common(10))}",
        "",
    ])

    REPORT.write_text("\n".join(report), encoding="utf-8")

    print(f"완료 -> {REPORT}")
    print(f"수동확인 일치 후보: {len(candidates)}")
    print(f"재검토 필요: {len(recheck)}")
    print(f"판단불가: {len(unverifiable)}")


if __name__ == "__main__":
    main()
