#!/usr/bin/env python3
"""Second-pass audit for semantic, unit and period consistency of MCP gold.

The coordinate audit proves that official codes exist and typed OBJ bindings
are plausible.  This audit additionally asks whether the selected table/ITEM
answers the extracted indicator and whether the frozen period agrees with the
gold-free claim extraction.  It never rewrites gold; suspicious rows are
separated for actual KOSIS/MCP review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from audit_mcp_gold_coordinate_consistency import audit_row as coordinate_audit_row
from kosis_indicator_table_match import indicator_table_mismatch
from kosis_meta_coordinates import unit_dimension_compatible
from kosis_sqlite_metadata import clean
from kosis_sqlite_resolver import MetadataStore, lookup_keys
from prepare_kosis_mapping_input import unit_dimension


EMPTY = {"", "-", "N/A", "NA", "NAN", "NONE", "NULL"}


def explicit_concept_mismatch(indicator: str, claim_text: str, item_name: str) -> str:
    """Return a high-precision concept contradiction between claim and ITEM.

    Character n-gram overlap is intentionally permissive for retrieval, but it
    cannot distinguish ``수입액`` from ``수출액`` because both share ``입액``.
    Gold auditing needs the opposite behaviour: only explicit contradictions
    are rejected.  These checks describe general statistical concepts and do
    not depend on a table id.
    """
    claim = " ".join(part for part in (clean(indicator), clean(claim_text)) if part)
    item = clean(item_name)
    if not claim or not item:
        return ""

    compact_claim = "".join(claim.split())
    compact_item = "".join(item.split())
    claim_import = "수입" in compact_claim and "수출입" not in compact_claim
    claim_export = "수출" in compact_claim and "수출입" not in compact_claim
    item_import = "수입" in compact_item and "수출입" not in compact_item
    item_export = "수출" in compact_item and "수출입" not in compact_item
    if claim_import and item_export and not item_import:
        return "IMPORT_EXPORT_DIRECTION_MISMATCH"
    if claim_export and item_import and not item_export:
        return "IMPORT_EXPORT_DIRECTION_MISMATCH"

    count_or_volume = any(
        term in compact_claim
        for term in ("수출대수", "수입대수", "수출물량", "수입물량", "수출수량", "수입수량")
    )
    if count_or_volume and any(term in compact_item for term in ("수출액", "수입액")):
        return "TRADE_COUNT_AMOUNT_MISMATCH"

    mutually_exclusive = (
        (("취업자", "고용자"), ("실업률", "실업자")),
        (("실업률",), ("취업자", "고용자")),
    )
    for claim_terms, item_terms in mutually_exclusive:
        if any(term in compact_claim for term in claim_terms) and any(
            term in compact_item for term in item_terms
        ):
            return "EMPLOYMENT_CONCEPT_MISMATCH"
    return ""


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


def value(row: dict[str, str], *fields: str) -> str:
    for field in fields:
        text = clean(row.get(field))
        if text.upper() not in EMPTY:
            return text
    return ""


def claim_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    mapped: dict[str, dict[str, str]] = {}
    for row in rows:
        for key in lookup_keys(row):
            mapped[key] = row
    return mapped


def obj_names(audited: dict[str, object]) -> str:
    return " ".join(
        clean(audited.get(f"official_obj_l{level}_name")) for level in range(1, 9)
        if clean(audited.get(f"official_obj_l{level}_name"))
    )


def semantic_indicator(claim: dict[str, str]) -> str:
    explicit = value(claim, "measurement_indicator", "indicator", "item_intent_terms")
    # Missing structured indicators are themselves low-confidence.  The local
    # claim text is still useful for catching strong contradictions such as
    # 혼인 -> 출생아수, but it must not make a row PASS by itself.
    return explicit or value(claim, "claim_text")


def audit_row(
    gold: dict[str, str], claim: dict[str, str], store: MetadataStore
) -> dict[str, object]:
    coordinate = coordinate_audit_row(gold, claim, store)
    reasons: list[str] = []
    if clean(coordinate.get("audit_status")) != "PASS":
        reasons.extend(
            reason for reason in clean(coordinate.get("audit_reason")).split("|") if reason
        )

    org_id = value(gold, "gold_org_id")
    tbl_id = value(gold, "gold_tbl_id")
    table = store.table(org_id, tbl_id) or {}
    item_id = value(gold, "gold_itm_id")
    item = next(
        (row for row in store.items(org_id, tbl_id) if clean(row.get("itm_id")) == item_id),
        {},
    )
    indicator = semantic_indicator(claim)
    explicit_indicator = value(claim, "measurement_indicator", "indicator", "item_intent_terms")
    mismatch = indicator_table_mismatch(
        indicator,
        clean(table.get("tbl_name") or gold.get("gold_tbl_name")),
        clean(item.get("itm_name") or gold.get("gold_item_name")),
        obj_names(coordinate),
        clean(table.get("category_path")),
        org_id=org_id,
        org_name=clean(table.get("organization_name")),
    )
    if mismatch:
        reasons.append("INDICATOR_TABLE_ITEM_MISMATCH")
    concept_mismatch = explicit_concept_mismatch(
        indicator,
        value(claim, "claim_text") or value(gold, "claim_text"),
        clean(item.get("itm_name") or gold.get("gold_item_name")),
    )
    if concept_mismatch:
        reasons.append(concept_mismatch)
    if not explicit_indicator:
        reasons.append("STRUCTURED_INDICATOR_MISSING")

    claim_prd = value(claim, "measurement_prd_se", "prd_se").upper()
    gold_prd = value(gold, "gold_prd_se").upper()
    if gold_prd and not claim_prd:
        reasons.append("STRUCTURED_PERIODICITY_MISSING")
    if claim_prd and gold_prd and claim_prd != gold_prd:
        reasons.append("PERIODICITY_MISMATCH")
    claim_period = value(claim, "measurement_period", "period")
    gold_period = value(gold, "gold_period")
    if gold_period and not claim_period:
        reasons.append("STRUCTURED_TARGET_PERIOD_MISSING")
    if claim_period and gold_period and claim_period != gold_period:
        reasons.append("TARGET_PERIOD_MISMATCH")
    claim_previous = value(claim, "previous_period", "comparison_period")
    gold_previous = value(gold, "gold_previous_period")
    if gold_previous and not claim_previous:
        reasons.append("STRUCTURED_PREVIOUS_PERIOD_MISSING")
    if claim_previous and gold_previous and claim_previous != gold_previous:
        reasons.append("PREVIOUS_PERIOD_MISMATCH")

    claim_dimension = value(claim, "unit_dimension") or unit_dimension(
        value(claim, "canonical_unit", "unit", "claim_unit")
    )
    source_unit = value(item, "unit_name") or value(gold, "gold_source_unit")
    source_dimension = unit_dimension(source_unit)
    semantic = value(claim, "semantic_type").lower()
    derived = semantic in {"rate_change", "absolute_change"} or "derived" in value(
        gold, "gold_derivation_method"
    ).lower()
    if not derived and not unit_dimension_compatible(
        claim_dimension, source_dimension, value(claim, "mapping_type")
    ):
        reasons.append("DIRECT_UNIT_DIMENSION_MISMATCH")

    unique_reasons = list(dict.fromkeys(reasons))
    status = "PASS" if not unique_reasons else "REVIEW"
    return {
        **gold,
        "semantic_audit_status": status,
        "semantic_audit_reason": "|".join(unique_reasons),
        "semantic_indicator": indicator,
        "semantic_indicator_explicit": "Y" if explicit_indicator else "N",
        "semantic_table_item_mismatch_detail": mismatch,
        "semantic_explicit_concept_mismatch": concept_mismatch,
        "semantic_claim_unit_dimension": claim_dimension,
        "semantic_source_unit_dimension": source_dimension,
        "semantic_derived_mapping": "Y" if derived else "N",
        "semantic_claim_prd_se": claim_prd,
        "semantic_claim_period": claim_period,
        "semantic_claim_previous_period": claim_previous,
        "coordinate_audit_status": clean(coordinate.get("audit_status")),
        "coordinate_audit_reason": clean(coordinate.get("audit_reason")),
        "official_tbl_name": clean(coordinate.get("official_tbl_name")),
        "official_itm_name": clean(coordinate.get("official_itm_name")),
        "official_itm_unit": clean(coordinate.get("official_itm_unit")),
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
        audited = [
            audit_row(gold, claims.get(value(gold, "gold_id"), gold), store)
            for gold in read_csv(args.gold)
        ]
    finally:
        store.close()
    write_csv(args.output, audited)
    passed = [row for row in audited if row["semantic_audit_status"] == "PASS"]
    if args.pass_output:
        write_csv(args.pass_output, passed)
    summary = {
        "gold_rows": len(audited),
        "pass_rows": len(passed),
        "status_counts": dict(Counter(row["semantic_audit_status"] for row in audited)),
        "reason_counts": dict(Counter(
            reason for row in audited
            for reason in clean(row["semantic_audit_reason"]).split("|") if reason
        )),
        "warning": "Rule-audited diagnostic subset; not a substitute for independent actual KOSIS/MCP labels.",
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
