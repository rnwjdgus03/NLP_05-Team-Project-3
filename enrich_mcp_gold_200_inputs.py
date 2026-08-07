#!/usr/bin/env python3
"""Add gold-free value/unit/period fields to the MCP gold-200 input fixture."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from prepare_kosis_mapping_input import (
    canonicalize_unit,
    semantic_type as infer_semantic_type,
    unit_dimension,
)
from search_mcp_gold_200_chroma_bge import _number_variants, select_claim_unit


COUNTRY_ALIASES = {
    "대미": "미국", "미국": "미국", "대중": "중국", "대중국": "중국",
    "중국": "중국", "대일": "일본", "일본": "일본", "홍콩": "홍콩",
    "대만": "대만", "베트남": "베트남", "싱가포르": "싱가포르",
    "인도": "인도", "인도네시아": "인도네시아", "말레이시아": "말레이시아",
    "태국": "태국", "필리핀": "필리핀", "독일": "독일", "프랑스": "프랑스",
    "영국": "영국", "캐나다": "캐나다", "멕시코": "멕시코", "브라질": "브라질",
    "호주": "호주", "러시아": "러시아", "사우디아라비아": "사우디아라비아",
    "아랍에미리트": "아랍에미리트", "폴란드": "폴란드",
}
PRODUCT_ALIASES = {
    "메모리반도체": "반도체", "반도체": "반도체", "자동차": "자동차",
    "친환경차": "자동차", "전기차": "자동차", "하이브리드차": "자동차",
    "승용차": "자동차", "선박": "선박", "화장품": "화장품", "K뷰티": "화장품",
    "바이오헬스": "바이오헬스", "의약품": "의약품", "농수산식품": "농수산식품",
    "K푸드": "농수산식품", "원유": "원유", "석유": "석유", "고등어": "고등어",
    "김치": "김치", "돼지고기": "돼지고기", "삼겹살": "돼지고기",
    "달걀": "달걀", "계란": "달걀", "가전제품": "가전제품",
}
REGION_TERMS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기도", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
INDICATOR_ALIASES = (
    ("실업률", "실업률"), ("고용률", "고용률"), ("취업자", "취업자"),
    ("합계출산율", "합계출산율"), ("출생아", "출생아수"),
    ("소비자물가지수", "소비자물가지수"), ("생활물가지수", "생활물가지수"),
    ("소매판매액지수", "소매판매액지수"), ("서비스업생산지수", "서비스업생산지수"),
    ("수입액", "수입액"), ("수입", "수입액"), ("수출액", "수출액"), ("수출", "수출액"),
)


@dataclass(frozen=True)
class PeriodMention:
    start: int
    end: int
    prd_se: str
    period: str
    source: str
    priority: int


def _month_period(year: int, month: int) -> str:
    return f"{year:04d}{month:02d}"


def _previous_month(period: str) -> str:
    year, month = int(period[:4]), int(period[4:])
    return _month_period(year - 1, 12) if month == 1 else _month_period(year, month - 1)


def _add_matches(
    mentions: list[PeriodMention],
    occupied: list[tuple[int, int]],
    text: str,
    pattern: str,
    builder,
    source: str,
    priority: int,
) -> None:
    for match in re.finditer(pattern, text):
        if any(match.start() < end and match.end() > start for start, end in occupied):
            continue
        prd_se, period = builder(match)
        if period:
            mentions.append(
                PeriodMention(match.start(), match.end(), prd_se, period, source, priority)
            )
            occupied.append((match.start(), match.end()))


def period_mentions(text: str, publication_date: date) -> list[PeriodMention]:
    mentions: list[PeriodMention] = []
    occupied: list[tuple[int, int]] = []
    year = publication_date.year

    _add_matches(
        mentions, occupied, text,
        r"(?P<year>20\d{2})년\s*(?P<start>1[0-2]|0?[1-9])\s*[~∼\-]\s*(?P<end>1[0-2]|0?[1-9])월",
        lambda m: ("M", _month_period(int(m.group("year")), int(m.group("end")))),
        "explicit_year_month_range", 7,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?P<year>20\d{2})년\s*(?P<month>1[0-2]|0?[1-9])월",
        lambda m: ("M", _month_period(int(m.group("year")), int(m.group("month")))),
        "explicit_year_month", 7,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?P<year>20\d{2})년\s*(?P<quarter>[1-4])분기",
        lambda m: ("M", _month_period(int(m.group("year")), int(m.group("quarter")) * 3)),
        "explicit_year_quarter", 7,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?P<rel>지난해|작년|올해)\s*(?P<start>1[0-2]|0?[1-9])\s*[~∼\-]\s*(?P<end>1[0-2]|0?[1-9])월",
        lambda m: (
            "M",
            _month_period(year if m.group("rel") == "올해" else year - 1, int(m.group("end"))),
        ),
        "relative_year_month_range", 6,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?P<rel>지난해|작년|올해)\s*(?P<month>1[0-2]|0?[1-9])월",
        lambda m: (
            "M",
            _month_period(year if m.group("rel") == "올해" else year - 1, int(m.group("month"))),
        ),
        "relative_year_month", 6,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?P<rel>지난해|작년|올해|지난)\s*(?P<quarter>[1-4])분기",
        lambda m: (
            "M",
            _month_period(year if m.group("rel") in {"올해", "지난"} else year - 1, int(m.group("quarter")) * 3),
        ),
        "relative_quarter", 6,
    )
    _add_matches(
        mentions, occupied, text,
        r"지난달",
        lambda m: ("M", _previous_month(_month_period(year, publication_date.month))),
        "previous_month", 5,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?<!\d)(?P<start>1[0-2]|0?[1-9])\s*[~∼\-]\s*(?P<end>1[0-2]|0?[1-9])월",
        lambda m: (
            "M",
            _month_period(year if int(m.group("end")) <= publication_date.month else year - 1, int(m.group("end"))),
        ),
        "month_range", 4,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?:지난\s*)?(?P<month>1[0-2]|0?[1-9])월",
        lambda m: (
            "M",
            _month_period(year if int(m.group("month")) <= publication_date.month else year - 1, int(m.group("month"))),
        ),
        "month", 3,
    )
    _add_matches(
        mentions, occupied, text,
        r"(?P<year>20\d{2})년",
        lambda m: ("Y", m.group("year")),
        "explicit_year", 5,
    )
    _add_matches(
        mentions, occupied, text,
        r"지난해|작년(?:\s*한\s*해)?|올해",
        lambda m: ("Y", str(year if m.group(0).startswith("올해") else year - 1)),
        "relative_year", 2,
    )
    return mentions


def value_positions(text: str, value: str) -> list[int]:
    positions: list[int] = []
    for variant in _number_variants(value):
        escaped = re.escape(variant).replace(r"\.", r"[.,]").replace(r"\-", r"[-−]")
        positions.extend(match.start() for match in re.finditer(rf"(?<![0-9.]){escaped}(?![0-9.])", text))
    return sorted(set(positions))


def _nearest_named_term(
    text: str,
    value: str,
    aliases: dict[str, str] | Iterable[tuple[str, str]],
) -> str:
    pairs = aliases.items() if isinstance(aliases, dict) else aliases
    anchors = value_positions(text, value)
    found: list[tuple[int, int, str]] = []
    for alias, canonical in pairs:
        for match in re.finditer(re.escape(alias), text, flags=re.IGNORECASE):
            distance = min((abs(match.start() - anchor) for anchor in anchors), default=match.start())
            found.append((distance, -len(alias), canonical))
    return min(found)[2] if found else ""


def extract_structured_targets(claim: dict[str, str]) -> dict[str, str]:
    """Extract target-bearing fields used by the coordinate OBJ stage."""

    text = str(claim.get("claim_text", "") or "")
    value = str(claim.get("claim_value", "") or "")
    country = _nearest_named_term(text, value, COUNTRY_ALIASES)
    product = _nearest_named_term(text, value, PRODUCT_ALIASES)
    indicator = _nearest_named_term(text, value, INDICATOR_ALIASES)

    age = ""
    age_patterns = (
        (r"15\s*[~∼\-]\s*29세|15\s*[- ]\s*29세|청년층?|청년", "15 - 29세"),
        (r"20대", "20 - 29세"), (r"30대", "30 - 39세"),
        (r"40대", "40 - 49세"), (r"50대", "50 - 59세"),
        (r"60대", "60 - 69세"), (r"65세\s*이상|고령층|노인", "65세 이상"),
    )
    age_matches = []
    anchors = value_positions(text, value)
    for pattern, canonical in age_patterns:
        for match in re.finditer(pattern, text):
            distance = min((abs(match.start() - anchor) for anchor in anchors), default=match.start())
            age_matches.append((distance, canonical))
    if age_matches:
        age = min(age_matches)[1]

    gender = _nearest_named_term(
        text,
        value,
        (("여성", "여자"), ("여자", "여자"), ("남성", "남자"), ("남자", "남자")),
    )
    region = _nearest_named_term(text, value, ((term, term) for term in REGION_TERMS))
    if region == "경기도":
        region = "경기"

    is_export = "수출" in text
    is_import = "수입" in text and not is_export
    obj_terms = [term for term in (country, age, gender, region) if term]
    # Country tables and product tables are alternative coordinate spaces.
    # When a country is explicit, keep the product only as an audit field.
    if not country and product:
        obj_terms.append(product)
    return {
        "indicator": indicator,
        "measurement_indicator": indicator,
        "industry_or_item": "" if country else product,
        "measurement_item": "" if country else product,
        "extracted_product": product,
        "region": region,
        "age_group": age,
        "gender": gender,
        "origin_country": country if is_import else "",
        "destination_country": country if is_export or not is_import else "",
        "obj_target_terms": "|".join(dict.fromkeys(obj_terms)),
        "item_intent_terms": indicator,
    }


def choose_period(claim: dict[str, str]) -> tuple[str, str, str, str]:
    try:
        publication_date = date.fromisoformat(str(claim.get("date", ""))[:10])
    except ValueError:
        return "", "", "", "no_publication_date"
    text = str(claim.get("claim_text", "") or "")
    mentions = period_mentions(text, publication_date)
    if not mentions:
        return "", "", "", "no_period_mention"
    positions = value_positions(text, claim.get("claim_value", ""))

    def score(mention: PeriodMention) -> tuple[float, int, int]:
        if not positions:
            distance = mention.start
        else:
            distance = min(
                min(abs(position - mention.end), abs(mention.start - position))
                for position in positions
            )
        return distance, -mention.priority, -mention.start

    selected = min(mentions, key=score)
    previous = ""
    local = text[max(0, selected.start - 80) : min(len(text), selected.end + 140)]
    if selected.prd_se == "M":
        if re.search(r"전월|전달|한\s*달\s*(?:전|새)", local):
            previous = _previous_month(selected.period)
        elif re.search(r"전년\s*(?:동월|같은\s*달|대비|보다)|작년\s*(?:같은\s*달|대비|보다)|1년\s*전", local):
            previous = str(int(selected.period[:4]) - 1) + selected.period[4:]
    elif re.search(r"전년|1년\s*전|재작년|지난해\s*대비", local):
        previous = str(int(selected.period) - 1)
    return selected.prd_se, selected.period, previous, selected.source


def infer_change_fields(
    claim: dict[str, str], prd_se: str, period: str, previous_period: str
) -> tuple[str, str, str]:
    """Return ``value_type``, ``measurement_role`` and a conservative base.

    ``mapping_type`` is deliberately not inferred here because it depends on
    the selected KOSIS ITEM.  The coordinate search computes it after ITEM
    selection.  These claim-only fields are enough to distinguish direct
    전월비/전년동월비 ITEMs from a rate derived from level values.
    """

    claim_type = str(claim.get("claim_type", "") or "").upper()
    text = re.sub(r"\s+", "", str(claim.get("claim_text", "") or ""))
    if claim_type == "CHANGE_RATE":
        value_type, role = "증감률", "증감률"
    elif claim_type == "CHANGE_POINT":
        value_type, role = "증감량", "증감값"
    else:
        value_type, role = "", "수준값"

    change_base = ""
    if re.search(r"전월|전달|한달(?:전|새)", text):
        change_base = "전월"
    elif re.search(r"전년동월|전년같은달|작년같은달|1년전", text):
        change_base = "전년동월" if prd_se == "M" else "전년"
    elif re.search(r"전년|작년|지난해", text):
        change_base = "전년동월" if prd_se == "M" else "전년"
    elif period and previous_period:
        if len(period) == 6 and len(previous_period) == 6:
            if previous_period == _previous_month(period):
                change_base = "전월"
            elif previous_period == str(int(period[:4]) - 1) + period[4:]:
                change_base = "전년동월"
        elif len(period) == 4 and previous_period == str(int(period) - 1):
            change_base = "전년"
    return value_type, role, change_base


def enrich_row(row: dict[str, str]) -> dict[str, str]:
    forbidden = [key for key in row if key.startswith("gold_") and key != "gold_id"]
    if forbidden:
        raise ValueError("input contains gold answer fields: " + ", ".join(sorted(forbidden)))
    adapted = {
        **row,
        "claim_value": row.get("claim_value") or row.get("value", ""),
        "claim_unit": row.get("claim_unit") or row.get("unit") or row.get("raw_unit", ""),
        "claim_type": row.get("claim_type") or row.get("semantic_type", ""),
    }
    prd_se, period, previous, source = choose_period(adapted)
    selected_unit = select_claim_unit(adapted)
    canonical_unit = canonicalize_unit(selected_unit)
    dimension = unit_dimension(canonical_unit)
    value_type, measurement_role, change_base = infer_change_fields(
        adapted, prd_se, period, previous
    )
    if not previous and period:
        if change_base == "전월" and len(period) == 6:
            previous = _previous_month(period)
        elif change_base == "전년동월" and len(period) == 6:
            previous = str(int(period[:4]) - 1) + period[4:]
        elif change_base == "전년" and len(period) == 4:
            previous = str(int(period) - 1)
    if adapted["claim_type"].upper() == "CHANGE_RATE" and dimension not in {"rate", "duration"}:
        value_type, measurement_role = "증감량", "증감값"
    if adapted["claim_type"].upper() == "LEVEL" and dimension == "rate":
        value_type = "비율"
    semantic = infer_semantic_type(
        {
            **adapted,
            "value_type": value_type,
            "measurement_role": measurement_role,
        },
        dimension,
    )
    input_quality_status = "READY"
    input_quality_reason = ""
    if adapted["claim_type"].upper() in {"CHANGE_RATE", "CHANGE_POINT"} and dimension == "duration":
        input_quality_status = "NEEDS_INPUT_REVIEW"
        input_quality_reason = "CHANGE_VALUE_LOOKS_TEMPORAL"
    elif adapted["claim_type"].upper() == "LEVEL" and dimension == "duration":
        input_quality_status = "NEEDS_INPUT_REVIEW"
        input_quality_reason = "LEVEL_VALUE_LOOKS_TEMPORAL"
    elif (
        adapted["claim_type"].upper() == "CHANGE_RATE"
        and selected_unit == "대"
        and re.search(rf"(?<!\d){re.escape(str(adapted['claim_value']).split('.')[0])}대(?:는|가|의|에서)", adapted["claim_text"])
    ):
        input_quality_status = "NEEDS_INPUT_REVIEW"
        input_quality_reason = "CHANGE_VALUE_LOOKS_DEMOGRAPHIC"
    targets = extract_structured_targets(adapted)
    targets = {key: value or row.get(key, "") for key, value in targets.items()}
    return {
        **row,
        "claim_measurement_id": row.get("claim_measurement_id") or row.get("claim_id", ""),
        "value": adapted["claim_value"],
        "unit": selected_unit,
        "raw_unit": adapted["claim_unit"],
        "canonical_unit": canonical_unit,
        "unit_dimension": dimension,
        "semantic_type": semantic,
        "value_type": value_type,
        "measurement_role": measurement_role,
        "period": period or row.get("period", ""),
        "measurement_period": period or row.get("measurement_period", ""),
        "prd_se": prd_se or row.get("prd_se", ""),
        "measurement_prd_se": prd_se or row.get("measurement_prd_se", ""),
        "previous_period": previous or row.get("previous_period", ""),
        "comparison_period": previous or row.get("comparison_period", ""),
        "change_base": change_base or row.get("change_base", ""),
        # ITEM-dependent; kosis_chroma_hybrid_search.resolve_mapping_type fills it.
        "mapping_type": row.get("mapping_type", ""),
        "input_quality_status": input_quality_status,
        "input_quality_reason": input_quality_reason,
        "period_extraction_source": source,
        **targets,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stats", type=Path, default=None)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = [enrich_row(row) for row in csv.DictReader(handle)]
    write_csv(args.output, rows)
    stats = {
        "rows": len(rows),
        "unit_selected": sum(bool(row["unit"]) for row in rows),
        "period_selected": sum(bool(row["period"]) for row in rows),
        "annual": sum(row["prd_se"] == "Y" for row in rows),
        "monthly": sum(row["prd_se"] == "M" for row in rows),
        "previous_period_selected": sum(bool(row["previous_period"]) for row in rows),
        "change_base_selected": sum(bool(row["change_base"]) for row in rows),
        "input_quality_counts": {
            value: sum(row["input_quality_status"] == value for row in rows)
            for value in sorted({row["input_quality_status"] for row in rows})
        },
        "semantic_type_counts": {
            value: sum(row["semantic_type"] == value for row in rows)
            for value in sorted({row["semantic_type"] for row in rows})
        },
    }
    if args.stats:
        args.stats.parent.mkdir(parents=True, exist_ok=True)
        args.stats.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
