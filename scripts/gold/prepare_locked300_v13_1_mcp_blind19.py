#!/usr/bin/env python3
"""Re-freeze the still-blind 19 claims after a gold-free period repair.

The first v13 blind claim was inspected with KOSIS MCP and therefore became a
development diagnostic.  It must never be counted in the independent score.
The remaining IDs were selected before any of their KOSIS coordinates or values
were inspected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prepare_kosis_mapping_input import prepare
from scripts.gold.prepare_locked300_v13_mcp_blind20 import LOCKED_IDS, freeze


PROMOTED_TO_DEVELOPMENT = ("A2681-SP30B42ECECF-m1",)
BLIND_IDS = tuple(value for value in LOCKED_IDS if value not in PROMOTED_TO_DEVELOPMENT)
DEFAULT_SOURCE = (
    ROOT / "outputs/locked_holdout_300_v10_sqlite/gpu_results/05_hcx_measurements.csv"
)
DEFAULT_READY = ROOT / "data/locked300_v13_1_period_repaired_ready.csv"
DEFAULT_OUTPUT = ROOT / "data/locked300_v13_1_mcp_blind19_candidates.csv"
DEFAULT_MANIFEST = ROOT / "data/locked300_v13_1_mcp_blind19_candidates.manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(source: Path, ready: Path, output: Path, manifest_path: Path) -> dict[str, object]:
    # The same production prepare path is used; no gold field or v13 prediction
    # is available to the period-repair rule.
    prepare(source, ready)
    manifest = freeze(
        ready,
        output,
        manifest_path,
        locked_ids=BLIND_IDS,
        selection_version="locked300_v13_1_mcp_blind19_after_period_repair",
    )
    manifest.update(
        promoted_to_development=list(PROMOTED_TO_DEVELOPMENT),
        promotion_reason=(
            "KOSIS MCP inspection exposed an HCX comparison-year binding error; "
            "the inspected claim is excluded from all independent scores"
        ),
        raw_source_path=str(source.relative_to(ROOT)),
        raw_source_sha256=sha256(source),
        period_repair_module="prepare_kosis_mapping_input.py",
        period_repair_module_sha256=sha256(ROOT / "prepare_kosis_mapping_input.py"),
        independence_status="19 CLAIMS STILL UNSEEN; DO_NOT TUNE AFTER LABELING STARTS",
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--ready", type=Path, default=DEFAULT_READY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.ready, args.output, args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
