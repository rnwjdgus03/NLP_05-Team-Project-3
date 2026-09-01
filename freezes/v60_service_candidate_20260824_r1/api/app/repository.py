from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    input_stage TEXT NOT NULL,
                    progress_step TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    request_path TEXT NOT NULL,
                    run_dir TEXT NOT NULL,
                    result_path TEXT,
                    error TEXT
                )
                """
            )

    def create(self, *, job_id: str, input_stage: str, request_path: Path, run_dir: Path) -> dict[str, Any]:
        now = utcnow()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs VALUES (?, 'QUEUED', ?, 'queued', ?, ?, NULL, NULL, ?, ?, NULL, NULL)",
                (job_id, input_stage, now, now, str(request_path), str(run_dir)),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def recoverable_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM jobs WHERE status='QUEUED' ORDER BY created_at"
            ).fetchall()
            connection.execute(
                "UPDATE jobs SET status='FAILED', progress_step='interrupted', "
                "error='service restarted during GPU pipeline; submit a new job', "
                "completed_at=?, updated_at=? WHERE status='RUNNING'",
                (utcnow(), utcnow()),
            )
        return [row[0] for row in rows]

    def mark_running(self, job_id: str) -> None:
        now = utcnow()
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='RUNNING', progress_step='starting', started_at=?, updated_at=?, error=NULL "
                "WHERE job_id=?",
                (now, now, job_id),
            )

    def progress(self, job_id: str, step: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET progress_step=?, updated_at=? WHERE job_id=?",
                (step, utcnow(), job_id),
            )

    def succeed(self, job_id: str, result_path: Path) -> None:
        now = utcnow()
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='SUCCEEDED', progress_step='complete', result_path=?, "
                "completed_at=?, updated_at=? WHERE job_id=?",
                (str(result_path), now, now, job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        now = utcnow()
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='FAILED', progress_step='failed', error=?, completed_at=?, updated_at=? "
                "WHERE job_id=?",
                (error[:4000], now, now, job_id),
            )
