#!/usr/bin/env python3
"""Shared contracts for the low-memory PostgreSQL coordinate pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from run_kosis_postgres_coordinate_top3 import stable_claim_id
from prepare_kosis_mapping_input import (
    apply_article_scope,
    apply_orphan_scope,
    normalize_row as normalize_mapping_row,
)


TABLE_RETRIEVAL_SCHEMA = "kosis-low-memory-table-retrieval-v1"
TABLE_POOL_SCHEMA = "kosis-low-memory-table-pool-v1"
BEAM_POOL_SCHEMA = "kosis-low-memory-coordinate-beam-v1"


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_unique_claims(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """Assign deterministic, unique IDs without silently merging duplicate IDs."""
    source_rows = [dict(row) for row in rows]
    needs_v16_contract = any(
        any(
            key in row
            for key in (
                "measurement_indicator", "measurement_period",
                "measurement_prd_se", "measurement_value",
            )
        )
        and not all(
            key in row
            for key in (
                "mapping_gate", "canonical_unit", "unit_dimension_hypotheses",
                "allowed_mapping_types", "derived_computation_required",
            )
        )
        for row in source_rows
    )
    if needs_v16_contract:
        source_rows = [
            normalize_mapping_row(row)
            if any(
                key in row
                for key in (
                    "measurement_indicator", "measurement_period",
                    "measurement_prd_se", "measurement_value",
                )
            )
            else row
            for row in source_rows
        ]
        apply_article_scope(source_rows)
        apply_orphan_scope(source_rows)
    prepared: list[tuple[int, dict[str, Any]]] = []
    used: set[str] = set()
    for row_number, source in enumerate(source_rows, 1):
        claim = dict(source)
        claim_id = stable_claim_id(claim, row_number)
        if claim_id in used:
            digest = stable_json_hash({
                "row_number": row_number,
                "claim": {key: compact_text(value) for key, value in claim.items()},
            })[:12]
            claim_id = f"{claim_id}--ROW-{row_number:06d}-{digest}"
        if claim_id in used:
            raise ValueError(f"could not create a unique claim ID for row {row_number}")
        used.add(claim_id)
        claim["claim_measurement_id"] = claim_id
        prepared.append((row_number, claim))
    return prepared


def search_eligible_claims(
    rows: Sequence[tuple[int, Mapping[str, Any]]],
) -> list[tuple[int, dict[str, Any]]]:
    """Honor an explicit mapping gate while accepting ungated standalone fixtures."""
    output = []
    for row_number, source in rows:
        claim = dict(source)
        gate = compact_text(claim.get("mapping_gate")).upper()
        if gate and gate != "READY":
            continue
        output.append((row_number, claim))
    return output


class JsonlCheckpoint:
    """Append-only JSONL checkpoint with trailing-record crash recovery."""

    def __init__(self, path: str | Path, *, id_field: str = "claim_measurement_id"):
        self.path = Path(path)
        self.id_field = id_field
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records = self._recover_and_load()
        self.completed_ids = {
            compact_text(record.get(id_field)) for record in self.records
            if compact_text(record.get(id_field))
        }

    def _recover_and_load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        records: list[dict[str, Any]] = []
        valid_end = 0
        position = 0
        lines = raw.splitlines(keepends=True)
        for index, line in enumerate(lines):
            position += len(line)
            stripped = line.strip()
            if not stripped:
                valid_end = position
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                if index != len(lines) - 1:
                    raise ValueError(f"malformed JSONL record inside {self.path}")
                break
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record must be an object: {self.path}")
            identifier = compact_text(value.get(self.id_field))
            if not identifier:
                raise ValueError(f"JSONL record has no {self.id_field}: {self.path}")
            if any(compact_text(row.get(self.id_field)) == identifier for row in records):
                raise ValueError(f"duplicate {self.id_field}={identifier!r} in {self.path}")
            records.append(value)
            valid_end = position
        if valid_end != len(raw):
            with self.path.open("r+b") as handle:
                handle.truncate(valid_end)
                handle.flush()
                os.fsync(handle.fileno())
        return records

    def append(self, record: Mapping[str, Any]) -> None:
        value = dict(record)
        identifier = compact_text(value.get(self.id_field))
        if not identifier:
            raise ValueError(f"record has no {self.id_field}")
        if identifier in self.completed_ids:
            raise ValueError(f"checkpoint already contains {identifier}")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(value)
        self.completed_ids.add(identifier)


def require_schema(record: Mapping[str, Any], expected: str) -> None:
    if record.get("schema_version") != expected:
        raise ValueError(
            f"expected schema_version={expected}, got {record.get('schema_version')!r}"
        )


def claim_fingerprint(claim: Mapping[str, Any]) -> str:
    return stable_json_hash(dict(claim))


def coordinate_document_from_row(row: Mapping[str, Any]) -> str:
    fields = [
        f"통계표: {compact_text(row.get('tbl_name'))}",
        f"항목: {compact_text(row.get('selected_itm_name'))}",
        f"단위: {compact_text(row.get('selected_itm_unit'))}",
    ]
    for axis in range(1, 9):
        name = compact_text(row.get(f"selected_obj_l{axis}_name"))
        if not name:
            continue
        axis_name = compact_text(row.get(f"selected_obj_l{axis}_axis_name")) or f"OBJ{axis}"
        fields.append(f"{axis_name}: {name}")
    return " | ".join(field for field in fields if not field.endswith(": "))


def selected_rows(
    records: Iterable[Mapping[str, Any]], completed_ids: set[str],
) -> list[Mapping[str, Any]]:
    return [
        record for record in records
        if compact_text(record.get("claim_measurement_id")) not in completed_ids
    ]


def assert_resume_compatible(
    source_records: Iterable[Mapping[str, Any]],
    completed_records: Iterable[Mapping[str, Any]],
    *,
    require_fingerprint: bool = True,
) -> None:
    """Reject stale checkpoints instead of silently reusing changed claims."""
    source_by_id = {
        compact_text(record.get("claim_measurement_id")): record
        for record in source_records
    }
    for completed in completed_records:
        claim_id = compact_text(completed.get("claim_measurement_id"))
        source = source_by_id.get(claim_id)
        if source is None:
            raise ValueError(f"checkpoint contains unknown claim ID: {claim_id}")
        expected = compact_text(source.get("claim_fingerprint"))
        actual = compact_text(completed.get("claim_fingerprint"))
        if require_fingerprint and (not expected or not actual):
            raise ValueError(f"checkpoint fingerprint is missing for claim {claim_id}")
        if expected and actual and expected != actual:
            raise ValueError(f"stale checkpoint fingerprint for claim {claim_id}")
