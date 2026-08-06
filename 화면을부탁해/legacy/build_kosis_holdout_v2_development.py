"""Evaluate codebook v2 on the former holdout, now treated as development data."""

from __future__ import annotations

import os
import runpy


os.environ["KOSIS_CODEBOOK_FILE"] = "kosis_codebook_v2.py"
os.environ["KOSIS_HOLDOUT_STEM"] = "holdout100_v2_development"

runpy.run_path("build_kosis_holdout_evaluation.py", run_name="__main__")
