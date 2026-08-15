#!/usr/bin/env python3
"""Re-run locked blind table retrieval after catalog improvements.

The v14 hybrid file contains both vector and catalog-only rows.  To avoid
feeding the old catalog back as if it were a vector result, this runner keeps
only rows carrying ``vector_rank`` and unions them with the current structured
catalog retrieval.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from evaluate_locked_blind_mcp import evaluate, read_csv, read_jsonl
from kosis_sqlite_table_fts import ensure_fts, retrieve_all, write_csv
from merge_kosis_table_candidate_pools import merge_pools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--v14-hybrid", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--v14-selected", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--catalog-top-k", type=int, default=30)
    parser.add_argument("--hybrid-top-k", type=int, default=50)
    args = parser.parse_args()

    claims = read_csv(args.claims)
    previous = read_csv(args.v14_hybrid)
    vector_rows = [row for row in previous if str(row.get("vector_rank", "")).strip()]

    connection = sqlite3.connect(args.metadata_db)
    connection.row_factory = sqlite3.Row
    try:
        ensure_fts(connection)
        catalog_rows = retrieve_all(connection, claims, limit=args.catalog_top_k)
    finally:
        connection.close()

    hybrid_rows = merge_pools(
        claims, vector_rows, catalog_rows, limit=args.hybrid_top_k,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "vector_pool.csv", vector_rows)
    write_csv(args.output_dir / "catalog_top30.csv", catalog_rows)
    write_csv(args.output_dir / "hybrid_candidates.csv", hybrid_rows)

    # Table retrieval can be evaluated before coordinates are regenerated.
    result = evaluate(
        read_jsonl(args.evidence), hybrid_rows, read_csv(args.v14_selected), claims,
    )
    result["evaluation_note"] = (
        "table recall uses v15 candidates; selected/coordinate metrics still use frozen v14 selection"
    )
    output = args.output_dir / "mcp_partial_retrieval_evaluation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
