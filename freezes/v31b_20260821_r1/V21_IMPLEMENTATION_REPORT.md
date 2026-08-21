# v21 implementation report

## Implemented

- Survey/organization/table-family Stage A consensus reranking and family-diverse Top-k selection.
- Exact OBJ hierarchy gate for aggregate products, broad product labels, and detailed HS leaves.
- HCX prompt and deterministic post-processing for `작년 N월`, `지난달`, `한 달 전`, and explicit comparison-record years.
- The same period recovery in `prepare_kosis_mapping_input.py`, so an existing HCX CSV can be repaired without paying for another HCX run.
- Stratified actual-coordinate gold: 40 rows, 14 tables, 6 organizations, maximum single-table share 32.5%.
- Stable code SHA exclusions for `.pytest_cache`, `.test-tmp-*`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pyc`, and `.pyo`.

## Verification

- v21 pipeline tests: 20 passed.
- HCX extraction/prompt tests: 32 passed.
- Gold builder rejects incomplete coordinates, duplicate measurement IDs, `CODEBOOK_KOSIS`, and table-only labels.

## Evaluation boundary

No new GPU retrieval result is claimed in this package. The notebook creates a fresh OUT_DIR and measures v21 on execution. The 30 overlapping READY52 rows preserve direct v20 regression comparability; the additional 10 rows broaden the locked evaluation asset but need their corresponding claim input for a full 40-row retrieval score.
