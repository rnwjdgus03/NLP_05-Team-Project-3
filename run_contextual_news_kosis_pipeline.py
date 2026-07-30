"""Run the context-preserving news-to-KOSIS pipeline.

Long-running HCX and BGE stages use their existing resumable outputs. The
numbered filenames are a stable handoff contract for local and Colab runs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STAGES = [
    "sentences",
    "chunks",
    "spans",
    "contexts",
    "retrieval",
    "measurements",
    "gate",
    "mapping",
]


def run(command: list[object]) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def should_stop(current: str, stop_after: str) -> bool:
    return STAGES.index(current) >= STAGES.index(stop_after)


def output_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "sentences": out_dir / "01_sentences.csv",
        "chunks": out_dir / "02_chunks.csv",
        "spans": out_dir / "03_claim_spans.csv",
        "span_progress": out_dir / "03_claim_spans_progress.csv",
        "contexts": out_dir / "03_claim_contexts.csv",
        "early_candidates": out_dir / "04_early_bge_candidates_top20.csv",
        "early_context": out_dir / "04_early_bge_context_top5.csv",
        "measurements": out_dir / "05_hcx_measurements.csv",
        "ready": out_dir / "06_mapping_ready.csv",
        "enrich": out_dir / "06_mapping_enrich.csv",
        "reject": out_dir / "06_mapping_reject.csv",
        "mapping": out_dir / "07_mapping",
    }


def run_if_missing(path: Path, command: list[object], force: bool) -> None:
    if path.exists() and not force:
        print(f"reuse={path}", flush=True)
        return
    run(command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run KSS, chunk/span detection, early BGE, HCX, and KOSIS mapping."
    )
    parser.add_argument("--articles", required=True, type=Path)
    parser.add_argument("--table-index", required=True, type=Path)
    parser.add_argument("--semantic-index", required=True, type=Path)
    parser.add_argument("--early-meta-index", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--model", default="HCX-007")
    parser.add_argument("--device", default="")
    parser.add_argument("--article-limit", type=int, default=0)
    parser.add_argument("--span-limit", type=int, default=0)
    parser.add_argument("--measurement-limit", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--overlap", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--stop-after", choices=STAGES, default="mapping")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for label, path in (
        ("article CSV", args.articles),
        ("KOSIS table index", args.table_index),
        ("BGE semantic index", args.semantic_index),
    ):
        if not path.exists():
            raise SystemExit(f"{label} not found: {path}")
    if args.early_meta_index and not args.early_meta_index.exists():
        raise SystemExit(f"early meta index not found: {args.early_meta_index}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths = output_paths(args.out_dir)

    preprocess = [
        sys.executable,
        SCRIPT_DIR / "preprocess_news.py",
        "--input",
        args.articles,
        "--output",
        paths["sentences"],
        "--splitter",
        "kss",
    ]
    if args.article_limit:
        preprocess.extend(["--limit", args.article_limit])
    if args.force:
        preprocess.append("--overwrite")
    run_if_missing(paths["sentences"], preprocess, args.force)
    if should_stop("sentences", args.stop_after):
        return

    chunks = [
        sys.executable,
        SCRIPT_DIR / "build_news_chunks.py",
        "--input",
        paths["sentences"],
        "--output",
        paths["chunks"],
        "--chunk-size",
        args.chunk_size,
        "--overlap",
        args.overlap,
    ]
    if args.force:
        chunks.append("--overwrite")
    run_if_missing(paths["chunks"], chunks, args.force)
    if should_stop("chunks", args.stop_after):
        return

    span_command = [
        sys.executable,
        SCRIPT_DIR / "detect_claim_spans_hcx.py",
        "--input",
        paths["chunks"],
        "--output",
        paths["spans"],
        "--progress-output",
        paths["span_progress"],
        "--model",
        args.model,
        "--sleep",
        args.sleep,
    ]
    if args.span_limit:
        span_command.extend(["--limit", args.span_limit])
    if args.force:
        span_command.append("--overwrite")
    run(span_command)
    if should_stop("spans", args.stop_after):
        return

    contexts = [
        sys.executable,
        SCRIPT_DIR / "build_claim_contexts.py",
        "--sentences",
        paths["sentences"],
        "--spans",
        paths["spans"],
        "--output",
        paths["contexts"],
    ]
    if args.force:
        contexts.append("--overwrite")
    run_if_missing(paths["contexts"], contexts, args.force)
    if should_stop("contexts", args.stop_after):
        return

    retrieval = [
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
        "20",
        "--rerank-top-k",
        "20",
        "--context-top-k",
        "5",
    ]
    if args.early_meta_index:
        retrieval.extend(["--meta-index", args.early_meta_index])
    if args.device:
        retrieval.extend(["--device", args.device])
    if args.no_reranker:
        retrieval.append("--no-reranker")
    if args.force:
        retrieval.append("--overwrite")
    run(retrieval)
    if should_stop("retrieval", args.stop_after):
        return

    extraction = [
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
    if args.measurement_limit:
        extraction.extend(["--limit", args.measurement_limit])
    if args.force:
        extraction.append("--overwrite")
    run(extraction)
    if should_stop("measurements", args.stop_after):
        return

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
        ]
    )
    if should_stop("gate", args.stop_after):
        return

    mapping = [
        sys.executable,
        SCRIPT_DIR / "run_kosis_measurement_pipeline.py",
        "--input",
        paths["measurements"],
        "--table-index",
        args.table_index,
        "--out-dir",
        paths["mapping"],
        "--retrieval-mode",
        "hybrid",
        "--semantic-index",
        args.semantic_index,
        "--semantic-top-k",
        "50",
        "--rerank-top-k",
        "20",
    ]
    if args.device:
        mapping.extend(["--device", args.device])
    if args.no_reranker:
        mapping.append("--no-reranker")
    if args.verify:
        mapping.append("--verify")
    run(mapping)
    run(
        [
            sys.executable,
            SCRIPT_DIR / "evaluate_contextual_kosis_run.py",
            "--run-dir",
            args.out_dir,
        ]
    )
    print(f"pipeline_complete={args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
