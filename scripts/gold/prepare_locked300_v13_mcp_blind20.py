#!/usr/bin/env python3
"""Freeze 20 disjoint claims before looking at v13 predictions or coordinates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = (
    ROOT / "outputs/locked_holdout_300_v10_sqlite/gpu_results/07_mapping_sqlite"
    / "05_hcx_measurements_kosis_ready.csv"
)
DEFAULT_OUTPUT = ROOT / "data/locked300_v13_mcp_blind20_candidates.csv"
DEFAULT_MANIFEST = ROOT / "data/locked300_v13_mcp_blind20_candidates.manifest.json"

# Selected from claim text, structured period/axis fields, and source diversity only.
# No table candidate, SQLite coordinate, KOSIS API response, or v13 prediction was used.
LOCKED_IDS = (
    "A2681-SP30B42ECECF-m1",  # multicultural birth
    "A0673-SPFFFDAEF95A-m1",  # county employment rate
    "A1411-SP5F8BCC33E4-m2",  # age-group net worth
    "A2648-SP179F478D32-m6",  # age x industry employment change
    "A2657-SP7761543E77-m1",  # foreign residents
    "A1381-SP5C0FA03C99-m1",  # farm households
    "A1940-SPF9ECF92995-m1",  # household income
    "A2195-SP58D2B7A6CE-m1",  # one-person households
    "A2386-SP476B05C816-m3",  # historical illiteracy count
    "A2284-SPCBEB52F561-m1",  # regional GRDP
    "A1019-SP67B37A8EED-m1",  # spouse-age marriage count
    "A0964-SP596B552885-m1",  # enterprise-size wage
    "A0148-SP4A2E2CE320-m1",  # enterprise-size starting salary
    "A2015-SP474A13E300-m1",  # GNI per capita
    "A0834-SPE8364569CF-m3",  # historical GNI per capita
    "A2335-SP264A54BFC4-m1",  # monthly construction output
    "A2666-SP91F468293F-m1",  # rent transactions
    "A2691-SP1ADEC33A36-m2",  # trade concentration
    "A1121-SP787A049679-m2",  # floating population
    "A1960-SP54F638689B-m1",  # age-group consumption propensity
)

SAFE_FIELDS = (
    "claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
    "claim_text", "prev_sentence", "next_sentence", "measurement_indicator",
    "measurement_item", "measurement_role", "value", "unit", "value_type",
    "semantic_type", "period", "period_end", "prd_se", "comparison_period",
    "change_base", "region", "age_group", "gender", "industry_or_item",
    "origin_country", "destination_country", "entity_type", "unit_dimension",
    "claim_domain_scope", "measurement_usage", "measurement_binding_source",
    "measurement_period", "measurement_prd_se", "mapping_eligible", "mapping_gate",
    "extraction_confidence", "measurement_repaired", "measurement_fallback_count",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_display_path(path: Path) -> str:
    """Use a repository-relative path when possible, absolute otherwise."""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def freeze(
    source: Path,
    output: Path,
    manifest_path: Path,
    *,
    locked_ids: tuple[str, ...] = LOCKED_IDS,
    selection_version: str = "locked300_v13_mcp_blind20",
) -> dict[str, object]:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {str(row.get("claim_measurement_id") or "").strip(): row for row in rows}
    missing = [claim_id for claim_id in locked_ids if claim_id not in by_id]
    if missing:
        raise ValueError(f"locked claims missing from source: {missing}")
    selected = [{field: by_id[claim_id].get(field, "") for field in SAFE_FIELDS} for claim_id in locked_ids]
    if len({row["claim_measurement_id"] for row in selected}) != len(locked_ids):
        raise ValueError("claim IDs are not unique")
    if len({row["article_id"] for row in selected}) != len(locked_ids):
        raise ValueError("blind holdout must contain one unique article per claim")
    if any(not row["measurement_indicator"].strip() for row in selected):
        raise ValueError("measurement indicator missing")
    if any(not row["period"].strip() or not row["prd_se"].strip() for row in selected):
        raise ValueError("period or periodicity missing")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SAFE_FIELDS))
        writer.writeheader()
        writer.writerows(selected)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FROZEN_UNLABELED",
        "selection_version": selection_version,
        "selection_basis": "claim text + HCX structured period/axis + source diversity only",
        "forbidden_at_selection": [
            "v13 table predictions", "SQLite coordinate predictions",
            "KOSIS API values", "KOSIS gold coordinates",
        ],
        "source_path": manifest_display_path(source),
        "source_sha256": sha256(source),
        "output_path": manifest_display_path(output),
        "output_sha256": sha256(output),
        "rows": len(selected),
        "unique_articles": len({row["article_id"] for row in selected}),
        "claim_measurement_ids": list(locked_ids),
        "label_status": "UNLABELED_DO_NOT_SCORE",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    print(json.dumps(freeze(args.source, args.output, args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
