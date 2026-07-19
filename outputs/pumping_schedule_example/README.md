# Pumping schedule example: deepest purification chain found

docs/Handoff_Timing_and_Pumping_Visualization.md, Part 2.

## Already-seen baselines (fixed builders, for context)

- `flexible_paper_schedule(N=4)`: chain depth = 2
- `baseline_end_node_pumping(N=4, n_pur=5)`: chain depth = 1

## Configs tried (beam_search, pumping enabled, default settings)

| N | e_d | f_min | label | chain depth | score | F | R | cost |
|---|-----|-------|-------|--------------|-------|---|---|------|
| 3 | 0.008 | 0.95 | beam.span.(hop0+(hop1+hop2)) | 0 | 33333.3 | 0.9533 | 3.333e+04 | 6 |
| 3 | 0.010 | 0.98 | beam.span.(pump[YY](hop0.n3.YY_ZX,hop0.n3.YY_ZX)+(hop1.n3.ZX_YY+hop2.n3.ZX_YY)) | 3 **<- selected** | 26580.8 | 0.9859 | 2.658e+04 | 24 |
| 4 | 0.008 | 0.95 | beam.span.(hop0.n3.YY_ZX+(hop1+(hop2+hop3.n2.ZX))) | 2 | 23455.6 | 0.9530 | 2.346e+04 | 14 |
| 4 | 0.010 | 0.98 | beam.span.(pump[YY](hop0.n3.YY_ZX,hop0.n3.YY_ZX)+(pump[YY](hop1.n3.YY_ZX,hop1.n3.YY_ZX)+(hop2.n3.ZX_YY+hop3.n3.ZX_YY))) | 3 | 17680 | 0.9857 | 1.768e+04 | 36 |
| 4 | 0.010 | 0.95 | beam.span.(pump[YY](hop0.n3.YY_ZX,hop0.n3.YY_ZX)+(hop1.n2.YY+(hop2+hop3.n2.YY))) | 3 | 21027.5 | 0.9540 | 2.103e+04 | 22 |

## Result

Deepest chain found: **3** rounds, at N=3, e_d=0.010, f_min=0.98 (label `beam.span.(pump[YY](hop0.n3.YY_ZX,hop0.n3.YY_ZX)+(hop1.n3.ZX_YY+hop2.n3.ZX_YY))`) -- deeper than the already-seen baselines (max depth 2).

- Score: 26580.8
- Fidelity F: 0.9859
- Rate R: 2.658e+04
- Resource cost C (Gen-node count): 24

## Visualization

- DOT source: `schedule.dot`
- Rendered SVG: `schedule.svg`
- Rendered PNG: `schedule.png`

The rendering reuses the existing per-node-type color/shape convention (`schedule.visualize.to_dot`). The two independent copies converging into each Purify-* node along the deepest chain are additionally boxed in labeled clusters: the chain's own Purify-* nodes in one color, and each round's freshly-generated independent copy in a second color -- making every pumping move along the chain visually distinguishable from an ordinary split/join.
