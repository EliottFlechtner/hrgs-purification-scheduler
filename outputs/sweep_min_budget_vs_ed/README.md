# Minimum Required Budget vs. e_d (resource-vs-quality reframe)

Per [docs/Roadmap_Derisk_and_Reframe.md](../../docs/Roadmap_Derisk_and_Reframe.md), §3: reframes [outputs/sweep_ed_n10/](../sweep_ed_n10/README.md)'s existing percent-improvement framing into the stronger claim: minimum resource cost required to sustain a target fidelity ($f_{min}$=0.9), as a function of noise level $e_d$, rather than assuming the paper's fixed `e_max=100` choice is the right amount to spend at every noise level.

Network: `NetworkConfig.integrating_paper_config(e_d=e_d)` (N=10, the paper's exact config, only `e_d` varies). Objective: `maximize_rate_with_fidelity_floor(f_min=0.9)`. Method: bisection over `e_max` per `e_d` point, identical to [outputs/sweep_min_budget_vs_n/](../sweep_min_budget_vs_n/README.md)'s §2 method, just parameterized by `e_d` instead of `N`.

## Results

| $e_d$ | Paper's fixed $e_{max}$ | Min. feasible $e_{max}$ (this sweep) | Ratio | Best F | Best label |
|---|---|---|---|---|---|
| 0.000 | 100 | 21 | 0.210x | 1.0000 | beam.span.(hop0+(hop1+(hop2+(hop3+(hop4+(hop5+(hop6+(hop7+(hop8+hop9))))))))) |
| 0.001 | 100 | 21 | 0.210x | 0.9803 | beam.span.(hop0+(hop1+(hop2+(hop3+(hop4+(hop5+(hop6+(hop7+(hop8+hop9))))))))) |
| 0.002 | 100 | 21 | 0.210x | 0.9610 | beam.span.((hop0+(hop1+(hop2+(hop3+hop4))))+(hop5+(hop6+(hop7+(hop8+hop9))))) |
| 0.003 | 100 | 21 | 0.210x | 0.9422 | beam.span.(hop0+(hop1+((hop2+(hop3+hop4))+(hop5+(hop6+(hop7+(hop8+hop9))))))) |
| 0.004 | 100 | 21 | 0.210x | 0.9239 | beam.span.(hop0+(hop1+((hop2+hop3)+((hop4+hop5)+(hop6+(hop7+(hop8+hop9))))))) |
| 0.005 | 100 | 21 | 0.210x | 0.9061 | beam.span.(hop0+(hop1+(hop2+(hop3+(hop4+(hop5+(hop6+(hop7+(hop8+hop9))))))))) |
| 0.006 | 100 | 28 | 0.280x | 0.9023 | beam.span.((hop0.n3.YY_ZX+hop1.n3.YY_ZX)+(hop2+(hop3+((hop4+(hop5+hop6))+(hop7+(hop8+hop9)))))) |
| 0.007 | 100 | 37 | 0.370x | 0.9032 | beam.span.((hop0.n3.YY_ZX+(hop1.n3.YY_ZX+(hop2.n3.YY_ZX+hop3.n3.YY_ZX)))+(hop4+(hop5+(hop6+(hop7+(hop8+hop9)))))) |
| 0.008 | 100 | 40 | 0.400x | 0.9020 | link.n2.YY |
| 0.009 | 100 | 46 | 0.460x | 0.9032 | beam.span.((hop0+(hop1.n2.YY+(hop2+hop3)))+(hop4.n3.ZX_YY+(hop5.n3.ZX_YY+(hop6.n3.ZX_YY+(hop7.n3.ZX_YY+(hop8.n3.ZX_YY+hop9.n3.ZX_YY)))))) |
| 0.010 | 100 | 50 | 0.500x | 0.9047 | beam.span.((hop0.n2.YY+(hop1+hop2))+(hop3.n3.ZX_YY+(hop4.n3.ZX_YY+(hop5.n3.ZX_YY+(hop6.n3.ZX_YY+(hop7.n3.ZX_YY+(hop8.n3.ZX_YY+hop9.n3.ZX_YY))))))) |

Across the tested range, the minimum feasible `e_max` needed is only 0.21x-0.50x the paper's fixed `e_max=100` -- equivalently, the paper's fixed choice spends 2.0x-4.8x the minimum this sweep's searched families actually require to clear the fidelity floor, i.e. the paper's fixed choice is overspending at every point tested, most severely at low $e_d$ (where little-to-no purification is needed at all) and least severely as $e_d$ approaches its upper end of the tested range.

## Relationship to §2 / the excluded-move caveat

This sweep fixes `N=10`, where [outputs/sweep_min_budget_vs_n/](../sweep_min_budget_vs_n/README.md) (§2) already found the searched families comfortably sufficient (min. feasible `e_max=50` at `e_d=0.01`, half the paper's budget) -- N=10 is far from the N=18 regime where §2 found a search-family wall and §1's excluded move was needed to rescue feasibility. So unlike §2's N=18 result, the numbers here should be read at face value as genuine minimum requirements for this searched family at this `N`, not a lower bound qualified by an out-of-scope search move -- consistent with the hedge used throughout [docs/Optimality Scope.md](../../docs/Optimality%20Scope.md), which only bites at larger `N`.

## Figures

`min_budget_vs_ed.png` / `.svg`: minimum required `e_max` vs. `e_d`, with the paper's fixed `e_max=100` overlaid as a horizontal reference line, making visually obvious how much the paper's fixed choice overspends at each noise level.

Full data: [`results.csv`](results.csv).

## Reproducing

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
source .venv/bin/activate
PYTHONPATH=src python3 -u validation/sweep_min_budget_vs_ed.py
```

Total wall-clock time: ~510s.
