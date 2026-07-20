"""
2,001건 filled 검증 결과 후처리 스크립트.

목적:
- verify_claim.py 1차 결과에서 명백한 자동판정 오류를 줄인다.
- 특히 무역 통계(KOSIS: 천달러, 기사: 억달러) 단위 차이를 보정한다.
- 증감률 claim인데 actual_change_pct가 없어서 수준값(actual_value)과 비교된 행은
  "불일치"가 아니라 "판단불가_증감률계산불가"로 분류한다.

출력:
- outputs/bteam_review/final_verified_filled_2001_refined.csv
- outputs/bteam_review/final_verified_filled_2001_refined_summary.csv
- outputs/bteam_review/final_verified_filled_2001_refined_review_samples.csv
"""

import csv
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

BASE_DIR = Path("outputs/bteam_review")
DEFAULT_INPUT_PATH = BASE_DIR / "final_verified_filled_2001.csv"
DEFAULT_OUTPUT_PATH = BASE_DIR / "final_verified_filled_2001_refined.csv"

NUMBER = r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?"

CHANGE_RE = re.compile(
    r"(증가|감소|줄었|늘었|올랐|내렸|상승|하락|급증|급감|성장|둔화|위축|확대|축소|개선|악화|반등|신장|역성장)"
)
POINT_RE = re.compile(r"(포인트|%p|p\s*(?:상승|하락|증가|감소))")

DATE_RANGE_RE = re.compile(
    rf"{NUMBER}\s*[~∼\-]\s*{NUMBER}\s*(?:년대?|월|일|주째|주|분기|개월|시|번째|차|위)"
)
DATE_SUFFIX_RE = re.compile(rf"{NUMBER}\s*(?:년대?|월|일|주째|주|분기|개월|시|번째|차|위)")

TRADE_TBLS = {
    "DT_1R11001_FRM101",  # 수출
    "DT_1R11002_FRM101",  # 수입
    "DT_1R11006_FRM101",  # 무역수지/수출입 관련
}

# 값 자체가 이미 비율/등락률인 표. 이런 표는 actual_change_pct를 다시 계산하면
# "등락률의 등락률"이 되어 claim과 어긋난다.
RATE_VALUE_TBLS = {
    "DT_1J22042",  # 월별 소비자물가 등락률
    "DT_1J22041",  # 연도별 소비자물가 등락률
}

DECREASE_RE = re.compile(r"감소|줄었|줄어|줄며|하락|내렸|떨어|급감|축소|마이너스|적자")

TOLERANCE = {
    "CHANGE_RATE": 0.3,
    "POINT_CHANGE": 0.3,
    "LEVEL": 0.05,
    "ABS_TO_ABS": 0.02,
}

CLAIM_TYPE_MAP = {
    "수준값": "LEVEL",
    "증감률": "CHANGE_RATE",
    "증감": "CHANGE_RATE",
    "포인트": "POINT_CHANGE",
    "전망·예측": "UNVERIFIABLE",
    "전망/예측": "UNVERIFIABLE",
    "전망": "UNVERIFIABLE",
    "예측": "UNVERIFIABLE",
    "순위": "UNVERIFIABLE",
    "개별상품가격": "UNVERIFIABLE",
}


def normalize_claim_type(value, text):
    raw = str(value or "").strip()
    if raw in CLAIM_TYPE_MAP:
        return CLAIM_TYPE_MAP[raw]
    if raw in {"LEVEL", "CHANGE_RATE", "POINT_CHANGE", "ABS_TO_ABS", "UNVERIFIABLE"}:
        return raw
    return classify(text)


def to_float(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    m = re.search(NUMBER, text)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def classify(text):
    if re.search(r"(에서|→|->).*(으로|로)", text):
        return "ABS_TO_ABS"
    if POINT_RE.search(text):
        return "POINT_CHANGE"
    if CHANGE_RE.search(text):
        return "CHANGE_RATE"
    return "LEVEL"


def strip_date_numbers(text):
    cleaned = DATE_RANGE_RE.sub(" ", text)
    cleaned = DATE_SUFFIX_RE.sub(" ", cleaned)
    # 기사 앞에 붙은 문단/문장 번호처럼 보이는 "24 한국의 ..." 형태 제거
    cleaned = re.sub(rf"^\s*{NUMBER}\s+(?=[가-힣A-Za-z])", " ", cleaned)
    return cleaned


def numbers_from(text):
    out = []
    for raw in re.findall(NUMBER, text):
        val = to_float(raw)
        if val is not None:
            out.append(val)
    return out


def last_number_before_unit(text, unit_pattern):
    matches = re.findall(rf"({NUMBER})\s*{unit_pattern}", text)
    if not matches:
        return None
    return to_float(matches[-1])


def pick_claim_number(text, claim_type, row=None):
    """기사 문장에서 실제 검증 대상 숫자 하나를 고른다."""
    row = row or {}
    target = to_float(row.get("target_number"))
    if target is not None:
        if claim_type in {"CHANGE_RATE", "POINT_CHANGE"} and target > 0 and DECREASE_RE.search(text):
            return -target, "target_number 컬럼 사용 + 감소/하락 문맥으로 음수 보정"
        return target, "target_number 컬럼 사용"

    if claim_type in {"CHANGE_RATE", "POINT_CHANGE"}:
        point = last_number_before_unit(text, r"(?:%p|포인트|p\b)")
        if point is not None:
            return point, "포인트/%p 숫자 선택"
        pct = last_number_before_unit(text, r"%")
        if pct is not None:
            return pct, "% 숫자 선택"

    # 수준값은 단위가 붙은 숫자를 우선 선택한다.
    unit_patterns = [
        (r"억\s*달러", "억달러 숫자 선택"),
        (r"만\s*달러", "만달러 숫자 선택"),
        (r"달러", "달러 숫자 선택"),
        (r"조\s*원", "조원 숫자 선택"),
        (r"억\s*원", "억원 숫자 선택"),
        (r"만\s*원", "만원 숫자 선택"),
        (r"원", "원 숫자 선택"),
        (r"%", "% 숫자 선택"),
        (r"만\s*명", "만명 숫자 선택"),
        (r"명", "명 숫자 선택"),
        (r"만\s*건", "만건 숫자 선택"),
        (r"건", "건 숫자 선택"),
        (r"가구", "가구 숫자 선택"),
        (r"배", "배 숫자 선택"),
    ]
    for pattern, label in unit_patterns:
        val = last_number_before_unit(text, pattern)
        if val is not None:
            return val, label

    filtered = strip_date_numbers(text)
    nums = numbers_from(filtered)
    if nums:
        return nums[0], "날짜/기간 숫자 제거 후 첫 숫자 선택"
    return None, "claim 숫자 선택 실패"


def actual_for_claim(row, claim_type):
    """claim 유형/단위에 맞춰 KOSIS 실제값을 선택하고 필요하면 단위 변환한다."""
    text = row.get("claim_text", "")
    tbl_id = row.get("tbl_id", "")
    target_unit = str(row.get("target_unit", "")).strip()

    if str(row.get("verifiable", "")).strip().lower() == "false" or claim_type == "UNVERIFIABLE":
        return None, "KOSIS 직접 검증 대상 아님"

    if claim_type == "CHANGE_RATE":
        # 등락률/비율 표는 actual_value 자체가 이미 claim과 비교할 값인 경우가 있다.
        if tbl_id in RATE_VALUE_TBLS:
            val = to_float(row.get("actual_value"))
            if val is not None:
                return val, "actual_value 사용(등락률 표)"

        val = to_float(row.get("actual_change_pct"))
        if val is None:
            return None, "증감률 claim인데 actual_change_pct 없음"
        actual_value = to_float(row.get("actual_value"))
        target = to_float(row.get("target_number"))

        # KOSIS 표/항목에 따라 actual_value 자체가 이미 % 값인 경우가 있다.
        # 둘 중 claim target에 더 가까운 값을 택하되, actual_value가 비율로 보기 어려운
        # 큰 수이면 제외한다.
        if target is not None and actual_value is not None and abs(actual_value) <= 100:
            signed_target = -target if target > 0 and DECREASE_RE.search(text) else target
            if abs(actual_value - signed_target) < abs(val - signed_target):
                return actual_value, "actual_value 사용(비율값이 target에 더 가까움)"

        return val, "actual_change_pct 사용"

    if claim_type == "POINT_CHANGE":
        val = to_float(row.get("actual_change_point"))
        if val is None:
            return None, "포인트 변화 claim인데 actual_change_point 없음"
        return val, "actual_change_point 사용"

    actual = to_float(row.get("actual_value"))
    if actual is None:
        return None, row.get("api_error") or "actual_value 없음"

    # KOSIS 무역표는 보통 천달러 단위, target_unit에 맞춰 변환한다.
    if tbl_id in TRADE_TBLS and target_unit == "달러":
        return actual * 1000, "무역 천달러 -> 달러 변환"

    # 천달러 -> 억달러: 100,000으로 나눔.
    if tbl_id in TRADE_TBLS and (target_unit == "억달러" or re.search(r"억\s*달러", text)):
        return actual / 100000, "무역 천달러 -> 억달러 변환"

    # 천달러 -> 만달러: 10으로 나눔.
    if tbl_id in TRADE_TBLS and (target_unit == "만달러" or re.search(r"만\s*달러", text)):
        return actual / 10, "무역 천달러 -> 만달러 변환"

    return actual, "actual_value 사용"


def judge(claim_number, actual_number, claim_type):
    if claim_number is None:
        return "판단불가", "", "claim 숫자 선택 실패"
    if actual_number is None:
        return "판단불가", "", "KOSIS 실제값/계산값 없음"

    tol = TOLERANCE.get(claim_type, 0.05)
    if claim_type in {"CHANGE_RATE", "POINT_CHANGE"}:
        diff = abs(claim_number - actual_number)
        ok = diff <= tol
    else:
        if actual_number == 0:
            return "판단불가", "", "실제값 0으로 상대오차 계산 불가"
        diff = abs(claim_number - actual_number) / abs(actual_number)
        ok = diff <= tol
    return ("일치" if ok else "불일치"), diff, f"claim={claim_number}, adjusted_actual={actual_number}, 오차={diff:.3f}, 허용={tol}"


def final_status(verdict, row, claim_type, actual_reason):
    if verdict == "일치":
        return "수동확인필요_일치후보"
    if verdict == "판단불가":
        if str(row.get("verifiable", "")).strip().lower() == "false" or claim_type == "UNVERIFIABLE":
            return "판단불가_검증대상아님"
        if "미확정" in (row.get("reviewer_note", "") + row.get("api_error", "")):
            return "판단불가_파라미터미확정"
        if "actual_change" in actual_reason or "증감률" in actual_reason or "포인트" in actual_reason:
            return "판단불가_증감계산값없음"
        return "판단불가_API조회실패"
    if claim_type in {"CHANGE_RATE", "POINT_CHANGE"}:
        return "재검토필요_증감률불일치"
    return "재검토필요_수준값불일치"


def main(input_path=DEFAULT_INPUT_PATH, output_path=DEFAULT_OUTPUT_PATH):
    input_path = Path(input_path)
    output_path = Path(output_path)
    summary_path = output_path.with_name(output_path.stem + "_summary.csv")
    sample_path = output_path.with_name(output_path.stem + "_review_samples.csv")

    with open(input_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for row in rows:
        text = row.get("claim_text", "")
        claim_type = normalize_claim_type(row.get("claim_type"), text)
        # 기존 판정이 LEVEL인데 문장상 변화 표현이 있으면 재분류한다.
        inferred_type = classify(text)
        if inferred_type != "LEVEL" and claim_type == "LEVEL" and not row.get("target_number"):
            claim_type = inferred_type

        claim_number, claim_reason = pick_claim_number(text, claim_type, row)
        actual_number, actual_reason = actual_for_claim(row, claim_type)
        verdict, diff, note = judge(claim_number, actual_number, claim_type)

        new_row = dict(row)
        new_row.update({
            "refined_claim_type": claim_type,
            "refined_claim_number": claim_number if claim_number is not None else "",
            "refined_claim_number_reason": claim_reason,
            "refined_actual_number": actual_number if actual_number is not None else "",
            "refined_actual_reason": actual_reason,
            "refined_verdict": verdict,
            "refined_diff": diff,
            "refined_judge_note": note,
            "refined_final_status": final_status(verdict, row, claim_type, actual_reason),
        })
        out_rows.append(new_row)

    fieldnames = list(out_rows[0].keys())
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    summary_rows = []
    for group, column in [
        ("refined_verdict", "refined_verdict"),
        ("refined_final_status", "refined_final_status"),
        ("refined_claim_type", "refined_claim_type"),
        ("tbl_id", "tbl_id"),
    ]:
        counter = Counter(row.get(column, "") for row in out_rows)
        for key, count in counter.most_common():
            summary_rows.append({"group": group, "key": key, "count": count})

    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["group", "key", "count"])
        writer.writeheader()
        writer.writerows(summary_rows)

    samples = []
    by_status = defaultdict(list)
    for row in out_rows:
        by_status[row["refined_final_status"]].append(row)
    for status, status_rows in by_status.items():
        samples.extend(status_rows[:10])

    sample_fields = [
        "claim_id", "claim_text", "tbl_id", "prd_se", "actual_period",
        "refined_claim_type", "refined_claim_number", "refined_claim_number_reason",
        "refined_actual_number", "refined_actual_reason", "refined_verdict",
        "refined_final_status", "refined_judge_note",
    ]
    with open(sample_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sample_fields)
        writer.writeheader()
        writer.writerows([{k: row.get(k, "") for k in sample_fields} for row in samples])

    print(f"완료 -> {output_path}")
    print("refined_verdict:", Counter(row["refined_verdict"] for row in out_rows))
    print("refined_final_status:", Counter(row["refined_final_status"] for row in out_rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="verify_claim.py 결과 CSV")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="후처리 결과 CSV")
    args = parser.parse_args()
    main(args.input, args.output)
