#!/usr/bin/env python3
"""Run the full KOSIS table BGE -> Chroma -> gold-200 evaluation chain."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATUS = ROOT / "outputs" / "runs" / "mcp_gold_200_chroma_bge" / "status.json"
ML_RUNTIME = ROOT.parent / ".codex_ml_runtime"
HF_HOME = ROOT / "data" / "models" / "huggingface"


def configure_environment() -> None:
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(ML_RUNTIME) + (os.pathsep + existing if existing else "")
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_OFFLINE"] = "1"


def configure_logging() -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = (STATUS.parent / "pipeline.log").open(
        "a", encoding="utf-8", buffering=1
    )
    sys.stderr = (STATUS.parent / "pipeline.error.log").open(
        "a", encoding="utf-8", buffering=1
    )


def write_status(stage: str, state: str, **extra: object) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "state": state,
        "pid": os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(stage: str, args: list[str]) -> None:
    write_status(stage, "running", command=args)
    print(f"stage={stage} state=running", flush=True)
    subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    write_status(stage, "completed", command=args)
    print(f"stage={stage} state=completed", flush=True)


def main() -> None:
    configure_logging()
    configure_environment()
    try:
        enriched_inputs = "outputs/runs/mcp_gold_200_chroma_bge/enriched_inputs.csv"
        run(
            "enrich_gold_free_inputs",
            [
                "enrich_mcp_gold_200_inputs.py",
                "--input", "data/gold/mcp_full_gold_200_inputs.csv",
                "--output", enriched_inputs,
                "--stats", "outputs/runs/mcp_gold_200_chroma_bge/input_enrichment_stats.json",
            ],
        )
        run(
            "build_bge_table_index",
            [
                "kosis_build_embedding_index.py",
                "--table-index", "data/reference/kosis_table_summary.csv",
                "--out-dir", "data/indexes/kosis_bge_m3",
                "--embedding-model", "BAAI/bge-m3",
                "--batch-size", "16",
                "--device", "cpu",
                "--torch-threads", str(min(8, os.cpu_count() or 4)),
            ],
        )
        run(
            "load_chroma_table_index",
            [
                "kosis_load_chroma_table_index.py",
                "--semantic-index", "data/indexes/kosis_bge_m3",
                "--persist-dir", "data/indexes/kosis_table_chroma",
                "--collection", "kosis_table",
            ],
        )
        lexical_candidates = "outputs/runs/mcp_gold_200_chroma_bge/lexical_table_candidates.csv"
        dense_candidates = "outputs/runs/mcp_gold_200_chroma_bge/dense_table_candidates.csv"
        candidates = "outputs/runs/mcp_gold_200_chroma_bge/table_candidates.csv"
        run(
            "build_lexical_table_candidates",
            [
                "build_mcp_gold_200_lexical_table_candidates.py",
                "--input", enriched_inputs,
                "--table-index", "data/reference/kosis_table_summary.csv",
                "--output", lexical_candidates,
                "--top-k", "50",
            ],
        )
        run(
            "search_dense_gold_200",
            [
                "search_mcp_gold_200_chroma_bge.py",
                "--claims", enriched_inputs,
                "--persist-dir", "data/indexes/kosis_table_chroma",
                "--collection", "kosis_table",
                "--output", dense_candidates,
                "--top-k", "20",
                "--batch-size", "16",
                "--device", "cpu",
            ],
        )
        run(
            "rerank_table_candidates",
            [
                "rerank_mcp_gold_200_table_candidates.py",
                "--claims", enriched_inputs,
                "--lexical-candidates", lexical_candidates,
                "--dense-candidates", dense_candidates,
                "--output", candidates,
                "--lexical-top-k", "50",
                "--dense-top-k", "20",
                "--final-top-k", "20",
                "--device", "cpu",
                "--batch-size", "8",
            ],
        )
        run(
            "evaluate_retrieval",
            [
                "evaluate_mcp_gold_200_mapping.py",
                "--candidates", candidates,
                "--input-fixture", enriched_inputs,
                "--output-dir", "outputs/regression/mcp_full_gold_200/chroma_bge_table_search",
            ],
        )
        run(
            "build_chroma_coordinate_index",
            [
                "kosis_build_chroma_meta_index.py",
                "--meta-index", "data/reference/kosis_gold10_meta_index.csv",
                "--persist-dir", "data/indexes/kosis_gold10_meta_chroma",
                "--collection", "kosis_gold10_coordinates",
                "--embedding-model", "BAAI/bge-m3",
                "--device", "cpu",
                "--batch-size", "16",
                "--torch-threads", str(min(8, os.cpu_count() or 4)),
                "--axis-value-limit", "6000",
                "--max-coordinates-per-table", "12000",
                "--reset",
            ],
        )
        mapped = "outputs/runs/mcp_gold_200_chroma_bge/coordinate_candidates.csv"
        run(
            "search_coordinates",
            [
                "kosis_chroma_hybrid_search.py",
                "--claims", enriched_inputs,
                "--table-candidates", candidates,
                "--output", mapped,
                "--persist-dir", "data/indexes/kosis_gold10_meta_chroma",
                "--collection", "kosis_gold10_coordinates",
                "--embedding-model", "BAAI/bge-m3",
                "--device", "cpu",
                "--table-top-k", "5",
                "--dense-top-k", "50",
                "--lexical-top-k", "50",
                "--rerank-top-k", "20",
                "--final-top-k", "10",
                "--stats-output", "outputs/runs/mcp_gold_200_chroma_bge/coordinate_search_stats.csv",
            ],
        )
        selected = "outputs/runs/mcp_gold_200_chroma_bge/coordinate_selected.csv"
        run(
            "select_two_stage_coordinates",
            [
                "select_mcp_gold_200_two_stage_coordinates.py",
                "--claims", enriched_inputs,
                "--candidates", mapped,
                "--output", selected,
            ],
        )
        run(
            "evaluate_full_mapping",
            [
                "evaluate_mcp_gold_200_mapping.py",
                "--candidates", candidates,
                "--mapped", selected,
                "--input-fixture", enriched_inputs,
                "--output-dir", "outputs/regression/mcp_full_gold_200/chroma_bge_full_mapping",
            ],
        )
        write_status(
            "complete",
            "completed",
            candidates=candidates,
            mapped=selected,
            retrieval_report="outputs/regression/mcp_full_gold_200/chroma_bge_table_search/report.md",
            mapping_report="outputs/regression/mcp_full_gold_200/chroma_bge_full_mapping/report.md",
        )
    except Exception as exc:
        write_status("failed", "failed", error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
