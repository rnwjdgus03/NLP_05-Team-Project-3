#!/usr/bin/env python3
"""Lock one KOSIS run to exact code, index, snapshot, input and parameters."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "kosis-hybrid-run-manifest-v1"
PIPELINE_ARTIFACT_PREFIXES = (
    "stage_a_", "stage_b_", "stage_c_", "local_coordinate_",
    "kosis_mcp_", "mcp_top2_", "kosis_api_", "hybrid_top5_",
    "metadata_hydration", "top5_merge_",
)
CODE_DIGEST_EXCLUDED_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_bundle_digest(root: Path) -> tuple[str, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if (
            any(part in CODE_DIGEST_EXCLUDED_DIRS for part in parts)
            or any(part.startswith(".test-tmp-") for part in parts)
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        records.append({
            "path": relative,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            f"{record['path']}\0{record['size']}\0{record['sha256']}\n".encode("utf-8")
        )
    return digest.hexdigest(), records


def semantic_index_record(root: Path) -> dict[str, Any]:
    files = {}
    for name in ("tables.csv", "embeddings.npy", "manifest.json"):
        path = root / name
        if not path.exists():
            raise FileNotFoundError(f"semantic index file missing: {path}")
        files[name] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(f"{name}\0{value['size']}\0{value['sha256']}\n".encode("utf-8"))
    return {"root": str(root), "sha256": digest.hexdigest(), "files": files}


def parse_parameters(values: list[str]) -> dict[str, str]:
    output = {}
    for raw in values:
        key, separator, value = raw.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"parameter must be NAME=VALUE: {raw!r}")
        if key.strip() in output:
            raise ValueError(f"duplicate parameter: {key.strip()}")
        output[key.strip()] = value.strip()
    return dict(sorted(output.items()))


def fingerprint_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: manifest[key]
        for key in (
            "schema_version", "run_id", "source_bundle", "code_bundle_sha256",
            "semantic_index", "postgres_snapshot", "claims", "parameters",
        )
    }


def run_fingerprint(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        fingerprint_payload(manifest), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def existing_pipeline_artifacts(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(
        child.name for child in path.iterdir()
        if child.name != "run_manifest.json"
        and child.name.startswith(PIPELINE_ARTIFACT_PREFIXES)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--semantic-index", required=True, type=Path)
    parser.add_argument("--postgres-manifest", required=True, type=Path)
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--parameter", action="append", default=[])
    args = parser.parse_args()

    for path in (args.bundle_root, args.semantic_index):
        if not path.is_dir():
            raise NotADirectoryError(path)
    for path in (args.postgres_manifest, args.claims):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.source_bundle is not None and not args.source_bundle.is_file():
        raise FileNotFoundError(args.source_bundle)

    code_digest, code_files = code_bundle_digest(args.bundle_root)
    postgres_manifest = json.loads(args.postgres_manifest.read_text(encoding="utf-8"))
    source_bundle = None
    if args.source_bundle is not None:
        source_bundle = {
            "path": str(args.source_bundle),
            "size": args.source_bundle.stat().st_size,
            "sha256": sha256_file(args.source_bundle),
        }
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(args.out_dir),
        "source_bundle": source_bundle,
        "code_bundle_sha256": code_digest,
        "code_file_count": len(code_files),
        "code_files": code_files,
        "semantic_index": semantic_index_record(args.semantic_index),
        "postgres_snapshot": {
            "manifest_path": str(args.postgres_manifest),
            "manifest_sha256": sha256_file(args.postgres_manifest),
            "snapshot_id": str(postgres_manifest.get("snapshot_id") or ""),
            "semantic_tables_sha256": str(
                postgres_manifest.get("semantic_tables_sha256") or ""
            ),
        },
        "claims": {
            "path": str(args.claims),
            "size": args.claims.stat().st_size,
            "sha256": sha256_file(args.claims),
        },
        "parameters": parse_parameters(args.parameter),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
    }
    manifest["run_fingerprint"] = run_fingerprint(manifest)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    output = args.out_dir / "run_manifest.json"
    if output.exists():
        current = json.loads(output.read_text(encoding="utf-8"))
        if current.get("run_fingerprint") != manifest["run_fingerprint"]:
            raise RuntimeError(
                "run manifest mismatch; use a new OUT_DIR instead of mixing artifacts"
            )
        print("RUN MANIFEST RESUME OK =", output)
        print("run_fingerprint =", manifest["run_fingerprint"])
        return

    stale = existing_pipeline_artifacts(args.out_dir)
    if stale:
        raise RuntimeError(
            "OUT_DIR already contains pipeline artifacts without a manifest: "
            + ", ".join(stale[:20])
        )
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(output)
    print("RUN MANIFEST CREATED =", output)
    print("run_fingerprint =", manifest["run_fingerprint"])


if __name__ == "__main__":
    main()
