#!/usr/bin/env python3
"""One-shot blind evaluation using the immutable v24b freeze."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv


PROJECT = Path("/home/ubuntu/kosis-project")
FREEZE = PROJECT / "freezes/v24b_20260820_blind"
APP = FREEZE / "app"
INPUT = FREEZE / "blind_official_release_measurements31.csv"
GOLD = FREEZE / "blind_official_release_coordinate_gold31_locked.csv"
FREEZE_MANIFEST = FREEZE / "freeze_manifest.json"
SEMANTIC = PROJECT / "indexes/bge_m3_table_v2_complete"
PG_MANIFEST = PROJECT / "postgres_snapshot_v1/manifest.json"
SOURCE_BUNDLE = PROJECT / "kosis_hybrid_gpu_bundle_v21_family_hierarchy_period_gold.zip"
POSTGRES_DSN = "postgresql:///kosis_project"
RUN_ID = "blind_v24b_official_release31_20260820"
OUT = PROJECT / "runs" / RUN_ID


def run(command: list[object]) -> None:
    command = [str(value) for value in command]
    print("\n$", " ".join(command), flush=True)
    subprocess.run(command, cwd=APP, env=ENV, check=True)


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


for required in (APP, INPUT, GOLD, FREEZE_MANIFEST, SEMANTIC / "embeddings.npy", PG_MANIFEST):
    if not required.exists():
        raise FileNotFoundError(required)
if OUT.exists() and any(OUT.iterdir()):
    raise RuntimeError(f"blind run is one-shot; OUT_DIR must be new and empty: {OUT}")

freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
if not freeze.get("prediction_artifacts_present_at_freeze") is False:
    raise RuntimeError("freeze was not created before prediction")
load_dotenv(PROJECT / ".env")
if not os.environ.get("KOSIS_API_KEY", "").strip():
    raise RuntimeError("KOSIS_API_KEY missing")

OUT.mkdir(parents=True)
sys.path.insert(0, str(APP))
ENV = os.environ.copy()
ENV.update({
    "PYTHONUNBUFFERED": "1", "KOSIS_POSTGRES_DSN": POSTGRES_DSN,
    "TOKENIZERS_PARALLELISM": "false", "HF_HOME": str(PROJECT / "cache/huggingface"),
})
from kosis_coordinate_merge import merge_fallback_coordinate_packets
from kosis_hybrid_top3 import read_csv

prepared_all = OUT / "prepared_all.csv"
prepared_ready = OUT / "prepared_ready.csv"
prepared_rejected = OUT / "prepared_rejected.csv"
prepared_enrich = OUT / "prepared_enrich.csv"

run([
    sys.executable, "-u", APP / "write_kosis_run_manifest.py",
    "--bundle-root", APP, "--semantic-index", SEMANTIC,
    "--postgres-manifest", PG_MANIFEST, "--claims", INPUT,
    "--out-dir", OUT, "--source-bundle", SOURCE_BUNDLE, "--run-id", RUN_ID,
    "--parameter", "lexical_top_k=300", "--parameter", "dense_top_k=300",
    "--parameter", "table_rerank_top_k=100", "--parameter", "table_pool_top_k=10",
    "--parameter", "stage_a_period_prefilter=KNOWN_MISMATCH_REJECT",
    "--parameter", "stage_a_metadata_score=SURVEY_ORG_CATEGORY",
    "--parameter", "stage_a_family_slots=0_REJECTED_BY_AB",
    "--parameter", "measurement_endpoint_period=TYPE_AWARE_DIRECT_ENDPOINT_PRESERVED",
    "--parameter", "stage_b_per_table_review_slot=ENABLED",
    "--parameter", "coordinate_top3_policy=ONE_PER_TABLE_THEN_FILL",
    "--parameter", "stage_c_obj_scope_bonus=0.10",
    "--parameter", "stage_c_local_rank45_fallback=ONLY_IF_TOP3_UNRESOLVED",
    "--parameter", "mcp_postgres_gate=COMPLETE_PERIOD_UNIT_REQUIRED",
    "--parameter", "mcp_top_k=2",
    "--parameter", "fallback_policy=LOCAL_TOP3_THEN_LOCAL_RANK45_THEN_MCP",
    "--parameter", f"blind_gold_sha256={freeze['blind_gold_sha256']}",
    "--parameter", "blind_protocol=ONE_SHOT_NO_TUNING",
])
run([
    sys.executable, "-u", APP / "prepare_kosis_mapping_input.py",
    "--input", INPUT, "--output", prepared_ready,
    "--rejected-output", prepared_rejected, "--enrich-output", prepared_enrich,
    "--all-output", prepared_all, "--expect-ready", "31",
])

stage_a = OUT / "stage_a_table_pool.jsonl"
stage_b = OUT / "stage_b_coordinate_beam.jsonl"
local_top3 = OUT / "local_coordinate_top3.jsonl"
local_rank45 = OUT / "local_coordinate_rank4_5_fallback.jsonl"
run([
    sys.executable, "-u", APP / "run_kosis_coordinate_stage_a.py",
    "--claims", prepared_all, "--semantic-index", SEMANTIC,
    "--postgres-dsn", POSTGRES_DSN, "--output", stage_a, "--device", "cuda",
    "--lexical-top-k", "300", "--dense-top-k", "300",
    "--table-rerank-top-k", "100", "--table-pool-top-k", "10",
    "--reranker-batch-size", "32",
])
run([
    sys.executable, "-u", APP / "run_kosis_selective_metadata_hydration.py",
    "--candidates", stage_a, "--dsn", POSTGRES_DSN,
    "--checkpoint", OUT / "metadata_hydration.jsonl",
    "--failures", OUT / "metadata_hydration_failures.jsonl",
    "--per-claim-table-limit", "10", "--workers", "4", "--retries", "2", "--delay", "0.5",
])
run([
    sys.executable, "-u", APP / "run_kosis_coordinate_stage_b.py",
    "--table-pool", stage_a, "--postgres-dsn", POSTGRES_DSN,
    "--output", stage_b, "--device", "cuda", "--embedding-batch-size", "128",
    "--coordinate-pool-top-k", "200", "--preserve-table-fallback",
])
run([
    sys.executable, "-u", APP / "run_kosis_coordinate_stage_c.py",
    "--beam-pool", stage_b, "--output", local_top3,
    "--fallback-output", local_rank45, "--state-output", OUT / "stage_c_state.jsonl",
    "--device", "cuda", "--reranker-batch-size", "32", "--obj-scope-bonus", "0.10",
])

mcp_top2 = OUT / "kosis_mcp_coordinate_top2_independent.jsonl"
run([
    sys.executable, "-u", APP / "run_kosis_mcp_coordinate_top2.py",
    "--claims", prepared_all, "--mcp-url", "http://127.0.0.1:3000/mcp",
    "--output", mcp_top2, "--state-output", OUT / "mcp_top2_state.jsonl",
    "--search-limit", "8", "--mcp-min-interval", "0.35", "--mcp-retries", "3",
    "--mcp-cache", OUT / "mcp_tool_cache.sqlite3", "--postgres-dsn", POSTGRES_DSN,
])

local = {row["claim_measurement_id"]: row for row in jsonl(local_top3)}
rank45 = {row["claim_measurement_id"]: row for row in jsonl(local_rank45)}
mcp = {row["claim_measurement_id"]: row for row in jsonl(mcp_top2)}
ready_ids = {
    row["claim_measurement_id"] for row in read_csv(prepared_all)
    if str(row.get("mapping_gate", "")).upper() == "READY"
}
merged_path = OUT / "kosis_api_candidates_fallback.jsonl"
statuses = []
with merged_path.open("w", encoding="utf-8") as handle:
    for claim_id in sorted(ready_ids):
        if claim_id not in local and claim_id not in rank45 and claim_id not in mcp:
            statuses.append("ALL_COORDINATE_BRANCHES_MISSING")
            continue
        statuses.append(
            "LOCAL_AND_MCP_AVAILABLE" if claim_id in local and claim_id in mcp
            else "LOCAL_READY_MCP_MISSING" if claim_id in local
            else "LOCAL_MISSING_MCP_FALLBACK_AVAILABLE"
        )
        packet = merge_fallback_coordinate_packets(local.get(claim_id), mcp.get(claim_id), rank45.get(claim_id))
        handle.write(json.dumps(packet, ensure_ascii=False) + "\n")

run([
    sys.executable, "-u", APP / "evaluate_coordinate_topk.py",
    "--predictions", merged_path, "--gold", GOLD,
    "--summary", OUT / "coordinate_topk_blind_summary.json",
    "--details", OUT / "coordinate_topk_blind_details.csv", "--ks", "1,3,5,10",
])

run([
    sys.executable, "-u", APP / "run_kosis_top5_verification.py",
    "--claims", prepared_all, "--candidates", merged_path,
    "--output", OUT / "kosis_api_top5_verified.jsonl", "--postgres-dsn", POSTGRES_DSN,
    "--claim-output", OUT / "hybrid_top5_claim_decisions.jsonl",
    "--sqlite-cache", OUT / "kosis_api_cache.sqlite3", "--delay", "0.5",
])

summary = json.loads((OUT / "coordinate_topk_blind_summary.json").read_text(encoding="utf-8"))
run_manifest = json.loads((OUT / "run_manifest.json").read_text(encoding="utf-8"))
audit = {
    "schema_version": "v24b-blind-evaluation-result-v1",
    "run_id": RUN_ID, "one_shot_completed": True,
    "frozen_code_sha256": freeze["code_bundle_sha256"],
    "run_code_sha256": run_manifest["code_bundle_sha256"],
    "semantic_index_sha256": run_manifest["semantic_index"]["sha256"],
    "postgres_snapshot_id": run_manifest["postgres_snapshot"]["snapshot_id"],
    "blind_input_sha256": freeze["blind_input_sha256"],
    "blind_gold_sha256": freeze["blind_gold_sha256"],
    "ready_claims": len(ready_ids), "merged_packets": len(jsonl(merged_path)),
    "packet_status_counts": dict(Counter(statuses)),
    "metrics": summary["metrics"],
    "limitations": [
        "structured official-release measurements evaluate retrieval/mapping, not HCX extraction",
        "31 rows from 9 official releases and three KOSIS tables",
        "10 rows reuse one development table; article/url/claim IDs are disjoint",
    ],
}
if audit["run_code_sha256"] != audit["frozen_code_sha256"]:
    raise RuntimeError("frozen code hash changed during blind run")
(OUT / "blind_evaluation_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nBLIND V24B COMPLETE")
print(json.dumps(audit, ensure_ascii=False, indent=2))
