"""
audited_v4 결과의 수동확인/재검토/판단불가 행에 원인 라벨을 붙인다.

출력:
- outputs/bteam_review/submission_recheck_cause_analysis.csv
- outputs/bteam_review/submission_recheck_cause_summary.csv
"""

import csv
import re
from collections import Counter
from pathlib import Path

BASE = Path("outputs/bteam_review")
INPUT = BASE / "final_verified_filled_2001_audited_v4.csv"
OUT = BASE / "submission_recheck_cause_analysis.csv"
SUMMARY = BASE / "submission_recheck_cause_summary.csv"

ITEM_KEYWORDS = re.compile(
    r"반도체|자동차|선박|화장품|바이오|의약품|농수산|식품|석유|철강|고등어|닭고기|품목"
)
FORECAST_KEYWORDS = re.compile(r"전망|예상|목표|가능성|계획|추정|예측|것으로 봤다|전망했다")
PRICE_KEYWORDS = re.compile(r"가격|값|원으로|원에|최저임금|분양가|매매가|전셋값")
TIME_KEYWORDS = re.compile(r"지난달|전월|전년동월|전년 동월|1~9월|누적|분기|월")


def label(row):
    status = row.get("audit_status") or row.get("refined_final_status", "")
    text = row.get("claim_text", "")
    metric = row.get("metric", "")
    tbl_id = row.get("tbl_id", "")
    claim_type = row.get("refined_claim_type", "")

    if status == "수동확인필요_일치후보":
        return "일치후보_매핑수동확인", "수치는 허용오차 안이지만 표/항목/단위/의미 매핑 확정 필요"
    if status == "재검토필요_미래시점":
        return "미래시점오류", "기사 게재일보다 뒤의 KOSIS 시점을 사용함"
    if status == "판단불가_전망문장":
        return "비검증성_전망정책문장", "전망/예상/목표 문장은 현재 공식 통계값 검증 대상이 아님"
    if status == "재검토필요_정확시점불일치":
        return "정확시점재검증불일치", "정확한 목표 시점으로 재조회한 KOSIS 값과 주장 수치가 다름"
    if status == "판단불가_정확시점조회실패":
        return "정확시점조회실패", row.get("rerun_api_error") or "정확한 시점의 KOSIS 값 조회/계산 실패"
    if status == "판단불가_파라미터미확정":
        return "파라미터미확정", "obj_l1/itm_id 등 필수 코드가 비어 있음"
    if status == "판단불가_API조회실패":
        return "API조회실패", row.get("api_error", "KOSIS 실제값 조회 실패")
    if status == "판단불가_증감계산값없음":
        return "증감계산불가", "증감률/포인트 claim인데 이전 시점 값이 없어 계산 불가"

    if FORECAST_KEYWORDS.search(text):
        return "비검증성_전망정책문장", "전망/예상/목표 문장은 실제 공식 통계값 검증 대상이 아님"
    if "무역" in metric and ITEM_KEYWORDS.search(text):
        return "품목코드불일치_무역세부품목", "반도체/자동차/화장품 등 품목 claim인데 전체 수출입 코드로 비교됐을 가능성"
    if "무역" in metric and ("수입" in text and "수출" in tbl_id):
        return "항목코드오류_수입수출혼재", "수입 claim에 수출 계열 표/항목이 붙었을 가능성"
    if PRICE_KEYWORDS.search(text) and "물가" not in metric:
        return "KOSIS부적합_개별가격문장", "개별 가격/시장 가격 문장은 KOSIS 표와 직접 대응이 어려움"
    if claim_type in {"CHANGE_RATE", "POINT_CHANGE"} and TIME_KEYWORDS.search(text):
        return "시점기준재확인_증감률", "전년동월/전월/누적 등 비교 기준을 더 정확히 맞춰야 함"
    if row.get("refined_claim_number_reason", "").startswith("날짜"):
        return "claim_number추출주의", "날짜/순위/기간 숫자가 섞여 target_number 확정 필요"
    return "기타_수동확인필요", "표/항목/단위/시점 중 어느 축이 다른지 수동 확인 필요"


def main():
    with open(INPUT, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for row in rows:
        cause, reason = label(row)
        out_rows.append({
            "claim_id": row.get("claim_id", ""),
            "cause_label": cause,
            "reason": reason,
            "final_status": row.get("audit_status") or row.get("refined_final_status", ""),
            "metric": row.get("metric", ""),
            "tbl_id": row.get("tbl_id", ""),
            "claim_text": row.get("claim_text", ""),
            "claim_number": row.get("refined_claim_number", ""),
            "actual_number": row.get("refined_actual_number", ""),
            "actual_period": row.get("actual_period", ""),
            "actual_prev_period": row.get("actual_prev_period", ""),
            "judge_note": row.get("refined_judge_note", ""),
        })

    fields = list(out_rows[0].keys())
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)

    counter = Counter(row["cause_label"] for row in out_rows)
    with open(SUMMARY, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["cause_label", "count"], lineterminator="\n")
        writer.writeheader()
        for key, count in counter.most_common():
            writer.writerow({"cause_label": key, "count": count})

    print(f"완료 -> {OUT}")
    print(counter)


if __name__ == "__main__":
    main()
