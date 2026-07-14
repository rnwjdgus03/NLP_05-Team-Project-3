"""
뉴스 주장과 KOSIS 실제값 비교 판정기 (담당: 팀원)

목표: claim(뉴스 주장)에서 뽑은 숫자와, 그 주장이 가리키는 KOSIS 실제 통계 값을 비교해서
"일치 / 불일치 / 판단불가"를 자동(또는 반자동)으로 판정한다.

입력 전제 (table_claim_mapping.csv 검토가 끝난 뒤 생기는 정보):
- claim_text, numbers(추출된 숫자 리스트), units(단위 리스트)
- 사람이 최종 확정한 candidate_kosis_table 하나 (orgId, tblId)
- 그 표에서 실제로 조회한 값(들) - kosis_api_test.get_stat_data()로 가져옴

사용 예:
  python verify_claim.py
  python verify_claim.py --input table_claim_mapping.csv --output verified_claims.csv

주의:
  table_claim_mapping.csv에 actual_number / actual_value / kosis_value 같은 실제값 컬럼이 있으면
  바로 판정한다. 아직 실제값 컬럼이 없으면 "판단불가"로 남기고 사유를 적는다.
"""

import argparse
import csv
import json
import re
import sys

# claim_text/후보 컬럼 등 일부 필드가 매우 길 수 있어(특히 obj_l1_candidates/
# itm_id_candidates), 기본 필드 크기 제한(131072바이트)을 넉넉하게 늘려둔다.
csv.field_size_limit(sys.maxsize)

# ------------------------------------------------------------------
# 1) claim 유형 분류
# ------------------------------------------------------------------
# 뉴스 주장은 크게 세 갈래로 나뉘는 걸로 보임 (table_claim_mapping.csv 실제 사례 기준):
#   - CHANGE_RATE : "OO이 X% 증가/감소/올랐다/줄었다" (전기 대비 증감률)
#   - LEVEL       : "OO은 X(원/명/%)이다" (특정 시점의 수준/절대값 그 자체)
#   - ABS_TO_ABS  : "9860원에서 1만30원으로" (이전 값 -> 이후 값, 둘 다 절대값으로 명시)
#
# TODO: 실제 table_claim_mapping.csv 사례를 더 보고 이 분류가 충분한지 점검.

CHANGE_KEYWORDS = re.compile(
    r"(증가|감소|줄었|늘었|올랐|내렸|상승|하락|급증|급감|"
    r"성장|뒷걸음질|둔화|위축|확대|축소|개선|악화|반등|신장|역성장)"
)
POINT_KEYWORDS = re.compile(r"(포인트|p\s*(?:상승|하락|올라|내려|증가|감소)|%p)")
NUMBER_RE = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
# 날짜/기간 표현에 붙는 숫자(예: "1월", "5~9일", "2023년", "3분기", "16개월")는
# 비교 대상 수치가 아니므로 claim_number 후보에서 제외한다.
# 범위 표현(예: "5∼9일", "1~3월")은 두 숫자 모두 제거하기 위해 범위 패턴을 먼저 처리한다.
DATE_RANGE_RE = re.compile(
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*[~∼\-]\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:년대?|월|일|주째|주|분기|개월|시|번째|차)"
)
DATE_SUFFIX_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:년대?|월|일|주째|주|분기|개월|시|번째|차)")

ACTUAL_VALUE_COLUMNS = (
    "actual_number",
    "actual_value",
    "kosis_value",
    "kosis_actual_value",
    "actual",
)
# CHANGE_RATE(%) / POINT_CHANGE(포인트, %p) 판정 시 우선적으로 사용할, 미리 계산된
# 전기 대비 증감 컬럼 (fetch_kosis_actual_values.py가 채워둠).
CHANGE_PCT_COLUMNS = ("actual_change_pct",)
CHANGE_POINT_COLUMNS = ("actual_change_point",)

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


def normalize_claim_type(value, claim_text="", numbers=None):
    """A팀/수동 라벨의 한국어 claim_type을 내부 판정 타입으로 변환."""
    text = str(value or "").strip()
    if text in CLAIM_TYPE_MAP:
        return CLAIM_TYPE_MAP[text]
    if text in ("LEVEL", "CHANGE_RATE", "POINT_CHANGE", "ABS_TO_ABS", "UNVERIFIABLE"):
        return text
    return classify_claim_type(claim_text, numbers or [])


def classify_claim_type(claim_text, numbers):
    """
    claim_text와 추출된 numbers 개수/패턴을 보고 claim 유형을 대충 분류.
    TODO: 좀 더 정교하게 다듬기 (지금은 1차 추정용 규칙 기반).
    """
    if len(numbers) >= 2 and re.search(r"(에서|→|->).*(으로|로)", claim_text):
        return "ABS_TO_ABS"
    if POINT_KEYWORDS.search(claim_text):
        return "POINT_CHANGE"
    if CHANGE_KEYWORDS.search(claim_text):
        return "CHANGE_RATE"
    return "LEVEL"


def extract_numbers(text):
    """
    문장에서 숫자만 1차 추출.
    예: "6838억달러, 8.2% 증가" -> [6838.0, 8.2]

    TODO: "1만30원", "1006조원"처럼 한국어 단위가 붙은 숫자는
    실제 검증 단계에서 단위 변환 규칙을 더 정교하게 붙여야 함.
    """
    if not text:
        return []
    numbers = []
    for match in NUMBER_RE.findall(str(text)):
        try:
            numbers.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return numbers


def parse_number(value):
    """CSV 셀에 들어 있는 숫자 문자열을 float로 변환."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = NUMBER_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def strip_date_numbers(text):
    """
    "1월", "5~9일", "2023년", "3분기", "16개월", "두번째" 등 날짜/기간 표현에
    붙은 숫자를 제거한 뒤 남는 숫자만 뽑는다. (claim_number가 날짜 조각을
    잘못 집는 걸 방지)
    """
    if not text:
        return []
    cleaned = DATE_RANGE_RE.sub(" ", str(text))
    cleaned = DATE_SUFFIX_RE.sub(" ", cleaned)
    out = []
    for match in NUMBER_RE.findall(cleaned):
        try:
            out.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return out


def pick_claim_number(row, numbers, claim_type):
    """
    주장에서 비교 대상 숫자 하나를 고른다.
    - CHANGE_RATE/POINT_CHANGE는 %  또는 포인트 표현이 핵심이므로 그 계열을 우선 사용.
    - LEVEL/ABS_TO_ABS는 날짜/기간 숫자(1월, 5~9일, 2023년 등)를 먼저 걸러내고 남는
      숫자 중에서 고른다 (예전엔 "1월 둘째주(5~9일)"에서 '5'나 '9'를 가격으로 착각하는
      문제가 있었음).

    TODO: 한 문장에 숫자가 여러 개 있을 때 어떤 숫자가 검증 대상인지 사람이 확정한
    claim_number 컬럼을 받는 방식이 가장 안전함.
    """
    for column in ("claim_number", "target_number", "number_to_verify"):
        picked = parse_number(row.get(column))
        if picked is not None:
            return picked

    text = str(row.get("claim_text", ""))

    if claim_type in ("CHANGE_RATE", "POINT_CHANGE"):
        # %p / 포인트 표현이 있으면 그 앞 숫자를 최우선으로 사용
        point_matches = re.findall(r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:%p|포인트|p\b)", text)
        if point_matches:
            return parse_number(point_matches[-1])
        percent_matches = re.findall(r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*%", text)
        if percent_matches:
            return parse_number(percent_matches[-1])

    # LEVEL / ABS_TO_ABS 등: 날짜/기간 조각 제거 후 남는 숫자 사용
    filtered = strip_date_numbers(text)
    if filtered:
        return filtered[0]

    return numbers[0] if numbers else None


# ------------------------------------------------------------------
# 2) 허용 오차(tolerance) 기준
# ------------------------------------------------------------------
# 뉴스 기사는 반올림/추정치를 쓰는 경우가 많아서, 100% 정확히 일치하지 않아도
# "사실상 맞는 주장"으로 볼 수 있는 오차 범위를 둬야 함.
#
# TODO: 실제 사례로 이 숫자들이 적절한지 검증하고 조정할 것.
TOLERANCE = {
    "CHANGE_RATE": 0.3,  # %p 단위 절대 오차 (예: 주장 6.4% vs 실제 6.1% -> 0.3%p 차이면 일치)
    "POINT_CHANGE": 0.3,  # CSI 등 포인트 변화 - 절대 오차 0.3포인트
    "LEVEL": 0.05,  # 상대 오차 5% (예: 주장 21% vs 실제 20.3% -> 5% 이내면 일치)
    "ABS_TO_ABS": 0.02,  # 절대 수치(금액 등)는 더 엄격하게 2% 이내
}


# ------------------------------------------------------------------
# 3) 실제 비교 로직
# ------------------------------------------------------------------
def judge(claim_number, actual_number, claim_type):
    """
    claim_number: 주장에서 뽑은 숫자 (예: 6.4)
    actual_number: KOSIS에서 실제로 계산/조회한 같은 성격의 숫자
    claim_type: classify_claim_type()의 결과

    반환: ("일치" | "불일치" | "판단불가", 차이값, 설명)
    """
    if actual_number is None:
        return "판단불가", None, "KOSIS 실제값을 못 가져옴 (표/시점/분류 코드 재확인 필요)"

    tol = TOLERANCE.get(claim_type, 0.05)

    if claim_type in ("CHANGE_RATE", "POINT_CHANGE"):
        diff = abs(claim_number - actual_number)  # %p/포인트 절대 차이
        ok = diff <= tol
    else:
        # 상대 오차로 비교 (0으로 나누기 방지)
        if actual_number == 0:
            return "판단불가", None, "실제값이 0이라 상대 오차 계산 불가"
        diff = abs(claim_number - actual_number) / abs(actual_number)
        ok = diff <= tol

    verdict = "일치" if ok else "불일치"
    note = f"claim={claim_number}, actual={actual_number}, 오차={diff:.3f} (허용={tol})"
    return verdict, diff, note


# ------------------------------------------------------------------
# 4) KOSIS 실제값 가져오기 / 일괄 판정
# ------------------------------------------------------------------
def calculate_change_rate(previous_value, current_value):
    """원자료 두 시점으로 증감률을 계산: (현재-이전)/이전*100."""
    if previous_value is None or current_value is None:
        return None
    if previous_value == 0:
        return None
    return (current_value - previous_value) / previous_value * 100


def get_actual_value(row, claim_type="LEVEL"):
    """
    실제 KOSIS 값을 가져온다. claim_type에 따라 어떤 컬럼을 볼지 우선순위가 다르다:
      - CHANGE_RATE(%) -> actual_change_pct (fetch_kosis_actual_values.py가 전기 대비
        증감률을 미리 계산해둔 값) 우선, 없으면 actual_value(수준값) 자체를 최후 수단으로 사용
      - POINT_CHANGE(포인트/%p, 예: CSI) -> actual_change_point 우선
      - LEVEL/ABS_TO_ABS -> actual_value(수준값) 그대로 사용

    1순위: 위 규칙에 맞는, 사람/스크립트가 미리 계산해둔 컬럼 사용
    2순위: org_id, tbl_id, obj_l1, itm_id 등이 있으면 kosis_api_test.get_stat_data() 직접 호출
           (이 경로는 단일 시점만 조회하므로 CHANGE_RATE/POINT_CHANGE는 정확히 계산 못 함 -
            증감이 필요한 claim은 fetch_kosis_actual_values.py로 미리 채워두는 걸 권장)

    TODO: objL2, objL3 같은 다중 분류축을 claim별로 정확히 넘기는 규칙 보강
    """
    preferred_columns = []
    if claim_type == "CHANGE_RATE":
        preferred_columns = list(CHANGE_PCT_COLUMNS)
    elif claim_type == "POINT_CHANGE":
        preferred_columns = list(CHANGE_POINT_COLUMNS)

    for column in preferred_columns:
        actual_number = parse_number(row.get(column))
        if actual_number is not None:
            return actual_number, f"{column} 컬럼 사용(전기대비 계산값)"

    for column in ACTUAL_VALUE_COLUMNS:
        actual_number = parse_number(row.get(column))
        if actual_number is not None:
            label = f"{column} 컬럼 사용"
            if claim_type in ("CHANGE_RATE", "POINT_CHANGE"):
                label += " (주의: 증감 계산값이 없어 수준값 자체와 비교 - 부정확할 수 있음)"
            return actual_number, label

    org_id = row.get("org_id") or row.get("ORG_ID")
    tbl_id = row.get("tbl_id") or row.get("TBL_ID")
    obj_l1 = row.get("obj_l1") or row.get("objL1")
    itm_id = row.get("itm_id") or row.get("itmId")
    prd_se = row.get("prd_se") or row.get("prdSe") or "Y"
    time_value = row.get("time") or row.get("year") or row.get("PRD_DE")

    if not all([org_id, tbl_id, obj_l1, itm_id]):
        return None, "실제값 컬럼이 없고 org_id/tbl_id/obj_l1/itm_id가 부족함"

    try:
        from kosis_api_test import get_stat_data
    except Exception as exc:
        return None, f"kosis_api_test import 실패: {exc}"

    extra = {}
    if time_value:
        extra["startPrdDe"] = str(time_value)
        extra["endPrdDe"] = str(time_value)
    for key in ("objL2", "objL3", "objL4", "objL5", "objL6", "objL7", "objL8"):
        value = row.get(key) or row.get(key.lower())
        if value:
            extra[key] = value

    try:
        rows = get_stat_data(
            org_id=org_id,
            tbl_id=tbl_id,
            obj_l1=obj_l1,
            itm_id=itm_id,
            prd_se=prd_se,
            new_est_prd_cnt=1,
            **extra,
        )
    except Exception as exc:
        return None, f"KOSIS 조회 실패: {exc}"

    if not rows:
        return None, "KOSIS 응답이 비어 있음"

    actual_number = parse_number(rows[0].get("DT"))
    if actual_number is None:
        return None, "KOSIS 응답에 숫자 DT 값이 없음"
    return actual_number, "KOSIS API 조회값 사용"


def parse_numbers_cell(row):
    """numbers 컬럼이 있으면 우선 쓰고, 없으면 claim_text에서 숫자 추출."""
    raw_numbers = row.get("numbers")
    if raw_numbers:
        try:
            parsed = json.loads(raw_numbers)
            if isinstance(parsed, list):
                return [parse_number(x) for x in parsed if parse_number(x) is not None]
        except Exception:
            pass
        return extract_numbers(raw_numbers)
    return extract_numbers(row.get("claim_text", ""))


def verify_row(row):
    """CSV 한 줄을 판정 결과가 붙은 dict로 변환."""
    claim_text = row.get("claim_text", "")
    numbers = parse_numbers_cell(row)
    claim_type = normalize_claim_type(row.get("claim_type"), claim_text, numbers)
    claim_number = pick_claim_number(row, numbers, claim_type)
    actual_number, actual_source = get_actual_value(row, claim_type)

    if str(row.get("verifiable", "")).strip().lower() == "false" or claim_type == "UNVERIFIABLE":
        verdict, diff, note = "판단불가", None, "KOSIS 직접 검증 대상 아님(verifiable=False 또는 비검증 claim_type)"
    elif claim_number is None:
        verdict, diff, note = "판단불가", None, "claim에서 비교할 숫자를 고르지 못함"
    else:
        verdict, diff, note = judge(claim_number, actual_number, claim_type)

    result = dict(row)
    result.update({
        "claim_type": claim_type,
        "claim_number": claim_number,
        "actual_number": actual_number,
        "actual_source": actual_source,
        "verdict": verdict,
        "diff": diff,
        "judge_note": note,
    })
    return result


def verify_file(input_path, output_path):
    """table_claim_mapping.csv를 읽어 verified_claims.csv를 만든다."""
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise RuntimeError(f"{input_path}에 데이터가 없음")

    verified_rows = [verify_row(row) for row in rows]
    fieldnames = list(rows[0].keys())
    for column in (
        "claim_type",
        "claim_number",
        "actual_number",
        "actual_source",
        "verdict",
        "diff",
        "judge_note",
    ):
        if column not in fieldnames:
            fieldnames.append(column)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(verified_rows)

    counts = {}
    for row in verified_rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return counts


def run_examples():
    # 간단한 예시 (실행 확인용) - 실제 데이터 연결 전 로직 자체만 테스트
    examples = [
        ("최저임금이 1.7% 인상된다", [1.7], "CHANGE_RATE", 1.7, 1.72),
        ("소비자물가가 2.2% 올랐다", [2.2], "CHANGE_RATE", 2.2, 1.8),
        ("청년 고용률 49개월 만에 최대 낙폭", [], "LEVEL", 42.5, 42.3),
    ]
    for text, nums, ctype, claim_val, actual_val in examples:
        verdict, diff, note = judge(claim_val, actual_val, ctype)
        print(f"[{ctype}] {text}\n  -> {verdict} | {note}\n")


def main():
    parser = argparse.ArgumentParser(description="뉴스 claim 숫자와 KOSIS 실제값 비교 판정")
    parser.add_argument("--input", default="table_claim_mapping.csv", help="입력 CSV")
    parser.add_argument("--output", default="verified_claims.csv", help="출력 CSV")
    parser.add_argument("--examples", action="store_true", help="간단 예시만 실행")
    args = parser.parse_args()

    if args.examples:
        run_examples()
        return

    try:
        counts = verify_file(args.input, args.output)
    except FileNotFoundError:
        print(f"{args.input} 파일이 없어서 예시만 실행합니다.\n")
        run_examples()
        return

    print(f"완료 -> {args.output}")
    for verdict, count in counts.items():
        print(f"{verdict}: {count}건")


if __name__ == "__main__":
    main()
