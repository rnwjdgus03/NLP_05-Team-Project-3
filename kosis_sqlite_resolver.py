#!/usr/bin/env python3
"""Resolve ITEM/OBJ coordinates exactly from SQLite within retrieved KOSIS tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from kosis_meta_coordinates import (
    axis_name_matches_kind,
    axis_target_alignment,
    claim_axis_value_mentions,
    claim_axis_targets,
    coordinate_id,
    normalize_periodicity,
    periodicity_satisfied,
    unit_dimension_compatible,
)
from kosis_sqlite_metadata import SCHEMA_VERSION, clean, connect
from prepare_kosis_mapping_input import unit_dimension
from select_mcp_gold_200_two_stage_coordinates import (
    AGGREGATE_NAMES,
    item_match_score,
    normalized,
    obj_term_matches,
    select_two_stage,
)


MAX_AXIS = 8
METRIC_AXIS_MARKERS = ("항목", "지표", "가계수지")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def row_key(row: Mapping[str, str]) -> str:
    return clean(row.get("gold_id") or row.get("claim_measurement_id") or row.get("claim_id"))


def lookup_keys(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        clean(row.get(field)) for field in ("gold_id", "claim_measurement_id", "claim_id")
        if clean(row.get(field))
    ))


def int_value(value: object, default: int = 999) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return default


class MetadataStore:
    def __init__(self, path: Path):
        self.connection = connect(path)
        version = self.connection.execute(
            "SELECT value FROM metadata_info WHERE key='schema_version'"
        ).fetchone()
        if not version or version[0] != SCHEMA_VERSION:
            raise ValueError(f"unsupported SQLite metadata schema: {version[0] if version else 'missing'}")

    def close(self) -> None:
        self.connection.close()

    def table(self, org_id: str, tbl_id: str) -> dict[str, str] | None:
        row = self.connection.execute(
            "SELECT * FROM kosis_tables WHERE org_id=? AND tbl_id=?", (org_id, tbl_id)
        ).fetchone()
        return dict(row) if row else None

    def items(self, org_id: str, tbl_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM kosis_items WHERE org_id=? AND tbl_id=? ORDER BY itm_id",
            (org_id, tbl_id),
        )]

    def axes(self, org_id: str, tbl_id: str) -> list[dict[str, object]]:
        axes = []
        for axis in self.connection.execute(
            "SELECT * FROM kosis_axes WHERE org_id=? AND tbl_id=? ORDER BY axis_order",
            (org_id, tbl_id),
        ):
            values = [dict(row) for row in self.connection.execute(
                """
                SELECT * FROM kosis_axis_values
                WHERE org_id=? AND tbl_id=? AND axis_order=?
                ORDER BY obj_code
                """,
                (org_id, tbl_id, axis["axis_order"]),
            )]
            axes.append({**dict(axis), "values": values})
        return axes

    def periodicities(self, org_id: str, tbl_id: str) -> set[str]:
        return {str(row[0]) for row in self.connection.execute(
            "SELECT prd_se FROM kosis_periodicities WHERE org_id=? AND tbl_id=?",
            (org_id, tbl_id),
        )}


def aggregate_value(values: Iterable[Mapping[str, object]]) -> dict[str, str] | None:
    rows = [dict(value) for value in values]
    # KOSIS axes sometimes contain both a real grand total (for example
    # ``총액``) and a leaf whose display name is merely ``-``.  Metadata is
    # ordered by code, so returning the first aggregate-looking value can
    # silently bind the leaf instead of the total.  Prefer an explicit,
    # root-level aggregate and use ``-`` only as a last resort.
    priority = {
        normalized("총계"): 0,
        normalized("총액"): 1,
        # ``합계`` is the explicit grand total in several KOSIS geographic
        # axes, while a second ``계`` row is the subtotal used after a
        # particular province/city is selected.  Metadata does not expose the
        # cross-axis parent relation, so prefer the unambiguous grand total.
        normalized("합계"): 2,
        normalized("계"): 3,
        normalized("전체"): 4,
        normalized("전국"): 5,
        normalized("총지수"): 6,
        normalized("total"): 7,
        normalized("all"): 8,
        normalized("-"): 99,
        "": 100,
    }
    aggregate_rows = [
        row for row in rows if normalized(row.get("obj_name")) in priority
    ]
    if aggregate_rows:
        aggregate_rows.sort(key=lambda row: (
            priority[normalized(row.get("obj_name"))],
            0 if not clean(row.get("parent_obj_code")) else 1,
            clean(row.get("obj_code")),
        ))
        return aggregate_rows[0]
    return rows[0] if rows else None


def metric_axis_value_mentions(
    claim: Mapping[str, str], axis_name: str, values: Iterable[Mapping[str, object]]
) -> tuple[str, ...]:
    """Match a claimed metric when KOSIS models it as an OBJ, not an ITEM.

    Some official tables put the population group in ITEM (for example
    ``전체가구``) and the measured concept (``소득``) in an ``항목별`` OBJ.
    This conservative bridge is enabled only for explicit metric axes and only
    when an official value is literally contained in the extracted indicator.
    """
    axis = normalized(axis_name)
    if not any(normalized(marker) in axis for marker in METRIC_AXIS_MARKERS):
        return ()
    indicator_texts = tuple(
        normalized(claim.get(field))
        for field in ("item_intent_terms", "measurement_indicator", "indicator")
        if normalized(claim.get(field))
    )
    found = []
    aggregate_names = {normalized(name) for name in AGGREGATE_NAMES}
    for value in values:
        name = clean(value.get("obj_name"))
        term = normalized(name)
        if len(term) < 2 or term in aggregate_names:
            continue
        if any(term in indicator for indicator in indicator_texts):
            found.append(name)
    found.sort(key=lambda value: (-len(normalized(value)), normalized(value)))
    return tuple(dict.fromkeys(found))


def resolve_axis(
    claim: Mapping[str, str], axis: Mapping[str, object]
) -> tuple[dict[str, str] | None, str, tuple[str, ...], tuple[str, ...]]:
    targets = claim_axis_targets(claim)
    axis_name = clean(axis.get("axis_name"))
    relevant = tuple(
        term for kind, terms in targets.items()
        if axis_name_matches_kind(axis_name, kind)
        for term in terms
    )
    values = [dict(value) for value in axis.get("values", [])]
    dynamic = claim_axis_value_mentions(
        claim,
        axis_name,
        ({"name": value.get("obj_name"), "axis_name": axis_name} for value in values),
    )
    metric_targets = metric_axis_value_mentions(claim, axis_name, values)
    relevant = tuple(dict.fromkeys((*relevant, *dynamic, *metric_targets)))
    if relevant:
        matches = [
            value for value in values
            if all(obj_term_matches(term, clean(value.get("obj_name"))) for term in relevant)
        ]
        if matches:
            matches.sort(key=lambda value: (len(normalized(value.get("obj_name"))), clean(value.get("obj_code"))))
            return matches[0], "EXACT_TARGET", relevant, dynamic
        return aggregate_value(values), "TARGET_NOT_FOUND", relevant, dynamic
    selected = aggregate_value(values)
    if selected is None:
        return None, "AXIS_EMPTY", (), ()
    status = "AGGREGATE_DEFAULT" if normalized(selected.get("obj_name")) in {
        normalized(name) for name in AGGREGATE_NAMES
    } else "NON_AGGREGATE_DEFAULT"
    return selected, status, (), ()


def item_candidates(
    claim: Mapping[str, str], table_row: Mapping[str, str], items: list[dict[str, str]], top_k: int
) -> list[tuple[dict[str, str], float, str, bool]]:
    scored = []
    for item in items:
        pseudo = {
            **table_row,
            "selected_itm_id": item.get("itm_id", ""),
            "selected_itm_name": item.get("itm_name", ""),
            "selected_itm_unit": item.get("unit_name", ""),
        }
        score, matched = item_match_score(claim, pseudo)
        coordinate_dimension = clean(item.get("unit_dimension"))
        # 기존 SQLite DB에는 새로 구분한 복합단위 차원이 없을 수 있다. raw 단위에서
        # 즉시 다시 계산해 ``명``과 ``명/㎢`` 같은 조합을 호환으로 통과시키지 않는다.
        raw_dimension = unit_dimension(clean(item.get("unit_name")))
        if raw_dimension != "unknown":
            coordinate_dimension = raw_dimension
        compatible = unit_dimension_compatible(
            clean(claim.get("unit_dimension")), coordinate_dimension,
            clean(claim.get("mapping_type")),
        )
        if compatible:
            score += 30.0
        else:
            score -= 200.0
        scored.append((item, score, matched, compatible))
    scored.sort(key=lambda value: (-value[1], clean(value[0].get("itm_id"))))
    return scored[: max(1, top_k)]


def table_coordinate_candidates(
    claim: Mapping[str, str],
    table_candidate: Mapping[str, str],
    store: MetadataStore,
    *,
    item_top_k: int,
) -> list[dict[str, object]]:
    org_id = clean(table_candidate.get("org_id"))
    tbl_id = clean(table_candidate.get("tbl_id"))
    table = store.table(org_id, tbl_id)
    items = store.items(org_id, tbl_id)
    axes = store.axes(org_id, tbl_id)
    if not table or not items:
        return []
    wanted_prd = normalize_periodicity(
        clean(claim.get("measurement_prd_se") or claim.get("prd_se"))
    )
    available_prd = store.periodicities(org_id, tbl_id)
    prd_match = periodicity_satisfied(wanted_prd, available_prd)
    axis_selections = []
    for axis in axes:
        value, status, targets, dynamic_targets = resolve_axis(claim, axis)
        axis_selections.append((axis, value, status, targets, dynamic_targets))
    obj_codes = {
        int(axis["axis_order"]): clean(value.get("obj_code"))
        for axis, value, _, _, _ in axis_selections if value
    }
    outputs = []
    for item, item_score, item_matched, unit_match in item_candidates(
        claim, table_candidate, items, item_top_k
    ):
        row: dict[str, object] = {**claim, **table_candidate}
        row.update({
            "org_id": org_id,
            "tbl_id": tbl_id,
            "tbl_name": clean(table.get("tbl_name") or table_candidate.get("tbl_name")),
            "category_path": clean(table.get("category_path") or table_candidate.get("category_path")),
            "table_rank": clean(table_candidate.get("candidate_rank")),
            "coordinate_id": coordinate_id(org_id, tbl_id, clean(item.get("itm_id")), obj_codes),
            "selected_itm_id": clean(item.get("itm_id")),
            "selected_itm_name": clean(item.get("itm_name")),
            "selected_itm_unit": clean(item.get("unit_name")),
            "selected_itm_score": str(item_score),
            "sqlite_item_matched_terms": item_matched,
            "sqlite_unit_compatible": "Y" if unit_match else "N",
            "coordinate_prd_se": "|".join(sorted(available_prd)),
            "prd_se_match": "Y" if prd_match else "N",
            "metadata_backend": "sqlite_exact_v1",
            "candidate_status": "SQLITE_EXACT_COORDINATE",
        })
        axis_statuses = []
        for axis, value, status, targets, dynamic_targets in axis_selections:
            level = int(axis["axis_order"])
            if value:
                row[f"selected_obj_l{level}"] = clean(value.get("obj_code"))
                row[f"selected_obj_l{level}_name"] = clean(value.get("obj_name"))
            row[f"selected_obj_l{level}_axis_id"] = clean(axis.get("axis_id"))
            row[f"selected_obj_l{level}_axis_name"] = clean(axis.get("axis_name"))
            row[f"selected_obj_l{level}_resolution"] = status
            row[f"selected_obj_l{level}_target_terms"] = "|".join(targets)
            row[f"selected_obj_l{level}_dynamic_target_terms"] = "|".join(dynamic_targets)
            axis_statuses.append(status)
        alignment = axis_target_alignment(claim, row)
        row.update({
            "sqlite_axis_resolution": "|".join(axis_statuses),
            "sqlite_obj_axis_enforceable": "Y" if alignment["enforceable"] else "N",
            "sqlite_obj_strict_match": "Y" if alignment["strict_match"] else "N",
            "sqlite_obj_matched": "|".join(alignment["matched"]),
            "sqlite_obj_missing": "|".join((*alignment["missing_axis"], *alignment["mismatched"])),
            "sqlite_obj_score": str(alignment["score"]),
        })
        outputs.append(row)
    return outputs


def resolve(
    claims: list[dict[str, str]],
    table_candidates: list[dict[str, str]],
    store: MetadataStore,
    *,
    table_top_k: int = 10,
    item_top_k: int = 5,
    selection_mode: str = "joint",
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    claim_map = {}
    for claim in claims:
        for key in lookup_keys(claim):
            claim_map[key] = claim
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for candidate in table_candidates:
        grouped[row_key(candidate)].append(candidate)

    all_candidates: list[dict[str, object]] = []
    selected_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for key, candidates in grouped.items():
        claim = claim_map.get(key)
        if not claim:
            failures.append({"key": key, "reason": "CLAIM_NOT_FOUND"})
            continue
        candidates.sort(key=lambda row: int_value(row.get("candidate_rank")))
        generated = []
        for table_candidate in candidates[:table_top_k]:
            generated.extend(table_coordinate_candidates(
                claim, table_candidate, store, item_top_k=item_top_k
            ))
        for index, candidate in enumerate(generated, start=1):
            candidate["candidate_rank"] = str(index)
        all_candidates.extend(generated)
        selection_pool = generated
        if selection_mode == "table_locked" and generated:
            best_table_rank = min(int_value(row.get("table_rank")) for row in generated)
            selection_pool = [
                row for row in generated if int_value(row.get("table_rank")) == best_table_rank
            ]
        elif selection_mode == "table_top3":
            selection_pool = [
                row for row in generated if int_value(row.get("table_rank")) <= 3
            ]
        elif selection_mode != "joint":
            raise ValueError(f"unsupported selection mode: {selection_mode}")
        selected = select_two_stage(
            claim, [dict(row) for row in selection_pool], item_top_k=item_top_k
        )
        if selected:
            selected.update({
                "selection_backend": "sqlite_exact_item_obj_v1",
                "sqlite_candidate_count": str(len(generated)),
                "sqlite_selection_pool_count": str(len(selection_pool)),
                "sqlite_selection_mode": selection_mode,
            })
            selected_rows.append(selected)
        else:
            failures.append({
                "key": key,
                "claim_measurement_id": clean(claim.get("claim_measurement_id")),
                "article_id": clean(claim.get("article_id")),
                "reason": "NO_SQLITE_COORDINATE",
                "retrieved_table_count": len(candidates[:table_top_k]),
            })
    return all_candidates, selected_rows, failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--table-candidates", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--selected-output", type=Path, required=True)
    parser.add_argument("--failure-output", type=Path, required=True)
    parser.add_argument("--table-top-k", type=int, default=10)
    parser.add_argument("--item-top-k", type=int, default=5)
    parser.add_argument(
        "--selection-mode", choices=("joint", "table_top3", "table_locked"), default="joint"
    )
    args = parser.parse_args()
    store = MetadataStore(args.metadata_db)
    try:
        candidates, selected, failures = resolve(
            read_csv(args.claims), read_csv(args.table_candidates), store,
            table_top_k=args.table_top_k, item_top_k=args.item_top_k,
            selection_mode=args.selection_mode,
        )
    finally:
        store.close()
    write_csv(args.candidate_output, candidates)
    write_csv(args.selected_output, selected)
    write_csv(args.failure_output, failures)
    print(json.dumps({
        "coordinate_candidates": len(candidates),
        "selected": len(selected),
        "failures": len(failures),
        "metadata_backend": "sqlite_exact_v1",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
