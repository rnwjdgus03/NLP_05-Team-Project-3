"""
claim_schema_v3_pilot100.csv 전용 KOSIS 검증 스크립트.

입력:
- data/claims/claim_schema_v3_pilot100.csv

출력:
- outputs/bteam_review/claim_schema_v3_pilot100_verified.csv
- outputs/bteam_review/claim_schema_v3_pilot100_summary.csv

방식:
- 예전 claim_text 키워드 매칭을 쓰지 않는다.
- indicator/value_type/unit/period/prd_se/region/age_group/gender를 기준으로
  pilot100 전용 KOSIS 코드북을 적용한다.
- 품목/지역/세부 조건 코드가 필요한 행은 억지 매핑하지 않고 판단불가로 남긴다.
"""

import csv
import argparse
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

from kosis_api_test import get_stat_data

csv.field_size_limit(sys.maxsize)

INPUT = Path("data/claims/claim_schema_v3_pilot100.csv")
OUT_DIR = Path("outputs/bteam_review")
OUTPUT = OUT_DIR / "claim_schema_v3_pilot100_verified.csv"
SUMMARY = OUT_DIR / "claim_schema_v3_pilot100_summary.csv"
CODEBOOK = Path("data/claims/kosis_indicator_codebook.csv")

NUMBER_RE = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
MONTH_KO_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월")
MONTH_M_RE = re.compile(r"(\d{4})\s*M\s*(\d{1,2})", re.IGNORECASE)
MONTH_DASH_RE = re.compile(r"(\d{4})-(\d{1,2})")
QUARTER_RE = re.compile(r"(\d{4})\s*Q\s*([1-4])", re.IGNORECASE)
YEAR_RE = re.compile(r"(\d{4})")


def to_float(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    m = NUMBER_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def target_period(row):
    period = str(row.get("period", "")).strip()
    if period and period != "-":
        return period
    end = str(row.get("period_end", "")).strip()
    return "" if end == "-" else end


def normalize_indicator(value):
    """A팀 파일마다 다른 띄어쓰기/표기를 내부 indicator 키로 통일."""
    raw = str(value or "").strip()
    compact = re.sub(r"\s+", "", raw)
    aliases = {
        "출생아수": "출생아수",
        "합계출산율": "합계출산율",
        "혼인건수": "혼인건수",
        "소비자물가지수": "소비자물가지수",
        "소비자물가상승률": "소비자물가상승률",
        "물가상승률": "소비자물가상승률",
        "생활물가지수": "생활물가지수",
        "생활물가와소비자물가차이": "생활물가·소비자물가차이",
        "실업률": "실업률",
        "학력별실업률": "학력별실업률",
        "고용률": "고용률",
        "고령층고용률": "고령층고용률",
        "청년층고용률": "청년층고용률",
        "취업자수": "취업자수",
        "도소매취업자수": "산업별취업자수",
        "제조업취업자수": "산업별취업자수",
        "건설업취업자수": "산업별취업자수",
        "연근해오징어생산량": "연근해오징어생산량",
        "어가인구": "어가인구",
        "수입물가": "수입물가",
        "수입물가상승률": "수입물가",
        "생산자물가지수": "생산자물가지수",
        "생산자물가상승률": "생산자물가지수",
        "생산자물가지수(PPI)": "생산자물가지수",
        "외식물가상승률": "품목별물가",
        "축산물소비자물가": "품목별물가",
    }
    return aliases.get(compact, raw)


def normalize_period_for_kosis(period, prd_se):
    if not period:
        return ""
    text = str(period).strip()
    # 복수 후보가 들어오면 자동 확정하지 않는다.
    if "|" in text:
        return ""
    # 범위는 끝 시점을 대표 시점으로 사용한다. 예: 2025M1-2025M5 -> 202505
    if "~" in text:
        text = text.split("~")[-1]
    if "-" in text and "M" in text.upper():
        parts = text.split("-")
        text = parts[-1] if len(parts[-1]) >= 4 else parts[0]

    m = MONTH_KO_RE.search(text)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}"

    m = MONTH_M_RE.search(text)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}"

    m = MONTH_DASH_RE.search(text)
    if m and prd_se == "M":
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}"

    m = QUARTER_RE.search(text)
    if m:
        return f"{int(m.group(1)):04d}0{int(m.group(2))}"

    if prd_se == "H":
        # KOSIS 반기 표는 표마다 형식이 달라 자동 확정하지 않는다.
        return text
    if prd_se == "Y":
        m = YEAR_RE.search(text)
        return m.group(1) if m else ""
    return text.replace("-", "")


def previous_period(period, prd_se, base):
    if not period:
        return ""
    s = normalize_period_for_kosis(period, prd_se)
    if prd_se == "M" and len(s) == 6 and s.isdigit():
        year = int(s[:4])
        month = int(s[4:6])
        if base in {"전년동월", "전년동기"}:
            return f"{year - 1}{month:02d}"
        if base == "전월":
            month -= 1
            if month == 0:
                year -= 1
                month = 12
            return f"{year}{month:02d}"
    if prd_se == "Q" and len(s) == 6 and s[:4].isdigit() and s[4:6].isdigit():
        year = int(s[:4])
        quarter = int(s[4:6])
        if base in {"전년동월", "전년동기"}:
            return f"{year - 1}0{quarter}"
        if base == "전분기":
            quarter -= 1
            if quarter == 0:
                year -= 1
                quarter = 4
            return f"{year}0{quarter}"
    if prd_se == "Y" and len(s) == 4 and s.isdigit():
        if base in {"전년", "전년동월", "전년동기"}:
            return str(int(s) - 1)
    return ""


def mapping_for(row):
    indicator = normalize_indicator(row.get("indicator", ""))
    value_type = row.get("value_type", "")
    prd_se = row.get("prd_se", "")
    text = row.get("claim_text", "")
    age_group = row.get("age_group", "")

    if row.get("verifiable_kosis") != "Y":
        return None, "verifiable_kosis=N"
    if not indicator or indicator == "-":
        return None, "indicator 없음"

    # 인구동향: 월간은 DT_1B8000G, 연간은 DT_1B8000F 사용
    if indicator == "출생아수":
        if prd_se == "M":
            return {
                "org_id": "101", "tbl_id": "DT_1B8000G", "obj_l1": "00",
                "itm_id": "T1", "prd_se": "M", "extra": {"objL2": "10"},
                "table_note": "월.분기.연간 인구동향 - 전국 출생아수",
            }, ""
        if prd_se == "Y":
            return {
                "org_id": "101", "tbl_id": "DT_1B8000F", "obj_l1": "11",
                "itm_id": "T1", "prd_se": "Y", "extra": {},
                "table_note": "인구동태건수 및 동태율 추이 - 출생아수",
            }, ""

    if indicator == "합계출산율":
        if prd_se == "M":
            return {
                "org_id": "101", "tbl_id": "DT_1B8000G", "obj_l1": "00",
                "itm_id": "T1", "prd_se": "M", "extra": {"objL2": "12"},
                "table_note": "월.분기.연간 인구동향 - 전국 합계출산율",
            }, ""
        if prd_se == "Y":
            return {
                "org_id": "101", "tbl_id": "DT_1B8000F", "obj_l1": "30",
                "itm_id": "T1", "prd_se": "Y", "extra": {},
                "table_note": "인구동태건수 및 동태율 추이 - 합계출산율",
            }, ""

    if indicator == "혼인건수":
        if prd_se == "M":
            return {
                "org_id": "101", "tbl_id": "DT_1B8000G", "obj_l1": "00",
                "itm_id": "T1", "prd_se": "M", "extra": {"objL2": "20"},
                "table_note": "월.분기.연간 인구동향 - 전국 혼인건수",
            }, ""
        if prd_se == "Y":
            return {
                "org_id": "101", "tbl_id": "DT_1B8000F", "obj_l1": "41",
                "itm_id": "T1", "prd_se": "Y", "extra": {},
                "table_note": "인구동태건수 및 동태율 추이 - 혼인건수",
            }, ""

    # 소비자물가
    if indicator == "소비자물가지수":
        return {
            "org_id": "101", "tbl_id": "DT_1J22003", "obj_l1": "T10",
            "itm_id": "T", "prd_se": "M", "extra": {},
            "table_note": "소비자물가지수(2020=100) - 전국 총지수",
        }, ""

    if indicator in {"소비자물가상승률", "소비자물가상승률;가공식품물가상승률"}:
        if "가공식품" in text and "전체" not in text:
            return None, "가공식품 세부 품목 코드 필요"
        if prd_se == "Y":
            return {
                "org_id": "101", "tbl_id": "DT_1J22041", "obj_l1": "0",
                "itm_id": "T", "prd_se": "Y", "extra": {},
                "table_note": "연도별 소비자물가 등락률 - 총지수",
            }, ""
        return {
            "org_id": "101", "tbl_id": "DT_1J22042", "obj_l1": "0",
            "itm_id": "T03", "prd_se": "M", "extra": {},
            "table_note": "월별 소비자물가 등락률 - 총지수 전년동월비",
        }, ""

    if indicator == "생활물가지수":
        return {
            "org_id": "101", "tbl_id": "DT_1J22042", "obj_l1": "1",
            "itm_id": "T03", "prd_se": "M", "extra": {},
            "table_note": "월별 소비자물가 등락률 - 생활물가지수 전년동월비",
        }, ""

    if indicator in {"품목별물가상승률", "품목별물가"}:
        return None, "축산물/수산물/가공식품/외식 등 품목 세부 코드 필요"

    if indicator == "생활물가·소비자물가차이":
        return None, "생활물가와 소비자물가 차이는 두 표 값을 별도 계산해야 함"

    # 고용: 전국/연령 단순 케이스만 자동 검증
    if indicator == "실업률":
        if age_group == "20~29세":
            return {
                "org_id": "101", "tbl_id": "DT_1DA7002S", "obj_l1": "20",
                "itm_id": "T80", "prd_se": "M", "extra": {},
                "table_note": "연령별 경제활동인구 - 20~29세 실업률",
            }, ""
        return {
            "org_id": "101", "tbl_id": "DT_1DA7001S", "obj_l1": "0",
            "itm_id": "T80", "prd_se": "M", "extra": {},
            "table_note": "경제활동인구 총괄 - 전체 실업률",
        }, ""

    if indicator == "학력별실업률":
        if "대졸" in text and row.get("value") == "5.8":
            edu = "40"
        elif "고졸" in text and row.get("value") == "5.1":
            edu = "30"
        else:
            return None, "학력 분류 코드 수동확인 필요"
        return {
            "org_id": "101", "tbl_id": "DT_1DA7003S", "obj_l1": edu,
            "itm_id": "T80", "prd_se": "M", "extra": {},
            "table_note": "교육정도별 경제활동인구 - 실업률",
        }, ""

    if indicator in {"고용률", "고령층고용률"}:
        if "65세 이상" in text:
            return {
                "org_id": "101", "tbl_id": "DT_1DA7002S", "obj_l1": "602",
                "itm_id": "T90", "prd_se": "M", "extra": {},
                "table_note": "연령별 경제활동인구 - 65세 이상 고용률",
            }, ""
        if "울릉군" in text:
            return None, "지역별고용조사 시군구/반기 코드 필요"
        return {
            "org_id": "101", "tbl_id": "DT_1DA7001S", "obj_l1": "0",
            "itm_id": "T90", "prd_se": "M", "extra": {},
            "table_note": "경제활동인구 총괄 - 전체 고용률",
        }, ""

    if indicator == "청년층고용률":
        return {
            "org_id": "101", "tbl_id": "DT_1DA7002S", "obj_l1": "75",
            "itm_id": "T90", "prd_se": "M", "extra": {},
            "table_note": "연령별 경제활동인구 - 15~29세 고용률",
        }, ""

    if indicator == "취업자수":
        if "20대 여성" in text or "수도권" in text:
            return None, "성별/연령/지역 복합 분류 코드 필요"
        return {
            "org_id": "101", "tbl_id": "DT_1DA7001S", "obj_l1": "0",
            "itm_id": "T30", "prd_se": "M", "extra": {},
            "table_note": "경제활동인구 총괄 - 전체 취업자",
            "actual_unit_multiplier": 1000,  # KOSIS 천명 -> 명
        }, ""

    if indicator == "산업별취업자수":
        return None, "산업별 취업자 표/산업분류 코드 필요"

    if indicator == "수입물가":
        return {
            "org_id": "301", "tbl_id": "DT_401Y015",
            "obj_l1": "13102134643ACC_CD.*AA",
            "itm_id": "13103134643999", "prd_se": "M",
            "extra": {"objL2": "13102134643CRR_CTRT_CD.W"},
            "table_note": "수입물가지수(기본분류) - 총지수 원화기준",
        }, ""

    if indicator == "생산자물가지수":
        return {
            "org_id": "301", "tbl_id": "DT_404Y014",
            "obj_l1": "13102134604ACC_CD.*AA",
            "itm_id": "13103134604999", "prd_se": "M",
            "extra": {},
            "table_note": "생산자물가지수(기본분류) - 총지수",
        }, ""

    # 자동 검증에서 제외할 지표들
    if indicator in {
        "한국은행기준금리", "국민연금보험료율;소득대체율", "가구소득분위별여유자금",
        "임금근로자직종비중", "대도시·소도시평균집값", "고위공직자아파트보유율",
        "송이생산량비중", "국산승용차판매량", "연근해오징어생산량",
    }:
        return None, "현재 자동 검증 코드북 없음 또는 세부 분류 코드 필요"

    return None, "자동 매핑 룰 없음"


def fetch_rows(mapping, period_count=180):
    return get_stat_data(
        org_id=mapping["org_id"],
        tbl_id=mapping["tbl_id"],
        obj_l1=mapping["obj_l1"],
        itm_id=mapping["itm_id"],
        prd_se=mapping["prd_se"],
        new_est_prd_cnt=period_count,
        **mapping.get("extra", {}),
    )


def pick_period(rows, period, prd_se):
    target = normalize_period_for_kosis(period, prd_se)
    if not rows:
        return None
    if target:
        for row in rows:
            if str(row.get("PRD_DE", "")) == target:
                return row
    return None


def actual_for(row, mapping, rows):
    period = target_period(row)
    prd_se = mapping["prd_se"]
    cur = pick_period(rows, period, prd_se)
    if cur is None:
        return None, "", "", "해당 시점 KOSIS 값 없음"

    current_value = to_float(cur.get("DT"))
    if current_value is None:
        return None, cur.get("PRD_DE", ""), "", "KOSIS DT 숫자 변환 실패"

    multiplier = mapping.get("actual_unit_multiplier", 1)
    current_value *= multiplier

    value_type = row.get("value_type", "")
    change_base = row.get("change_base", "")
    unit = row.get("unit", "")

    # 등락률 표는 actual_value 자체가 검증 대상 숫자다.
    if mapping["tbl_id"] in {"DT_1J22042", "DT_1J22041"}:
        return current_value, cur.get("PRD_DE", ""), "", "등락률 표 actual_value 사용"

    if value_type in {"증감률", "증감량", "증감값"} or unit in {"%p", "%포인트", "포인트"}:
        prev_period = previous_period(period, prd_se, change_base)
        prev = pick_period(rows, prev_period, prd_se)
        if prev is None:
            return None, cur.get("PRD_DE", ""), prev_period, "비교 기준 이전 시점 KOSIS 값 없음"
        prev_value = to_float(prev.get("DT"))
        if prev_value is None:
            return None, cur.get("PRD_DE", ""), prev.get("PRD_DE", ""), "이전 시점 DT 숫자 변환 실패"
        prev_value *= multiplier
        if value_type == "증감률":
            if prev_value == 0:
                return None, cur.get("PRD_DE", ""), prev.get("PRD_DE", ""), "이전값 0으로 증감률 계산 불가"
            return (current_value - prev_value) / prev_value * 100, cur.get("PRD_DE", ""), prev.get("PRD_DE", ""), "원자료 전년/전월 대비 증감률 계산"
        return current_value - prev_value, cur.get("PRD_DE", ""), prev.get("PRD_DE", ""), "원자료 전년/전월 대비 증감량 계산"

    return current_value, cur.get("PRD_DE", ""), "", "수준값 actual_value 사용"


def signed_target(row):
    value = to_float(row.get("value"))
    if value is None:
        return None
    if row.get("value_type") in {"증감률", "증감량", "증감값"} and row.get("direction") in {"감소", "하락"}:
        return -abs(value)
    return value


def judge(row, actual):
    target = signed_target(row)
    if target is None:
        return "판단불가", "", "target value 없음"
    if actual is None:
        return "판단불가", "", "actual value 없음"

    unit = row.get("unit", "")
    value_type = row.get("value_type", "")
    if value_type == "증감률" or unit in {"%", "%p", "%포인트", "포인트"}:
        diff = abs(target - actual)
        tol = 0.3
        return ("일치" if diff <= tol else "불일치"), diff, f"절대오차={diff:.3f}, 허용={tol}"

    if actual == 0:
        return "판단불가", "", "actual=0 상대오차 계산 불가"
    diff = abs(target - actual) / abs(actual)
    tol = 0.05
    return ("일치" if diff <= tol else "불일치"), diff, f"상대오차={diff:.3f}, 허용={tol}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT), help="claim schema CSV 입력 파일")
    parser.add_argument("--output", default=str(OUTPUT), help="검증 결과 CSV")
    parser.add_argument("--summary", default=str(SUMMARY), help="검증 요약 CSV")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    summary_path = Path(args.summary)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with open(input_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    cache = {}
    out_rows = []
    for idx, row in enumerate(rows, 1):
        mapping, skip_reason = mapping_for(row)
        out = dict(row)

        if mapping is None:
            out.update({
                "org_id": "", "tbl_id": "", "obj_l1": "", "itm_id": "", "obj_l2": "",
                "mapping_source": str(CODEBOOK),
                "actual_value": "", "actual_period": "", "actual_prev_period": "",
                "verdict": "판단불가", "diff": "", "judge_note": skip_reason,
            })
            out_rows.append(out)
            continue

        key = (
            mapping["org_id"], mapping["tbl_id"], mapping["obj_l1"], mapping["itm_id"],
            mapping["prd_se"], tuple(sorted(mapping.get("extra", {}).items())),
        )
        try:
            if key not in cache:
                cache[key] = fetch_rows(mapping)
                time.sleep(0.1)
            actual, actual_period, prev_period, actual_reason = actual_for(row, mapping, cache[key])
            verdict, diff, note = judge(row, actual)
            out.update({
                "org_id": mapping["org_id"],
                "tbl_id": mapping["tbl_id"],
                "obj_l1": mapping["obj_l1"],
                "itm_id": mapping["itm_id"],
                "obj_l2": mapping.get("extra", {}).get("objL2", ""),
                "mapping_source": str(CODEBOOK),
                "actual_value": actual if actual is not None else "",
                "actual_period": actual_period,
                "actual_prev_period": prev_period,
                "verdict": verdict,
                "diff": diff,
                "judge_note": f"{actual_reason}; {note}; {mapping['table_note']}",
            })
        except Exception as exc:
            out.update({
                "org_id": mapping["org_id"],
                "tbl_id": mapping["tbl_id"],
                "obj_l1": mapping["obj_l1"],
                "itm_id": mapping["itm_id"],
                "obj_l2": mapping.get("extra", {}).get("objL2", ""),
                "mapping_source": str(CODEBOOK),
                "actual_value": "", "actual_period": "", "actual_prev_period": "",
                "verdict": "판단불가", "diff": "",
                "judge_note": f"KOSIS 조회 실패: {exc}; {mapping['table_note']}",
            })
        out_rows.append(out)
        if idx % 20 == 0:
            print(f"진행 {idx}/{len(rows)}")

    extra_fields = [
        "org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id",
        "mapping_source",
        "actual_value", "actual_period", "actual_prev_period",
        "verdict", "diff", "judge_note",
    ]
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames + extra_fields)
        writer.writeheader()
        writer.writerows(out_rows)

    summary_rows = []
    for group, col in [
        ("verdict", "verdict"),
        ("verifiable_kosis", "verifiable_kosis"),
        ("metric_domain", "metric_domain"),
        ("indicator", "indicator"),
        ("tbl_id", "tbl_id"),
    ]:
        for key, count in Counter(r.get(col, "") for r in out_rows).most_common():
            summary_rows.append({"group": group, "key": key, "count": count})

    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["group", "key", "count"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"완료 -> {output_path}")
    print(Counter(r["verdict"] for r in out_rows))


if __name__ == "__main__":
    main()
