# Real article 5-claim end-to-end report

## Run identity

- Date: 2026-08-21
- Job ID: `08bad84558a24c3dbecfe74dfcf72fc8`
- Engine: frozen `v31b_20260821_r1`
- Input: five claims from three real news articles
- Path: HCX extraction → READY gate → Stage A → Stage B → Stage C → PostgreSQL preflight → KOSIS API → public verdict

## Aggregate result

| Metric | Result |
|---|---:|
| Raw claims | 5 |
| Articles | 3 |
| HCX measurements | 12 |
| READY measurements searched | 5 |
| ENRICH measurements withheld | 6 |
| REJECT measurements withheld | 1 |
| MATCH | 2 |
| UNRESOLVED | 10 |
| VALUE_MISMATCH | 0 |

The API job completed with `SUCCEEDED`. All five READY measurements obtained Stage A Top-10 candidates. Stage B created coordinate beams for all five; Stage C selected coordinates for four and safely abstained for one.

## Resolved evidence

1. Annual exports
   - Claim: USD 683.8 billion in 2024
   - KOSIS: USD 683,609,488,000
   - Table: `DT_1R11001_FRM101`, `품목별 수출액, 수입액`
   - Verdict: `MATCH`

2. Monthly semiconductor exports
   - Claim: USD 14.5 billion in 2024-12
   - KOSIS: USD 14,511,028,387
   - Table: `DT_092_115_2009_S023`, `IT산업별/월별 수출 현황`
   - Verdict: `MATCH`

## Conservative outcomes

- The separate 31.5% growth measurement was `UNRESOLVED` because the candidate unit was uncertain.
- For shipbuilding technical workforce, Stage A correctly ranked the official `산업기술인력수급실태조사` tables, including the industrial-current-personnel table at rank 2. Stage C could not safely bind the shipbuilding OBJ coordinate, so it abstained instead of guessing.
- The foreign-workforce sentence was withheld by role/periodicity enrichment gates.
- The Korea Consumer Agency product-price survey was withheld as contextual/non-KOSIS evidence, as intended.
- No unconfirmed numeric difference was exposed as `VALUE_MISMATCH`.

## Conclusion

The deployed API contract, HCX integration, GPU queue, retrieval, coordinate selection, PostgreSQL preflight, KOSIS API lookup, result persistence, and frontend-facing serialization all work end to end. The remaining quality opportunity is resolution coverage—not safety—especially OBJ binding for the shipbuilding industry and enrichment of comparison/periodicity fields. Keep v31b frozen; address those issues in a new candidate version and regress it before promotion.
