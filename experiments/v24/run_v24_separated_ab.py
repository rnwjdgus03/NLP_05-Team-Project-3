#!/usr/bin/env python3
"""Run the three v24 policies as separated, resumable A/B experiments."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from collections import Counter
from pathlib import Path


PROJECT = Path(os.environ.get("KOSIS_PROJECT_ROOT", "/home/ubuntu/kosis-project"))
APP = PROJECT / "app"
PATCH = PROJECT / "experiments/v24_patch"
V23 = PROJECT / "runs/hybrid_bge_m3_postgres_mcp_v23_expanded_k_obj_scope_20260820"
OUT = PROJECT / "experiments/v24_separated_ab_20260820"
SEMANTIC_INDEX = PROJECT / "indexes/bge_m3_table_v2_complete"
PYTHON = PROJECT / ".venv/bin/python"
POSTGRES_DSN = "postgresql:///kosis_project"
GOLD = APP / "data/gold/stratified_actual_coordinate_gold_v21.csv"
INPUT = PROJECT / "06_in_ready_all_latest.csv"


def run(command: list[object]) -> None:
    rendered = [str(value) for value in command]
    print("RUN:", " ".join(rendered), flush=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(PATCH), str(APP)))
    environment["PYTHONUNBUFFERED"] = "1"
    subprocess.run(rendered, cwd=PROJECT, env=environment, check=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def gold_identity(row: dict[str, str]) -> tuple[str, str, str]:
    org = row.get("gold_org_id") or row.get("org_id") or ""
    table = row.get("gold_tbl_id") or row.get("tbl_id") or ""
    item = row.get("gold_itm_id") or row.get("itm_id") or row.get("item_id") or ""
    return org, table, item


def stage_a_metrics(path: Path, gold_rows: list[dict[str, str]]) -> dict:
    packets = {row["claim_measurement_id"]: row for row in read_jsonl(path)}
    ranks = []
    details = []
    for gold in gold_rows:
        claim_id = gold["claim_measurement_id"]
        org_id, tbl_id, _item = gold_identity(gold)
        rank = None
        for position, candidate in enumerate(
            packets.get(claim_id, {}).get("table_candidates", []), 1
        ):
            table = candidate.get("table", {})
            if str(table.get("org_id", "")) == org_id and str(table.get("tbl_id", "")) == tbl_id:
                rank = position
                break
        ranks.append(rank)
        details.append({
            "claim_measurement_id": claim_id,
            "gold_org_id": org_id,
            "gold_tbl_id": tbl_id,
            "table_rank": rank or "",
        })
    summary = {"claims": len(gold_rows)}
    for k in (1, 3, 5, 10):
        summary[f"table_top{k}"] = sum(rank is not None and rank <= k for rank in ranks)
    return {"summary": summary, "details": details}


def prepare_period_ab(gold_ids: set[str]) -> dict:
    period_dir = OUT / "period_binding"
    period_dir.mkdir(parents=True, exist_ok=True)
    prepared_all = period_dir / "prepared_all.csv"
    run([
        PYTHON, "-u", PATCH / "prepare_kosis_mapping_input.py",
        "--input", INPUT,
        "--output", period_dir / "prepared_ready.csv",
        "--rejected-output", period_dir / "prepared_rejected.csv",
        "--enrich-output", period_dir / "prepared_enrich.csv",
        "--all-output", prepared_all,
    ])
    baseline = {
        row["claim_measurement_id"]: row
        for row in read_csv(V23 / "06_in_ready_all_latest_prepared_all.csv")
    }
    current = {
        row["claim_measurement_id"]: row for row in read_csv(prepared_all)
    }
    changes = []
    for claim_id in sorted(gold_ids):
        old = baseline.get(claim_id, {})
        new = current.get(claim_id, {})
        fields = ("period", "comparison_period", "period_alignment_status")
        if any(old.get(field, "") != new.get(field, "") for field in fields):
            changes.append({
                "claim_measurement_id": claim_id,
                **{f"old_{field}": old.get(field, "") for field in fields},
                **{f"new_{field}": new.get(field, "") for field in fields},
            })
    if changes:
        write_csv(period_dir / "gold_period_changes.csv", changes)
    target = current.get("A0012-SPFEFB3037E3-m1", {})
    return {
        "changed_gold_rows": len(changes),
        "target_claim_period": target.get("period"),
        "target_claim_status": target.get("period_alignment_status"),
        "target_recovered": target.get("period") == "2022",
    }


def run_stage_a_ab(gold_rows: list[dict[str, str]], gold_ids: set[str]) -> dict:
    stage_a_dir = OUT / "stage_a_family_slots"
    stage_a_dir.mkdir(parents=True, exist_ok=True)
    v23_claims = [
        row for row in read_csv(V23 / "06_in_ready_all_latest_prepared_all.csv")
        if row.get("claim_measurement_id") in gold_ids
    ]
    claims_path = stage_a_dir / "gold30_claims.csv"
    write_csv(claims_path, v23_claims)

    baseline_rows = [
        row for row in read_jsonl(V23 / "stage_a_table_pool.jsonl")
        if row.get("claim_measurement_id") in gold_ids
    ]
    baseline_path = stage_a_dir / "slots_0.jsonl"
    write_jsonl(baseline_path, baseline_rows)

    results = {"slots_0": stage_a_metrics(baseline_path, gold_rows)}
    for slots in (20, 40, 60):
        output = stage_a_dir / f"slots_{slots}.jsonl"
        run([
            PYTHON, "-u", PATCH / "run_kosis_coordinate_stage_a.py",
            "--claims", claims_path,
            "--semantic-index", SEMANTIC_INDEX,
            "--postgres-dsn", POSTGRES_DSN,
            "--output", output,
            "--device", "cuda",
            "--lexical-top-k", "300",
            "--dense-top-k", "300",
            "--table-rerank-top-k", "100",
            "--table-pool-top-k", "10",
            "--rerank-family-slots", str(slots),
            "--reranker-batch-size", "32",
        ])
        results[f"slots_{slots}"] = stage_a_metrics(output, gold_rows)

    baseline_hits = {
        row["claim_measurement_id"]
        for row in results["slots_0"]["details"] if row["table_rank"]
    }
    for name, result in results.items():
        hits = {
            row["claim_measurement_id"]
            for row in result["details"] if row["table_rank"]
        }
        result["summary"]["new_recovery_vs_slots_0"] = len(hits - baseline_hits)
        result["summary"]["regression_loss_vs_slots_0"] = len(baseline_hits - hits)
    return {name: value["summary"] for name, value in results.items()}


def run_stage_b_ab(gold_rows: list[dict[str, str]], gold_ids: set[str]) -> dict:
    stage_b_dir = OUT / "stage_b_table_slots"
    stage_b_dir.mkdir(parents=True, exist_ok=True)
    table_pool = stage_b_dir / "v23_stage_a_gold30.jsonl"
    if not table_pool.exists():
        write_jsonl(table_pool, [
            row for row in read_jsonl(V23 / "stage_a_table_pool.jsonl")
            if row.get("claim_measurement_id") in gold_ids
        ])
    beam = stage_b_dir / "table_slot_beam.jsonl"
    run([
        PYTHON, "-u", PATCH / "run_kosis_coordinate_stage_b.py",
        "--table-pool", table_pool,
        "--postgres-dsn", POSTGRES_DSN,
        "--output", beam,
        "--device", "cuda",
        "--item-top-k", "10",
        "--axis-top-k", "20",
        "--beam-width", "200",
        "--coordinate-pool-top-k", "200",
        "--embedding-batch-size", "16",
        "--preserve-table-fallback",
    ])
    primary = stage_b_dir / "local_top3.jsonl"
    fallback = stage_b_dir / "local_rank4_5.jsonl"
    run([
        PYTHON, "-u", APP / "run_kosis_coordinate_stage_c.py",
        "--beam-pool", beam,
        "--output", primary,
        "--fallback-output", fallback,
        "--state-output", stage_b_dir / "stage_c_state.jsonl",
        "--device", "cuda",
        "--reranker-batch-size", "32",
        "--obj-scope-bonus", "0.10",
    ])

    # Merge Local Top-3 and Local rank 4–5 without MCP to evaluate this policy alone.
    import sys
    sys.path.insert(0, str(APP))
    from kosis_coordinate_merge import merge_fallback_coordinate_packets

    primary_by_id = {row["claim_measurement_id"]: row for row in read_jsonl(primary)}
    fallback_by_id = {row["claim_measurement_id"]: row for row in read_jsonl(fallback)}
    merged = [
        merge_fallback_coordinate_packets(
            primary_by_id.get(claim_id), None, fallback_by_id.get(claim_id)
        )
        for claim_id in sorted(gold_ids)
        if primary_by_id.get(claim_id) or fallback_by_id.get(claim_id)
    ]
    merged_path = stage_b_dir / "merged_local_top5.jsonl"
    write_jsonl(merged_path, merged)
    summary_path = stage_b_dir / "coordinate_topk_summary.json"
    run([
        PYTHON, "-u", APP / "evaluate_coordinate_topk.py",
        "--predictions", merged_path,
        "--gold", GOLD,
        "--summary", summary_path,
        "--details", stage_b_dir / "coordinate_topk_details.csv",
    ])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trace = Counter()
    for row in read_jsonl(beam):
        values = row.get("component_trace", {})
        trace["per_table_slot_candidates"] += int(values.get("per_table_slot_candidates") or 0)
        trace["per_table_slot_recovered_tables"] += int(
            values.get("per_table_slot_recovered_tables") or 0
        )
    return {
        "coordinate_metrics": summary["metrics"]["coordinate"],
        "full_metrics": summary["metrics"]["full"],
        "trace": dict(trace),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gold_rows_all = read_csv(GOLD)
    eligible = {
        row["claim_measurement_id"]
        for row in read_csv(V23 / "coordinate_topk_actual_gold_details.csv")
    }
    gold_rows = [
        row for row in gold_rows_all if row.get("claim_measurement_id") in eligible
    ]
    if len(gold_rows) != 30:
        raise AssertionError(f"expected 30 eligible gold rows, got {len(gold_rows)}")

    report = {
        "schema_version": "v24-separated-ab-v1",
        "gold_rows": len(gold_rows),
        "period_binding": prepare_period_ab(eligible),
        "stage_b_table_slots": run_stage_b_ab(gold_rows, eligible),
        "stage_a_family_slots": run_stage_a_ab(gold_rows, eligible),
    }
    (OUT / "v24_separated_ab_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("V24 SEPARATED AB COMPLETE")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
