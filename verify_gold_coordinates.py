#!/usr/bin/env python3
"""Verify final gold KOSIS coordinates directly with the KOSIS data API.

This script is intentionally separate from the production automatic verifier.
It consumes human-confirmed gold coordinates such as A01/M00/F20, converts them
to KOSIS API objL1/objL2/objL3 parameters, fetches official data, derives the
needed actual value, and compares it with the extracted claim value.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from pathlib import Path

from kosis_api_test import get_meta, get_stat_data
from prepare_kosis_mapping_input import canonicalize_unit, unit_dimension


def nz(value) -> str:
    text = str(value or "").strip()
    return "" if text in {"", "-", "?", "nan", "None"} else text


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compact(value) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def parse_number(value):
    text = str(value or "").replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
    return float(match.group()) if match else None


def parse_period(value: str) -> str:
    text = nz(value)
    match = re.search(r"((?:19|20)\d{2})\s*[Qq]\s*([1-4])", text)
    if match:
        return f"{match.group(1)}0{match.group(2)}"
    match = re.search(r"((?:19|20)\d{2})\s*년\s*([1-4])\s*분기", text)
    if match:
        return f"{match.group(1)}0{match.group(2)}"
    match = re.search(r"((?:19|20)\d{2})\D?(0[1-9]|1[0-2])", text)
    if match:
        return match.group(1) + match.group(2)
    match = re.search(r"(19\d{2}|20\d{2})", text)
    return match.group(1) if match else text


def previous_period(period: str, prd_se: str, row: dict[str, str]) -> str:
    current = parse_period(period)
    prd_se = nz(prd_se).upper()
    context = compact(" ".join(str(row.get(k, "")) for k in ("claim_text", "change_base")))
    yoy = any(token in context for token in ("전년동기", "전년대비", "지난해같은기간", "작년같은기간", "전년"))
    if prd_se == "Q" and len(current) == 6 and current[4] == "0":
        year, quarter = int(current[:4]), int(current[5])
        if yoy or True:
            return f"{year - 1}0{quarter}"
    if prd_se == "M" and len(current) == 6:
        year, month = int(current[:4]), int(current[4:])
        if yoy:
            return f"{year - 1}{month:02d}"
        if month == 1:
            return f"{year - 1}12"
        return f"{year}{month - 1:02d}"
    if len(current) >= 4:
        return str(int(current[:4]) - 1)
    return ""


def split_gold_obj(value: str) -> tuple[str, str]:
    """Return (axis_id, code) from A01/M00/F20 or raw official codes."""
    text = nz(value)
    if not text:
        return "", ""
    if "_" not in text:
        match = re.fullmatch(r"([A-Z]+)(\d+)", text)
        if match:
            return match.group(1), match.group(2)
    return "", text


def meta_maps(meta_rows):
    items = {row.get("ITM_ID", ""): row for row in meta_rows if row.get("OBJ_ID") == "ITEM"}
    axes = {}
    codes = {}
    for row in meta_rows:
        obj_id = row.get("OBJ_ID", "")
        if obj_id == "ITEM":
            continue
        axes.setdefault(obj_id, row.get("OBJ_NM", ""))
        codes[(obj_id, row.get("ITM_ID", ""))] = row
    return items, axes, codes


def repair_coordinates(row, meta_rows):
    items, axes, codes = meta_maps(meta_rows)
    itm_id = nz(row.get("gold_itm_id"))
    gold_objs = [nz(row.get(f"gold_obj_l{level}")) for level in range(1, 9)]

    # Some overseas direct investment rows are stored with item/axis swapped:
    # gold_itm_id=axis code, gold_obj_l1=item code.
    first_axis, first_code = split_gold_obj(gold_objs[0] if gold_objs else "")
    if itm_id not in items and first_code in items:
        swapped_axis_code = itm_id
        itm_id = first_code
        gold_objs = [swapped_axis_code] + gold_objs[1:]

    obj_codes = []
    obj_axis_ids = []
    obj_names = []
    for raw in gold_objs:
        axis_id, code = split_gold_obj(raw)
        if not code:
            continue
        if not axis_id:
            # Find the official axis containing the code.
            for (candidate_axis, candidate_code), meta in codes.items():
                if candidate_code == code:
                    axis_id = candidate_axis
                    break
        obj_codes.append(code)
        obj_axis_ids.append(axis_id)
        obj_names.append(codes.get((axis_id, code), {}).get("ITM_NM", ""))

    return itm_id, obj_codes, obj_axis_ids, obj_names, items.get(itm_id, {})


def fetch_rows(row, itm_id: str, obj_codes: list[str], prd_se: str, start: str, end: str, delay: float):
    if not obj_codes:
        return []
    extra = {f"obj_l{idx}": code for idx, code in enumerate(obj_codes[1:], start=2)}
    rows = get_stat_data(
        org_id=row["gold_org_id"],
        tbl_id=row["gold_tbl_id"],
        obj_l1=obj_codes[0],
        itm_id=itm_id,
        prd_se=prd_se,
        startPrdDe=start,
        endPrdDe=end,
        **extra,
    )
    if delay:
        time.sleep(delay)
    exact = []
    for record in rows:
        if str(record.get("ITM_ID", "")) != str(itm_id):
            continue
        if all(str(record.get(f"C{level}", "")) == str(code) for level, code in enumerate(obj_codes, start=1)):
            exact.append(record)
    return exact


def value_for_period(rows, period: str):
    matches = [row for row in rows if str(row.get("PRD_DE", "")) == period]
    if not matches:
        matches = [row for row in rows if str(row.get("PRD_DE", "")).startswith(period)]
    if not matches:
        return None, ""
    matches.sort(key=lambda row: str(row.get("PRD_DE", "")))
    return parse_number(matches[-1].get("DT")), str(matches[-1].get("PRD_DE", ""))


def unit_scale(unit: str):
    value = compact(canonicalize_unit(unit)).lower()
    if "불" in value:
        value = value.replace("불", "달러")
    if "달러" in value or "usd" in value:
        scale = 1.0
        if "천" in value:
            scale = 1e3
        elif "백만" in value:
            scale = 1e6
        elif "억" in value:
            scale = 1e8
        return "currency_usd", scale
    if value in {"%", "퍼센트"}:
        return "rate", 1.0
    if value in {"대", "개", "건"}:
        return "count", 1.0
    return unit_dimension(value), 1.0


def convert_value(value, kosis_unit: str, claim_unit: str):
    if value is None:
        return None, "actual 없음"
    k_family, k_scale = unit_scale(kosis_unit)
    c_family, c_scale = unit_scale(claim_unit)
    if k_family != c_family:
        return None, f"단위 불일치: KOSIS={kosis_unit}, claim={claim_unit}"
    return value * k_scale / c_scale, f"단위환산={kosis_unit}->{claim_unit}"


def top_n_from_obj_names(obj_names: list[str]):
    for name in obj_names:
        match = re.search(r"상위\s*(\d+)\s*대", name)
        if match:
            return float(match.group(1))
    return None


def derive_actual(row, itm_id, obj_codes, obj_names, item_meta, current_rows, prd_se, period, delay):
    indicator = compact(row.get("measurement_indicator"))
    claim_unit = nz(row.get("unit"))
    current, current_period = value_for_period(current_rows, period)
    kosis_unit = item_meta.get("UNIT_NM") or (current_rows[0].get("UNIT_NM", "") if current_rows else "")

    if unit_scale(claim_unit)[0] == "count":
        top_n = top_n_from_obj_names(obj_names)
        if top_n is not None:
            return top_n, "", "", "상위기업별 축명에서 N대 파생", claim_unit

    if row.get("gold_tbl_id") == "DT_1TEC_N314" and ("무역집중도" in indicator or unit_scale(claim_unit)[0] == "rate"):
        denom_codes = list(obj_codes)
        if len(denom_codes) >= 3:
            denom_codes[2] = "00"
        denom_rows = fetch_rows(row, itm_id, denom_codes, prd_se, period, period, delay)
        denominator, denom_period = value_for_period(denom_rows, period)
        if current is None or denominator in (None, 0):
            return None, current_period, denom_period, "무역집중도 분자/분모 부족", "%"
        return current / denominator * 100, current_period, denom_period, "무역집중도=상위기업교역액/전체기업교역액*100", "%"

    if "증감률" in indicator or unit_scale(claim_unit)[0] == "rate":
        prev = previous_period(row.get("measurement_period", ""), prd_se, row)
        prev_rows = fetch_rows(row, itm_id, obj_codes, prd_se, prev, prev, delay)
        previous, previous_used = value_for_period(prev_rows, prev)
        if current is None or previous in (None, 0):
            return None, current_period, previous_used, "증감률 현재/이전 값 부족", "%"
        return (current - previous) / abs(previous) * 100, current_period, previous_used, "수준값에서 증감률 계산", "%"

    converted, reason = convert_value(current, kosis_unit, claim_unit)
    return converted, current_period, "", reason, claim_unit


def judge(claim_value, actual_value):
    if claim_value is None:
        return "판단불가", "VALUE_MISSING", "claim value 없음"
    if actual_value is None:
        return "판단불가", "ACTUAL_DERIVATION_FAILED", "actual value 없음"
    diff = abs(actual_value - claim_value)
    pct = diff / max(abs(claim_value), 1e-9) * 100
    if pct <= 1.5:
        return "일치", "MATCH", f"차이={diff:.6g}, 차이율={pct:.3g}%"
    if pct <= 4.0:
        return "판정보류", "WITHIN_UNCERTAINTY_BAND", f"차이={diff:.6g}, 차이율={pct:.3g}%"
    return "불일치", "VALUE_MISMATCH", f"차이={diff:.6g}, 차이율={pct:.3g}%"


def verify(row, meta_cache, delay):
    out = dict(row)
    org_id, tbl_id = nz(row.get("gold_org_id")), nz(row.get("gold_tbl_id"))
    if not org_id or not tbl_id:
        out.update(verdict="판단불가", verdict_code="GOLD_COORDINATE_MISSING", verdict_reason="gold org/tbl 없음")
        return out
    key = (org_id, tbl_id)
    if key not in meta_cache:
        meta_cache[key] = get_meta(org_id, tbl_id, "ITM")
        if delay:
            time.sleep(delay)
    itm_id, obj_codes, obj_axis_ids, obj_names, item_meta = repair_coordinates(row, meta_cache[key])
    if not itm_id or not obj_codes:
        out.update(verdict="판단불가", verdict_code="GOLD_COORDINATE_MISSING", verdict_reason="gold item/obj 없음")
        return out
    prd_se = nz(row.get("measurement_prd_se")) or "Y"
    period = parse_period(row.get("measurement_period", ""))
    current_rows = fetch_rows(row, itm_id, obj_codes, prd_se, period, period, delay)
    actual, used_period, previous_period_used, derive_reason, actual_unit = derive_actual(
        row, itm_id, obj_codes, obj_names, item_meta, current_rows, prd_se, period, delay
    )
    claim_value = parse_number(row.get("value"))
    verdict, code, reason = judge(claim_value, actual)
    out.update(
        org_id=org_id,
        tbl_id=tbl_id,
        selected_itm_id=itm_id,
        selected_itm_name=item_meta.get("ITM_NM", ""),
        selected_itm_unit=item_meta.get("UNIT_NM", ""),
        selected_obj_l1=obj_codes[0] if len(obj_codes) > 0 else "",
        selected_obj_l2=obj_codes[1] if len(obj_codes) > 1 else "",
        selected_obj_l3=obj_codes[2] if len(obj_codes) > 2 else "",
        selected_obj_l1_axis_id=obj_axis_ids[0] if len(obj_axis_ids) > 0 else "",
        selected_obj_l2_axis_id=obj_axis_ids[1] if len(obj_axis_ids) > 1 else "",
        selected_obj_l3_axis_id=obj_axis_ids[2] if len(obj_axis_ids) > 2 else "",
        selected_obj_l1_name=obj_names[0] if len(obj_names) > 0 else "",
        selected_obj_l2_name=obj_names[1] if len(obj_names) > 1 else "",
        selected_obj_l3_name=obj_names[2] if len(obj_names) > 2 else "",
        kosis_actual_value=actual if actual is not None else "",
        kosis_actual_unit=actual_unit,
        kosis_period_used=used_period,
        kosis_previous_period_used=previous_period_used,
        claim_value_numeric=claim_value if claim_value is not None else "",
        verdict=verdict,
        verdict_code=code,
        verdict_reason=f"{reason} / {derive_reason}",
    )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()

    rows = [row for row in read_csv(Path(args.gold)) if nz(row.get("gold_tbl_id"))]
    meta_cache = {}
    out = []
    for idx, row in enumerate(rows, 1):
        try:
            verified = verify(row, meta_cache, args.delay)
        except Exception as exc:
            verified = dict(row)
            verified.update(verdict="판단불가", verdict_code="VERIFY_ERROR", verdict_reason=f"{type(exc).__name__}: {exc}")
        out.append(verified)
        print(f"{idx}/{len(rows)} {verified.get('claim_measurement_id')} {verified.get('gold_tbl_id')} -> {verified.get('verdict')}: {verified.get('verdict_reason')}")
    write_csv(Path(args.output), out)
    counts = {}
    for row in out:
        counts[row.get("verdict", "")] = counts.get(row.get("verdict", ""), 0) + 1
    print("saved=" + args.output)
    print("verdict_counts=" + ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
