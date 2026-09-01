from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "QUEUED"
    running = "RUNNING"
    succeeded = "SUCCEEDED"
    failed = "FAILED"


class RawClaim(BaseModel):
    claim_id: str | None = Field(default=None, max_length=100)
    article_id: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    date: str = Field(min_length=4, max_length=30)
    url: str = Field(default="", max_length=2000)
    claim_text: str = Field(min_length=1, max_length=5000)
    prev_sentence: str = Field(default="-", max_length=5000)
    next_sentence: str = Field(default="-", max_length=5000)
    article_context: str = Field(default="", max_length=20000)


class VerificationRequest(BaseModel):
    input_stage: Literal["claims", "measurements"] = "claims"
    claims: list[RawClaim] = Field(default_factory=list)
    measurements: list[dict[str, Any]] = Field(default_factory=list)
    client_request_id: str | None = Field(default=None, max_length=100)


class JobAccepted(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str
    result_url: str


class JobView(BaseModel):
    job_id: str
    status: JobStatus
    input_stage: str
    progress_step: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result_url: str | None = None
