#!/usr/bin/env python3
"""Build the v8 Colab rerun bundle from frozen v6/v7 checkpoints."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/holdout8_stratified48_v8_checkpoint_gpu_colab.ipynb"
CHECKPOINTS = ROOT / "outputs/holdout8_stratified48_v6/gpu_results_20260809/extracted"
PREREG = ROOT / "docs/holdout8_v8_prereg_20260809.md"
OUTPUT_DIR = ROOT / "outputs/holdout8_stratified48_v8"
BUNDLE = OUTPUT_DIR / "holdout8_v8_checkpoint_colab_input_bundle.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_bundle() -> dict[str, object]:
    if not NOTEBOOK.is_file():
        raise FileNotFoundError(NOTEBOOK)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    archive_files: dict[str, Path] = {path.name: path for path in ROOT.glob("*.py")}
    for relative in (
        "requirements.txt",
        "requirements-ml.txt",
        "data/holdout8_stratified_articles.csv",
        "data/holdout8_stratified_assignments.csv",
        "data/holdout8_stratified_manifest.json",
        "data/seed_region_codes.csv",
        "data/reference/kosis_table_summary.csv",
    ):
        archive_files[relative] = ROOT / relative
    archive_files["docs/holdout8_v8_prereg_20260809.md"] = PREREG
    archive_files["data/checkpoints/01_sentences.csv"] = CHECKPOINTS / "01_sentences.csv"
    archive_files["data/checkpoints/03_claim_contexts.csv"] = CHECKPOINTS / "03_claim_contexts.csv"
    archive_files["data/checkpoints/05_hcx_measurements.csv"] = CHECKPOINTS / "05_hcx_measurements.csv"
    missing = [path for path in archive_files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle files missing: {missing}")

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "holdout8 v8 table-scope and table-diverse coordinate rerun",
        "secrets_included": False,
        "gold_included": False,
        "checkpoint_rows": {"sentences": 1054, "claim_contexts": 317, "measurements": 769},
        "files": {name: sha256(path) for name, path in archive_files.items()},
    }
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(archive_files.items()):
            archive.write(path, name)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    return manifest


def main() -> None:
    manifest = build_bundle()
    print(f"notebook={NOTEBOOK}")
    print(f"bundle={BUNDLE}")
    print(f"bundle_size={manifest['bundle_size_bytes']}")
    print(f"bundle_sha256={manifest['bundle_sha256']}")


if __name__ == "__main__":
    main()
