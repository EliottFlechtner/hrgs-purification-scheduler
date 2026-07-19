# Sweep: Optimizer vs. Paper Baseline across hop count N

Per [docs/Roadmap Remaining Work.md](../../docs/Roadmap%20Remaining%20Work.md), item 3: generalize the headline single-point experiment across the number of repeater hops, N in [2, 4, 6, 8, 10, 14, 18], at fixed $e_d$=0.01, keeping every other per-hop network parameter fixed at the paper's own values (`integrating_paper_config`'s zero-inner-error, zero-gamma parameterization) -- only N changes. Resource budget `e_max = 10*N` follows the paper's own cost formula (5 half-RGS copies/side x 2 sides x N hops), so the paper baseline is always includable at exactly its own cost.

## Headline table (per N)

Rates marked `†` come from a schedule that does **not** itself clear the fidelity floor $f_{min}$=0.9 -- `EvaluationResult` always returns a real `rate` even for infeasible schedules, but that rate is not an achievable operating point under the objective's constraint, so treat `†`-marked improvement percentages as descriptive only, not as a valid apples-to-apples comparison.

| N | e_max | Paper cost | Paper F | Paper meets floor | Paper rate | Matched F | Matched meets floor | Matched rate | Matched improvement | Budget cost | Budget F | Budget meets floor | Budget rate | Budget improvement |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 20 | 20 | 0.9865 | Yes | 41495.76 | 0.9364 | Yes | 43798.27 | +5.55% | 4 | 0.9608 | Yes | 50000.00 | +20.49% |
| 4 | 40 | 40 | 0.9729 | Yes | 17266.59 | 0.9708 | Yes | 17325.26 | +0.34% | 8 | 0.9236 | Yes | 25000.00 | +44.79% |
| 6 | 60 | 60 | 0.9590 | Yes | 9608.16 | 0.9543 | Yes | 9686.92 | +0.82% | 18 | 0.9056 | Yes | 15393.63 | +60.21% |
| 8 | 80 | 80 | 0.9445 | Yes | 6034.09 | 0.9363 | Yes | 6126.84 | +1.54% | 32 | 0.9015 | Yes | 10113.21 | +67.60% |
| 10 | 100 | 100 | 0.9295 | Yes | 4055.92 | 0.9168 | Yes | 4158.14 | +2.52% | 50 | 0.9047 | Yes | 6713.18 | +65.52% |
| 14 | 140 | 140 | 0.8973 | **No** | 2067.90† | 0.9121 | Yes | 1931.56 | -6.59% | 82 | 0.9050 | Yes | 3485.88 | +68.57% |
| 18 | 180 | 180 | 0.8616 | **No** | 1166.49† | 0.8225 | **No** | 142.35† | -87.80%† | 108 | 0.8878 | **No** | 2134.34† | +82.97%† |

## Observations

1. **The paper's own fixed-cost schedule stops clearing the fidelity floor as N grows.** `flexible_paper_schedule(N)`'s fidelity is monotonically decreasing in N under this fixed `e_d`=0.01 (more hops accumulate more depolarizing noise for a circuit whose *shape* -- and hence purification power -- does not scale up with N). At N in [14, 18] its fidelity falls below $f_{min}$=0.9. The largest N at which the paper baseline still clears the floor in this sweep is N=10.
2. **Feasibility flip at fixed cost.** At N=14 (0.8973 -> 0.9121, same cost 140), the paper's own fixed circuit family fails the fidelity floor, but a different circuit at the *exact same* resource cost (`optimizer_matched_cost`) clears it. This is the sweep's most actionable finding: for these N, no extra resources are needed to restore feasibility -- only a different choice of purification circuit at the same budget. Note the matched-cost rate can still be lower than the paper baseline's raw (infeasible) rate, since a fidelity-boosting circuit trades away some success probability -- compare the F columns, not just the rate columns, when reading these rows.
3. **No feasible schedule at all within the paper's own budget, at large N.** At N in [18], every one of the three reported variants (including the budget-relaxed optimizer, which searches the *entire* `e_max=10N` budget, not just the paper's specific circuit) fails to clear $f_{min}$=0.9. This means the paper's own linear resource-cost formula (`10*N`) is not sufficient to sustain the target fidelity at that hop count for *any* schedule this search considers -- restoring feasibility there would require a larger budget than the paper's own formula allocates, not just a smarter schedule at the same budget. This sweep does not explore raising `e_max` beyond `10*N` to find the budget at which feasibility is restored; that would be a natural follow-up.
4. Among the N values where both the paper baseline and the budget-relaxed optimizer are feasible (2, 4, 6, 8, 10), the budget-relaxed optimizer's rate improvement over the paper baseline ranges from +20.5% to +67.6%.

Full data: [`results.csv`](results.csv), [`improvement_summary.csv`](improvement_summary.csv). Figures: [`rate_vs_n.png`](rate_vs_n.png), [`fidelity_vs_n.png`](fidelity_vs_n.png), [`improvement_vs_n.png`](improvement_vs_n.png).

## Exact DP cross-check

`dp_search` is tractable at the small end of this N range under this exact zero-inner-error paper parameterization; N=6 was tested manually before writing this script and did not finish in several minutes (much slower than the N=6 case in `sweep_beam_width.py`'s cross-check, which uses nonzero inner-error params and therefore prunes more aggressively -- see module docstring). The cross-check grid is capped at N in [2, 4].

| N | dp_search time (s) | Exact rate | Exact meets floor | beam_search rate | Beam meets floor | Gap from exact (%) |
|---|---|---|---|---|---|---|
| 2 | 0.04 | 50000.00 | Yes | 50000.00 | Yes | 0.0000 |
| 4 | 0.91 | 25000.00 | Yes | 25000.00 | Yes | 0.0000 |

`beam_search` (beam_width=25) matches the exact DP optimum at both cross-check points -- consistent with `sweep_beam_width.py`'s finding that this codebase's default beam width already reaches the true optimum well before its practical runtime ceiling.

Full data: [`dp_crosscheck.csv`](dp_crosscheck.csv).

## Reproducing

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
source .venv/bin/activate
PYTHONPATH=src python3 validation/sweep_hop_count.py
```

Total wall-clock time for this script: ~216s.
