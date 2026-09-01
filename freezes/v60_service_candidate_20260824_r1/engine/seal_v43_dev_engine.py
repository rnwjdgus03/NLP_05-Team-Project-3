#!/usr/bin/env python3
"""Write a reproducible development manifest for a v42-derived v43 engine."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


IGNORED_NAMES = {
    "__pycache__", ".pytest_cache", "freeze_manifest.json",
    "code_files_sha256.txt", "code_files_sha256_v43.txt",
    "prepare_ab",
}


def ignored(path: Path) -> bool:
    return any(
        part in IGNORED_NAMES or part.startswith(".test-tmp-")
        for part in path.parts
    ) or path.suffix in {".pyc", ".pyo"}


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--overlay-id", required=True)
    parser.add_argument("--parent-freeze-id", required=True)
    parser.add_argument("--parent-code-sha256", required=True)
    args = parser.parse_args()

    files = []
    digest = hashlib.sha256()
    for path in sorted(p for p in args.engine.rglob("*") if p.is_file()):
        rel_path = path.relative_to(args.engine)
        if ignored(rel_path):
            continue
        rel = rel_path.as_posix()
        sha = file_sha(path)
        size = path.stat().st_size
        digest.update(f"{sha}  {rel}\n".encode())
        files.append({"path": rel, "sha256": sha, "bytes": size})

    code_sha = digest.hexdigest()
    manifest = {
        "schema_version": "kosis-v43-development-manifest-v1",
        "freeze_id": args.overlay_id,
        "status": "DEVELOPMENT_ONLY_NOT_PROMOTED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_tree_sha256": code_sha,
        "parent_freeze": {
            "freeze_id": args.parent_freeze_id,
            "code_tree_sha256": args.parent_code_sha256,
        },
        "code_files": files,
        "evaluation_policy": (
            "Validate only on pre-existing non-blind URL development data; "
            "promotion requires a new locked URL evaluation."
        ),
    }
    (args.engine / "freeze_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.engine / "code_files_sha256_v43.txt").write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in files),
        encoding="utf-8",
    )
    print(json.dumps({
        "freeze_id": args.overlay_id,
        "status": manifest["status"],
        "code_tree_sha256": code_sha,
        "files": len(files),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
