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


PUBLIC_REASON_MESSAGES = {
    "COMPARISON_PERIOD_MISSING": "기사의 비교 기준 기간이 명확하지 않아 같은 기간의 공식값인지 확인할 수 없습니다.",
    "PERIODICITY_NOT_AVAILABLE": "기사의 월·분기·연 주기와 일치하는 KOSIS 통계 주기를 찾지 못했습니다.",
    "SEMANTIC_SCOPE_REVIEW_REQUIRED": "후보 통계표의 조사 대상이나 지표 범위가 기사 주장과 완전히 일치하는지 확인이 필요합니다.",
    "UNIT_UNCERTAIN": "기사 수치와 KOSIS 항목의 단위 또는 환산 기준이 확정되지 않았습니다.",
    "LIKELY_MISMAPPING": "검색된 통계표·항목이 기사 주장과 다른 대상을 나타낼 가능성이 있습니다.",
    "OBJ_UNRESOLVED": "성별·연령·지역·품목 등 기사 대상과 일치하는 KOSIS 분류값을 확정하지 못했습니다.",
    "ACTUAL_DERIVATION_FAILED": "KOSIS 원자료에서 기사와 같은 방식의 증감률·합계·비율을 계산하지 못했습니다.",
    "MISMATCH_BLOCKED_UNCONFIRMED_COORDINATE": "표·항목·대상·기간 좌표가 완전히 확인되지 않아 수치 불일치 판정을 보류했습니다.",
    "THRESHOLD_CLAIM_UNSUPPORTED": "'이상·이하·최대·최저'와 같은 범위형 주장을 공식값과 동일한 조건으로 비교하지 못했습니다.",
    "REVISION_VINTAGE_RISK": "기사 작성 당시 통계와 현재 KOSIS 수정치가 다를 수 있어 판정을 보류했습니다.",
    "NOT_KOSIS_VALUE": "기업 실적 등 KOSIS 공식 통계로 직접 검증할 수 없는 수치입니다.",
    "PERIOD_MISSING": "기사에서 검증에 필요한 기준 기간을 찾지 못했습니다.",
    "VALUE_MISSING": "기사에서 비교 가능한 수치값을 찾지 못했습니다.",
    "KOSIS_GATE_WITHHELD": "KOSIS로 안전하게 검증할 조건이 충족되지 않았습니다.",
}


def public_explanation(
    decision: dict[str, Any], selected: dict[str, Any] | None, public_verdict: str,
) -> dict[str, Any]:
    if public_verdict == "MATCH":
        detail = (
            (selected or {}).get("verdict_reason")
            or "기사 수치와 확인된 KOSIS 공식 통계값이 허용 오차 내에서 일치합니다."
        )
        return {"title": "공식 통계와 일치", "detail": detail, "reasons": []}
    if public_verdict == "MISMATCH_REVIEW_REQUIRED":
        detail = (
            (selected or {}).get("verdict_reason")
            or "확인된 KOSIS 공식값과 차이가 있어 원문 맥락과 통계 개정 여부를 추가 검토해야 합니다."
        )
        return {"title": "수치 차이 검토 필요", "detail": detail, "reasons": []}

    counts = decision.get("candidate_verdict_counts") or {}
    ranked = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    reasons = [
        {
            "code": str(code),
            "count": int(count),
            "message": PUBLIC_REASON_MESSAGES.get(
                str(code), "공식 통계 좌표 또는 비교 조건을 충분히 확인하지 못했습니다."
            ),
        }
        for code, count in ranked[:3]
    ]
    detail = (
        reasons[0]["message"] if reasons
        else "검증 가능한 KOSIS 표·항목·대상·기간 좌표를 확정하지 못해 판단을 보류했습니다."
    )
    return {"title": "판단 보류", "detail": detail, "reasons": reasons}


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


def csv_data_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_gate_only_result_inputs(measurements: Path, run_dir: Path) -> None:
    rows = csv_data_rows(measurements)
    decisions = []
    for row in rows:
        claim_id = str(row.get("claim_measurement_id") or "")
        if not claim_id:
            continue
        gate = str(row.get("mapping_exclusion_code") or row.get("mapping_gate") or "KOSIS_GATE_WITHHELD")
        decisions.append({
            "claim_measurement_id": claim_id,
            "claim_decision": "UNRESOLVED",
            "selected_coordinate_id": "",
            "candidate_count": 0,
            "candidate_verdict_counts": {gate: 1},
            "service_gate_only": True,
        })
    with (run_dir / "claim_decisions.jsonl").open("w", encoding="utf-8") as handle:
        for row in decisions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (run_dir / "verified_candidates.jsonl").write_text("", encoding="utf-8")


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
    measurement_index = {
        row.get("claim_measurement_id", ""): row
        for row in csv_data_rows(run_dir / "measurements.csv")
        if row.get("claim_measurement_id")
    }
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
        measurement = measurement_index.get(claim_id, {})
        explanation = public_explanation(decision, selected, public_verdict)
        claims.append({
            "claim_measurement_id": claim_id,
            "claim": {
                "text": measurement.get("claim_text") or measurement.get("evidence_text") or "",
                "indicator": measurement.get("measurement_indicator") or measurement.get("claim_indicator") or "",
                "item": measurement.get("measurement_item") or measurement.get("claim_industry_or_item") or "",
                "period": measurement.get("measurement_period") or measurement.get("claim_period") or "",
                "value": measurement.get("value") or measurement.get("measurement_text") or "",
                "unit": measurement.get("unit") or measurement.get("canonical_unit") or "",
            },
            "verdict": public_verdict,
            "decision_status": state,
            "selected_evidence": public_evidence(selected) if selected else None,
            "candidate_count": decision.get("candidate_count", 0),
            "candidate_verdict_counts": decision.get("candidate_verdict_counts", {}),
            "explanation": explanation,
            "review_required": state == "MISMATCH_EVIDENCE_REVIEW_REQUIRED",
            "candidates": [public_evidence(row) for row in evidence_by_claim[claim_id]],
        })
    counts = Counter(row["verdict"] for row in claims)
    ready_path = run_dir / "service_prepared_ready.csv"
    ready_measurement_count = (
        len(csv_data_rows(ready_path)) if ready_path.exists() else len(claims)
    )
    return {
        "schema_version": "kosis-service-result-v3",
        "engine": {"freeze_id": EXPECTED_FREEZE_ID, "code_tree_sha256": EXPECTED_CODE_SHA256},
        "job_id": job_id,
        "summary": {
            # Public verification coverage is measured only on claims that
            # passed the KOSIS-ready gate.  Raw HCX rows remain available as a
            # diagnostic count but cannot dilute evidence precision.
            "measurement_count": ready_measurement_count,
            "ready_measurement_count": ready_measurement_count,
            "result_claim_count": len(claims),
            "extracted_measurement_count": len(measurement_index),
            "verdict_counts": dict(counts),
        },
        "claims": claims,
    }


class PipelineRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _command(
        self, args: list[str], *, run_dir: Path, log_handle,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.settings.engine_dir,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "KOSIS_POSTGRES_DSN": self.settings.postgres_dsn,
                **(env_overrides or {}),
            },
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

            # A URL containing only contextual/non-KOSIS measurements is a
            # valid conservative outcome, not a pipeline error.
            await progress("prepare")
            service_ready = run_dir / "service_prepared_ready.csv"
            await self._command([
                python, "-u", str(engine / "prepare_kosis_mapping_input.py"),
                "--input", str(measurements), "--output", str(service_ready),
                "--rejected-output", str(run_dir / "service_prepared_rejected.csv"),
                "--enrich-output", str(run_dir / "service_prepared_enrich.csv"),
                "--all-output", str(run_dir / "service_prepared_all.csv"),
            ], run_dir=run_dir, log_handle=log)
            if not csv_data_rows(service_ready):
                await progress("gate_only_unresolved")
                write_gate_only_result_inputs(run_dir / "service_prepared_all.csv", run_dir)
                result_path = run_dir / "result.json"
                result_path.write_text(
                    json.dumps(build_result(job_id, run_dir), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return result_path

            await progress("v42_pipeline")
            engine_run = run_dir / "engine"
            await self._command([
                "bash", str(engine / "cloud_setup" / "run_v58_dev300_pipeline.sh"),
            ], run_dir=run_dir, log_handle=log, env_overrides={
                "PROJECT_ROOT": str(self.settings.project_root),
                "PYTHON_BIN": python,
                "KOSIS_SEMANTIC_INDEX": str(self.settings.index_dir),
                "INPUT": str(service_ready),
                "OUT": str(engine_run),
                "KOSIS_DEVICE": self.settings.device,
            })

            # Reuse the v42 branch API cache and verify the selected final Top-5
            # once so the public result contract has one authoritative decision.
            await progress("final_kosis_verification")
            await self._command([
                python, "-u", str(engine / "run_kosis_top5_verification.py"),
                "--claims", str(service_ready),
                "--candidates", str(engine_run / "final_candidates_top5.jsonl"),
                "--output", str(run_dir / "verified_candidates.jsonl"),
                "--claim-output", str(run_dir / "claim_decisions.jsonl"),
                "--postgres-dsn", self.settings.postgres_dsn,
                "--sqlite-cache", str(engine_run / "api_cache.sqlite3"),
                "--delay", str(self.settings.kosis_delay),
            ], run_dir=run_dir, log_handle=log)
        await progress("result_serialization")
        result_path = run_dir / "result.json"
        result_path.write_text(
            json.dumps(build_result(job_id, run_dir), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result_path
