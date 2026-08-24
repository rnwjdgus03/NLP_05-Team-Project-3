# V36 fixed Stage-A rank blend

V36 was developed only on `v36_generalization_dev200_20260822_r1`, which has
zero table overlap with v33, v34 development, v35 blind, and historical gold.
V35 rows were never read for tuning; their table IDs were used only as an
exclusion set.

The selected fixed blend preserves the existing cross-encoder score and adds
small, per-claim normalized evidence from ITEM component recall, hybrid RRF,
and structural metadata. Five table-level folds selected the weights. The
production application requires no gold labels.

Development results on 200 claims:

- base unique-coordinate ITEM Top-5: 71.0%
- base unique-coordinate coordinate Top-5: 67.0%
- KOSIS API exact-match multigold ITEM Top-5: 80.0%
- KOSIS API exact-match multigold coordinate/full Top-5: 77.0%
- API alternates: PostgreSQL-valid, exact-period, VERIFIED_MATCH/MATCH only

These are development results, not blind evidence. The candidate must be
frozen before selecting another table-disjoint blind100.
