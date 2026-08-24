#!/usr/bin/env python3
"""Freeze the v26e candidate before constructing a new blind gold set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


EXCLUDED_PARTS = {".pytest_cache", "__pycache__"}
EXCLUDED_PREFIXES = (".test-tmp-",)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def included(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    return not (
        any(part in EXCLUDED_PARTS for part in parts)
        or any(part.startswith(EXCLUDED_PREFIXES) for part in parts)
        or path.suffix in {".pyc", ".pyo"}
    )


def code_records(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and included(path, root)
    ]


def tree_digest(records: list[dict[str, object]]) -> str:
    payload = "".join(
        f"{record['sha256']}  {record['path']}\n" for record in records
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl_decisions(path: Path) -> Counter:
    counts: Counter = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            counts[json.loads(line)["claim_decision"]] += 1
    return counts


def verdict_counts(path: Path) -> Counter:
    text = path.read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("{"):
        return Counter(
            json.loads(line).get("verdict_code", "")
            for line in text.splitlines() if line.strip()
        )
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return Counter(row.get("verdict_code", "") for row in csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dev-gold", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=False)
    records = code_records(args.code)
    code_tree_sha256 = tree_digest(records)
    archive = args.out_dir / "v26e_frozen_code.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for record in records:
            path = args.code / str(record["path"])
            handle.add(path, arcname=f"app/{record['path']}", recursive=False)

    stage_a = json_read(args.run / "stage_a_table_recall_summary.json")
    coordinate = json_read(args.run / "coordinate_topk_summary.json")
    decisions = jsonl_decisions(args.run / "claim_decisions_safety_v2.csv")
    verdicts = verdict_counts(args.run / "verified_candidates_safety_v2.csv")
    manifest = {
        "schema_version": "kosis-v26e-freeze-v1",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": (
            "Code frozen after opened-development regression and safety audit; "
            "new blind articles and coordinate gold must be created only after this timestamp."
        ),
        "code_tree_sha256": code_tree_sha256,
        "code_file_count": len(records),
        "archive": {
            "path": str(archive),
            "bytes": archive.stat().st_size,
            "sha256": sha256(archive),
        },
        "opened_development_metrics": {
            "stage_a_table_top10": stage_a["metrics_all_eligible_gold"]["accuracy_at_10"],
            "table_item_top5": coordinate["metrics_all_eligible_gold"]["item"]["accuracy_at_5"],
            "coordinate_top5": coordinate["metrics_all_eligible_gold"]["coordinate"]["accuracy_at_5"],
            "full_top5": coordinate["metrics_all_eligible_gold"]["full"]["accuracy_at_5"],
            "gold_rows": coordinate["eligible_gold_rows"],
        },
        "opened_safety_audit": {
            "claim_decisions": dict(decisions),
            "value_mismatch_rows": verdicts.get("VALUE_MISMATCH", 0),
            "mismatch_blocked_rows": verdicts.get(
                "MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE", 0
            ),
        },
        "immutable_inputs": {
            "development_input": {"path": str(args.input), "sha256": sha256(args.input)},
            "development_gold": {"path": str(args.dev_gold), "sha256": sha256(args.dev_gold)},
            "semantic_index": {
                name: sha256(args.index / name)
                for name in ("tables.csv", "embeddings.npy", "manifest.json")
            },
        },
        "code_files": records,
    }
    manifest_path = args.out_dir / "freeze_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "manifest": str(manifest_path),
        "code_tree_sha256": code_tree_sha256,
        "archive_sha256": manifest["archive"]["sha256"],
        "opened_development_metrics": manifest["opened_development_metrics"],
        "opened_safety_audit": manifest["opened_safety_audit"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
