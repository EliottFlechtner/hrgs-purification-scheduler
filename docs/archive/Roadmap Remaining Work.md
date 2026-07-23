# Roadmap: From Current State to Report-Ready Results

**Audience:** the coding assistant working in this repo (VSCode). This
document assumes full familiarity with `Repository State & Progress.md`
and does not re-explain anything already established there. It picks up
exactly where that document's §9 ("Suggested next steps") leaves off,
expands it, reprioritizes it against the report deadline, and adds items
that document didn't cover.

**Context for prioritization:** the user is ~6-7 weeks out from a 30-page
master's internship report (state of the art, problem definition,
formalism, personal contributions/results, conclusion) and is ahead of
the original week-by-week plan (headline experiment already produced a
result by week 3). Target venue framing is networking/quantum-engineering
(QCE/TQE-style), which means **results need to read as a coherent
experimental campaign with figures, not a single anecdote.** The current
state is one data point (`N=10`, `e_d=0.01`). Everything in "Critical
path" below exists to turn that one point into a defensible, sweep-based
results section. Everything in "Strengthening" raises the ceiling of the
report if time allows. "Stretch" items should only be touched once
Critical path is fully done and Strengthening is substantially done.

**Ground rule carried over from the existing repo culture**: every new
result must be reproducible from a single script invocation, every
physics claim must cite the exact section/equation it implements or
deviates from, and every non-obvious interpretive choice must be flagged
in a docstring or its own doc file, exactly as done so far. Do not lower
this bar for the sake of speed.

---

## Critical path (report-blocking, do these first, in this order)

### 1. Sweep the headline experiment across `e_d ∈ [0, 0.01]`

Currently only run at the single point `e_d=0.01`. Re-run
`headline_experiment_n10` logic (or a generalized version of it) across a
grid, e.g. `e_d ∈ {0, 0.001, 0.002, ..., 0.010}` (11 points, matching the
Fig. 5/6 validation scripts' own sweep granularity for visual
consistency with those reproduction figures).

**For each point, capture:**
- `flexible_paper` baseline: `F`, `success_prob`, `R`, `C`.
- Optimizer at matched cost (`C = 100`): `F`, `success_prob`, `R`.
- Optimizer at best-found cost within `C ≤ 100`: `F`, `success_prob`,
  `R`, `C`.
- The rate/fidelity delta (%) at each point, both matched-cost and
  budget-relaxed.

**Deliverable**: a `outputs/sweep_ed_n10/` directory with a `results.csv`
(long format: one row per `(e_d, schedule_variant)` pair) and a plotting
script producing at minimum: (a) rate vs. `e_d`, three lines (paper
baseline, optimizer matched-cost, optimizer budget-relaxed), (b) the same
for fidelity, (c) % improvement vs. `e_d` as a single summary curve. Use
`matplotlib` with a consistent style (see item 9 below re: a shared
plotting module, build that first if it doesn't exist yet, then reuse it
here rather than writing one-off plotting code per experiment).

**Why this is first**: it's the direct generalization of the one result
you already have and the highest-value/lowest-risk item on this whole
list. Everything needed to do it already exists in the codebase.

### 2. Sweep `beam_width` for quality/runtime characterization

Directly answers the "how performant is your optimizer" question. At a
fixed config (paper's `N=10`, `e_d=0.01`), sweep `beam_width` across a
range (e.g. `{1, 2, 4, 8, 16, 32, 64, ...}` up to whatever the DP tier's
practical ceiling is) and record, per width: wall-clock search time,
best `F`/`R` found, and (where feasible to compute, i.e. small widths)
distance from the exact-DP optimum on spans where exact DP is still
tractable, to get a real "quality vs. exact" curve, not just "quality
plateaus."

**Deliverable**: `outputs/sweep_beam_width/results.csv` +
runtime-vs-quality plot (likely a dual-axis or two-panel figure: time on
one, best-rate-found on the other, both vs. `beam_width`).

**Open question to resolve before running this**: is `beam_search`
fully deterministic (i.e. does `_beam_select`'s tie-breaking use a fixed
rule, or is there any `random`/hash-order dependence anywhere in the
tiers)? If there is any non-determinism, this sweep needs `k` repeated
runs per width with mean/std or min-max bands reported, not a single
run per width. Check this explicitly and document the answer in
`docs/`. If deterministic, say so explicitly in the report methodology
section, since a reviewer will otherwise assume some form of stochastic
search and expect error bars.

### 3. Sweep `N` (hop count) at fixed `e_d`

Run the same matched-cost / budget-relaxed comparison at several `N`
values (suggest `N ∈ {2, 4, 6, 8, 10, 14, 18}`, keeping other per-hop
config fixed at the paper's values, i.e. only `N` changes) at `e_d=0.01`.
This tests whether the optimizer's advantage is an artifact of the
paper's specific `N=10` config or a general phenomenon, and is the kind
of robustness check a reviewer will ask about if it isn't already there.

Use exact DP (Tier 2) for the small end of this range where it's
tractable (per the repo notes, roughly `N ≤ 7`-ish spans) as a
correctness cross-check against beam search's results at those same
`N`, then beam search alone for the larger `N` where DP isn't feasible.
This doubles as validation that beam search tracks DP closely on the
overlap.

**Deliverable**: `outputs/sweep_hop_count/results.csv` + a
rate-improvement-% vs. `N` plot. If there's a visible trend (advantage
growing or shrinking with `N`), that is very likely your strongest
"design principle" finding for the report, write it up as a named
observation, not just a plot caption.

### 4. Build a shared plotting/reporting module before doing any of the above

Before writing sweep scripts 1-3, add (if it doesn't already exist)
`src/hrgs_scheduler/reporting/plots.py` (or similar) with a small set of
consistent, reusable plotting helpers (consistent color scheme per
schedule variant, consistent axis labeling conventions, a standard
figure size/DPI for report inclusion, saving to both `.png` (preview)
and `.pdf` or `.svg` (for LaTeX/report embedding)). Write this once, use
it for all three sweeps above plus the Fig. 5/6 reproduction figures if
easy to retrofit. This avoids three slightly-inconsistent one-off
plotting scripts and saves real time later when assembling the report's
figure set.

### 5. Precisely scope and document the optimality claim

Per the known DP gap (partially-purified sub-span copies not explored
recursively, patched via merged brute-force families): before writing
any report language claiming DP/beam search is "optimal" or a "superset
of brute force," pin down the exact, defensible scope of that claim.
Concretely:

- Write a short `docs/Optimality Scope.md` stating precisely: which
  structural families are searched natively by the DP recursion, which
  are only available because they're merged in from
  `brute_force_search()`, and therefore what class of schedules the
  search is *not* guaranteed to find (i.e. anything requiring
  purification of copies of a partially-purified sub-span that isn't
  one of the merged-in fixed families).
- Add one constructed adversarial-ish test case if feasible: a small
  `N` where you can argue (even informally, doesn't need to be a proof)
  that the true optimum requires exactly this uncovered structure, to
  make the scope limitation concrete rather than theoretical. If no such
  case is easy to construct, that itself is worth noting (weak evidence
  the gap may not matter much in practice at these problem sizes).

This is a documentation/precision task, not new code, and it directly
prevents an overclaiming problem in the report's results section.

---

## Strengthening (meaningfully raises report quality, do after Critical path)

### 6. Attempt closing the DP gap for real (partially-purified sub-span copies)

Scope this properly before starting, don't just dive in:

- Write out (in `docs/` or as a design note) what the extended
  recursion would need to look like: currently `frontier(a,b)` explores
  split points and, at each split, either a raw hop/full-raw-chain copy
  or a recursively-optimal sub-frontier. The extension needs the
  recursion to also consider "take `n` independent draws from
  `frontier(a,b)` itself (already-partially-purified candidates) and
  purify them together" as a candidate-generation step, which is
  self-referential in a way the current code isn't. Think through
  whether this risks infinite/circular recursion (a sub-span pulling
  candidates from its own frontier) and how to bound it (e.g. cap
  purification depth `r`, which the `State` tuple already tracks per
  the formal model, §3.1, giving you a natural termination bound for
  free).
- Prototype on small `N` (`≤ 4`) first, verify against brute force,
  before scaling up.
- **Decision point, flag to the user rather than assuming**: this could
  be a multi-day task with real risk of not finishing cleanly. Given the
  report deadline, this is a good candidate to attempt only if items
  1-5 are fully done with time to spare, and even then, timebox it (e.g.
  2-3 days) and fall back to documenting the scope (item 5) if it
  doesn't converge cleanly. A well-documented known limitation is a
  perfectly fine report outcome; a half-finished, buggy extension is
  not.

### 7. Sensitivity to network configs beyond the paper's own

Run the matched-cost comparison at a couple of network configs that
*aren't* the paper's exact one, e.g. a different branching vector (try
a shallower tree, `(8,8,1)` or similar, and/or a longer per-hop
distance). This tests whether the finding is specific to the paper's
particular tuning or general. This is valuable for the networking
framing specifically (papers in this space usually want to know if a
result is an artifact of one config or holds more broadly), and is
cheap to run given the sweep infrastructure from items 1-4 already
exists by this point.

### 8. Multi-objective / Pareto frontier plots

Beyond the single "matched cost" and "budget-relaxed" points already
computed, generate full Pareto frontiers (`F` vs `C`, `F` vs `R`) at a
few representative `(N, e_d)` combinations, using the DP tier's existing
Pareto-frontier machinery (`_SpanPartitionSearch.frontier` already keeps
non-dominated `(cost, fidelity, success_prob)` tuples per span, per the
repo notes, so this is largely a matter of exposing/plotting that
existing internal data rather than computing anything new). This gives
report readers the full tradeoff surface rather than two isolated
points, and is a natural complement to the single-number headline
result.

### 9. Run and report the alternative objective presets

`cost_functions.py` already has
`maximize_fidelity_with_rate_floor`/`minimize_cost_with_constraints`
presets implemented but (per the progress doc) apparently not yet
exercised in any experiment. Run the headline config through these too
and report the results briefly, this is low-effort (infrastructure
exists) and directly demonstrates the "objective substitution" framing
from the formal model spec (§6.3) with real numbers instead of just
the abstract claim.

### 10. State the extracted design principles explicitly, as named findings

Once items 1, 3, and 7 are done, go back through the sweep results and
try to state 1-3 crisp, generalizable rules explicitly (example
templates, to be replaced with what the data actually shows, don't
force a rule that isn't there): "non-uniform per-hop purification
allocation outperforms uniform allocation by an increasing margin as
`N` grows" or "the marginal rate benefit of additional RGSS-level
purification rounds saturates beyond `n_pur = X` at this noise level."
These become the report's "personal contributions" bullet points, not
just "I built an optimizer and ran it once."

---

## Stretch (only if 1-10 are done with meaningful time still remaining)

### 11. Small adaptive-scheduling teaser (not a full implementation)

The formal model explicitly scopes out adaptive/closed-loop scheduling
as future work (§8, §3, §4.2). A full MDP implementation is out of
scope for this internship, but a small, honest illustration could
meaningfully strengthen the "perspectives" section of the report: take
one small `N` case, manually compare the non-adaptive optimum against
a hand-constructed "what if we could branch on one intermediate
purification outcome" alternative, and report whether there's visible
headroom. This does **not** need general infrastructure, a single
constructed example is enough to make the future-work section
concrete rather than speculative. Do not build general MDP machinery
for this, that would be a scope violation given the timeline.

### 12. Connection to generalized-RGS (Bikun Li) comparison

Per earlier project discussions, this was considered and set aside as
too large a scope addition. Recommend continuing to leave it out of the
report entirely, or at most one paragraph in "perspectives" noting it
as a natural extension, rather than attempting any actual comparison
code. Flagging here only so it's an explicit decision, not a dropped
thread.

### 13. Automated `timing.py` cross-check test

Already noted as low-priority in the progress doc. Only do this once
everything above is done, it's good hygiene but not results-bearing.

---

## Engineering/report-support tasks (interleave with the above, not sequential)

### 14. A single "reproduce everything" script

Add `scripts/reproduce_all.sh` (or `.py`) that regenerates every figure
and table used in the report from scratch, in order, with clear console
output of what's running. This matters for two reasons: it's good
practice the user should be able to point to in the report's
reproducibility statement, and it will save real time during the
writing phase when a figure needs to be regenerated after a late tweak.
Build this incrementally as each sweep script is written, don't leave
it for the end.

### 15. Pin the environment properly

Confirm `requirements.txt`/`pyproject.toml` (whichever exists) is fully
pinned (exact versions, not ranges) and that a clean `venv` from that
file reproduces the 233-test pass and the headline numbers exactly. Do
this once, early, rather than discovering a version-drift issue during
report writing.

### 16. Appendix material, assembled as you go rather than at the end

Keep a running `docs/Report Appendix Material.md` collecting: the full
operations catalog table (already exists in the formal model doc, just
needs pulling out), exact hyperparameters used per experiment (beam
width, budget, `n_pur`, etc., per sweep), and the full config dump for
`integrating_paper_config()`. Update this file every time a new sweep is
run rather than reconstructing it from scratch at report-writing time.

---

## Suggested sequencing against the remaining ~6-7 weeks

This is a suggestion, not a hard schedule, adjust freely, but the
dependency order (4 before 1-3, 5 before writing any optimality
language, Critical path before Strengthening before Stretch) should
hold regardless of exact week boundaries:

1. Item 4 (shared plotting module), then items 1-3 (the three sweeps),
   then item 5 (optimality scoping) — this is the core "turn one data
   point into a results section" push, do it as a tight block.
2. Items 6-10 (strengthening) — pick based on how much time is left
   after step 1; item 6 (closing the DP gap) is the only one with real
   schedule risk, timebox it explicitly per its own note above.
3. Items 14-16 (engineering/report support) — interleave throughout
   rather than doing at the end, cheapest to do incrementally.
4. Item 11 only if there's clear slack after everything else; item 12
   stays out of scope; item 13 is filler if genuinely nothing else is
   left.

**Checkpoint suggestion**: after finishing items 1-5, that is a natural
point to pause and report back (to the user, and potentially worth a
quick sync with the mentors) with the resulting figures before deciding
how much of "Strengthening" to pursue, since that decision should be
informed by what the sweeps actually show (e.g. if item 3's `N`-sweep
reveals a particularly interesting trend, that might justify spending
more time on item 7's config-generality check to substantiate it, ahead
of the higher-risk item 6).
