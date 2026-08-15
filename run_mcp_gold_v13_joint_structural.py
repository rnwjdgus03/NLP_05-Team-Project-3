#!/usr/bin/env python3
"""Reproduce v13 structural table ranking and joint ITEM/OBJ selection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(command: list[object]) -> None:
    printable = " ".join(str(value) for value in command)
    print(f"$ {printable}", flush=True)
    subprocess.run([str(value) for value in command], check=True, cwd=ROOT)


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claims", type=Path,
        default=ROOT / "outputs/mcp_gold_200_v11_metadata_reranker/input_bundle/data/dev/enriched_inputs.csv",
    )
    parser.add_argument(
        "--table-candidates", type=Path,
        default=ROOT / "outputs/mcp_gold_200_v11_metadata_reranker/input_bundle/data/dev/table_candidates.csv",
    )
    parser.add_argument(
        "--metadata-db", type=Path,
        default=ROOT / "outputs/mcp_gold_200_v12_structural/kosis_metadata.sqlite",
    )
    parser.add_argument(
        "--semantic-gold", type=Path,
        default=ROOT / "data/gold/mcp_actual_semantic_verified.csv",
    )
    parser.add_argument(
        "--coordinate-gold", type=Path,
        default=ROOT / "data/gold/mcp_actual_verified_23.csv",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/mcp_gold_200_v13_joint_structural_raw",
    )
    parser.add_argument("--structural-weight", type=float, default=0.8)
    parser.add_argument("--table-top-k", type=int, default=20)
    parser.add_argument("--item-top-k", type=int, default=10)
    args = parser.parse_args()

    required = (
        args.claims, args.table_candidates, args.metadata_db,
        args.semantic_gold, args.coordinate_gold,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("missing inputs: " + ", ".join(missing))
    if args.structural_weight < 0:
        parser.error("--structural-weight must be non-negative")

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    tables = out / "tables.csv"
    coordinates = out / "coordinates.csv"
    selected = out / "selected.csv"
    failures = out / "failures.csv"
    run([
        sys.executable, ROOT / "apply_kosis_structural_table_policy.py",
        "--claims", args.claims, "--candidates", args.table_candidates,
        "--metadata-db", args.metadata_db, "--output", tables,
        "--weight", args.structural_weight,
    ])
    run([
        sys.executable, ROOT / "kosis_sqlite_resolver.py",
        "--claims", args.claims, "--table-candidates", tables,
        "--metadata-db", args.metadata_db, "--candidate-output", coordinates,
        "--selected-output", selected, "--failure-output", failures,
        "--table-top-k", args.table_top_k, "--item-top-k", args.item_top_k,
        "--selection-mode", "joint",
    ])

    evaluations = {
        "mcp_actual_semantic": args.semantic_gold,
        "mcp_actual_coordinate23": args.coordinate_gold,
    }
    summary: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "v13_joint_structural",
        "structural_weight": args.structural_weight,
        "table_top_k": args.table_top_k,
        "item_top_k_per_table": args.item_top_k,
        "evaluations": {},
    }
    for name, gold in evaluations.items():
        eval_dir = out / f"eval_{name}"
        run([
            sys.executable, ROOT / "evaluate_mcp_gold_200_mapping.py",
            "--gold", gold, "--candidates", coordinates, "--mapped", selected,
            "--output-dir", eval_dir, "--ks", 1, 5, 10, 20,
        ])
        summary["evaluations"][name] = read_json(eval_dir / "summary.json")  # type: ignore[index]
    summary_path = out / "v13_run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
