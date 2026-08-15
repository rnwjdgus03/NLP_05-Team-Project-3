#!/usr/bin/env python3
"""Freeze a 30-article v14 holdout before KOSIS labels are inspected.

Sixteen rows retain their untouched status from the v13 freeze.  Four v13
claims used for debugging are excluded.  Fourteen additional articles are
chosen from the same locked article corpus using only claim text, source,
periodicity, domain and KOSIS-scope plausibility.  Retrieval predictions,
table IDs, coordinates and KOSIS values are forbidden inputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gold.prepare_locked300_v13_mcp_blind20 import LOCKED_IDS, freeze, sha256


DEVELOPMENT_IDS = (
    "A2681-SP30B42ECECF-m1",
    "A0673-SPFFFDAEF95A-m1",
    "A1411-SP5F8BCC33E4-m2",
    "A1381-SP5C0FA03C99-m1",
)
RETAINED_UNTOUCHED_IDS = tuple(value for value in LOCKED_IDS if value not in DEVELOPMENT_IDS)

# Fixed before running v14 on these rows.  The set deliberately contains both
# likely KOSIS series and official/non-KOSIS boundary controls so READY precision
# can be scored together with retrieval recall.
NEW_IDS = (
    "A0495-SPD347F35204-m1",  # completed unsold housing, monthly
    "A0835-SPC2BB4BE058-m1",  # monthly average wage
    "A0904-SP44BF876821-m1",  # bar-service production, monthly
    "A0912-SPD1111F3FEA-m1",  # household-finance retirement living cost
    "A1341-SP1D18743548-m3",  # industry employment change, quarterly
    "A2606-SP1ACA18560A-m1",  # infant cause of death
    "A2614-SPF52356A9A7-m2",  # online food-service transactions
    "A2676-SP7584553AD8-m1",  # age-group non-wage workers
    "A2680-SP37B568B3E8-m2",  # unemployment rate
    "A2686-SPA255D86131-m2",  # GDP growth
    "A0361-SPB0D4FE646E-m1",  # private pet-household report control
    "A0393-SP3E1B566FB8-m2",  # brand vehicle sales control
    "A1719-SPC545842473-m4",  # insurer surrender refund control
    "A2032-SP065E5AB651-m1",  # real-estate credit aggregate boundary
)
BLIND_IDS = RETAINED_UNTOUCHED_IDS + NEW_IDS

DEFAULT_SOURCE = ROOT / "data/locked300_v13_1_period_repaired_ready.csv"
DEFAULT_OUTPUT = ROOT / "data/locked300_v14_mcp_blind30_candidates.csv"
DEFAULT_MANIFEST = ROOT / "data/locked300_v14_mcp_blind30_candidates.manifest.json"


def build(source: Path, output: Path, manifest_path: Path) -> dict[str, object]:
    if len(BLIND_IDS) != 30:
        raise ValueError(f"expected 30 frozen IDs, got {len(BLIND_IDS)}")
    manifest = freeze(
        source, output, manifest_path,
        locked_ids=BLIND_IDS,
        selection_version="locked300_v14_mcp_blind30_hybrid_retrieval",
    )
    manifest.update({
        "development_ids_excluded": list(DEVELOPMENT_IDS),
        "retained_unseen_from_v13": list(RETAINED_UNTOUCHED_IDS),
        "newly_frozen_ids": list(NEW_IDS),
        "strata_intent": {
            "periodicity": ["Y", "Q", "M"],
            "axes": ["age", "region", "country", "industry_or_item", "aggregate"],
            "scope": ["likely_KOSIS", "official_non_KOSIS", "private_source_control"],
        },
        "code_freeze_sha256": {
            "prepare_kosis_mapping_input.py": sha256(ROOT / "prepare_kosis_mapping_input.py"),
            "kosis_sqlite_table_fts.py": sha256(ROOT / "kosis_sqlite_table_fts.py"),
            "merge_kosis_table_candidate_pools.py": sha256(ROOT / "merge_kosis_table_candidate_pools.py"),
            "kosis_meta_coordinates.py": sha256(ROOT / "kosis_meta_coordinates.py"),
            "apply_kosis_structural_table_policy.py": sha256(ROOT / "apply_kosis_structural_table_policy.py"),
        },
        "independence_status": (
            "FROZEN BEFORE V14 PREDICTIONS AND KOSIS LABELS; "
            "DO NOT CHANGE RULES AFTER LABELING STARTS"
        ),
        "source_sha256": sha256(source),
    })
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
