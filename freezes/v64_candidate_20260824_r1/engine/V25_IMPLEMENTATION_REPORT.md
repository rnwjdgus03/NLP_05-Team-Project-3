# v25 range / ITEM recall / default-total implementation

v25 is a new working copy. The frozen v24b blind code and its one-shot result
remain unchanged.

## Changes

- Normalize official Y/Q/M range strings to periodicity-specific ordinals.
- Use the same range parser in Local and MCP PostgreSQL preflight.
- Evaluate every eligible locked-gold row; a missing prediction packet is a
  failure instead of disappearing from the denominator.
- Add a bounded PostgreSQL ITEM-name-to-table recall channel before Stage A
  cross-encoder reranking. No ITEM/OBJ Cartesian vector index is created.
- Reserve configurable ITEM-recall slots in the reranker pool.
- Prevent short incidental Korean substrings such as `물가지수` → `가지`
  from becoming implicit OBJ targets. Explicit structured targets remain valid.
- Add ITEM-name prefix and simple-FTS indexes for the PostgreSQL metadata
  snapshot.
- Preserve the incumbent Stage A Top-10 and append at most two ITEM-recall
  fallback tables.
- Carry the Stage A channel label through PostgreSQL hydration and Stage B.
- Lock Stage C ranks 1-3 to the incumbent channel; expanded ITEM candidates
  are allowed to enter only ranks 4-5.

## Development A/B result (locked 30-row overlap)

| policy | Full Top-1 | Full Top-3 | Full Top-5 | decision |
|---|---:|---:|---:|---|
| v24b baseline | 15/30 | 20/30 | 22/30 | reference |
| replace/rerank expanded Top-12 | 15/30 | 19/30 | 23/30 | rejected: Top-3 regression |
| incumbent Top-3 lock + expanded rank 4-5 | 15/30 | 20/30 | 23/30 | adopted for v25 candidate |

The adopted implementation was rerun end-to-end from the merged Stage A table
pool through fresh Stage B and Stage C checkpoints. It reproduced the composed
A/B exactly: Top-1 15, Top-3 20, Top-5 23, MRR 0.59 on the 30 prediction-overlap
rows. Against all 40 eligible gold rows, including 10 missing prediction
packets as failures, Top-1/3/5 are 15/40, 20/40, and 23/40.

Stage A alone recovered 24/30 tables by Top-12 while retaining the incumbent
Top-10 unchanged. Earlier direct replacement variants (r1/r2/r3) were not
adopted because they either reduced Top-10 recall or swapped existing wins.

## Evaluation protocol

The previous 31-row blind set is diagnostic only after this change. Run the
existing development regression first, freeze code/index/snapshot hashes, and
then create a new disjoint blind gold before reporting v25 headline metrics.

Therefore these numbers are development-regression results, not a new blind
headline. The next valid comparison requires freezing this v25 candidate and
building a fresh disjoint coordinate gold without using these 30 rows for rule
changes.
