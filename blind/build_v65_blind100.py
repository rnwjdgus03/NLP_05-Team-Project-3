#!/usr/bin/env python3
"""Create and lock a new post-v64 table-disjoint blind100 before prediction."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


PROJECT = Path("/home/ubuntu/kosis-project")
FREEZE = PROJECT / "freezes/v64_candidate_20260824_r1"
OUT = PROJECT / "blind/v65_post_v64_table_disjoint_blind100_20260824_r1"
INPUT = OUT / "blind_input100.csv"
GOLD = OUT / "blind_coordinate_gold100_locked.csv"
MANIFEST = OUT / "blind_manifest.json"
SEED = "v65-post-v64-table-disjoint-blind100-r1"
TARGET_PLAN = {
    "M": {"region": 3, "gender": 2, "age": 2, "item": 2, "other": 5},
    "Q": {"region": 0, "gender": 0, "age": 0, "item": 0, "other": 7},
    "Y": {"region": 4, "gender": 3, "age": 3, "item": 4, "other": 7},
}
PERIOD_TABLE_SOFT_TARGETS = {"M": 20, "Q": 7, "Y": 23}
PERIOD_TABLE_MINIMUMS = {"M": 8, "Q": 5, "Y": 15}
MAX_TABLES_PER_FAMILY = 8

sys.path.insert(0, str(PROJECT / "blind"))
import build_v33_table_disjoint_blind100 as base  # noqa: E402

sys.path.insert(0, str(FREEZE / "engine"))
from kosis_api_test import KosisAPIError  # noqa: E402

base.SEED = SEED


def read_gold_tables(path: Path) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            org_id = str(row.get("gold_org_id") or "").strip()
            tbl_id = str(row.get("gold_tbl_id") or "").strip()
            if tbl_id:
                result.add((org_id, tbl_id))
    return result


def rewrite_ids(input_rows, gold_rows, serial_start: int, built_at: str) -> None:
    for offset, (input_row, gold_row) in enumerate(zip(input_rows, gold_rows)):
        article_id = f"V65BLIND100-{serial_start + offset:03d}"
        measurement_id = f"{article_id}-m1"
        for row in (input_row, gold_row):
            row["claim_id"] = article_id
            row["claim_measurement_id"] = measurement_id
            row["article_id"] = article_id
            row["prompt_version"] = "v65-blind100-r1"
            row["extracted_at"] = built_at
            row["blind_source_type"] = (
                "KOSIS_API_V65_POST_V64_FREEZE_TABLE_DISJOINT"
            )
        gold_row["gold_reason"] = (
            "v64 후보 동결 후 예측 전에 생성; 프로젝트의 모든 기존 골드 표와 분리"
        )
        gold_row["gold_label_source"] = (
            "KOSIS_OPEN_API_PRE_PREDICTION_BLIND"
        )


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"blind set already exists: {OUT}")
    freeze_manifest_path = FREEZE / "freeze_manifest.json"
    freeze = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    if freeze.get("freeze_id") != "v64_candidate_20260824_r1":
        raise RuntimeError("unexpected candidate freeze")
    if freeze.get("status") != "FROZEN_CANDIDATE_PENDING_NEW_BLIND100":
        raise RuntimeError("candidate is not registered for the new blind100")
    if freeze["development_evaluation"]["promotion_gate"] != "PASS":
        raise RuntimeError("development regression gate did not pass")

    # This scan runs before OUT is created.  It excludes every table appearing
    # in any prior project CSV whose filename contains 'gold'.
    historical = base.historical_tables()
    v33_input = (
        PROJECT
        / "blind/v33_table_disjoint_stratified_blind100_20260821/blind_input100.csv"
    )
    v33_gold = (
        PROJECT
        / "blind/v33_table_disjoint_stratified_blind100_20260821/"
        "blind_coordinate_gold100_locked.csv"
    )
    input_fields = base.headers(v33_input)
    gold_fields = base.headers(v33_gold)
    built_at = datetime.now(timezone.utc).isoformat()
    inputs: list[dict[str, str]] = []
    gold_rows: list[dict[str, str]] = []
    selected: set[tuple[str, str]] = set()
    rejected: set[tuple[str, str, str]] = set()
    family_counts: Counter[str] = Counter()
    strata_counts: Counter[str] = Counter()
    period_counts: Counter[str] = Counter()
    OUT.mkdir(parents=True)

    with psycopg.connect("postgresql:///kosis_project") as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT DISTINCT t.org_id,t.tbl_id,t.tbl_name,t.category_path,p.prd_se
                   FROM kosis_tables t JOIN kosis_periodicities p
                     ON p.org_id=t.org_id AND p.tbl_id=t.tbl_id
                   WHERE p.prd_se IN ('M','Q','Y')
                     AND (SELECT count(*) FROM kosis_axes a
                          WHERE a.org_id=t.org_id AND a.tbl_id=t.tbl_id) BETWEEN 1 AND 3
                     AND (SELECT count(*) FROM kosis_items i
                          WHERE i.org_id=t.org_id AND i.tbl_id=t.tbl_id) BETWEEN 1 AND 12"""
            )
            candidates = [dict(row) for row in cursor.fetchall()]

        for row in candidates:
            row["family"] = (
                str(row.get("category_path") or "").split(">")[0].strip()
                or "기타"
            )
        candidates.sort(
            key=lambda row: base.stable_key(
                row["org_id"], row["tbl_id"], row["prd_se"]
            )
        )

        for prd_se, plan in TARGET_PLAN.items():
            for wanted, count in plan.items():
                built = 0
                for table in candidates:
                    if built == count:
                        break
                    key = str(table["org_id"]), str(table["tbl_id"])
                    family = str(table["family"])
                    reject_key = (*key, wanted)
                    if (
                        str(table["prd_se"]) != prd_se
                        or key in historical
                        or key in selected
                        or reject_key in rejected
                        or family_counts[family] >= MAX_TABLES_PER_FAMILY
                    ):
                        continue
                    try:
                        result = base.build_table_rows(
                            connection,
                            table,
                            wanted,
                            input_fields,
                            gold_fields,
                            len(inputs) + 1,
                            built_at,
                        )
                    except (
                        AssertionError,
                        KeyError,
                        TypeError,
                        ValueError,
                        KosisAPIError,
                    ):
                        result = None
                    if not result:
                        rejected.add(reject_key)
                        continue
                    table_inputs, table_gold = result
                    rewrite_ids(table_inputs, table_gold, len(inputs) + 1, built_at)
                    inputs.extend(table_inputs)
                    gold_rows.extend(table_gold)
                    selected.add(key)
                    family_counts[family] += 1
                    strata_counts[f"{prd_se}:{wanted}"] += 1
                    period_counts[prd_se] += 1
                    built += 1
                    print(
                        f"blind_tables={len(selected)}/50 "
                        f"blind_rows={len(inputs)}/100 "
                        f"stratum={prd_se}:{wanted} {built}/{count}",
                        flush=True,
                    )
                if built != count:
                    print(
                        f"stratum_shortfall={prd_se}:{wanted} {built}/{count}",
                        flush=True,
                    )

            fallback_needed = max(
                0, PERIOD_TABLE_SOFT_TARGETS[prd_se] - period_counts[prd_se]
            )
            fallback_built = 0
            for table in candidates:
                if fallback_built == fallback_needed:
                    break
                key = str(table["org_id"]), str(table["tbl_id"])
                family = str(table["family"])
                reject_key = (*key, "other")
                if (
                    str(table["prd_se"]) != prd_se
                    or key in historical
                    or key in selected
                    or reject_key in rejected
                    or family_counts[family] >= MAX_TABLES_PER_FAMILY
                ):
                    continue
                try:
                    result = base.build_table_rows(
                        connection,
                        table,
                        "other",
                        input_fields,
                        gold_fields,
                        len(inputs) + 1,
                        built_at,
                    )
                except (
                    AssertionError,
                    KeyError,
                    TypeError,
                    ValueError,
                    KosisAPIError,
                ):
                    result = None
                if not result:
                    rejected.add(reject_key)
                    continue
                table_inputs, table_gold = result
                rewrite_ids(table_inputs, table_gold, len(inputs) + 1, built_at)
                inputs.extend(table_inputs)
                gold_rows.extend(table_gold)
                selected.add(key)
                family_counts[family] += 1
                strata_counts[f"{prd_se}:other_fallback"] += 1
                period_counts[prd_se] += 1
                fallback_built += 1
                print(
                    f"blind_tables={len(selected)}/50 "
                    f"blind_rows={len(inputs)}/100 "
                    f"stratum={prd_se}:other_fallback "
                    f"{fallback_built}/{fallback_needed}",
                    flush=True,
                )
            if period_counts[prd_se] < PERIOD_TABLE_SOFT_TARGETS[prd_se]:
                print(
                    f"period_soft_target_shortfall={prd_se} "
                    f"{period_counts[prd_se]}/"
                    f"{PERIOD_TABLE_SOFT_TARGETS[prd_se]}",
                    flush=True,
                )

        # Historical exclusions can exhaust a specific periodicity.  Fill the
        # remaining predeclared 50-table cardinality in deterministic catalog
        # order without relaxing table disjointness or family diversity.
        for table in candidates:
            if len(selected) == 50:
                break
            key = str(table["org_id"]), str(table["tbl_id"])
            family = str(table["family"])
            reject_key = (*key, "global_other")
            if (
                key in historical
                or key in selected
                or reject_key in rejected
                or (*key, "other") in rejected
                or family_counts[family] >= MAX_TABLES_PER_FAMILY
            ):
                continue
            try:
                result = base.build_table_rows(
                    connection,
                    table,
                    "other",
                    input_fields,
                    gold_fields,
                    len(inputs) + 1,
                    built_at,
                )
            except (
                AssertionError,
                KeyError,
                TypeError,
                ValueError,
                KosisAPIError,
            ):
                result = None
            if not result:
                rejected.add(reject_key)
                continue
            table_inputs, table_gold = result
            rewrite_ids(table_inputs, table_gold, len(inputs) + 1, built_at)
            inputs.extend(table_inputs)
            gold_rows.extend(table_gold)
            selected.add(key)
            family_counts[family] += 1
            prd_se = str(table["prd_se"])
            strata_counts[f"{prd_se}:global_fallback"] += 1
            period_counts[prd_se] += 1
            print(
                f"blind_tables={len(selected)}/50 "
                f"blind_rows={len(inputs)}/100 "
                f"stratum={prd_se}:global_fallback",
                flush=True,
            )

    if not (
        len(selected) == 50 and len(inputs) == 100 and len(gold_rows) == 100
    ):
        raise RuntimeError("blind100 cardinality invariant failed")
    if len({row["claim_measurement_id"] for row in inputs}) != 100:
        raise RuntimeError("blind100 measurement IDs are not unique")
    if selected & historical:
        raise RuntimeError("blind100 overlaps a historical gold table")
    for prd_se, minimum in PERIOD_TABLE_MINIMUMS.items():
        if period_counts[prd_se] < minimum:
            raise RuntimeError(
                f"blind100 periodicity minimum failed: {prd_se} "
                f"{period_counts[prd_se]}/{minimum}"
            )

    base.write_csv(INPUT, input_fields, inputs)
    base.write_csv(GOLD, gold_fields, gold_rows)
    engine_sha = freeze["components"]["engine"]["tree_sha256"]
    manifest = {
        "schema_version": "kosis-v65-post-v64-table-disjoint-blind100-v1",
        "blind": True,
        "evaluation_only": True,
        "candidate_frozen_before_gold": True,
        "no_tuning_after_unblind": True,
        "selection_seed": SEED,
        "rows": 100,
        "tables": 50,
        "period_table_counts": dict(sorted(period_counts.items())),
        "period_table_soft_targets": PERIOD_TABLE_SOFT_TARGETS,
        "period_table_minimums": PERIOD_TABLE_MINIMUMS,
        "period_shortfall_fill_policy": "deterministic_global_other",
        "strata_table_counts": dict(sorted(strata_counts.items())),
        "family_table_counts": dict(sorted(family_counts.items())),
        "historical_gold_tables_scanned": len(historical),
        "historical_table_overlap": 0,
        "candidate_freeze_id": freeze["freeze_id"],
        "candidate_code_tree_sha256": engine_sha,
        "candidate_freeze_manifest_sha256": base.digest(freeze_manifest_path),
        "blind_builder_sha256": base.digest(Path(__file__)),
        "blind_base_builder_sha256": base.digest(
            PROJECT / "blind/build_v33_table_disjoint_blind100.py"
        ),
        "input_sha256": base.digest(INPUT),
        "gold_sha256": base.digest(GOLD),
        "gold_created_before_prediction": True,
        "preregistered_thresholds": {
            "item_accuracy_at_5_min": 0.75,
            "coordinate_accuracy_at_5_min": 0.70,
            "eligible_overlap_exact": 100,
            "missing_prediction_packets_max": 0,
        },
        "official_metric_policy": "locked_unique_gold_only",
        "api_verified_decisions_are_secondary": True,
        "human_reviewed": False,
        "created_at": built_at,
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(INPUT, 0o444)
    os.chmod(GOLD, 0o400)
    os.chmod(MANIFEST, 0o444)
    os.chmod(OUT, 0o555)
    print(
        json.dumps(
            {
                "status": "V65_BLIND100_LOCKED",
                "rows": 100,
                "tables": 50,
                "historical_overlap": 0,
                "input_sha256": manifest["input_sha256"],
                "gold_sha256": manifest["gold_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
