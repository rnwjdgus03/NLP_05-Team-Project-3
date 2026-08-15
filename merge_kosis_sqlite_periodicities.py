#!/usr/bin/env python3
"""Copy a SQLite metadata DB and supplement its official periodicities."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from kosis_sqlite_metadata import connect


def merge_periodicities(base: Path, supplement: Path, output: Path) -> dict[str, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() != base.resolve():
        shutil.copy2(base, output)
    target = connect(output)
    source = sqlite3.connect(supplement)
    try:
        before = int(target.execute("SELECT COUNT(*) FROM kosis_periodicities").fetchone()[0])
        source_rows = source.execute(
            "SELECT org_id, tbl_id, prd_se FROM kosis_periodicities"
        ).fetchall()
        target_tables = {
            (str(row[0]), str(row[1]))
            for row in target.execute("SELECT org_id, tbl_id FROM kosis_tables")
        }
        rows = [
            row for row in source_rows if (str(row[0]), str(row[1])) in target_tables
        ]
        target.executemany(
            "INSERT OR IGNORE INTO kosis_periodicities(org_id, tbl_id, prd_se) VALUES(?,?,?)",
            rows,
        )
        target.commit()
        after = int(target.execute("SELECT COUNT(*) FROM kosis_periodicities").fetchone()[0])
        tables = int(target.execute(
            "SELECT COUNT(DISTINCT org_id || ':' || tbl_id) FROM kosis_periodicities"
        ).fetchone()[0])
    finally:
        source.close()
        target.close()
    return {
        "base_periodicities": before,
        "supplement_rows_read": len(source_rows),
        "supplement_rows_for_base_tables": len(rows),
        "merged_periodicities": after,
        "inserted_periodicities": after - before,
        "tables_with_periodicity": tables,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    summary = merge_periodicities(args.base, args.supplement, args.output)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
