#!/usr/bin/env python3
"""Build a reusable exact KOSIS coordinate cache from development mappings."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import psycopg


def text(value: object) -> str:
    return str(value or "").strip()


def normalized(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", text(value).casefold())


def mapping_key(row: dict[str, str]) -> str:
    unit = row.get("canonical_unit") or row.get("gold_source_unit") or row.get("unit")
    prd_se = row.get("prd_se") or row.get("gold_prd_se") or row.get("measurement_prd_se")
    return "\x1f".join(
        normalized(value)
        for value in (row.get("metric_domain"), row.get("indicator"), unit, prd_se)
    )


def signature(row: dict[str, str]) -> tuple[str, ...]:
    return (
        text(row.get("gold_org_id")),
        text(row.get("gold_tbl_id")),
        text(row.get("gold_itm_id")),
        *(text(row.get(f"gold_obj_l{level}")) for level in range(1, 9)),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dsn", default="postgresql:///kosis_project")
    args = parser.parse_args()

    with args.gold.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if text(row.get("gold_ready")).upper() not in {"", "Y"}:
            continue
        if all(text(row.get(column)) for column in ("gold_org_id", "gold_tbl_id", "gold_itm_id")):
            groups[mapping_key(row)].append(row)

    tables = {
        (text(row["gold_org_id"]), text(row["gold_tbl_id"]))
        for values in groups.values()
        for row in values
    }
    axis_lookup: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    with psycopg.connect(args.dsn) as connection, connection.cursor() as cursor:
        for org_id, tbl_id in sorted(tables):
            cursor.execute(
                "SELECT axis_order, axis_id, axis_name FROM kosis_axes "
                "WHERE org_id=%s AND tbl_id=%s ORDER BY axis_order, axis_id",
                (org_id, tbl_id),
            )
            axis_lookup[(org_id, tbl_id)] = [
                {"axis_order": int(order), "axis_id": text(axis_id), "axis_name": text(name)}
                for order, axis_id, name in cursor.fetchall()
            ]

    entries = {}
    collisions = {}
    covered_rows = 0
    for key, values in sorted(groups.items()):
        signatures = {signature(row) for row in values}
        if len(signatures) != 1:
            collisions[key] = {
                "rows": len(values),
                "coordinate_count": len(signatures),
            }
            continue
        row = values[0]
        org_id, tbl_id = text(row["gold_org_id"]), text(row["gold_tbl_id"])
        axes = axis_lookup[(org_id, tbl_id)]
        axis_values = []
        for level in range(1, 9):
            value_id = text(row.get(f"gold_obj_l{level}"))
            if not value_id:
                continue
            if level > len(axes):
                raise ValueError(f"missing axis metadata: {org_id}/{tbl_id}/level={level}")
            axis = axes[level - 1]
            axis_values.append({
                "axis_order": level,
                "axis_id": axis["axis_id"],
                "axis_name": axis["axis_name"],
                "value_id": value_id,
                "value_name": text(row.get(f"gold_obj_l{level}_name")),
            })
        entries[key] = {
            "metric_domain": text(row.get("metric_domain")),
            "indicator": text(row.get("indicator")),
            "canonical_unit": text(row.get("canonical_unit") or row.get("gold_source_unit")),
            "prd_se": text(row.get("gold_prd_se") or row.get("prd_se")).upper(),
            "coordinate": {
                "org_id": org_id,
                "tbl_id": tbl_id,
                "item_id": text(row["gold_itm_id"]),
                "axis_values": axis_values,
                "prd_se": text(row.get("gold_prd_se") or row.get("prd_se")).upper(),
            },
            "evidence": {
                "tbl_name": text(row.get("gold_tbl_name")),
                "item_name": text(row.get("gold_itm_name")),
                "unit": text(row.get("gold_source_unit") or row.get("canonical_unit")),
                "objects": axis_values,
                "mapping_memory_source": "development_verified_coordinate",
            },
            "support_rows": len(values),
        }
        covered_rows += len(values)

    artifact = {
        "schema_version": "kosis-exact-mapping-memory-v1",
        "dataset_role": "DEVELOPMENT_SUPERVISED_CACHE",
        "blind_labels_used": 0,
        "key_fields": ["metric_domain", "indicator", "canonical_unit", "prd_se"],
        "gold_rows": len(rows),
        "entry_count": len(entries),
        "covered_development_rows": covered_rows,
        "collision_key_count": len(collisions),
        "collisions": collisions,
        "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in artifact.items() if key not in {"entries", "collisions"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
