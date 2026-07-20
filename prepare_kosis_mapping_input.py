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
SKIP_ROLES = {"이전값", "참고값", "목표값"}


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


def exclusion(row: dict, dimension: str, semantic: str):
    measurement_id = nz(row.get("claim_measurement_id"))
    if not measurement_id:
        return "NO_MEASUREMENT", "측정값 없는 placeholder"
    usage = nz(row.get("measurement_usage"))
    if usage != "KOSIS_VALUE":
        return "NOT_KOSIS_VALUE", f"measurement_usage={usage or '-'}"
    scope = nz(row.get("claim_domain_scope"))
    if scope != "국내공식통계":
        return "OUT_OF_KOSIS_SCOPE", f"claim_domain_scope={scope or '-'}"
    source = nz(row.get("measurement_binding_source"))
    if source != "hcx":
        return "BINDING_NOT_CONFIRMED", f"measurement_binding_source={source or '-'}"
    role = nz(row.get("measurement_role"))
    if role in SKIP_ROLES:
        return "ROLE_NOT_DIRECT_TARGET", f"measurement_role={role}"
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
    raw_unit = nz(row.get("unit"))
    canonical_unit = canonicalize_unit(raw_unit)
    dimension = unit_dimension(canonical_unit)
    semantic = semantic_type(row, dimension)
    code, reason = exclusion(row, dimension, semantic)

    # Preserve claim-level fields while exposing the aliases expected by the
    # feature/model matcher.  The aliases are always measurement-level values.
    out["claim_indicator"] = nz(row.get("indicator"))
    out["claim_industry_or_item"] = nz(row.get("industry_or_item"))
    out["claim_period"] = nz(row.get("period"))
    out["claim_prd_se"] = nz(row.get("prd_se"))
    out["indicator"] = nz(row.get("measurement_indicator")) or nz(row.get("indicator"))
    out["industry_or_item"] = nz(row.get("measurement_item")) or nz(row.get("industry_or_item"))
    out["period"] = nz(row.get("measurement_period"))
    out["prd_se"] = nz(row.get("measurement_prd_se"))
    out["raw_unit"] = raw_unit
    out["canonical_unit"] = canonical_unit
    out["unit"] = canonical_unit
    out["unit_dimension"] = dimension
    out["semantic_type"] = semantic
    out["entity_type"] = entity_type(row)
    out["comparison_period"] = comparison_period(row, semantic)
    out["mapping_eligible"] = "Y" if not code else "N"
    out["mapping_exclusion_code"] = code
    out["mapping_exclusion_reason"] = reason
    return out


DERIVED_FIELDS = [
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
