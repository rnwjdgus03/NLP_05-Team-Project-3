# End-to-End improvement audit

This directory evaluates the complete gold universe. It does not silently
restrict the denominator to `READY` rows.

## Baseline evidence

- Immutable baseline commit: `41e297b3f9327d6c2f25968f54602912407473bd`
- Historical independent v65 blind100: Table@5 59%, ITEM@5 58%, coordinate@5 54%.
- Historical dev600 resubstitution/mapping-memory results around 90% are not
  generalization estimates and must not be compared as if they were blind.
- The repository does not contain a current, negative-inclusive extraction and
  READY gold aligned to v64. Therefore a current E2E confusion matrix is
  `INSUFFICIENT_GOLD`, not zero and not the READY-only precision.

## Evaluation protocol

1. Lock an article-disjoint and table-family-disjoint split manifest.
2. Use development only for error analysis and thresholds.
3. Aggregate out-of-fold validation predictions by `claim_measurement_id`.
4. Keep all rejected/missing predictions in the denominator.
5. Open a new final test exactly once after code and thresholds are frozen.
6. Report Wilson 95% intervals and absolute correct/total counts.

Run:

```bash
python evaluation/e2e_improvement/evaluate_e2e.py \
  --gold path/to/locked_gold.csv \
  --predictions path/to/all_predictions.csv \
  --output evaluation/e2e_improvement/result.json
```

The input prediction file must contain exactly one row per complete gold ID,
including `NO_MATCH`/rejected/extraction-error cases. Missing or extra IDs fail
the evaluation so an omitted negative cannot be miscounted as a true negative.

## Failure taxonomy

Use exactly one earliest causal stage for each E2E failure:

`CLAIM_EXTRACTION_ERROR`, `MEASUREMENT_EXTRACTION_ERROR`, `SCHEMA_ERROR`,
`READY_FALSE_NEGATIVE`, `READY_FALSE_POSITIVE`, `TBL_RETRIEVAL_ERROR`,
`TBL_RANKING_ERROR`, `METADATA_ERROR`, `ITEM_MAPPING_ERROR`,
`OBJ_MAPPING_ERROR`, `TIME_MAPPING_ERROR`, `UNIT_MAPPING_ERROR`,
`COORDINATE_ERROR`, `API_QUERY_ERROR`, `VALUE_NORMALIZATION_ERROR`,
`TOLERANCE_ERROR`, `VERDICT_ERROR`, `INSUFFICIENT_GOLD`, `UNKNOWN`.
