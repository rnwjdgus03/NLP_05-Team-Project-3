#!/usr/bin/env python3
"""Apply the semantic READY gate to an existing validated mapping CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from kosis_validate_mapping_candidates import (
    READY,
    _read_csv,
    _write_csv,
    apply_semantic_ready_gate,
)


def _parse_selected_combination(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def harden_validated_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        if row.get("mapping_status") != READY:
            row.setdefault("semantic_gate_valid", "")
            row.setdefault("semantic_gate_reason", "")
            row.setdefault("semantic_gate_details", "")
            outputs.append(row)
            continue

        result = dict(row)
        result["selected_combination"] = _parse_selected_combination(
            row.get("selected_combination")
        )
        gated = apply_semantic_ready_gate(row, result)
        outputs.append({
            **row,
            "mapping_status": gated["mapping_status"],
            "mapping_reason": gated["mapping_reason"],
            "semantic_gate_valid": gated["semantic_gate_valid"],
            "semantic_gate_reason": gated["semantic_gate_reason"],
            "semantic_gate_details": gated["semantic_gate_details"],
        })
    return outputs


def write_ready_rows(
    path: Path,
    ready_rows: Sequence[Mapping[str, Any]],
    schema_rows: Sequence[Mapping[str, Any]],
) -> None:
    if ready_rows:
        _write_csv(path, ready_rows)
        return
    fields = list(dict.fromkeys(key for row in schema_rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields).writeheader()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harden existing mapping_status=READY rows without KOSIS API calls"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--ready-output",
        help="Optional CSV containing only rows that remain mapping_status=READY",
    )
    args = parser.parse_args()

    rows = _read_csv(Path(args.input))
    before_ready = sum(row.get("mapping_status") == READY for row in rows)
    outputs = harden_validated_rows(rows)
    after_ready = sum(row.get("mapping_status") == READY for row in outputs)
    demoted = before_ready - after_ready

    _write_csv(Path(args.output), outputs)
    if args.ready_output:
        write_ready_rows(
            Path(args.ready_output),
            [row for row in outputs if row.get("mapping_status") == READY],
            outputs,
        )
    print(
        f"rows={len(outputs)} ready_before={before_ready} "
        f"ready_after={after_ready} demoted={demoted} output={args.output}"
    )


if __name__ == "__main__":
    main()
