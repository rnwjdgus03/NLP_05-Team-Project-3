from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


EXPECTED_FREEZE_ID = os.getenv(
    "KOSIS_EXPECTED_FREEZE_ID", "v64_candidate_20260824_r1"
)
EXPECTED_CODE_SHA256 = os.getenv(
    "KOSIS_EXPECTED_CODE_SHA256",
    "760033bbd941a26acd6af1fc0360ef9665ae78d46adc81e80f901c80ce5a7d64",
)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_root: Path
    engine_dir: Path
    index_dir: Path
    python: Path
    runs_dir: Path
    state_db: Path
    postgres_dsn: str
    api_key: str
    cors_origins: tuple[str, ...]
    max_rows_per_job: int
    device: str
    require_readonly_engine: bool
    kosis_delay: float

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.getenv("KOSIS_PROJECT_ROOT", "/home/ubuntu/kosis-project"))
        service_root = Path(os.getenv("KOSIS_SERVICE_ROOT", str(root / "service_api")))
        cors = tuple(
            item.strip()
            for item in os.getenv("KOSIS_CORS_ORIGINS", "http://localhost:3000").split(",")
            if item.strip()
        )
        return cls(
            project_root=root,
            engine_dir=Path(os.getenv(
                "KOSIS_ENGINE_DIR",
                str(root / "freezes" / "v64_candidate_20260824_r1" / "engine"),
            )),
            index_dir=Path(os.getenv("KOSIS_INDEX_DIR", str(root / "indexes" / "bge_m3_table_v2_complete"))),
            python=Path(os.getenv("KOSIS_PYTHON", str(root / ".venv" / "bin" / "python"))),
            runs_dir=Path(os.getenv("KOSIS_SERVICE_RUNS_DIR", str(root / "runs" / "service_v64"))),
            state_db=Path(os.getenv("KOSIS_SERVICE_STATE_DB", str(service_root / "state" / "jobs.sqlite3"))),
            postgres_dsn=os.getenv("KOSIS_POSTGRES_DSN", "postgresql:///kosis_project"),
            api_key=os.getenv("KOSIS_SERVICE_API_KEY", ""),
            cors_origins=cors,
            max_rows_per_job=int(os.getenv("KOSIS_MAX_ROWS_PER_JOB", "20")),
            device=os.getenv("KOSIS_DEVICE", "cuda"),
            require_readonly_engine=_bool_env("KOSIS_REQUIRE_READONLY_ENGINE", True),
            kosis_delay=float(os.getenv("KOSIS_API_DELAY", "0.5")),
        )

    def validate_engine(self) -> dict:
        manifest_path = self.engine_dir / "freeze_manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"frozen engine manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("freeze_id") != EXPECTED_FREEZE_ID:
            raise RuntimeError("unexpected engine freeze_id")
        if manifest.get("code_tree_sha256") != EXPECTED_CODE_SHA256:
            raise RuntimeError("unexpected frozen engine code SHA")
        required = (
            "prepare_kosis_mapping_input.py",
            "run_kosis_coordinate_stage_a.py",
            "run_kosis_coordinate_stage_b.py",
            "run_kosis_coordinate_stage_c.py",
            "run_kosis_top5_verification.py",
            "cloud_setup/run_v58_dev300_pipeline.sh",
        )
        missing = [name for name in required if not (self.engine_dir / name).is_file()]
        if missing:
            raise RuntimeError(f"engine files missing: {missing}")
        if self.require_readonly_engine:
            writable = [
                str(path.relative_to(self.engine_dir))
                for path in self.engine_dir.rglob("*")
                if (
                    path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix not in {".pyc", ".pyo"}
                    and path.stat().st_mode & 0o222
                )
            ]
            if writable:
                raise RuntimeError(f"frozen engine contains writable files: {writable[:5]}")
        for path in (
            self.index_dir / "tables.csv",
            self.index_dir / "embeddings.npy",
            self.index_dir / "manifest.json",
            self.python,
        ):
            if not path.exists():
                raise RuntimeError(f"runtime dependency missing: {path}")
        return manifest

    def probe_runtime(self) -> dict:
        environment = {**os.environ, "KOSIS_POSTGRES_DSN": self.postgres_dsn}
        gpu = subprocess.run(
            [
                str(self.python), "-c",
                "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))",
            ],
            capture_output=True, text=True, timeout=30, check=True, env=environment,
        ).stdout.strip()
        postgres = subprocess.run(
            [
                str(self.python), "-c",
                "import os,psycopg; c=psycopg.connect(os.environ['KOSIS_POSTGRES_DSN']); "
                "q=c.execute('select count(*) from kosis_tables').fetchone()[0]; c.close(); print(q)",
            ],
            capture_output=True, text=True, timeout=30, check=True, env=environment,
        ).stdout.strip()
        return {"gpu": gpu, "postgres_kosis_tables": int(postgres)}
