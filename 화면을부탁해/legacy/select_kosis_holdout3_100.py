"""Select the 3rd independent 100-row sample, excluding gold100 + holdout100 +
holdout2_100 (the 300 rows already used across the two prior independent
holdouts and the dev/gold set). Uses the same leakage-resistant, salted,
domain/bucket-stratified selection logic as select_kosis_holdout100.py so this
sample is drawn the same way as the first two, just with a different salt and
a wider exclusion list.

Output: outputs/bteam_holdout3/holdout3_100_selection.csv (org_id/tbl_id/... and
all *_verdict-style columns are left as-is from the source pipeline; the actual
gold_* judgement columns still need to be filled in by hand, the same way
holdout2_100_review.csv was built from holdout2_100_selection.csv).
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path


repo = Path(__file__).resolve().parent
os.environ["KOSIS_HOLDOUT_EXTRA_EXCLUDE"] = os.pathsep.join(
    str(repo / path)
    for path in (
        "outputs/bteam_holdout/holdout100_selection.csv",
        "outputs/bteam_holdout2/holdout2_100_selection.csv",
    )
)
os.environ["KOSIS_HOLDOUT_EXTRA_SOURCE"] = str(
    repo / "outputs/archive/bteam_poc_20260714/bteam_verification/bteam_kosis_review_manual_prioritized_4403.csv"
)
os.environ["KOSIS_HOLDOUT_SELECTION_OUTPUT"] = str(repo / "outputs/bteam_holdout3/holdout3_100_selection.csv")
os.environ["KOSIS_HOLDOUT_RANK_SALT"] = "kosis-holdout-v3-independent"

runpy.run_path("select_kosis_holdout100.py", run_name="__main__")
