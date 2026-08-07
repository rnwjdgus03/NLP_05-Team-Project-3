# MCP gold 200 v5 GPU result

## Provenance

- Result ZIP: `mcp_gold_200_coordinate_ab_gpu_results_v5.zip`
- SHA-256: `f766660207cdaa69086f0b989e68753f86b4cfbc801e067f0a092cad4be92434`
- Population: 200 auto-gold development rows
- Scorable input rows: 194
- Input-review rows: 6

## Table retrieval

| Metric | Lexical | BGE reranked | Delta |
|---|---:|---:|---:|
| Recall@1 | 36.5% | 36.5% | 0.0%p |
| Recall@5 | 61.0% | 67.0% | +6.0%p |
| Recall@20 | 84.5% | 91.0% | +6.5%p |

BGE reranking improves candidate depth but not rank 1. The table retriever is
useful enough to continue; it is no longer the only dominant bottleneck.

## Coordinate A/B

| Metric | Top-5 | Top-10 | Delta |
|---|---:|---:|---:|
| Coverage | 74.5% | 83.5% | +9.0%p |
| Table accuracy | 60.5% | 67.0% | +6.5%p |
| Strict ITEM accuracy | 20.0% | 20.5% | +0.5%p |
| Period-group accuracy | 20.5% | 24.0% | +3.5%p |
| Full-coordinate accuracy | 6.5% | 5.5% | -1.0%p |

Top-10 gained 16 correct tables and lost 3. It gained 3 full mappings but lost
5, so it is not an end-to-end win despite better coverage and table accuracy.
Conditional on a correct table, Top-10 selected the correct ITM ID for 101/134
rows but the correct OBJ-L1 for only 61/134. OBJ selection and period binding
remain major bottlenecks.

## Failure that triggers v6

Three full-mapping losses (`MCPG-111`, `MCPG-115`, `MCPG-124`) kept the correct
consumer-price table but changed the ITEM from `전년동월비(%)` to `전월비`.
The claims had `change_base=전년동월`; the matching ITEM disappeared at the
global reranker cutoff after the table pool widened. v6 applies mapping
compatibility before that cutoff and preserves one compatible representative
per table/ITEM.

This is a general structural correction. It uses claim fields and public KOSIS
ITEM metadata only; it does not use gold coordinates to choose a candidate.
