from pathlib import Path

from app.repository import JobRepository


def test_job_lifecycle(tmp_path: Path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"
    row = repository.create(job_id="job1", input_stage="claims", request_path=request, run_dir=run_dir)
    assert row["status"] == "QUEUED"
    repository.mark_running("job1")
    repository.progress("job1", "stage_a")
    assert repository.get("job1")["progress_step"] == "stage_a"
    result = tmp_path / "result.json"
    result.write_text("{}", encoding="utf-8")
    repository.succeed("job1", result)
    assert repository.get("job1")["status"] == "SUCCEEDED"


def test_running_job_is_failed_after_restart(tmp_path: Path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    repository.create(job_id="job1", input_stage="measurements", request_path=request, run_dir=tmp_path / "run")
    repository.mark_running("job1")
    assert repository.recoverable_ids() == []
    row = repository.get("job1")
    assert row["status"] == "FAILED"
    assert row["progress_step"] == "interrupted"
