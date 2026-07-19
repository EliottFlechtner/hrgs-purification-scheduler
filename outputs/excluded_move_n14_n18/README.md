# Excluded-Move Check at N=14 and N=18

Per [docs/Roadmap_Derisk_and_Reframe.md](../../docs/Roadmap_Derisk_and_Reframe.md), §1: does the excluded same-span-purification move (demonstrated at N=3 in [docs/Optimality Scope.md](../../docs/Optimality%20Scope.md)) rescue feasibility at the paper's own budget (`e_max = 10*N`) for the two `N` values where [outputs/sweep_hop_count/README.md](../sweep_hop_count/README.md) reports the paper baseline and/or every searched variant failing the fidelity floor.

**Bounded, not exhaustive**: each of the two independent copies being purified together is sourced from a beam-limited frontier (`beam_width=25`, matching the rest of this report's convention), not an exact/exhaustive one -- an exact frontier at this `N` is expected to be intractable (see module docstring). A **positive** result below is an unconditional existence proof (any validated schedule found is real). A **negative** result means "not rescued by the excluded move within this bounded search", not "cannot be rescued" -- the true exact frontier might still contain a rescuing pair this search missed.

## Results

| N | e_max | Rescued? | Best excluded-move F | Best excluded-move cost | vs. existing best (sweep_hop_count) |
|---|---|---|---|---|---|
| 14 | 140 | **YES** | 0.904348 | 116 | existing best F=0.912092 (meets_floor=True), cost=140 |
| 18 | 180 | **YES** | 0.928596 | 180 | existing best F=0.887837 (meets_floor=False), cost=108 |

## Details

### N=14

- Frontier sizes (beam-limited, width=25): 25 (copy A) x 25 (copy B).
- Combined candidates evaluated (within `e_max=140`, across {YY, ZX, XZ}): 1875.
- Best found: `excluded_move.ZX(((hop0+hop1)+((hop2+hop3.n2.ZX)+((hop4.n3.YY_ZX+hop5.n3.YY_ZX)+(hop6.n3.YY_ZX+(hop7.n3.YY_ZX+(hop8.n3.YY_ZX+(hop9.n3.YY_ZX+(hop10.n3.YY_ZX+(hop11.n3.YY_ZX+(hop12.n3.YY_ZX+hop13.n3.YY_ZX)))))))))), (hop0+(((hop1.n2.YY+hop2.n2.YY)+((hop3+hop4)+(hop5+hop6.n2.YY)))+((hop7.n3.ZX_YY+(hop8.n3.ZX_YY+hop9.n3.ZX_YY))+((hop10+hop11)+(hop12+hop13))))))`, cost=116, F=0.904348, success_prob=0.350986, rate=2507.0457.
- Wall time: 96.9s.

### N=18

- Frontier sizes (beam-limited, width=25): 25 (copy A) x 25 (copy B).
- Combined candidates evaluated (within `e_max=180`, across {YY, ZX, XZ}): 1875.
- Best found: `excluded_move.YY((((hop0.n2.ZX+hop1.n2.ZX)+((hop2+hop3)+(hop4+hop5.n2.ZX)))+(hop6.n3.YY_ZX+((hop7.n3.YY_ZX+(hop8.n3.YY_ZX+hop9.n3.YY_ZX))+(hop10.n3.YY_ZX+(hop11.n3.YY_ZX+(hop12.n3.YY_ZX+(hop13.n3.YY_ZX+(hop14.n3.YY_ZX+(hop15.n3.YY_ZX+(hop16.n3.YY_ZX+hop17.n3.YY_ZX)))))))))), (((hop0.n2.ZX+hop1.n2.ZX)+((hop2+hop3)+(hop4+hop5.n2.ZX)))+(hop6.n3.YY_ZX+((hop7.n3.YY_ZX+(hop8.n3.YY_ZX+hop9.n3.YY_ZX))+(hop10.n3.YY_ZX+(hop11.n3.YY_ZX+(hop12.n3.YY_ZX+(hop13.n3.YY_ZX+(hop14.n3.YY_ZX+(hop15.n3.YY_ZX+(hop16.n3.YY_ZX+hop17.n3.YY_ZX)))))))))))`, cost=180, F=0.928596, success_prob=0.180855, rate=1004.7518.
- Wall time: 252.8s.

## Interpretation

**N=14**: a feasible schedule already existed at this budget before this check (`sweep_hop_count`'s `optimizer_matched_cost`, F=0.9121), so this is not an infeasibility case -- the excluded-move search here is a secondary check on whether it finds something *better*. It does not improve on the existing best within this bounded search.

**N=18**: this is the actual infeasibility case -- every variant `sweep_hop_count` searched (paper baseline, matched-cost, budget-relaxed) fails the fidelity floor at `e_max=180`. The excluded-move search **does** find a feasible schedule here (F=0.928596 >= 0.9), rescuing feasibility.

Given N=18 was rescued, `sweep_hop_count/README.md`'s "no feasible schedule at all" claim for N=18 needs the explicit correction that a feasible schedule does exist, found by the excluded move -- it just isn't reachable by `dp_search`/`beam_search` themselves. See the addenda added to both `sweep_hop_count/README.md` and `Optimality Scope.md` alongside this result.

## Reproducing

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
source .venv/bin/activate
PYTHONPATH=src python3 -u validation/excluded_move_at_scale.py
```

Total wall-clock time: ~350s.
