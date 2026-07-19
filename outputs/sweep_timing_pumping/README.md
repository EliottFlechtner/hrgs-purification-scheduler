# Timing sweep: dp_search / beam_search with pumping enabled

docs/Handoff_Timing_and_Pumping_Visualization.md, Part 1.

## Config

- Network: paper's own `integrating_paper_config` shape, generalized to variable N
  (`length=2.0, branching=(16,14,1), arm_count=18, p_x_inner=p_z_inner=0.0, e_d=0.01,
  gamma=0.0, c=2e5`).
- `e_max = 10*N`, objective = maximize rate with fidelity floor f_min=0.9.
- `beam_search(beam_width=25)` (default); `dp_search` at its default settings
  (pumping enabled, `exact_pumping=False`, i.e. heuristic-capped pumping frontier).
- Hard per-point timeout: 300s, enforced via a separate `multiprocessing.Process`
  killed on timeout. Once a method exceeds the cap at some N, it is skipped at every
  larger N (checked independently per method).
- Per-child-process memory cap: 3 GiB (`RLIMIT_AS`).

## Practical N ceiling

- dp_search: completed at every N tried (up to N=18), never hit the 300s cap.
- beam_search: completed at every N tried (up to N=18), never hit the 300s cap.

## Consistency check against earlier ad-hoc points

docs/Handoff_Integrate_Pumping_Into_Search.md's validation checks earlier reported,
for `beam_search` under this exact paper config: N=10 -> 15.22s (score=6195.95),
N=18 -> 139.70s (score=1214.41). (Its N=6 number, 6.75s, used a *different*,
nonzero-inner-error network, so it is not expected to match here.) See `results.csv`
for whether N=10/N=18 in this sweep land close to those figures.

## Full results

See `results.csv` for the raw per-point data and `runtime_vs_n.png`/`.svg` for the plot
(log-scale time axis; points that exceeded the cap are marked with an `x` at the cap
value rather than omitted).
