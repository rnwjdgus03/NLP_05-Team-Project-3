"""Run a controlled previous-context-window ablation from fixed claim spans.

Sentence splitting and claim-span detection are intentionally not repeated.
Only the number of sentences before each fixed evidence span changes.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STAGES = ["contexts", "retrieval", "measurements", "gate"]


def run(command: list[object]) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def should_stop(current: str, stop_after: str) -> bool:
    return STAGES.index(current) >= STAGES.index(stop_after)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def output_paths(out_dir: Path, window: int) -> dict[str, Path]:
    method_dir = out_dir / f"prev_{window}"
    return {
        "dir": method_dir,
        "contexts": method_dir / "03_claim_contexts.csv",
        "early_candidates": method_dir / "04_early_bge_candidates_top20.csv",
        "early_context": method_dir / "04_early_bge_context_top5.csv",
        "measurements": method_dir / "05_hcx_measurements.csv",
        "ready": method_dir / "06_mapping_ready.csv",
        "enrich": method_dir / "06_mapping_enrich.csv",
        "reject": method_dir / "06_mapping_reject.csv",
        "all": method_dir / "06_in_ready_all.csv",
    }


def add_overwrite(command: list[object], overwrite: bool) -> None:
    if overwrite:
        command.append("--overwrite")


def run_window(args: argparse.Namespace, window: int) -> dict[str, object]:
    paths = output_paths(args.out_dir, window)
    paths["dir"].mkdir(parents=True, exist_ok=True)

    context_command: list[object] = [
        sys.executable,
        SCRIPT_DIR / "build_claim_contexts.py",
        "--sentences",
        args.sentences,
        "--spans",
        args.spans,
        "--output",
        paths["contexts"],
        "--previous-window",
        window,
        "--next-window",
        args.next_window,
        "--related-limit",
        args.related_limit,
        "--lead-sentences",
        args.lead_sentences,
    ]
    add_overwrite(context_command, args.overwrite)
    if args.overwrite or not paths["contexts"].exists():
        run(context_command)
    else:
        print(f"reuse={paths['contexts']}", flush=True)
    if should_stop("contexts", args.stop_after):
        return summarize(window, paths)

    retrieval_command: list[object] = [
        sys.executable,
        SCRIPT_DIR / "kosis_early_retrieve.py",
        "--input",
        paths["contexts"],
        "--output-candidates",
        paths["early_candidates"],
        "--output-context",
        paths["early_context"],
        "--semantic-index",
        args.semantic_index,
        "--semantic-top-k",
        args.semantic_top_k,
        "--rerank-top-k",
        args.rerank_top_k,
        "--context-top-k",
        args.context_top_k,
    ]
    if args.meta_index:
        retrieval_command.extend(["--meta-index", args.meta_index])
    if args.device:
        retrieval_command.extend(["--device", args.device])
    if args.no_reranker:
        retrieval_command.append("--no-reranker")
    add_overwrite(retrieval_command, args.overwrite)
    run(retrieval_command)
    if should_stop("retrieval", args.stop_after):
        return summarize(window, paths)

    extraction_command: list[object] = [
        sys.executable,
        SCRIPT_DIR / "extract_hcx.py",
        "--input",
        paths["contexts"],
        "--retrieval-context",
        paths["early_context"],
        "--output",
        paths["measurements"],
        "--model",
        args.model,
        "--sleep",
        args.sleep,
    ]
    add_overwrite(extraction_command, args.overwrite)
    run(extraction_command)
    if should_stop("measurements", args.stop_after):
        return summarize(window, paths)

    run(
        [
            sys.executable,
            SCRIPT_DIR / "prepare_kosis_mapping_input.py",
            "--input",
            paths["measurements"],
            "--output",
            paths["ready"],
            "--enrich-output",
            paths["enrich"],
            "--rejected-output",
            paths["reject"],
            "--all-output",
            paths["all"],
        ]
    )
    return summarize(window, paths)


def summarize(window: int, paths: dict[str, Path]) -> dict[str, object]:
    result: dict[str, object] = {
        "previous_window": window,
        "run_dir": str(paths["dir"]),
    }
    for name in ("contexts", "measurements", "all"):
        path = paths[name]
        result[f"{name}_rows"] = len(read_rows(path)) if path.exists() else 0
    if paths["all"].exists():
        rows = read_rows(paths["all"])
        result["in_ready"] = dict(
            Counter(str(row.get("in_ready", "")).strip().upper() for row in rows)
        )
        result["mapping_gate"] = dict(
            Counter(str(row.get("mapping_gate", "")).strip() for row in rows)
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare previous 1-5 sentence contexts using fixed spans."
    )
    parser.add_argument("--sentences", required=True, type=Path)
    parser.add_argument("--spans", required=True, type=Path)
    parser.add_argument("--semantic-index", required=True, type=Path)
    parser.add_argument("--meta-index", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--windows", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--next-window", type=int, default=0)
    parser.add_argument("--related-limit", type=int, default=0)
    parser.add_argument("--lead-sentences", type=int, default=3)
    parser.add_argument("--semantic-top-k", type=int, default=20)
    parser.add_argument("--rerank-top-k", type=int, default=20)
    parser.add_argument("--context-top-k", type=int, default=5)
    parser.add_argument("--model", default="HCX-007")
    parser.add_argument("--device", default="")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--stop-after", choices=STAGES, default="gate")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for label, path in (
        ("sentences", args.sentences),
        ("spans", args.spans),
        ("semantic index", args.semantic_index),
    ):
        if not path.exists():
            raise SystemExit(f"{label} not found: {path}")
    if args.meta_index and not args.meta_index.exists():
        raise SystemExit(f"meta index not found: {args.meta_index}")
    if not args.windows or any(window < 0 for window in args.windows):
        raise SystemExit("--windows must contain non-negative integers")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summaries = [run_window(args, window) for window in dict.fromkeys(args.windows)]
    summary_path = args.out_dir / "context_window_run_summary.json"
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"summary={summary_path}", flush=True)


if __name__ == "__main__":
    main()
