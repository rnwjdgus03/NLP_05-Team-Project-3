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

from kosis_scope_gate import gate_decision


EMPTY = {"", "-", "nan", "none", "null"}
SKIP_ROLES = {"이전값", "참고값"}
TARGET_ROLES = {"목표값"}


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
    raw = re.sub(r"(?i)u\.?s\.?\$", "달러", raw)
    raw = re.sub(r"(?i)usd", "달러", raw)
    # KOSIS 는 단위를 '천$' / '백만$' 처럼 기호로 쓰는 표가 많다. 'US$' 만 처리하면
    # 이런 표기가 차원 미확정으로 떨어져 값 비교 자체를 못 한다(실측 확인).
    raw = raw.replace("＄", "$").replace("$", "달러")
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


def canonicalize_period(period: str, prd_se: str = "") -> str:
    raw = nz(period)
    periodicity = nz(prd_se).upper()
    if periodicity == "M":
        match = re.search(r"((?:19|20)\d{2})\D*(1[0-2]|0?[1-9])", raw)
        if match:
            return f"{match.group(1)}{int(match.group(2)):02d}"
    match = re.search(r"(?:19|20)\d{2}", raw)
    return match.group() if match else raw


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


def expected_base_period(target_period: str, change_base: str) -> str:
    """Return the comparison period implied by a target period and change base."""
    target = nz(target_period)
    base = nz(change_base)
    if not target or not base:
        return ""
    if base in {"전년동월", "전년동기"} and re.fullmatch(r"(?:19|20)\d{4}", target):
        return str(int(target[:4]) - 1) + target[4:]
    if base == "전월" and re.fullmatch(r"(?:19|20)\d{4}", target):
        year, month = int(target[:4]), int(target[4:])
        return f"{year - 1}12" if month == 1 else f"{year}{month - 1:02d}"
    if base == "전년" and re.fullmatch(r"(?:19|20)\d{2}", target):
        return str(int(target) - 1)
    return ""


def align_change_period(row: dict) -> tuple[str, str]:
    """Correct a change measurement that was bound to its comparison period."""
    measurement_period = canonicalize_period(
        row.get("measurement_period"),
        row.get("measurement_prd_se"),
    )
    claim_period = canonicalize_period(row.get("period"), row.get("prd_se"))
    role = nz(row.get("measurement_role"))
    if role not in {"증감률", "증감값"} or not claim_period:
        return measurement_period, ""
    base_period = expected_base_period(claim_period, row.get("change_base"))
    if base_period and measurement_period == base_period:
        return claim_period, "COMPARISON_PERIOD_TO_TARGET"
    return measurement_period, ""


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
    if role in TARGET_ROLES:
        return "TARGET_VALUE_NOT_OBSERVED", f"measurement_role={role}"
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


ENRICHMENT_ACTIONS = {
    "NO_MEASUREMENT": "REEXTRACT_MEASUREMENT",
    "BINDING_NOT_CONFIRMED": "CONFIRM_MEASUREMENT_BINDING",
    "ROLE_NOT_DIRECT_TARGET": "CONFIRM_DIRECT_TARGET_ROLE",
    "VALUE_MISSING": "REEXTRACT_VALUE",
    "INDICATOR_MISSING": "REEXTRACT_INDICATOR",
    "PERIOD_MISSING": "RESOLVE_PERIOD_FROM_CONTEXT",
    "PERIODICITY_MISSING": "RESOLVE_PERIODICITY",
    "UNIT_UNSUPPORTED": "NORMALIZE_UNIT",
    "VALUE_TYPE_UNIT_CONFLICT": "REPAIR_VALUE_TYPE_OR_UNIT",
}


def mapping_gate(row: dict, code: str) -> tuple[str, str]:
    """Classify strict eligibility failures into recoverable vs hard reject."""
    if not code:
        return "READY", ""
    if code == "OUT_OF_KOSIS_SCOPE":
        scope = nz(row.get("claim_domain_scope"))
        if not scope or scope == "기타":
            return "ENRICH", "CONFIRM_KOSIS_SCOPE"
        return "REJECT", ""
    if code == "NOT_KOSIS_VALUE":
        if not nz(row.get("measurement_usage")):
            return "ENRICH", "CLASSIFY_MEASUREMENT_USAGE"
        return "REJECT", ""
    if code == "RANK_NOT_DIRECTLY_COMPARABLE":
        return "REJECT", ""
    if code == "TARGET_VALUE_NOT_OBSERVED":
        return "REJECT", ""
    action = ENRICHMENT_ACTIONS.get(code)
    if action:
        return "ENRICH", action
    return "REJECT", ""


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
    out["raw_measurement_period"] = nz(row.get("measurement_period"))
    out["indicator"] = nz(row.get("measurement_indicator")) or nz(row.get("indicator"))
    out["industry_or_item"] = nz(row.get("measurement_item")) or nz(row.get("industry_or_item"))
    out["prd_se"] = nz(row.get("measurement_prd_se"))
    out["period"], out["period_alignment_status"] = align_change_period(row)
    out["raw_unit"] = raw_unit
    out["canonical_unit"] = canonical_unit
    out["unit"] = canonical_unit
    out["unit_dimension"] = dimension
    out["semantic_type"] = semantic
    out["entity_type"] = entity_type(row)
    comparison_row = dict(row)
    comparison_row["measurement_period"] = out["period"]
    comparison_row["measurement_prd_se"] = out["prd_se"]
    out["comparison_period"] = comparison_period(comparison_row, semantic)
    # 내용 기반 범위 판정 — HCX 자기 신고 라벨(measurement_usage/claim_domain_scope)만
    # 믿으면 비트코인 시세나 개별 브랜드 판매가도 그대로 통과한다(실측 확인).
    scope = gate_decision({**row, "unit": out["unit"]})
    out.update(scope)
    if not code and scope["scope_gate_blocked"] == "Y":
        code = scope["scope_gate_code"]
        reason = scope["scope_gate_reason"]

    out["mapping_eligible"] = "Y" if not code else "N"
    out["in_ready"] = out["mapping_eligible"]
    out["mapping_exclusion_code"] = code
    out["mapping_exclusion_reason"] = reason
    if scope["scope_gate_blocked"] == "Y":
        out["mapping_gate"] = "REJECT"
        out["mapping_gate_reason"] = code
        out["enrichment_actions"] = ""
    else:
        gate, action = mapping_gate(row, code)
        out["mapping_gate"] = gate
        out["mapping_gate_reason"] = code or "ELIGIBLE"
        out["enrichment_actions"] = action
    return out


DERIVED_FIELDS = [
    "claim_indicator",
    "claim_industry_or_item",
    "claim_period",
    "claim_prd_se",
    "raw_measurement_period",
    "period_alignment_status",
    "raw_unit",
    "canonical_unit",
    "unit_dimension",
    "semantic_type",
    "entity_type",
    "comparison_period",
    "mapping_eligible",
    "in_ready",
    "mapping_exclusion_code",
    "mapping_exclusion_reason",
    "mapping_gate",
    "mapping_gate_reason",
    "enrichment_actions",
    # 내용 기반 범위 판정 (kosis_scope_gate)
    "scope_gate_code",
    "scope_gate_reason",
    "scope_gate_severity",
    "scope_gate_blocked",
]


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prepare(
    input_path: Path,
    output_path: Path,
    rejected_path: Path | None = None,
    enrich_path: Path | None = None,
    all_output_path: Path | None = None,
):
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source_fields = list(reader.fieldnames or [])
        normalized = [normalize_row(row) for row in reader]

    fields = list(dict.fromkeys(source_fields + DERIVED_FIELDS))
    accepted = [row for row in normalized if row["mapping_eligible"] == "Y"]
    rejected = [row for row in normalized if row["mapping_eligible"] != "Y"]
    enrich = [row for row in normalized if row["mapping_gate"] == "ENRICH"]
    hard_rejected = [row for row in normalized if row["mapping_gate"] == "REJECT"]
    write_csv(output_path, accepted, fields)
    if rejected_path:
        # Legacy calls receive every non-READY row. New three-way calls that
        # also provide enrich_path receive only hard rejects here.
        write_csv(rejected_path, hard_rejected if enrich_path else rejected, fields)
    if enrich_path:
        write_csv(enrich_path, enrich, fields)
    if all_output_path:
        write_csv(all_output_path, normalized, fields)
    return accepted, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rejected-output", default="")
    parser.add_argument("--enrich-output", default="")
    parser.add_argument("--all-output", default="")
    parser.add_argument("--expect-ready", type=int, default=0)
    args = parser.parse_args()

    accepted, rejected = prepare(
        Path(args.input),
        Path(args.output),
        Path(args.rejected_output) if args.rejected_output else None,
        Path(args.enrich_output) if args.enrich_output else None,
        Path(args.all_output) if args.all_output else None,
    )
    counts = Counter(row["mapping_exclusion_code"] for row in rejected)
    gate_counts = Counter(
        ["READY"] * len(accepted) + [row["mapping_gate"] for row in rejected]
    )
    print(f"input={len(accepted) + len(rejected)} ready={len(accepted)} rejected={len(rejected)}")
    print("gate_counts=" + ", ".join(f"{key}:{value}" for key, value in gate_counts.most_common()))
    print("rejection_counts=" + ", ".join(f"{key}:{value}" for key, value in counts.most_common()))
    print(f"saved={args.output}")
    if args.rejected_output:
        print(f"rejected={args.rejected_output}")
    if args.enrich_output:
        print(f"enrich={args.enrich_output}")
    if args.all_output:
        print(f"all={args.all_output}")
    if args.expect_ready and len(accepted) != args.expect_ready:
        raise SystemExit(f"expected {args.expect_ready} ready rows, got {len(accepted)}")


if __name__ == "__main__":
    main()
