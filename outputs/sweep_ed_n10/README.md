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

Full per-point data: [`results.csv`](results.csv) (long format, one row per `(e_d, variant)` pair) and [`improvement_summary.csv`](improvement_summary.csv) (wide format, one row per `e_d`, with pre-computed % improvements).

## Observations

- **Zero-purification regime at low noise.** For `e_d <= ~0.004`, the budget-relaxed optimizer's global best is simply the **raw chain** (`cost=20` = 2 Gen nodes x N=10 hops, no purification at all), which already clears `f_min=0.9` on its own and gives the maximum possible rate (`10000`, i.e. `success_prob=1`). The paper's fixed 5-copy pumping structure (`cost=100`) is pure overhead in this regime — it doesn't fail, it just spends 5x the resources for a rate the raw chain already achieves. This is the sweep's clearest "design principle" finding: **purify only as much as the noise level actually requires**, not a fixed amount decided a priori.
- **Budget-relaxed improvement grows with e_d, then plateaus.** From `0%` (e_d=0, no purification needed anywhere) up to `~65-67%` once `e_d >= 0.007` — once the raw chain alone can no longer clear the fidelity floor, the optimizer starts spending on purification exactly where it's needed (see the per-hop labels in `results.csv`, e.g. `link.n2.YY` at e_d=0.008 growing to a full 3-hop-per-copy `ZX_YY` pattern by e_d=0.010), tracking the same "shape purification to where fidelity is actually lost" pattern documented in `outputs/headline_experiment_n10/README.md`.
- **Matched-cost curve is non-monotonic between e_d=0.003 and e_d=0.004** (dips to `+0.36%` after peaking at `+8.45%`), visible as a small dip in `fidelity_vs_ed.png` too. This is a real, explainable artifact of the **discrete** circuit-family search space, not a bug: at cost=100 the only candidates available are the four fixed `end_optimistic.n5.*` circuit-sequence families (`YY_YY_YY_YY`, `XZ_XZ_XZ_XZ`, `ZX_ZX_ZX_ZX`, mixed), and which one scores highest swaps abruptly as `e_d` crosses the point where their fidelity/success-probability tradeoffs cross — there is no continuous interpolation between them. Confirmed via the `label` column in `results.csv` (winner switches `YY_YY_YY_YY` -> `XZ_XZ_XZ_XZ` exactly at that crossover). Report language about this curve should describe it as "non-monotonic due to discrete circuit-family selection," not smooth.

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

Total wall-clock time for the 11-point sweep: ~148s (11 `beam_search` calls, one per e_d point; `beam_search` reuses `brute_force_search`'s families internally, so no separate brute-force pass is needed).
