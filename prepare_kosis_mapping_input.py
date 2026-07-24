"""Prepare measurement-level HCX output for KOSIS candidate matching.

The handoff contract is deliberately stricter than ``is_claim=True``.  Only a
measurement that already has a grounded value, semantic binding, and period is
allowed into table discovery.  Rejected rows are retained with stable reason
codes so a real ``UNVERIFIABLE`` result is distinguishable from bad input.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path


EMPTY = {"", "-", "nan", "none", "null"}
SKIP_ROLES = {"목표값"}
KOSIS_LIKE_DOMAINS = {
    "무역", "고용", "물가", "인구", "생산·산업", "교통", "소득·임금", "경제일반",
}
KOSIS_LIKE_INDICATOR_TOKENS = (
    "수출", "수입", "무역수지", "고용률", "실업률", "취업자", "근로자", "인구",
    "소비자물가", "물가", "생산지수", "소매판매", "여객", "이용객", "정비사",
    "사업체", "기업 수", "로봇 밀도", "로봇 보급률", "출생", "혼인", "이혼",
)
NON_OBSERVED_TOKENS = (
    "정책", "제도", "지원", "지원금", "급여", "장려금", "장학금", "봉급", "최저임금",
    "요건", "기준", "검진", "대상 연령", "양육비", "세율", "공제", "보험료",
    "참가", "통합한국관", "개별기업",
)
EXTERNAL_SOURCE_TOKENS = (
    "국제로봇연맹", "IFR", "WTO", "시리움", "Cirium", "전세계", "세계에서", "세계수출순위",
)


def nz(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in EMPTY else text


def parse_number(value):
    text = nz(value).replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def parse_article_date(row: dict):
    text = nz(row.get("date")) or nz(row.get("article_date"))
    match = re.search(r"((?:19|20)\d{2})\D?(0[1-9]|1[0-2])?\D?(0[1-9]|[12]\d|3[01])?", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    return year, month


def previous_month(year: int, month: int):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def infer_period_from_context(row: dict) -> tuple[str, str, str]:
    """Infer a missing measurement period only when the text gives a clear cue."""
    text = " ".join(nz(row.get(k)) for k in ("measurement_text", "claim_text", "prev_sentence", "next_sentence"))
    ctext = compact_text(text)

    month_match = re.search(r"((?:19|20)\d{2})\s*년\s*(0?[1-9]|1[0-2])\s*월", text)
    if month_match:
        return f"{month_match.group(1)}{int(month_match.group(2)):02d}", "M", "명시 연월에서 measurement_period 보정"

    quarter_match = re.search(r"((?:19|20)\d{2})\s*년\s*([1-4])\s*분기", text)
    if quarter_match:
        return f"{quarter_match.group(1)}Q{quarter_match.group(2)}", "Q", "명시 분기에서 measurement_period 보정"

    half_match = re.search(r"((?:19|20)\d{2})\s*년\s*(상반기|하반기)", text)
    if half_match:
        half = "H1" if half_match.group(2) == "상반기" else "H2"
        return f"{half_match.group(1)}{half}", "H", "명시 반기에서 measurement_period 보정"

    year_end_match = re.search(r"((?:19|20)\d{2})\s*년\s*말", text)
    if year_end_match:
        return year_end_match.group(1), "Y", "명시 연말 표현에서 연간 measurement_period 보정"

    year_match = re.search(r"((?:19|20)\d{2})\s*년", text)
    if year_match:
        return year_match.group(1), "Y", "명시 연도에서 measurement_period 보정"

    article_date = parse_article_date(row)
    if not article_date:
        return "", "", ""
    year, month = article_date

    relative_month = re.search(r"(?:지난|작년|올해)\s*(0?[1-9]|1[0-2])\s*월", text)
    if relative_month:
        rel_month = int(relative_month.group(1))
        rel_year = year - 1 if "작년" in ctext else year
        return f"{rel_year}{rel_month:02d}", "M", "기사 날짜 기준 상대 월 보정"

    quarter_only = re.search(r"([1-4])\s*분기", text)
    if quarter_only and ("올해" in ctext or "금년" in ctext or "지난" in ctext or "작년" in ctext):
        rel_year = year - 1 if ("작년" in ctext or "지난해" in ctext) else year
        return f"{rel_year}Q{quarter_only.group(1)}", "Q", "기사 날짜 기준 상대 분기 보정"

    if "지난달" in ctext or "전월" in ctext:
        py, pm = previous_month(year, month)
        return f"{py}{pm:02d}", "M", "기사 날짜 기준 지난달/전월 보정"
    if "지난해말" in ctext or "작년말" in ctext:
        return str(year - 1), "Y", "기사 날짜 기준 지난해 말/작년 말 보정"
    if "지난해" in ctext or "작년" in ctext or "전년" in ctext:
        return str(year - 1), "Y", "기사 날짜 기준 지난해/작년/전년 보정"
    if "올해" in ctext or "금년" in ctext or "올해들어" in ctext:
        return str(year), "Y", "기사 날짜 기준 올해/금년 보정"
    return "", "", ""


def is_policy_or_condition_text(row: dict) -> bool:
    text = compact_text(" ".join(nz(row.get(k)) for k in (
        "metric_domain", "indicator", "measurement_indicator", "measurement_item", "claim_text", "measurement_text"
    )))
    return any(compact_text(token) in text for token in NON_OBSERVED_TOKENS)


def has_external_source_context(row: dict) -> bool:
    text = compact_text(nz(row.get("claim_text")))
    return any(compact_text(token) in text for token in EXTERNAL_SOURCE_TOKENS)


def indicator_value_context_conflict(row: dict) -> bool:
    indicator = compact_text(nz(row.get("measurement_indicator")) or nz(row.get("indicator")))
    if not any(token in indicator for token in ("수출액", "수입액")):
        return False
    measurement = nz(row.get("measurement_text"))
    text = nz(row.get("claim_text"))
    if not measurement or not text:
        return False
    idx = text.find(measurement)
    window = text[idx: idx + len(measurement) + 12] if idx >= 0 else text
    return any(token in compact_text(window) for token in ("적자", "흑자"))


def looks_kosis_observed_stat(row: dict, dimension: str, semantic: str) -> bool:
    if semantic in {"rank", "condition", "multiple"}:
        return False
    if is_policy_or_condition_text(row):
        return False
    domain = nz(row.get("metric_domain"))
    scope = nz(row.get("claim_domain_scope"))
    text = compact_text(" ".join(nz(row.get(k)) for k in (
        "metric_domain", "indicator", "measurement_indicator", "measurement_item", "claim_text"
    )))
    if scope == "개별기업":
        return False
    if scope not in {"", "국내공식통계"} and has_external_source_context(row):
        return False
    if scope not in {"", "국내공식통계"} and domain != "무역":
        return False
    domain_hit = any(token in domain for token in KOSIS_LIKE_DOMAINS)
    indicator_hit = any(compact_text(token) in text for token in KOSIS_LIKE_INDICATOR_TOKENS)
    return (domain_hit or indicator_hit) and dimension in {"currency", "person_count", "count", "rate", "quantity"}


def canonicalize_unit(unit: str) -> str:
    raw = re.sub(r"\s+", "", nz(unit)).replace("％", "%")
    aliases = {
        "퍼센트": "%",
        "프로": "%",
        "퍼센트포인트": "%p",
        "%포인트": "%p",
        "퍼센트p": "%p",
        "불": "달러",
        "미달러": "달러",
        "미화달러": "달러",
        "개사": "개",
        "사": "개",
        "곳": "개",
        "인": "명",
        "사람": "명",
    }
    return aliases.get(raw, raw)


def unit_dimension(unit: str) -> str:
    value = canonicalize_unit(unit)
    if not value:
        return "unknown"
    if value in {"%", "%p"}:
        return "rate"
    if any(token in value for token in ("원", "달러", "엔", "유로")):
        return "currency"
    if value in {"명", "천명", "만명", "백만명"}:
        return "person_count"
    if value in {"개", "대", "건", "가구", "세대"}:
        return "count"
    if value in {"세", "살"}:
        return "age"
    if value in {"년", "개월", "월", "주", "일", "시간", "분", "초"}:
        return "duration"
    if value in {"배", "배수"}:
        return "multiple"
    if any(token in value for token in ("톤", "kg", "킬로그램", "ha", "헥타르")):
        return "quantity"
    if value in {"위"}:
        return "rank"
    return "unknown"


def semantic_type(row: dict, dimension: str) -> str:
    value_type = nz(row.get("value_type"))
    role = nz(row.get("measurement_role"))
    indicator = nz(row.get("measurement_indicator")) or nz(row.get("indicator"))
    compact = re.sub(r"\s+", "", indicator)

    if value_type == "순위" or dimension == "rank":
        return "rank"
    if value_type == "증감률" or role == "증감률" or any(
        token in compact for token in ("증감률", "증가율", "감소율", "상승률", "하락률")
    ):
        return "rate_change"
    if value_type in {"비율", "구성비"} or any(
        token in compact for token in ("비율", "구성비", "점유율")
    ):
        return "rate_level"
    if value_type == "증감량":
        return "absolute_change"
    if dimension == "currency":
        return "amount"
    if dimension in {"person_count", "count"}:
        return "count"
    if dimension == "multiple":
        return "multiple"
    if dimension in {"age", "duration"}:
        return "condition"
    return "level"


def entity_type(row: dict) -> str:
    indicator = nz(row.get("measurement_indicator"))
    text = " ".join(nz(row.get(key)) for key in ("measurement_item", "claim_text"))
    if any(token in indicator for token in ("정비사", "근로자", "취업자", "인구", "사람", "여객", "이용객")):
        return "person"
    if any(token in indicator for token in ("항공사", "기업", "업체", "회사")):
        return "organization"
    if any(token in text for token in ("가구", "세대")):
        return "household"
    if any(token in text for token in ("자동차", "차량", "선박", "항공기")):
        return "vehicle"
    if nz(row.get("measurement_item")):
        return "item"
    return "unspecified"


def comparison_period(row: dict, semantic: str) -> str:
    if semantic not in {"rate_change", "absolute_change"}:
        return ""
    target = nz(row.get("measurement_period"))
    target_match = re.search(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])?", target)
    target_value = target_match.group() if target_match else ""
    text = nz(row.get("claim_text"))

    explicit_patterns = [
        r"((?:19|20)\d{2})\s*년\s*(?:보다|대비|에\s*비해|과\s*비교)",
        r"(?:기준|비교)\s*(?:시점|연도)?\s*((?:19|20)\d{2})\s*년",
    ]
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1)
            if value != target_value:
                return value

    base = nz(row.get("change_base"))
    if target_value and "전년" in base:
        if len(target_value) == 6:
            return str(int(target_value[:4]) - 1) + target_value[4:]
        return str(int(target_value[:4]) - 1)
    if len(target_value) == 6 and "전월" in base:
        year, month = int(target_value[:4]), int(target_value[4:])
        if month == 1:
            return f"{year - 1}12"
        return f"{year}{month - 1:02d}"
    return ""


def reference_relation_confirmed(row: dict) -> bool:
    if not nz(row.get("measurement_period")):
        return False
    text = re.sub(r"\s+", "", " ".join(nz(row.get(k)) for k in ("claim_text", "measurement_text")))
    return any(token in text for token in ("이후", "보다", "대비", "비교", "기준", "최대", "최저", "종전", "기존"))


def exclusion(row: dict, dimension: str, semantic: str):
    measurement_id = nz(row.get("claim_measurement_id"))
    if not measurement_id:
        return "NO_MEASUREMENT", "측정값 없는 placeholder"
    usage = nz(row.get("measurement_usage"))
    rescue_observed = looks_kosis_observed_stat(row, dimension, semantic)
    if usage != "KOSIS_VALUE" and not rescue_observed:
        return "NOT_KOSIS_VALUE", f"measurement_usage={usage or '-'}"
    scope = nz(row.get("claim_domain_scope"))
    if scope != "국내공식통계" and not rescue_observed:
        return "OUT_OF_KOSIS_SCOPE", f"claim_domain_scope={scope or '-'}"
    source = nz(row.get("measurement_binding_source"))
    if source != "hcx":
        return "BINDING_NOT_CONFIRMED", f"measurement_binding_source={source or '-'}"
    role = nz(row.get("measurement_role"))
    if role == "목표값":
        return "ROLE_NOT_OBSERVED_VALUE", "목표값은 실제 관측 통계가 아님"
    if role == "참고값" and not reference_relation_confirmed(row):
        return "REFERENCE_RELATION_UNCLEAR", "참고값과 주장의 관계가 불명확함"
    if indicator_value_context_conflict(row):
        return "INDICATOR_VALUE_CONTEXT_CONFLICT", "수출액/수입액 지표로 추출됐지만 값 문맥은 흑자/적자라 무역수지 값일 가능성이 큼"
    if parse_number(row.get("value")) is None:
        return "VALUE_MISSING", "value가 숫자가 아님"
    if not (nz(row.get("measurement_indicator")) or nz(row.get("indicator"))):
        return "INDICATOR_MISSING", "measurement indicator 없음"
    if not nz(row.get("measurement_period")):
        return "PERIOD_MISSING", "measurement period 없음"
    if not nz(row.get("measurement_prd_se")):
        return "PERIODICITY_MISSING", "measurement prd_se 없음"
    if dimension == "unknown":
        return "UNIT_UNSUPPORTED", f"표준화할 수 없는 unit={nz(row.get('unit')) or '-'}"
    if semantic in {"rate_change", "rate_level"} and dimension != "rate":
        return "VALUE_TYPE_UNIT_CONFLICT", f"semantic_type={semantic}, unit_dimension={dimension}"
    if semantic == "rank":
        return "RANK_NOT_DIRECTLY_COMPARABLE", "순위는 KOSIS 원자료와 직접 비교하지 않음"
    return "", ""


def normalize_row(row: dict) -> dict:
    out = dict(row)
    inferred_period = ""
    inferred_prd_se = ""
    default_reason = ""
    if not nz(out.get("measurement_period")):
        inferred_period, inferred_prd_se, default_reason = infer_period_from_context(out)
        if inferred_period:
            out["measurement_period"] = inferred_period
            if not nz(out.get("measurement_prd_se")):
                out["measurement_prd_se"] = inferred_prd_se
    raw_unit = nz(out.get("unit"))
    canonical_unit = canonicalize_unit(raw_unit)
    dimension = unit_dimension(canonical_unit)
    semantic = semantic_type(out, dimension)
    code, reason = exclusion(out, dimension, semantic)

    # Preserve claim-level fields while exposing the aliases expected by the
    # feature/model matcher.  The aliases are always measurement-level values.
    out["claim_indicator"] = nz(out.get("indicator"))
    out["claim_industry_or_item"] = nz(out.get("industry_or_item"))
    out["claim_period"] = nz(out.get("period"))
    out["claim_prd_se"] = nz(out.get("prd_se"))
    out["indicator"] = nz(out.get("measurement_indicator")) or nz(out.get("indicator"))
    out["industry_or_item"] = nz(out.get("measurement_item")) or nz(out.get("industry_or_item"))
    out["period"] = nz(out.get("measurement_period"))
    out["prd_se"] = nz(out.get("measurement_prd_se"))
    out["raw_unit"] = raw_unit
    out["canonical_unit"] = canonical_unit
    out["unit"] = canonical_unit
    out["unit_dimension"] = dimension
    out["semantic_type"] = semantic
    if semantic == "rate_change":
        out["mapping_type"] = "rate_from_level"
    elif semantic == "absolute_change":
        out["mapping_type"] = "difference_from_level"
    else:
        out["mapping_type"] = "direct"
    out["entity_type"] = entity_type(row)
    out["comparison_period"] = comparison_period(row, semantic)
    out["mapping_eligible"] = "Y" if not code else "N"
    out["mapping_exclusion_code"] = code
    out["mapping_exclusion_reason"] = reason
    out["default_applied"] = "Y" if inferred_period else "N"
    out["default_reason"] = default_reason
    if not code and looks_kosis_observed_stat(out, dimension, semantic):
        rescue_reasons = []
        if nz(row.get("measurement_usage")) != "KOSIS_VALUE":
            rescue_reasons.append(f"measurement_usage={nz(row.get('measurement_usage')) or '-'}이지만 KOSIS형 관측 지표로 READY 허용")
        if nz(row.get("claim_domain_scope")) != "국내공식통계":
            rescue_reasons.append(f"claim_domain_scope={nz(row.get('claim_domain_scope')) or '-'}이지만 KOSIS형 관측 지표로 READY 허용")
        if rescue_reasons:
            out["default_applied"] = "Y"
            joined = "; ".join(rescue_reasons)
            out["default_reason"] = (out["default_reason"] + "; " + joined).strip("; ")
    return out


DERIVED_FIELDS = [
    "indicator",
    "industry_or_item",
    "period",
    "prd_se",
    "mapping_type",
    "claim_indicator",
    "claim_industry_or_item",
    "claim_period",
    "claim_prd_se",
    "raw_unit",
    "canonical_unit",
    "unit_dimension",
    "semantic_type",
    "entity_type",
    "comparison_period",
    "mapping_eligible",
    "mapping_exclusion_code",
    "mapping_exclusion_reason",
    "default_applied",
    "default_reason",
]


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prepare(input_path: Path, output_path: Path, rejected_path: Path | None = None):
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source_fields = list(reader.fieldnames or [])
        normalized = [normalize_row(row) for row in reader]

    fields = list(dict.fromkeys(source_fields + DERIVED_FIELDS))
    accepted = [row for row in normalized if row["mapping_eligible"] == "Y"]
    rejected = [row for row in normalized if row["mapping_eligible"] != "Y"]
    write_csv(output_path, accepted, fields)
    if rejected_path:
        write_csv(rejected_path, rejected, fields)
    return accepted, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rejected-output", default="")
    parser.add_argument("--expect-ready", type=int, default=0)
    args = parser.parse_args()

    accepted, rejected = prepare(
        Path(args.input),
        Path(args.output),
        Path(args.rejected_output) if args.rejected_output else None,
    )
    counts = Counter(row["mapping_exclusion_code"] for row in rejected)
    print(f"input={len(accepted) + len(rejected)} ready={len(accepted)} rejected={len(rejected)}")
    print("rejection_counts=" + ", ".join(f"{key}:{value}" for key, value in counts.most_common()))
    print(f"saved={args.output}")
    if args.rejected_output:
        print(f"rejected={args.rejected_output}")
    if args.expect_ready and len(accepted) != args.expect_ready:
        raise SystemExit(f"expected {args.expect_ready} ready rows, got {len(accepted)}")


if __name__ == "__main__":
    main()
