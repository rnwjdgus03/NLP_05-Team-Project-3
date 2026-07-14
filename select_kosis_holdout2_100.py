"""Select a fresh 100-row set excluding both gold100 and holdout100."""

from __future__ import annotations

import os
import runpy
from pathlib import Path


repo = Path(__file__).resolve().parent
os.environ["KOSIS_HOLDOUT_EXTRA_EXCLUDE"] = str(repo / "outputs/bteam_holdout/holdout100_selection.csv")
os.environ["KOSIS_HOLDOUT_EXTRA_SOURCE"] = str(repo / "outputs/archive/bteam_poc_20260714/bteam_verification/bteam_kosis_review_manual_prioritized_4403.csv")
os.environ["KOSIS_HOLDOUT_SELECTION_OUTPUT"] = str(repo / "outputs/bteam_holdout2/holdout2_100_selection.csv")
os.environ["KOSIS_HOLDOUT_RANK_SALT"] = "kosis-holdout-v2-independent"

runpy.run_path("select_kosis_holdout100.py", run_name="__main__")
