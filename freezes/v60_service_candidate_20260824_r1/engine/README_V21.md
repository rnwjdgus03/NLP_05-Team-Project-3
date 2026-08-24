# KOSIS Hybrid v21

v21 keeps the v20 safety contract and changes four independently auditable stages.

1. Stage A groups candidates by organization, survey/statistics ID, and normalized table family. Revision years do not split a family, while semantic axes such as `품목별` and `국가별` remain distinct. One leader per family is reserved before remaining Top-k slots are filled.
2. Component search applies a hard ITEM/OBJ hierarchy gate. A broad product target cannot be satisfied by a detailed HS leaf through substring similarity, and an explicit all-products target requires an official aggregate OBJ.
3. HCX and the CSV preparation fallback both repair relative months and comparison-value periods. Publication date is used only as the anchor for explicit relative expressions; a comparison record year is never reused as the delta observation period.
4. Actual-coordinate gold expands from 30 rows / 6 tables to 40 rows / 14 tables. Only locked `FULL_KOSIS` coordinates are admitted; `CODEBOOK_KOSIS` and table-only labels are excluded.

`write_kosis_run_manifest.py` excludes `.pytest_cache`, `.test-tmp-*`, Python bytecode, and common linter caches from the code digest. The source bundle and semantic-index SHA remain separately recorded in `run_manifest.json`.

Run the Colab notebook `KOSIS_hybrid_GPU_v21_family_hierarchy_period_gold.ipynb`. Existing READY52 regression uses the 30 overlapping gold rows; the 10 cross-survey rows are retained for the next mixed-claim evaluation and are visible through `eligible_overlap`.
