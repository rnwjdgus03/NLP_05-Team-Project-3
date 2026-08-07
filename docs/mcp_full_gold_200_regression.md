# MCP Full Gold 200 Development Regression

`data/gold/mcp_full_gold_200.csv` is the fixed development gold set for the
KOSIS-backed news fact verification pipeline.  Use it as a regression test
after changing prompts, retrieval, table mapping, period parsing, unit handling,
or final verdict logic.

## 1. Create the gold-free input fixture

```powershell
python evaluate_mcp_gold_200_regression.py `
  --input-fixture-out data\gold\mcp_full_gold_200_inputs.csv
```

Feed `data\gold\mcp_full_gold_200_inputs.csv` into the current pipeline.  The
pipeline prediction CSV should keep either `gold_id` or `claim_id`, and should
write one of these label columns:

- `predicted_label`, `prediction_label`, `auto_label`, or `label`
- `verdict`, `auto_verdict`, `refined_verdict`, `kosis_verdict`, or `verdict_code`

Supported labels are normalized to `SUPPORTS` and `REFUTES`; Korean `일치` and
`불일치` are also accepted.

## 2. Score a pipeline run

```powershell
python evaluate_mcp_gold_200_regression.py `
  --predictions outputs\runs\YOUR_RUN\predictions.csv `
  --output-dir outputs\regression\mcp_full_gold_200\YOUR_RUN `
  --min-covered-labels 180 `
  --min-strict-accuracy 0.70 `
  --min-strict-macro-f1 0.60
```

The evaluator writes:

- `summary.json`: headline regression metrics
- `report.md`: readable summary and confusion matrix
- `evaluated_rows.csv`: every gold row with prediction and scoring columns
- `failures.csv`: uncovered, invalid, or wrong rows for error analysis
- `confusion.csv`: label confusion counts
- `per_label_strict.csv`: precision, recall, and F1 by label

## 3. Score retrieval and mapping

Use `evaluate_mcp_gold_200_mapping.py` when you want to evaluate KOSIS table
retrieval and coordinate mapping separately from final `SUPPORTS`/`REFUTES`
labels.

```powershell
python evaluate_mcp_gold_200_mapping.py `
  --candidates outputs\runs\YOUR_RUN\table_candidates.csv `
  --mapped outputs\runs\YOUR_RUN\mapped_predictions.csv `
  --output-dir outputs\regression\mcp_full_gold_200\YOUR_RUN_mapping
```

`--candidates` should contain top-k table candidates with `gold_id` or
`claim_id`, `candidate_rank`, and `tbl_id`.

`--mapped` should contain the final selected coordinates with `gold_id` or
`claim_id`, plus fields such as `org_id`, `tbl_id`, `obj_l1`, `obj_l2`,
`itm_id`, `prd_se`, `period`, and `previous_period`.

The mapping evaluator writes:

- `retrieval_metrics.csv`: table recall and candidate coverage at k
- `retrieval_misses_at_max_k.csv`: gold rows whose table was not found by max k
- `mapping_metrics.csv`: table, item, period, and full-coordinate accuracy
- `evaluated_mappings.csv`: one scored row per gold item
- `mapping_failures.csv`: rows whose full mapping did not match
- `report.md` and `summary.json`: readable and machine-readable summaries

## 4. Sanity check

This command uses the gold labels as oracle predictions.  It should score 1.0.

```powershell
python evaluate_mcp_gold_200_regression.py `
  --predictions data\gold\mcp_full_gold_200.csv `
  --prediction-label-col gold_label `
  --output-dir outputs\regression\mcp_full_gold_200\oracle `
  --min-strict-accuracy 1.0 `
  --min-strict-macro-f1 1.0 `
  --min-covered-labels 200
```

Treat this gold set as a development benchmark, not as a human-reviewed public
benchmark.  The manifest says all rows are `FULL_KOSIS_MCP`, but
`human_reviewed=N`.

## 5. Colab GPU table retrieval v2

The first BGE-only run indexed all 107,138 tables successfully, but reached
only Recall@20 = 0.06.  The local lexical baseline reached Recall@20 = 0.41
and Recall@50 = 0.49; every BGE Top-20 hit was already present in lexical
Top-20.  Therefore the v2 run uses this guarded order:

```text
gold-free input
-> lexical Top-50 primary pool
-> Chroma/BGE-M3 Top-20 audit signal
-> BGE multilingual cross-encoder reranking
-> final table Top-20
-> ITEM/OBJ coordinate search
```

The query adapter reads `title`, `claim_text`, `claim_type`, `claim_value`, and
`claim_unit`.  It rejects answer fields such as `gold_tbl_id`; `gold_id` is
retained only as a row identifier.

Run [the Colab notebook](../notebooks/mcp_gold_200_chroma_bge_gpu_colab.ipynb)
and upload
`outputs/colab/mcp_gold_200_coordinate_ab_colab_bundle_v6.zip`.  The result
ZIP contains the lexical baseline, dense candidates, reranked candidates, and
both retrieval reports so a reranker regression cannot be hidden by a single
headline metric.

## 6. v3 unit-aware canonical retrieval

The v2 failure analysis found that every `claim_unit` was a serialized list of
all units in the sentence.  v3 binds `claim_value` back to the adjacent unit in
`claim_text`, adds general canonical table aliases, and demotes survey or
forecast tables for trade claims.  No table ID or other gold answer field is
used for retrieval.

The local 200-row development regression changed as follows:

| k | v2 lexical | v3 lexical |
|---:|---:|---:|
| 1 | 0.000 | 0.365 |
| 5 | 0.215 | 0.610 |
| 20 | 0.410 | 0.845 |
| 50 | 0.490 | 0.925 |

The BGE reranker now converts sigmoid scores back to logits and normalizes them
within each claim before fusion.  The output preserves raw probability, logit,
normalized score, lexical rank, dense rank, profile bonus, and profile reasons
for auditability.  Because these rules were developed on this 200-row set,
promotion requires a separate untouched holdout evaluation.

Before retrieval, `enrich_mcp_gold_200_inputs.py` now derives `unit`, `period`,
`prd_se`, and `previous_period` from only the publication date, claim text, and
claim value.  On the noisy auto-gold development labels it selected a unit for
200/200 rows and a period for 181/200.  Normalized field accuracy was 78.5%
for periodicity, 59.0% for period, 43.5% for previous period, and 33.5% for the
strict three-field period group.  Relative expressions and explicit historical
comparators are preserved with `period_extraction_source` for auditing.

## 7. v4 coordinate A/B and disjoint holdout

v4 separates coordinate selection into two auditable stages. The ITEM stage
first selects the statistic/indicator inside each candidate table. The OBJ
stage then selects the country, age, gender, region, or product coordinate.
Explicit target terms are matched before aggregate coordinates; when no target
is present, the aggregate coordinate remains preferred. The selector also
keeps the baseline rank-1 table fixed, so coordinate refinement cannot conceal
a table-retrieval regression.

Replaying the v3 Top-5 candidates on the 200-row development gold produced:

| metric | v3 raw Top-5 | v4 two-stage Top-5 |
|---|---:|---:|
| mapping coverage | 0.760 | 0.760 |
| table accuracy | 0.625 | 0.625 |
| item accuracy | 0.175 | 0.215 |
| period accuracy | 0.240 | 0.240 |
| full-coordinate accuracy | 0.050 | 0.075 |

The v4 Colab notebook runs the coordinate search twice with
`table_top_k=5` and `table_top_k=10`, evaluates both outputs with the same gold,
and writes `top5_vs_top10_ab/comparison.csv` plus `comparison.json`. This is a
true A/B run over one frozen retriever result, rather than a comparison between
different model runs.

The v4 rule validation packet uses 50 new articles selected from source row
301 onward. It excludes every URL present in the development gold and in
holdouts 5 and 6; four excluded or blank candidates were skipped, so the locked
selection ends at source row 354. The manifest records every selected row,
the input hash, and zero URL overlap. The holdout notebook reports blind
Top-5/Top-10 selection agreement and target-match coverage without looking at
gold answers. Accuracy labels, if desired later, must be created after this
blind run so they cannot influence v4 rules.

## 8. v4 GPU A/B result

The completed paired GPU run selected Top-10 for table candidate generation.
Compared with Top-5, Top-10 increased mapping coverage from 76.0% to 84.0% and
table accuracy from 61.0% to 68.5%. ITEM accuracy changed only from 19.0% to
19.5%, and full-coordinate accuracy remained 7.0%. The complete transition and
target-axis analysis is recorded in
[`mcp_gold_200_coordinate_ab_v4_20260807.md`](mcp_gold_200_coordinate_ab_v4_20260807.md).

## 9. holdout7 blind run

The disjoint 50-article run completed without KOSIS API errors. Top-5 and
Top-10 selected the same coordinate for all 41 commonly mapped measurements,
but none of the 42 locked measurements reached a verified KOSIS value. Only
nine articles survived the ready gate, and the structured OBJ sample contained
one age target and no country, gender, or product targets. The result is
therefore recorded as `REVIEW / INCONCLUSIVE`, not as a successful generalization
test. See [`holdout7_v4_result_20260807.md`](holdout7_v4_result_20260807.md).

## 9. v5 evaluation-input and search contract correction

The 200-row source fixture contains six rows where the extracted claim value is
actually a year, month count, vehicle model, rank, or age band. Those rows are
kept for audit but marked `NEEDS_INPUT_REVIEW`; accuracy is now reported both
over all 200 rows and over the 194 scorable rows. No row is deleted and no gold
coordinate is used to make this decision.

The enriched input now provides `claim_measurement_id`, canonical unit,
`unit_dimension`, normalized `semantic_type`, `value_type`, `measurement_role`,
`change_base`, and `comparison_period`. `CHANGE_RATE` is split by unit: percent
changes become `rate_change`, while changes expressed in people, currency, or
counts become `absolute_change`. `mapping_type` remains blank until an ITEM is
selected, then the coordinate search recovers `direct`, `rate_from_level`, or
`difference_from_level` from the claim structure and ITEM metadata.

The local gold-free CPU smoke test produced:

| Metric | All 200 | Scorable 194 |
|---|---:|---:|
| lexical table Recall@1 | 36.5% | - |
| lexical table Recall@5 | 61.0% | - |
| lexical table Recall@20 | 84.5% | 85.1% |
| coordinate coverage (Top-5, lexical coordinate fallback) | 66.0% | - |
| full-coordinate accuracy | 7.5% | 7.7% |

This CPU run is a contract smoke test, not the final model comparison. Run the
v6 Colab notebook on GPU for BGE table reranking and coordinate reranking.

## 10. v5 GPU result and v6 structural shortlist

The v5 GPU run confirmed that BGE reranking is useful for table retrieval:
Recall@5 increased from 61.0% to 67.0% and Recall@20 from 84.5% to 91.0%.
Expanding the coordinate table pool from Top-5 to Top-10 raised table accuracy
from 60.5% to 67.0%, but full-coordinate accuracy fell from 6.5% to 5.5%.

The paired failures exposed a cutoff bug. For several consumer-price claims
with `change_base=전년동월`, the wider global coordinate pool retained only the
semantically similar `전월비` ITEM and removed `전년동월비` before reranking.
v6 therefore inserts one compatible target/aggregate representative per
table/ITEM before the reranker cutoff and sorts direct, derived, then
incompatible mappings. The rule uses only structured claim fields and public
ITEM metadata, not gold coordinates.

A local lexical-only Top-10 smoke test after the change reached 27.5% strict
ITEM accuracy and 8.5% full-coordinate accuracy, compared with 20.5% and 5.5%
in the v5 GPU Top-10 run. These are different retrieval backends, so this is
only a direction check; the v6 GPU A/B remains the decision run.

Detailed evidence is recorded in
[`mcp_gold_200_v5_gpu_result_20260807.md`](mcp_gold_200_v5_gpu_result_20260807.md).

## 11. v6 GPU decision

v6 raises strict ITEM accuracy from 20.5% to 32.5% and full-coordinate accuracy
from 5.5% to 10.5% at Top-10. The intended `전년동월비` losses are fixed, so
v6 becomes the frozen pipeline baseline. Further tuning is paused because a
gold audit found only 21/200 asserted values agree with `gold_actual_value` and
24 rows compute a second change rate from an already-percent ITEM. Repair and
human review of the development gold now precede additional ranking changes.

See [`mcp_gold_200_v6_gpu_result_20260807.md`](mcp_gold_200_v6_gpu_result_20260807.md)
for the paired result and gold-quality audit.
