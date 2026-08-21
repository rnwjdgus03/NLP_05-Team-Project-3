from __future__ import annotations

import asyncio
import csv
import json
import os
import signal
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import EXPECTED_CODE_SHA256, EXPECTED_FREEZE_ID, Settings


ProgressCallback = Callable[[str], Awaitable[None]]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def public_evidence(row: dict[str, Any]) -> dict[str, Any]:
    objects = []
    for index in range(1, 9):
        value_id = row.get(f"selected_obj_l{index}")
        if value_id:
            objects.append({
                "level": index,
                "axis_id": row.get(f"selected_obj_l{index}_axis_id"),
                "axis_name": row.get(f"selected_obj_l{index}_axis_name"),
                "value_id": value_id,
                "value_name": row.get(f"selected_obj_l{index}_name"),
            })
    return {
        "coordinate_id": row.get("coordinate_id"),
        "decision_status": row.get("decision_status"),
        "verdict_code": row.get("verdict_code"),
        "verdict_reason": row.get("verdict_reason"),
        "table": {
            "org_id": row.get("org_id"),
            "tbl_id": row.get("tbl_id"),
            "name": row.get("official_table_name") or row.get("tbl_name"),
        },
        "item": {
            "id": row.get("selected_itm_id"),
            "name": row.get("official_item_name") or row.get("selected_itm_name"),
            "unit": row.get("official_item_unit") or row.get("selected_itm_unit"),
        },
        "objects": objects,
        "period": row.get("kosis_period_used") or row.get("normalized_target_period"),
        "claim_value": row.get("claim_value_numeric"),
        "kosis_value": row.get("kosis_actual_value"),
        "difference": row.get("value_diff"),
        "fallback_state": row.get("fallback_state"),
        "api_request": row.get("api_request_fields"),
    }


def build_result(job_id: str, run_dir: Path) -> dict[str, Any]:
    decisions = read_jsonl(run_dir / "claim_decisions.jsonl")
    evidence = read_jsonl(run_dir / "verified_candidates.jsonl")
    evidence_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    coordinate_index: dict[str, dict[str, Any]] = {}
    for row in evidence:
        evidence_by_claim[row["claim_measurement_id"]].append(row)
        if row.get("coordinate_id"):
            coordinate_index[row["coordinate_id"]] = row
    claims = []
    for decision in decisions:
        claim_id = decision["claim_measurement_id"]
        state = decision.get("claim_decision", "UNRESOLVED")
        public_verdict = {
            "VERIFIED_MATCH": "MATCH",
            "MISMATCH_EVIDENCE_REVIEW_REQUIRED": "MISMATCH_REVIEW_REQUIRED",
        }.get(state, "UNRESOLVED")
        selected = coordinate_index.get(decision.get("selected_coordinate_id", ""))
        claims.append({
            "claim_measurement_id": claim_id,
            "verdict": public_verdict,
            "decision_status": state,
            "selected_evidence": public_evidence(selected) if selected else None,
            "candidate_count": decision.get("candidate_count", 0),
            "candidate_verdict_counts": decision.get("candidate_verdict_counts", {}),
            "review_required": state == "MISMATCH_EVIDENCE_REVIEW_REQUIRED",
            "candidates": [public_evidence(row) for row in evidence_by_claim[claim_id]],
        })
    counts = Counter(row["verdict"] for row in claims)
    return {
        "schema_version": "kosis-service-result-v1",
        "engine": {"freeze_id": EXPECTED_FREEZE_ID, "code_tree_sha256": EXPECTED_CODE_SHA256},
        "job_id": job_id,
        "summary": {"measurement_count": len(claims), "verdict_counts": dict(counts)},
        "claims": claims,
    }


class PipelineRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _command(self, args: list[str], *, run_dir: Path, log_handle) -> None:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.settings.engine_dir,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "KOSIS_POSTGRES_DSN": self.settings.postgres_dsn},
            stdout=log_handle,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            code = await process.wait()
        except asyncio.CancelledError:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            await process.wait()
            raise
        if code:
            raise RuntimeError(f"pipeline command failed ({code}): {' '.join(args[:3])}")

    async def run(self, *, job_id: str, payload: dict[str, Any], run_dir: Path, progress: ProgressCallback) -> Path:
        run_dir.mkdir(parents=True, exist_ok=False)
        request_path = run_dir / "request.json"
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        python = str(self.settings.python)
        engine = self.settings.engine_dir
        log_path = run_dir / "pipeline.log"
        with log_path.open("ab", buffering=0) as log:
            if payload["input_stage"] == "claims":
                await progress("hcx_extraction")
                input_path = run_dir / "input_claims.csv"
                write_csv(input_path, payload["claims"])
                measurements = run_dir / "measurements.csv"
                await self._command([
                    python, "-u", str(engine / "extract_hcx.py"), "--input", str(input_path),
                    "--output", str(measurements), "--model", "HCX-007", "--effort", "none", "--sleep", "0.5",
                ], run_dir=run_dir, log_handle=log)
            else:
                measurements = run_dir / "measurements.csv"
                write_csv(measurements, payload["measurements"])

            await progress("prepare")
            prepared = run_dir / "prepared_all.csv"
            await self._command([
                python, "-u", str(engine / "prepare_kosis_mapping_input.py"), "--input", str(measurements),
                "--output", str(run_dir / "prepared_ready.csv"),
                "--rejected-output", str(run_dir / "prepared_rejected.csv"),
                "--enrich-output", str(run_dir / "prepared_enrich.csv"), "--all-output", str(prepared),
            ], run_dir=run_dir, log_handle=log)

            async def stage_a(policy: str, output: Path) -> None:
                await self._command([
                    python, "-u", str(engine / "run_kosis_coordinate_stage_a.py"),
                    "--claims", str(prepared), "--semantic-index", str(self.settings.index_dir),
                    "--postgres-dsn", self.settings.postgres_dsn, "--output", str(output),
                    "--device", self.settings.device, "--lexical-top-k", "300", "--dense-top-k", "300",
                    "--table-rerank-top-k", "200", "--table-pool-top-k", "10",
                    "--rerank-family-slots", "20", "--rerank-survey-groups", "20",
                    "--item-recall-top-k", "300", "--item-rerank-slots", "100",
                    "--item-recall-policy", policy, "--reranker-batch-size", "32",
                ], run_dir=run_dir, log_handle=log)

            await progress("stage_a_legacy")
            await stage_a("legacy", run_dir / "stage_a_legacy.jsonl")
            await progress("stage_a_balanced")
            await stage_a("balanced", run_dir / "stage_a_balanced.jsonl")
            await progress("stage_a_merge")
            await self._command([
                python, "-u", str(engine / "merge_stage_a_rankings.py"),
                "--legacy", str(run_dir / "stage_a_legacy.jsonl"),
                "--balanced", str(run_dir / "stage_a_balanced.jsonl"),
                "--output", str(run_dir / "stage_a_table_pool.jsonl"), "--legacy-slots", "7", "--top-k", "10",
            ], run_dir=run_dir, log_handle=log)
            await progress("stage_b")
            await self._command([
                python, "-u", str(engine / "run_kosis_coordinate_stage_b.py"),
                "--table-pool", str(run_dir / "stage_a_table_pool.jsonl"),
                "--postgres-dsn", self.settings.postgres_dsn,
                "--output", str(run_dir / "stage_b_coordinate_beam.jsonl"), "--device", self.settings.device,
                "--embedding-batch-size", "128", "--item-top-k", "10", "--axis-top-k", "20",
                "--beam-width", "250", "--coordinate-pool-top-k", "250", "--preserve-table-fallback",
            ], run_dir=run_dir, log_handle=log)
            await progress("stage_c")
            await self._command([
                python, "-u", str(engine / "run_kosis_coordinate_stage_c.py"),
                "--beam-pool", str(run_dir / "stage_b_coordinate_beam.jsonl"),
                "--output", str(run_dir / "local_coordinate_top3.jsonl"),
                "--fallback-output", str(run_dir / "local_coordinate_rank4_5_fallback.jsonl"),
                "--state-output", str(run_dir / "stage_c_state.jsonl"), "--device", self.settings.device,
                "--reranker-batch-size", "32", "--obj-scope-bonus", "0.10",
            ], run_dir=run_dir, log_handle=log)
            await self._command([
                python, "-u", str(engine / "merge_local_stage_c_candidates.py"),
                "--primary", str(run_dir / "local_coordinate_top3.jsonl"),
                "--fallback", str(run_dir / "local_coordinate_rank4_5_fallback.jsonl"),
                "--output", str(run_dir / "local_api_candidates_top5.jsonl"),
            ], run_dir=run_dir, log_handle=log)
            await progress("kosis_verification")
            await self._command([
                python, "-u", str(engine / "run_kosis_top5_verification.py"),
                "--claims", str(prepared), "--candidates", str(run_dir / "local_api_candidates_top5.jsonl"),
                "--output", str(run_dir / "verified_candidates.jsonl"),
                "--claim-output", str(run_dir / "claim_decisions.jsonl"),
                "--postgres-dsn", self.settings.postgres_dsn,
                "--sqlite-cache", str(run_dir / "kosis_api_cache.sqlite3"),
                "--delay", str(self.settings.kosis_delay),
            ], run_dir=run_dir, log_handle=log)
        await progress("result_serialization")
        result_path = run_dir / "result.json"
        result_path.write_text(
            json.dumps(build_result(job_id, run_dir), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result_path
