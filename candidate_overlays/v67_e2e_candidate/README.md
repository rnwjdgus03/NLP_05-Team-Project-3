# v67 E2E candidate

Parent: `v64_candidate_20260824_r1` at Git baseline `41e297b`.

This is a development candidate. It is **not deployed**, **not frozen**, and
must not replace v64 until grouped development evaluation and a new one-shot
final test pass.

Only modified modules are copied here; unchanged dependencies remain in the
immutable parent freeze. For an isolated development smoke run, put the
overlay before the parent on `PYTHONPATH`:

```bash
PYTHONPATH=candidate_overlays/v67_e2e_candidate/engine:freezes/v64_candidate_20260824_r1/engine \
  python candidate_overlays/v67_e2e_candidate/engine/extract_hcx.py --help
```

## General, non-ID-specific changes

1. Numeric candidates use source occurrence spans as identity, so equal values
   from different periods/categories survive extraction.
2. HCX normalization binds repeated candidates one-to-one instead of mapping
   every equal `(value, unit)` to the last occurrence.
3. PostgreSQL preflight rejects duplicate axis IDs, duplicate axis orders and
   candidate axis orders that disagree with official metadata.
4. Ambiguous six-digit periods are no longer inferred as annual/quarterly
   solely from their numeric shape.
5. KOSIS response rows must echo the requested organization, table, ITEM,
   periodicity and every supplied C1-C8 code before value derivation.
6. Empty, coordinate-mismatched and nonnumeric API responses receive separate
   failure codes.

No claim ID, article text, gold coordinate or opened blind label is encoded in
these changes.

## Validation performed

- Python compilation of modified modules.
- Seven number-normalization/measurement identity smoke tests.
- Axis-order, duplicate-axis and ambiguous-period smoke tests.
- API response coordinate echo smoke tests.

The repository lacks a current negative-inclusive E2E gold aligned to v64 and
the full local PostgreSQL/model runtime. Consequently this candidate has no
new independent accuracy claim. Historical v65 results remain read-only
baseline evidence and are not tuning data.
