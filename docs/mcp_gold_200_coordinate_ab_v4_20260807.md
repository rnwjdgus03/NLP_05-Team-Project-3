# MCP gold 200 coordinate A/B v4 result

## Provenance

- Result ZIP: `mcp_gold_200_coordinate_ab_gpu_results_v4.zip`
- Imported ZIP SHA-256: `8c56807e2886e12f0b403f97961b7f739a2479a8888b808b84a65578661e922a`
- Evaluation population: development gold, 200 rows
- Compared settings: identical retrieval pipeline with coordinate table pool Top-5 vs Top-10

## Headline result

| Metric | Top-5 | Top-10 | Delta |
|---|---:|---:|---:|
| Mapping coverage | 76.0% (152/200) | 84.0% (168/200) | +8.0%p |
| Table accuracy | 61.0% (122/200) | 68.5% (137/200) | +7.5%p |
| ITEM accuracy | 19.0% (38/200) | 19.5% (39/200) | +0.5%p |
| Period-group accuracy | 24.0% (48/200) | 27.5% (55/200) | +3.5%p |
| Full-coordinate accuracy | 7.0% (14/200) | 7.0% (14/200) | 0.0%p |

Top-10 gained 17 and lost 2 correct table mappings relative to Top-5. A paired
exact sign test gives `p=0.00073`, so the table improvement is strong on this
development set. ITEM changed by 8 gains and 7 losses (`p=1.0`), while full
mapping changed by 3 gains and 3 losses (`p=1.0`). Top-10 therefore wins the
table-candidate A/B, but does not yet improve the end-to-end coordinate result.

## Two-stage coordinate diagnosis

- Top-5 and Top-10 selected exactly the same table/ITEM/OBJ tuple for 129 of
  the 152 claims mapped by both settings.
- Conditional on a correct table, OBJ-L1 was correct for 53/122 Top-5 rows and
  58/137 Top-10 rows.
- Conditional on a correct table, ITM-ID was correct for 100/122 Top-5 rows and
  104/137 Top-10 rows.
- Explicit OBJ target terms were extracted for 83/200 inputs. The selector
  found a direct target match in 47 Top-5 selections and 53 Top-10 selections.

Target-specific Top-10 results show where the next work is needed:

| Extracted target | Rows | Correct table | Correct OBJ-L1 | Full coordinate |
|---|---:|---:|---:|---:|
| Origin country | 11 | 11 | 9 | 6 |
| Destination country | 29 | 18 | 11 | 5 |
| Age group | 17 | 6 | 2 | 0 |
| Gender | 1 | 1 | 0 | 0 |
| Product | 38 | 31 | 6 | 5 |

Country linkage is useful, but age and product targets remain the main OBJ
bottlenecks. The product result also shows that finding the correct table is
not sufficient: product labels still need normalization and axis-aware matching.

## Decision

Use `table_top_k=10` for subsequent candidate generation because it improves
coverage and table accuracy materially. Do not treat Top-10 as an end-to-end
quality win yet. Keep the two-stage ITEM -> OBJ audit fields and focus the next
iteration on age-band normalization, product synonym/code matching, and final
coordinate selection among correct-table candidates. Validate those changes on
the locked disjoint holdout rather than tuning them again on these 200 rows.
