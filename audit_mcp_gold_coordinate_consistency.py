#!/usr/bin/env python3
"""Audit frozen KOSIS gold coordinates against official SQLite metadata.

This is intentionally an audit, not an automatic gold rewriter.  It detects
missing official codes and coordinates whose typed OBJ binding contradicts the
claim.  Rows with no explicit target are expected to use a real aggregate when
the official axis provides one.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from kosis_meta_coordinates import axis_target_alignment
from kosis_sqlite_metadata import clean
from kosis_sqlite_resolver import MetadataStore, aggregate_value, lookup_keys


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalized_gold_code(value: object) -> str:
    value = clean(value)
    return "" if value.upper() in {"N/A", "NA", "-"} else value


def claim_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    mapped: dict[str, dict[str, str]] = {}
    for row in rows:
        for key in lookup_keys(row):
            mapped[key] = row
    return mapped


def audit_row(
    gold: dict[str, str], claim: dict[str, str], store: MetadataStore
) -> dict[str, object]:
    org_id = clean(gold.get("gold_org_id"))
    tbl_id = clean(gold.get("gold_tbl_id"))
    table = store.table(org_id, tbl_id)
    items = {clean(row.get("itm_id")): row for row in store.items(org_id, tbl_id)}
    axes = {int(axis["axis_order"]): axis for axis in store.axes(org_id, tbl_id)}
    item_id = clean(gold.get("gold_itm_id"))
    item = items.get(item_id)
    coordinate: dict[str, str] = {}
    reasons: list[str] = []
    review_reasons: list[str] = []

    if table is None:
        reasons.append("TABLE_NOT_IN_OFFICIAL_METADATA")
    if item is None:
        reasons.append("ITEM_NOT_IN_OFFICIAL_METADATA")

    nonaggregate_without_target: list[str] = []
    for level in range(1, 9):
        code = normalized_gold_code(gold.get(f"gold_obj_l{level}"))
        if not code:
            continue
        axis = axes.get(level)
        if axis is None:
            reasons.append(f"OBJ_L{level}_AXIS_NOT_IN_OFFICIAL_METADATA")
            continue
        values = {clean(value.get("obj_code")): value for value in axis.get("values", [])}
        value = values.get(code)
        if value is None:
            reasons.append(f"OBJ_L{level}_CODE_NOT_IN_OFFICIAL_METADATA")
            continue
        coordinate[f"selected_obj_l{level}"] = code
        coordinate[f"selected_obj_l{level}_name"] = clean(value.get("obj_name"))
        coordinate[f"selected_obj_l{level}_axis_name"] = clean(axis.get("axis_name"))
        aggregate = aggregate_value(axis.get("values", []))
        # axis_target_alignment below determines whether this axis has a typed
        # target.  Preserve the aggregate comparison for the no-target case.
        if aggregate and clean(aggregate.get("obj_code")) != code:
            nonaggregate_without_target.append(str(level))

    alignment = axis_target_alignment(claim, coordinate)
    if alignment["enforceable"] and not alignment["strict_match"]:
        review_reasons.append("EXPLICIT_OBJ_TARGET_MISMATCH")
    if not alignment["enforceable"] and nonaggregate_without_target:
        review_reasons.append("NON_AGGREGATE_OBJ_WITHOUT_TYPED_TARGET")

    if reasons:
        status = "FAIL"
    elif review_reasons:
        status = "REVIEW"
    else:
        status = "PASS"
    return {
        **gold,
        "audit_status": status,
        "audit_reason": "|".join((*reasons, *review_reasons)),
        "official_tbl_name": clean(table.get("tbl_name")) if table else "",
        "official_itm_name": clean(item.get("itm_name")) if item else "",
        "official_itm_unit": clean(item.get("unit_name")) if item else "",
        **{
            f"official_obj_l{level}_name": coordinate.get(f"selected_obj_l{level}_name", "")
            for level in range(1, 9)
        },
        "typed_obj_enforceable": "Y" if alignment["enforceable"] else "N",
        "typed_obj_strict_match": "Y" if alignment["strict_match"] else "N",
        "typed_obj_matched": "|".join(alignment["matched"]),
        "typed_obj_missing": "|".join((*alignment["missing_axis"], *alignment["mismatched"])),
        "nonaggregate_without_target_levels": "|".join(nonaggregate_without_target),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--pass-output", type=Path)
    args = parser.parse_args()

    claims = claim_map(read_csv(args.claims))
    store = MetadataStore(args.metadata_db)
    try:
        audited = []
        for gold in read_csv(args.gold):
            claim = claims.get(clean(gold.get("gold_id")), gold)
            audited.append(audit_row(gold, claim, store))
    finally:
        store.close()
    write_csv(args.output, audited)
    if args.pass_output:
        write_csv(
            args.pass_output,
            [row for row in audited if clean(row.get("audit_status")) == "PASS"],
        )
    summary = {
        "gold_rows": len(audited),
        "status_counts": dict(Counter(clean(row.get("audit_status")) for row in audited)),
        "reason_counts": dict(Counter(
            reason
            for row in audited
            for reason in clean(row.get("audit_reason")).split("|")
            if reason
        )),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
