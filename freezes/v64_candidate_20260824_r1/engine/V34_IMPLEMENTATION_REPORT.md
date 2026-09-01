# v34 candidate implementation report

## Scope

v33 blind100 remains evaluation-only and was not used for tuning. v34 was developed on 150 claims from 75 tables disjoint from v33 and all historical coordinate-gold tables.

## General changes

- Backfill only forward-stale period-range metadata when no current-range candidates are sufficient; true periodicity and backward-range mismatches remain blocked.
- Preserve five bounded raw-recall slots in a Top-12 table pool.
- Store cross-encoder scores for the full Stage A retrieval pool so protected raw candidates retain an auditable table prior without a second Stage A run.
- Reserve bounded exact-ITEM candidates and table-diverse coordinates in Stage C.
- Treat `비율별/비중별/... + 금액 지표` as a classification-axis modifier rather than forcing a rate unit; plain ratio indicators remain rates.
- Evaluate official API-confirmed alternate coordinates at claim level, never per gold row.

## Development evidence

- 150 claims, 75 new tables; v33/historical table overlap: 0.
- Stage A table recall: Top-10 74.7%, Top-12 77.3%.
- Single-coordinate gold: ITEM Top-5 70.0%, coordinate Top-5 68.7%.
- KOSIS API-confirmed multi-coordinate gold (150-claim denominator): ITEM Top-5 76.0%, coordinate/full Top-5 75.3%.
- PostgreSQL preflight and exact-period KOSIS API `MATCH` are required for alternates.
- 77 regression tests passed.

## Evidence limitation

The alternate coordinates were discovered from development candidate outputs, so these metrics select the candidate but are not final blind evidence. A new table-disjoint blind100 must build or adjudicate official alternate coordinates without tuning v34, then score once.
