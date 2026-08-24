from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from . import __version__
from .config import EXPECTED_CODE_SHA256, EXPECTED_FREEZE_ID, Settings
from .repository import JobRepository
from .runner import PipelineRunner
from .schemas import JobAccepted, JobStatus, JobView, VerificationRequest


class ServiceState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.repository = JobRepository(settings.state_db)
        self.runner = PipelineRunner(settings)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    async def start(self) -> None:
        self.settings.runs_dir.mkdir(parents=True, exist_ok=True)
        for job_id in self.repository.recoverable_ids():
            await self.queue.put(job_id)
        self.worker = asyncio.create_task(self.work(), name="kosis-v64-gpu-worker")

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    async def work(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                row = self.repository.get(job_id)
                if not row or row["status"] != JobStatus.queued.value:
                    continue
                self.repository.mark_running(job_id)
                payload = json.loads(Path(row["request_path"]).read_text(encoding="utf-8"))

                async def progress(step: str) -> None:
                    self.repository.progress(job_id, step)

                result = await self.runner.run(
                    job_id=job_id, payload=payload, run_dir=Path(row["run_dir"]), progress=progress
                )
                self.repository.succeed(job_id, result)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.repository.fail(job_id, f"{type(error).__name__}: {error}")
            finally:
                self.queue.task_done()


settings = Settings.from_env()
state_holder = ServiceState(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine_manifest = settings.validate_engine()
    app.state.runtime_status = settings.probe_runtime()
    await state_holder.start()
    yield
    await state_holder.stop()


app = FastAPI(
    title="KOSIS News Fact Verification API",
    version=__version__,
    description="Frozen KOSIS BGE + reranker + PostgreSQL + KOSIS API verification service",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and (not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def job_view(row: dict) -> JobView:
    return JobView(
        job_id=row["job_id"], status=row["status"], input_stage=row["input_stage"],
        progress_step=row["progress_step"], created_at=row["created_at"], updated_at=row["updated_at"],
        started_at=row["started_at"], completed_at=row["completed_at"], error=row["error"],
        result_url=f"/v1/verifications/{row['job_id']}/result" if row["status"] == "SUCCEEDED" else None,
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service_version": __version__}


@app.get("/readyz")
async def readyz() -> dict:
    manifest = settings.validate_engine()
    return {
        "status": "ready",
        "engine_freeze_id": manifest["freeze_id"],
        "engine_code_sha256": manifest["code_tree_sha256"],
        "gpu_queue_depth": state_holder.queue.qsize(),
        "runtime": app.state.runtime_status,
        "capabilities": {
            "measurements": bool(os.getenv("KOSIS_API_KEY")),
            "claims": bool(os.getenv("KOSIS_API_KEY") and os.getenv("CLOVA_API_KEY")),
        },
    }


@app.post("/v1/verifications", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_verification(payload: VerificationRequest, _: None = Depends(require_api_key)) -> JobAccepted:
    rows = payload.claims if payload.input_stage == "claims" else payload.measurements
    opposite = payload.measurements if payload.input_stage == "claims" else payload.claims
    if not rows or opposite:
        raise HTTPException(status_code=422, detail="provide only the rows matching input_stage")
    if payload.input_stage == "claims" and not os.getenv("CLOVA_API_KEY"):
        raise HTTPException(status_code=503, detail="raw claim extraction is not configured")
    if not os.getenv("KOSIS_API_KEY"):
        raise HTTPException(status_code=503, detail="KOSIS API verification is not configured")
    if len(rows) > settings.max_rows_per_job:
        raise HTTPException(status_code=413, detail=f"at most {settings.max_rows_per_job} rows per job")
    data = payload.model_dump(mode="json")
    if payload.input_stage == "claims":
        for index, row in enumerate(data["claims"], 1):
            row["claim_id"] = row.get("claim_id") or f"API-{uuid.uuid4().hex[:12]}-{index}"
            row["article_id"] = row.get("article_id") or row["claim_id"]
    else:
        required = {"claim_id", "claim_measurement_id", "claim_text", "value", "unit"}
        for index, row in enumerate(data["measurements"], 1):
            missing = sorted(key for key in required if not str(row.get(key, "")).strip())
            if missing:
                raise HTTPException(status_code=422, detail=f"measurements[{index}] missing: {missing}")
    job_id = uuid.uuid4().hex
    inbox = settings.runs_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    request_path = inbox / f"{job_id}.json"
    request_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    run_dir = settings.runs_dir / job_id
    state_holder.repository.create(
        job_id=job_id, input_stage=payload.input_stage, request_path=request_path, run_dir=run_dir
    )
    await state_holder.queue.put(job_id)
    return JobAccepted(
        job_id=job_id, status=JobStatus.queued,
        status_url=f"/v1/verifications/{job_id}", result_url=f"/v1/verifications/{job_id}/result",
    )


@app.get("/v1/verifications/{job_id}", response_model=JobView)
async def get_verification(job_id: str, _: None = Depends(require_api_key)) -> JobView:
    row = state_holder.repository.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return job_view(row)


@app.get("/v1/verifications/{job_id}/result")
async def get_result(job_id: str, _: None = Depends(require_api_key)) -> JSONResponse:
    row = state_holder.repository.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] != "SUCCEEDED":
        raise HTTPException(status_code=409, detail={"status": row["status"], "step": row["progress_step"]})
    return JSONResponse(json.loads(Path(row["result_path"]).read_text(encoding="utf-8")))


@app.get("/v1/verifications/{job_id}/log", response_class=PlainTextResponse)
async def get_log(job_id: str, lines: int = 100, _: None = Depends(require_api_key)) -> str:
    row = state_holder.repository.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    path = Path(row["run_dir"]) / "pipeline.log"
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-min(max(lines, 1), 500):])
