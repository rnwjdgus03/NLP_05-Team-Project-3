#!/usr/bin/env python3
"""Run table retrieval outputs through SQLite exact resolution and KOSIS API validation."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(command: list[object]) -> None:
    cmd = [str(value) for value in command]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--table-candidates", type=Path, required=True)
    parser.add_argument("--meta-index", type=Path, required=True)
    parser.add_argument("--table-index", type=Path)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--table-top-k", type=int, default=10)
    parser.add_argument("--item-top-k", type=int, default=5)
    parser.add_argument(
        "--selection-mode", choices=("joint", "table_top3", "table_locked"), default="joint"
    )
    parser.add_argument("--validate-api", action="store_true")
    parser.add_argument("--verify-values", action="store_true")
    args = parser.parse_args()
    if args.verify_values and not args.validate_api:
        parser.error("--verify-values requires --validate-api")
    for label, path in (
        ("claims", args.claims),
        ("table candidates", args.table_candidates),
        ("meta index", args.meta_index),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    build = [
        sys.executable, ROOT / "kosis_sqlite_metadata.py", "--db", args.metadata_db,
        "--meta-index", args.meta_index,
    ]
    if args.table_index:
        build.extend(["--table-index", args.table_index])
    run(build)

    candidates = args.out_dir / "01_sqlite_coordinate_candidates.csv"
    selected = args.out_dir / "02_sqlite_selected_coordinates.csv"
    failures = args.out_dir / "02_sqlite_resolution_failures.csv"
    run([
        sys.executable, ROOT / "kosis_sqlite_resolver.py",
        "--claims", args.claims,
        "--table-candidates", args.table_candidates,
        "--metadata-db", args.metadata_db,
        "--candidate-output", candidates,
        "--selected-output", selected,
        "--failure-output", failures,
        "--table-top-k", args.table_top_k,
        "--item-top-k", args.item_top_k,
        "--selection-mode", args.selection_mode,
    ])

    validated = args.out_dir / "03_sqlite_api_validated.csv"
    verified = args.out_dir / "04_sqlite_value_verified.csv"
    if args.validate_api and read_csv(selected):
        run([
            sys.executable, ROOT / "kosis_validate_mapping_candidates.py",
            "--input", selected,
            "--meta-index", args.meta_index,
            "--output", validated,
            "--strict-seeded-coordinate",
            "--item-top-k", "1",
            "--obj-top-k", "1",
            "--max-combinations", "1",
            "--allow-provisional",
        ])
    else:
        rows = read_csv(selected)
        fields = list(rows[0]) if rows else []
        for field in ("mapping_status", "mapping_reason"):
            if field not in fields:
                fields.append(field)
        pending = [
            {**row, "mapping_status": "PENDING_API_VALIDATION", "mapping_reason": "API_NOT_REQUESTED"}
            for row in rows
        ]
        if fields:
            write_csv(validated, pending, fields)

    validated_rows = read_csv(validated)
    if args.verify_values:
        ready = [row for row in validated_rows if row.get("mapping_status") == "READY"]
        verify_input = args.out_dir / "04_sqlite_verify_input.csv"
        if ready:
            write_csv(verify_input, ready, list(ready[0]))
            run([
                sys.executable, ROOT / "kosis_verify_claim_values.py",
                "--input", verify_input,
                "--output", verified,
                "--delay", "0.12",
                "--use-pinned-item",
            ])

    summary = {
        "architecture": "table-vector-search -> sqlite-exact-resolver -> kosis-api",
        "coordinate_chroma_used": False,
        "claims": len(read_csv(args.claims)),
        "table_candidate_rows": len(read_csv(args.table_candidates)),
        "sqlite_coordinate_candidates": len(read_csv(candidates)),
        "sqlite_selected_coordinates": len(read_csv(selected)),
        "sqlite_resolution_failures": len(read_csv(failures)),
        "mapping_status_counts": dict(Counter(row.get("mapping_status", "") for row in validated_rows)),
        "verified_rows": len(read_csv(verified)),
        "metadata_db": str(args.metadata_db),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
