# Handoff: Timing Sweep (Pumping Enabled) + Visualize a Deep Pumping Schedule

**Audience:** the coding assistant working in this repo. Assumes full
familiarity with the pumping-integration work just completed.

**Scope discipline, as before:** two small, bounded items. Stop and
report if either produces something surprising, don't investigate
further unprompted.

---

## Part 1: Timing sweep across N, pumping enabled, with hard safety caps

**Goal:** get real, trustworthy timing numbers for `dp_search` and
`beam_search` (both with pumping enabled, i.e. default settings) across
a range of `N`, since only three ad-hoc points exist so far (N=6, 10,
18 from the validation report).

**Config:** paper's own config (`integrating_paper_config`), `e_max =
10*N`, default `beam_width` (25). Sweep `N ∈ {2, 4, 6, 8, 10, 12, 14,
16, 18}`.

### Safety requirements, given the earlier hang and the earlier OOM

- **Hard per-point timeout, not a soft one.** Wrap each individual
  `dp_search`/`beam_search` call with a real timeout mechanism (e.g.
  `signal.alarm` on Linux, or `multiprocessing` with a `.join(timeout=...)`
  and terminate on expiry, whichever is more reliable in this codebase's
  existing patterns), not just a hope that it finishes. Suggested cap:
  **5 minutes per individual call.** If a call exceeds this, record it
  as `"exceeded cap"` for that `(N, method)` pair and move to the next
  point, do not wait longer and do not retry.
- **Once a method exceeds the cap at some N, do not test that method at
  any larger N in the same run.** Runtime is expected to grow with N;
  if `dp_search` times out at, say, N=14, skip N=16 and N=18 for
  `dp_search` specifically (still test `beam_search` there if it hasn't
  hit its own cap yet, the two methods may have different ceilings).
- **Run as a background process with incremental logging**, same
  pattern as the earlier roadmap's §0 (`nohup ... &`, log file, PID
  file, print a line as each `(N, method)` point starts and finishes so
  progress is visible via `tail`). Do not run this as a blocking
  foreground call.
- **Memory caution carried over from the earlier OOM incident**: if
  launching this with `setsid`/`ulimit -v` as done before, keep that
  practice here too, this sweep touches the same code path that caused
  that crash.

### Deliverable

`validation/sweep_timing_with_pumping.py` (or similar), producing:
- `outputs/sweep_timing_pumping/results.csv`: one row per `(N, method)`,
  columns for wall-clock time, whether it completed or hit the cap, and
  (if completed) the best score found, for a free consistency check
  against already-reported numbers at N=6/10/18.
- A simple runtime-vs-N plot, one line per method, log scale on the
  time axis given the likely growth rate, with capped points marked
  distinctly (e.g. an arrow/marker at the cap value) rather than
  omitted, so the plot honestly shows where the ceiling was hit rather
  than just stopping.
- A short README stating, plainly: the practical N ceiling for each
  method under this config, at this timeout.

---

## Part 2: Visualize a real pumping schedule, specifically one with deep purification chaining

**Goal:** produce an actual DOT/graphviz rendering (structure, not just
a label string) of a schedule the search found that uses pumping, and
specifically look for one with more than the shallow one-or-two-circuit
chains seen so far (e.g. deeper than a single `XZ` followed by a single
`YY`).

### 2.1 Selecting a good example, systematically rather than by eyeballing

Do not just pick the first pumping schedule found and hope it's deep.
Instead:

- Write a small helper that, given a `ScheduleDAG`, computes its
  **purification chain depth** (the longest path through the DAG
  consisting only of `Purify-*` nodes, i.e. how many purification
  rounds are stacked on top of each other before hitting a `Gen`/`Join`
  boundary) directly from the DAG's own node/edge structure (`T`,
  `phi`), not by parsing the human-readable label string, the label is
  a summary for humans and should not be treated as the source of
  truth for this measurement.
- Run `beam_search` (pumping enabled) at a **small handful** of small-N
  configs chosen to plausibly favor deeper purification (e.g. `N=3` or
  `N=4`, at a couple of `e_d` values on the higher end of the paper's
  tested range, and/or a stricter `f_min` like 0.95-0.98 rather than
  0.9, since a stricter floor is more likely to force multiple
  purification rounds to stack). This does not need to be a full sweep,
  3-5 configs is enough.
- Across those few runs, report the purification-chain depth of the
  best-found schedule at each, and pick the deepest one found for
  visualization. If none of them turn out deeper than what's already
  been seen, report that plainly rather than forcing a contrived
  example, that itself would be a useful thing to know (i.e. maybe
  deep chaining genuinely isn't favored by the objective at small N,
  which is a fine, reportable observation on its own, not a failure of
  this task).

### 2.2 Building the visualization

Reuse the existing DAG-visualization conventions already established
earlier in this project (node shape/color by operation type: `Gen`
ellipse green, `Join/EntSwap` box blue, `BSM` diamond orange,
`Purify-YY/ZX/XZ` box purple, `Idle` dashed grey box, `Herald` yellow
box, `PauliCorrect` red double-circle, `Discard` dashed grey box) if
compatible tooling already exists in this repo or can be added cheaply
(`graphviz` Python package + system `dot`). Build directly from the
selected `ScheduleDAG`'s actual node/edge structure, not from
re-deriving it out of the label string.

**Specifically make the pumping structure visually clear**: the two
independent copies being purified together at the same span should be
visually distinguishable as two separate subtrees converging into one
`Purify-*` node, e.g. via a subgraph/cluster boundary or distinct
edge styling for "copy A" vs "copy B", so it's visually obvious this
is the pumping move and not an ordinary split/join.

### 2.3 Deliverable

- `validation/visualize_pumping_schedule.py`: the selection + rendering
  script.
- `outputs/pumping_schedule_example/schedule.dot` (or `.svg`/`.png`):
  the rendered graph.
- `outputs/pumping_schedule_example/README.md`: which config produced
  it, its purification-chain depth, its cost/fidelity/rate, and the
  depth numbers found across the small handful of configs tried in
  §2.1 (even for the ones not chosen), so the selection process is
  visible and reproducible, not just the winning picture.

---

## What I'm expecting back

- Part 1: the timing CSV, the plot, and a one-line statement of the
  practical N ceiling per method under the 5-minute cap.
- Part 2: the rendered graph, its purification-chain depth, and the
  small depth comparison table from the configs tried. If nothing
  deeper than what's already been seen turns up, say so plainly rather
  than searching further unprompted, that's a fine outcome to report
  as-is.

Nothing else. No new sweeps, no chasing surprising numbers beyond
noting them, per the usual rule.
