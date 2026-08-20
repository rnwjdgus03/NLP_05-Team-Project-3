#!/usr/bin/env python3
"""Create an immutable v24b code/input/gold freeze after hash verification."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path("/home/ubuntu/kosis-project")
SOURCE_APP = PROJECT / "app"
V24_RUN = PROJECT / "runs/hybrid_bge_m3_postgres_mcp_v24b_period_stage_b_slots_20260820"
FREEZE = PROJECT / "freezes/v24b_20260820_blind"
BLIND_INPUT = Path("/tmp/blind_official_release_measurements31.csv")
BLIND_GOLD = Path("/tmp/blind_official_release_coordinate_gold31_locked.csv")
BLIND_GOLD_MANIFEST = Path("/tmp/blind_official_release_coordinate_gold31_lock_manifest.json")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if FREEZE.exists():
    raise SystemExit(f"freeze already exists; refusing overwrite: {FREEZE}")
for required in (SOURCE_APP, V24_RUN / "run_manifest.json", BLIND_INPUT, BLIND_GOLD, BLIND_GOLD_MANIFEST):
    if not required.exists():
        raise FileNotFoundError(required)

sys.path.insert(0, str(SOURCE_APP))
from write_kosis_run_manifest import code_bundle_digest

v24_manifest = json.loads((V24_RUN / "run_manifest.json").read_text(encoding="utf-8"))
live_code_sha, live_files = code_bundle_digest(SOURCE_APP)
expected = v24_manifest["code_bundle_sha256"]
if live_code_sha != expected:
    raise RuntimeError(f"live code differs from completed v24b: {live_code_sha} != {expected}")

FREEZE.mkdir(parents=True)
shutil.copytree(SOURCE_APP, FREEZE / "app", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".test-tmp-*", "*.pyc", "*.pyo"))
shutil.copy2(V24_RUN / "run_manifest.json", FREEZE / "v24b_completed_run_manifest.json")
shutil.copy2(BLIND_INPUT, FREEZE / BLIND_INPUT.name)
shutil.copy2(BLIND_GOLD, FREEZE / BLIND_GOLD.name)
shutil.copy2(BLIND_GOLD_MANIFEST, FREEZE / BLIND_GOLD_MANIFEST.name)

frozen_code_sha, frozen_files = code_bundle_digest(FREEZE / "app")
if frozen_code_sha != expected:
    raise RuntimeError(f"copied code hash mismatch: {frozen_code_sha} != {expected}")

manifest = {
    "schema_version": "v24b-blind-freeze-v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "freeze_root": str(FREEZE),
    "v24b_run_id": v24_manifest["run_id"],
    "v24b_run_fingerprint": v24_manifest["run_fingerprint"],
    "code_bundle_sha256": frozen_code_sha,
    "code_file_count": len(frozen_files),
    "semantic_index_sha256": v24_manifest["semantic_index"]["sha256"],
    "postgres_snapshot_id": v24_manifest["postgres_snapshot"]["snapshot_id"],
    "blind_input_sha256": file_sha(FREEZE / BLIND_INPUT.name),
    "blind_gold_sha256": file_sha(FREEZE / BLIND_GOLD.name),
    "blind_gold_manifest_sha256": file_sha(FREEZE / BLIND_GOLD_MANIFEST.name),
    "prediction_artifacts_present_at_freeze": False,
    "parameters": v24_manifest["parameters"],
}
(FREEZE / "freeze_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
)

for path in sorted(FREEZE.rglob("*"), reverse=True):
    if path.is_file():
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    elif path.is_dir():
        path.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
FREEZE.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
