# v64 End-to-End pipeline audit

Baseline: `Poc@41e297b3f9327d6c2f25968f54602912407473bd`

This document follows executable code rather than the presentation diagram.

| Stage | Input | Implementation | Output / fields | Earliest failure |
|---|---|---|---|---|
| Article/claim input | article text or claim rows | `service_api/app/runner.py::run_job` | claim CSV | `CLAIM_EXTRACTION_ERROR` |
| Measurement extraction | claim + article/local/antecedent context | `freezes/v64_candidate_20260824_r1/engine/extract_hcx.py` (`extract_claim`, `normalize_hcx_measurements`) with HCX-007 plus deterministic numeric fallback | one or more measurement rows; value, unit, indicator, role, period, raw evidence | `MEASUREMENT_EXTRACTION_ERROR`, `SCHEMA_ERROR` |
| READY gate | measurement rows | `prepare_kosis_mapping_input.py::exclusion` | ready and rejected CSVs | `READY_FALSE_NEGATIVE`, `READY_FALSE_POSITIVE` |
| Stage A table retrieval | READY measurement | `run_kosis_coordinate_stage_a.py::retrieve_without_reranker` | BM25 + BGE-M3 + RRF candidate pool | `TBL_RETRIEVAL_ERROR` |
| Stage A table ranking | table pool | `run_kosis_coordinate_stage_a.py::rerank_table_record`, merge scripts | Top-50 then fixed Top-30 | `TBL_RANKING_ERROR` |
| Metadata / components | candidate tables | PostgreSQL metadata hydrate and component index | official ITEM and OBJ components | `METADATA_ERROR` |
| Stage B ITEM/OBJ | table + measurement + components | `kosis_component_search.py` bounded beam | ITEM/OBJ coordinate beams (up to 400) | `ITEM_MAPPING_ERROR`, `OBJ_MAPPING_ERROR` |
| Stage C coordinate | beams | `run_kosis_coordinate_stage_c.py` | coordinate Top-3 plus ranks 4-5 | `TIME_MAPPING_ERROR`, `UNIT_MAPPING_ERROR`, `COORDINATE_ERROR` |
| API exact query | Top-5, then controlled fallbacks | `run_kosis_top5_verification.py` | KOSIS response matched to requested ITEM/axes/period | `API_QUERY_ERROR` |
| Value normalization | response + claim value/unit | verification unit/derived-value functions | comparable numeric values | `VALUE_NORMALIZATION_ERROR` |
| Verdict | comparable values + tolerance policy | `run_kosis_top5_verification.py` | MATCH/MISMATCH/UNRESOLVED and reason | `TOLERANCE_ERROR`, `VERDICT_ERROR` |
| Service result | stage artifacts | `service_api/app/runner.py::build_result` | API/UI payload | denominator loss / observability error |

## Actual fallbacks

The frozen shell first runs Stage-A legacy and balanced retrieval, merges and
compresses candidates, then runs PostgreSQL component search and coordinate
reranking. After primary Top-5 API validation it can try rank 6-10,
metadata-based fallback and a multi-branch cascade. v64 additionally inserts a
development mapping-memory path before Top-5 verification. That memory is a
development resubstitution feature, not independent evidence.

## Baseline evidence, with correct scope

- v65 historical table-disjoint blind100: Table@5 **59/100**, ITEM@5
  **58/100**, coordinate@5 **54/100**. Approximate Wilson 95% intervals for
  ITEM@5 and coordinate@5 are 48.2-67.2% and 44.3-63.4%.
- v62 table-disjoint dev600 failure funnel: success 357; Stage-A table 132;
  ITEM 85; OBJ 26. Among 243 failures that is 54.3%, 35.0%, 10.7%.
- v66 URL50 candidate audit: 269 candidates, with MATCH 19,
  UNIT_UNCERTAIN 90, unconfirmed-coordinate block 68, derivation failure 32,
  semantic-scope 21 and periodicity 14.
- The reported v64 dev600 ITEM@5 90.3% / coordinate@5 90.2% reused a mapping
  memory built from the same development rows. It is not a generalization
  estimate.

## Ranked bottlenecks

1. **Table source recall and Top-5 compression.** Stage-A causes 132/243 known
   dev failures. An expanded non-leaking union reaches Table@50 85.5%, while
   Top-5 remains far lower. The correct table is often in the large pool but is
   ranked out.
2. **ITEM/OBJ/unit/derived-coordinate validation.** Correct tables still fail
   due to ITEM (85), OBJ (26), unit ambiguity, required multi-period formulas
   and missing exact coordinate evidence.
3. **Measurement identity and relations.** Equal observations at different
   periods were collapsed; current/previous/rate rows have no explicit group
   relation.
4. **Evaluation observability.** Current service artifacts do not conserve all
   extracted, rejected, failed and verified rows, so a current full E2E
   confusion matrix cannot be reconstructed.
5. **Insufficient aligned gold.** Existing coordinate fixtures are positive
   only; opened historical blinds cannot be used again for tuning. Extraction
   and READY need a new negative-inclusive, article-disjoint gold.

## Count-conservation requirements

Every production/evaluation run must satisfy both identities for row count and
unique measurement ID count:

```text
extracted = gate_ready + gate_rejected + extraction_error + quarantine
gate_ready = match + mismatch + unresolved_after_ready
```

Duplicate IDs must fail the run. Missing predictions remain failures in the
gold denominator.

## Generalization protocol

- dev600 is a synthetic coordinate fixture of 300 tables x 2 rows. Use
  `GroupKFold(group=(gold_org_id, gold_tbl_id))`; never ordinary random KFold.
- Tune cache, aliases, weights and thresholds inside training folds only.
- Report out-of-fold results and table/family clustered uncertainty.
- Do not tune on v65 or other opened blind artifacts.
- After code, prompt, metadata/index and thresholds are frozen, label a new
  article-disjoint and table/family-disjoint final test and open it once.

Until that final gold exists, independent E2E 85% is **not established**.
