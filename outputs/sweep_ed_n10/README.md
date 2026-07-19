# Sweep: Optimizer vs. Paper Baseline across e_d in [0, 0.01]

Generalizes `outputs/headline_experiment_n10/` (single point, e_d=0.01) into a full sweep, per [docs/Roadmap Remaining Work.md](../../docs/Roadmap%20Remaining%20Work.md), item 1.

Grid: `e_d in {0.000, 0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.010}` (11 points), matching the granularity used by `validation/fig5_fidelity_vs_noise.py` / `fig6_rate_ratio.py`.

Network: `NetworkConfig.integrating_paper_config(e_d=e_d)` (N=10, l=2km, b=(16,14,1), k=18 arms — the paper's exact config, only e_d varies). Objective: `maximize_rate_with_fidelity_floor(f_min=0.9)`. Search: `beam_search(net, obj, e_max=100, beam_width=25)` (`e_max=100` = paper's own resource cost, so a single call yields the paper baseline, matched-cost, and budget-relaxed candidates all at once — `beam_search` always includes `brute_force_search`'s fixed families, so `flexible_paper` and the matched-cost family are present regardless of beam pruning).

## Headline numbers (endpoints of the sweep)

| e_d | Schedule | Cost | Fidelity | Success prob | Rate |
|---|---|---|---|---|---|
| 0.000 | Paper baseline | 100 | 1.0000 | 1.0000 | 10000.00 |
| 0.000 | Optimizer (matched cost) | 100 | 1.0000 | 1.0000 | 10000.00 |
| 0.000 | Optimizer (budget<=100) | 20 | 1.0000 | 1.0000 | 10000.00 |
| 0.010 | Paper baseline | 100 | 0.9295 | 0.4056 | 4055.92 |
| 0.010 | Optimizer (matched cost) | 100 | 0.9168 | 0.4158 | 4158.14 |
| 0.010 | Optimizer (budget<=100) | 50 | 0.9047 | 0.6713 | 6713.18 |

Matched-cost rate improvement: +0.0% at e_d=0.000, +2.5% at e_d=0.010.
Budget-relaxed rate improvement: +0.0% at e_d=0.000, +65.5% at e_d=0.010 (spending 20/100 and 50/100 of the paper's cost, respectively).

## Link-level baseline comparison [Roadmap_Derisk_and_Reframe.md §4]

The uniform link-level family (identical purification circuit applied at every hop) is already included in every `beam_search` call above -- it's the "reasonable default a practitioner would actually pick" without doing any optimization, distinct from the paper's own hand-picked `flexible_paper` demonstration schedule. Extracted here as its own labeled comparison point for the first time:

| e_d | Link cost | Link F | Link rate | Budget-relaxed improvement over link (%) |
|---|---|---|---|---|
| 0.000 | 40 | 1.0000 | 10000.00 | +0.00% |
| 0.001 | 40 | 0.9868 | 9737.03 | +2.70% |
| 0.002 | 40 | 0.9739 | 9481.32 | +5.47% |
| 0.003 | 40 | 0.9613 | 9232.65 | +8.31% |
| 0.004 | 40 | 0.9489 | 8990.83 | +11.22% |
| 0.005 | 40 | 0.9368 | 8755.66 | +14.21% |
| 0.006 | 40 | 0.9249 | 8526.95 | +10.02% |
| 0.007 | 40 | 0.9133 | 8304.52 | +3.75% |
| 0.008 | 40 | 0.9020 | 8088.20 | +0.00% |
| 0.009 | 60 | 0.9408 | 6197.15 | +18.24% |
| 0.010 | 60 | 0.9343 | 5877.42 | +14.22% |

The budget-relaxed optimizer's rate improvement over the *link-level* baseline specifically ranges from +0.0% to +18.2% across the sweep -- distinct from (and generally smaller than) its improvement over the paper's `flexible_paper` demonstration schedule reported above, since the link-level family is itself already a reasonable, non-hand-picked default. The improvement is exactly 0% at e_d=0.000 and e_d=0.008: at e_d=0.000 both families reach the maximum possible rate (success_prob=1, noiseless) despite different costs (raw chain, cost=20, vs. link-level's minimum cost=40, since the link-level family always applies at least one purification round); at e_d=0.008 the budget-relaxed optimizer's own global best *is* the link-level candidate (`link.n2.YY`), making the comparison trivially exact there.

Full per-point data: [`results.csv`](results.csv) (long format, one row per `(e_d, variant)` pair) and [`improvement_summary.csv`](improvement_summary.csv) (wide format, one row per `e_d`, with pre-computed % improvements).

## Figures

| File | Shows |
|---|---|
| `rate_vs_ed.png` / `.svg` | Rate vs. e_d, one line per schedule variant. |
| `fidelity_vs_ed.png` / `.svg` | Fidelity vs. e_d, one line per schedule variant, with the `f_min` floor marked. |
| `improvement_vs_ed.png` / `.svg` | Optimizer's % rate improvement over the paper baseline vs. e_d, for both the matched-cost and budget-relaxed framings. |

## Reproducing

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
source .venv/bin/activate
PYTHONPATH=src python3 validation/sweep_ed.py
```

Total wall-clock time for the 11-point sweep: ~147s (11 `beam_search` calls, one per e_d point; `beam_search` reuses `brute_force_search`'s families internally, so no separate brute-force pass is needed).
