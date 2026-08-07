#!/usr/bin/env python3
"""Build the secret-free upload bundle for the gold-200 Colab GPU run."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "outputs" / "colab" / "mcp_gold_200_coordinate_ab_colab_bundle_v6.zip"

FILES = (
    "requirements-ml.txt",
    "kosis_claim_shape.py",
    "kosis_scope_gate.py",
    "prepare_kosis_mapping_input.py",
    "kosis_semantic_search.py",
    "kosis_match_claims_to_index.py",
    "kosis_meta_coordinates.py",
    "kosis_build_embedding_index.py",
    "kosis_load_chroma_table_index.py",
    "enrich_mcp_gold_200_inputs.py",
    "build_mcp_gold_200_lexical_table_candidates.py",
    "search_mcp_gold_200_chroma_bge.py",
    "rerank_mcp_gold_200_table_candidates.py",
    "select_mcp_gold_200_two_stage_coordinates.py",
    "compare_mcp_gold_200_coordinate_ab.py",
    "kosis_build_chroma_meta_index.py",
    "kosis_chroma_hybrid_search.py",
    "evaluate_mcp_gold_200_mapping.py",
    "data/reference/kosis_table_summary.csv",
    "data/reference/kosis_gold10_meta_index.csv",
    "data/reference/kosis_gold10_mcp_meta_missing6.csv",
    "data/reference/kosis_gold10_mcp_meta_missing6_manifest.json",
    "data/gold/mcp_full_gold_200.csv",
    "data/gold/mcp_full_gold_200_inputs.csv",
    "data/seed_region_codes.csv",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    missing = [rel for rel in FILES if not (ROOT / rel).exists()]
    if missing:
        raise SystemExit("번들 필수 파일이 없습니다: " + ", ".join(missing))

    manifest = {
        "bundle_version": 6,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "MCP gold 200 v6 structure-aware coordinate shortlist A/B",
        "files": {rel: sha256(ROOT / rel) for rel in FILES},
        "search_input": "data/gold/mcp_full_gold_200_inputs.csv",
        "evaluation_gold": "data/gold/mcp_full_gold_200.csv",
        "gold_used_for_retrieval": False,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for rel in FILES:
            archive.write(ROOT / rel, arcname=rel)
        archive.writestr(
            "bundle_manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    print(f"bundle={output}")
    print(f"files={len(FILES)} bytes={output.stat().st_size}")


if __name__ == "__main__":
    main()
