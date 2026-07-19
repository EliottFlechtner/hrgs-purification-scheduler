# Roadmap: De-risking the Headline Findings and Reframing Toward Stronger Claims

**Audience:** the coding assistant working in this repo. Assumes full
familiarity with `Repository State & Progress.md`, the previous
`Roadmap Remaining Work.md`, and the four artifacts just produced
(`sweep_ed`, `sweep_beam_width`, `sweep_hop_count`,
`Optimality Scope.md` + `optimality_gap_example.py`).

**Why this doc exists.** Two things came out of reviewing that batch of
work:

1. `Optimality Scope.md` proved, with a real reproducible counterexample
   at `N=3`, that `dp_search`/`beam_search` can report a schedule as
   infeasible when a feasible one actually exists (the excluded
   same-span-purification move). `sweep_hop_count`'s README already
   states, correctly, that its `N=18` "no feasible schedule found"
   result should be read as "not found by this search," not "does not
   exist" — but that hedge has not actually been tested against the
   headline finding itself. Given the gap is now *demonstrated*, not
   just theoretical, it needs to be checked specifically at the point
   where it matters most (`N=14`, `N=18`) before that finding is
   reported with confidence.
2. "Optimizer beats the paper's Fig. 4 schedule" is a weak headline
   claim on its own — that schedule is explicitly presented by its own
   authors as a feasibility demonstration, not a claimed-optimal
   baseline, so a systematic search outperforming a hand-picked example
   is close to expected. The report needs to lead with claims that a
   single hand-picked example structurally cannot make: resource-vs-
   quality tradeoff curves, and a scaling-law question about minimum
   required budget as a function of `N`.

None of the existing results are wrong. Every schedule any search tier
returns is a real, `ScheduleDAG.validate()`-passing object, so every
"schedule S with property P exists" claim already made is safe as-is.
What's being refined here is (a) whether the *negative* claims
("infeasible at this budget") hold up, and (b) which claims get top
billing in the report.

---

## 0. Operational note on long-running scripts (read this before running anything below)

Several items below (particularly §1 and §2) will run substantially
longer than the sweeps done so far. `dp_search` at `N=6` under the
generic testbed config already took several minutes and was manually
killed in earlier work; frontier-based computation at `N=14`-`N=18` is
expected to take considerably longer than that, plausibly tens of
minutes or more, depending on how bounded the approach ends up being
(see §1.2 for a bounded variant specifically to keep this tractable).

**Do not judge a script as hung or failed just because it is still
running after the runtimes seen in prior sweeps (~100-220s).** Use this
pattern instead of a blocking foreground call:

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
source .venv/bin/activate
PYTHONPATH=src nohup python3 -u validation/<script>.py \
  > validation/<script>.log 2>&1 &
echo $! > validation/<script>.pid
```

Then check on it periodically rather than polling tightly or blocking:

```bash
ps -p $(cat validation/<script>.pid) > /dev/null && echo "still running" || echo "finished"
tail -n 20 validation/<script>.log
```

- Add print statements to each new script marking progress at natural
  checkpoints (e.g. "starting N=14 excluded-move search...",
  "frontier(0,7) done, N pairs found: ...") so `tail`-ing the log gives
  a real signal of progress, not just silence.
- Only conclude a script is actually stuck (as opposed to slow) if the
  log has shown **no new output for over 15 minutes** at a checkpoint
  that took seconds-to-low-minutes in smaller-`N` runs, or if total
  runtime exceeds roughly **45-60 minutes** with no sign of finishing.
  Below that, let it keep running and check back later rather than
  killing and retrying.
- If a script does need to be killed for being genuinely stuck, capture
  the last ~50 lines of its log before doing so, that's diagnostic
  information for figuring out where it's stuck, not just noise to
  discard.

---

## 1. Targeted excluded-move check at N=14 and N=18 (highest priority)

**Goal:** determine whether the excluded same-span-purification move
(demonstrated at `N=3` in `optimality_gap_example.py`) rescues
feasibility at the paper's own budget (`e_max = 10*N`) for the two `N`
values where `sweep_hop_count` currently reports no feasible schedule
found (`N=14`: paper baseline fails floor but matched-cost search
finds a fix; `N=18`: no variant found feasible at all).

This is **not** a general attempt to close the DP gap (that remains
correctly out of scope per the previous roadmap's risk/timebox
guidance). This is a narrow, targeted spot-check reusing the exact
technique already validated in `optimality_gap_example.py`, applied at
the two specific points where it would change a headline conclusion.

### 1.1 What to build

Generalize the construction from `optimality_gap_example.py` (two
independent `_SpanPartitionSearch` instances with disjoint node-id
pools, asserting no id collision, then purifying one candidate from
each frontier together) into a reusable function, e.g.
`excluded_move_candidates(net, obj, span, e_max_per_copy, circuits=("YY","ZX","XZ"))`,
that:

1. Builds two independent `_SpanPartitionSearch` instances for the full
   `Span(0, N)` (or the largest sub-span within budget, see §1.2 for
   why this may need to be bounded).
2. For each pair of frontier candidates (one from each instance, cost
   within the target budget when combined) and each purification
   circuit, constructs and validates the purified `Span(0, N)`
   candidate, exactly as done for the `N=3` case.
3. Returns the best (by the objective's scoring function) validated
   candidate found this way, alongside its cost/fidelity/success_prob/
   rate.

**Important, learned from the `N=3` construction**: the correctness
pitfall already documented in `Optimality Scope.md` §4 (candidates
sharing memoized Gen-node subtrees if drawn from the same
`_SpanPartitionSearch` instance) applies here identically and must be
guarded against the same way (disjoint node-id pools, explicit
collision assertion) — do not skip this check even though it adds
overhead, it is the difference between a valid result and a silently
wrong one.

### 1.2 Why this needs to be bounded, and how

At `N=3`, the frontiers involved were small enough to search
essentially exhaustively. At `N=14`/`N=18`, a full frontier at `Span(0,
N)` is expected to be far larger (per `sweep_beam_width`'s own finding
that frontier-join cost is at least quadratic in candidate count per
span and compounds across the span tree). A literal repeat of the
`N=3` approach at `N=18` may not finish in any reasonable time.

**Recommended approach**: rather than the *exact* full frontier, use
`beam_search`'s already-bounded frontier (i.e. reuse the beam-limited
`_SpanPartitionSearch` machinery, same `beam_width` the rest of this
report uses, e.g. 25) as the source of candidates for each of the two
independent copies, instead of an unbounded exact frontier. This is a
heuristic, bounded version of the excluded move, not an exhaustive one.

**This must be stated explicitly in the writeup** (see §1.3): a
negative result under this bounded construction ("the excluded move,
searched at beam_width=25, does not rescue feasibility at N=18") is
weaker evidence than an exhaustive negative result, and should be
reported as such, i.e. "not rescued by the excluded move within the
bounded search performed here" rather than "the excluded move cannot
rescue this." A positive result (it does rescue feasibility) needs no
such hedge, since any single validated schedule found is a real
existence proof regardless of how it was found.

### 1.3 Deliverable

`validation/excluded_move_at_scale.py`, following the operational
guidance in §0 (background run, logging, progress checkpoints given
the expected runtime). Output:

- `outputs/excluded_move_n14_n18/results.csv`: for each of `N=14`,
  `N=18`, at the paper's own `e_max = 10*N`: whether the excluded-move
  search found a feasible schedule, and if so its
  cost/fidelity/success_prob/rate compared against the best result
  `sweep_hop_count` already reported at that `N`.
- `outputs/excluded_move_n14_n18/README.md`: state the result plainly
  for each `N` (rescued / not rescued under the bounded search), with
  the explicit "bounded, not exhaustive" caveat from §1.2 for any
  negative result, and a direct cross-reference back to both
  `sweep_hop_count/README.md` and `Optimality Scope.md` so a reader
  following either document lands here.
- **Update `sweep_hop_count/README.md` and `Optimality Scope.md`** with
  a short addendum linking to this result once it exists, rather than
  leaving those two documents' "infeasible" language unqualified by
  what this check found. This cross-referencing is not optional, it is
  the actual point of doing this check.

---

## 2. Minimum required budget vs. N (the scaling-law question)

**Goal:** at `N=14` and `N=18` (and, if §1 finds these two informative,
consider adding one or two more `N` values above 10 to see a trend
rather than two isolated points, e.g. `N=12`, `N=16`), find the
smallest `e_max` at which **some** schedule (searched via
`beam_search`, unioned with brute-force families as usual, and
including the §1 excluded-move check if that was worth productionizing)
clears the fidelity floor (`f_min=0.9`, matching the rest of this
report's convention), rather than stopping at the paper's own `10*N`
formula. This is the direct follow-up `sweep_hop_count/README.md`
already names as a natural next step.

### 2.1 Method: bisection, not a linear grid

Do not blindly scan `e_max` linearly from `10*N` upward, each point is
a full `beam_search` call and this needs to stay tractable given §0's
runtime concerns. Use bisection instead:

- Lower bound: `10*N` (already known infeasible at `N=14`/`18` per
  `sweep_hop_count`).
- Upper bound: start at, e.g., `4 * 10*N` and double until a feasible
  point is found (standard exponential-then-bisect search), then
  bisect between the last-infeasible and first-feasible point until
  the minimum feasible `e_max` is pinned down to within a small
  tolerance (e.g. `+/- 2`, since `e_max` is effectively discretized by
  `Gen`-node counts anyway).
- Cache every `beam_search` call's result (by `(N, e_max)`) so no
  budget point is ever recomputed if bisection revisits it.

### 2.2 Deliverable

`validation/sweep_min_budget_vs_n.py` (background-run per §0). Output:

- `outputs/sweep_min_budget_vs_n/results.csv`: one row per tested `N`,
  with the paper's own `10*N` budget, the found minimum feasible
  `e_max`, and the ratio between them.
- A plot, `min_budget_vs_n.png`: minimum required `e_max` vs. `N`,
  with the paper's own linear `10*N` line overlaid for direct visual
  comparison. If the minimum-required curve visibly diverges from
  linear (grows faster), fit and report the apparent scaling (even a
  rough power-law or exponential fit is useful here, doesn't need to
  be rigorous, just descriptive) since this is the candidate
  "large claim" for the report: a mismatch between the paper's assumed
  linear resource-scaling formula and what schedules actually require
  to sustain a fixed fidelity target as `N` grows.
- README stating the finding plainly, and explicitly noting the
  relationship (if any) to §1's excluded-move result: if §1 found the
  excluded move rescues feasibility at the paper's own budget, then
  this budget-scaling question becomes about the *searched* schedule
  families' requirements, not a strict lower bound on what any scheme
  needs, state that scoping honestly here too, consistent with the
  hedge already used throughout `Optimality Scope.md`.

---

## 3. Reframe the e_d sweep as a resource-vs-quality curve

**Goal:** turn `sweep_ed`'s existing percent-improvement framing into
the stronger claim identified in discussion: minimum resource cost
required to sustain a target fidelity, as a function of noise level.
This is largely an *analysis* task over data you can mostly already
generate with the existing `sweep_ed.py` machinery, not a new search
capability.

### 3.1 Method

For each `e_d` in the existing sweep grid (`{0.000, ..., 0.010}`, 11
points), bisect over `e_max` (same method as §2.1) to find the minimum
`e_max` at which `beam_search` finds a schedule clearing `f_min=0.9`.
This gives an 11-point curve: minimum required cost vs. `e_d`.

### 3.2 Deliverable

`validation/sweep_min_budget_vs_ed.py` (this one is likely fast enough,
given `N=10` bisection should be much cheaper than `N=14`-`18`, but
still follow §0's logging conventions for safety). Output:

- `outputs/sweep_min_budget_vs_ed/results.csv` and a
  `min_budget_vs_ed.png` plot: minimum required cost vs. `e_d`, with
  the paper's fixed `e_max=100` marked as a horizontal reference line,
  making visually obvious the regions where the paper's fixed choice
  is overspending (as already found qualitatively in `sweep_ed`'s
  "zero-purification regime" observation) versus barely sufficient.
- Update `sweep_ed/README.md`'s "Observations" section to lead with
  this reframed curve rather than the percent-improvement numbers, and
  move the percent-improvement figures to a secondary/supporting role
  rather than the headline.

---

## 4. Add a uniform-link-level baseline alongside the paper's demo schedule

**Goal:** the `link_level` family (uniform circuit sequence applied
identically at every hop) already exists in `brute_force_search` and is
already included in every `beam_search`/`dp_search` call's unioned
results, but it has not been extracted and reported as its own labeled
comparison point anywhere. This is the "reasonable default a
practitioner would actually pick" baseline, as distinct from the
paper's explicitly-labeled feasibility demonstration, and beating it is
a more meaningful practical claim.

### 4.1 Method

No new search needed. At each headline point already computed across
§1-3 and the existing three sweeps (`sweep_ed`, `sweep_beam_width`,
`sweep_hop_count`), extract the best `link_level`-family candidate
specifically (filter the existing result set by label prefix, e.g.
`label.startswith("link.")`) alongside the already-reported
`flexible_paper` and optimizer-found results.

### 4.2 Deliverable

Rather than a new script, add a `link_level` column/row to the existing
`results.csv` / `improvement_summary.csv` outputs in `sweep_ed` and
`sweep_hop_count` (retroactively, by re-deriving from already-saved
raw search output if it was persisted, or by re-running the existing
sweep scripts if raw per-label results were not kept, check first
before deciding whether this needs a rerun). Update both READMEs'
headline tables to include this third comparison column, and add one
sentence to each stating the improvement over `link_level` specifically
(distinct from the improvement over `flexible_paper`), since both
numbers are now needed for a complete comparison story.

---

## Suggested order

1. **§1 first, always.** It directly de-risks the `N=18` claim that
   §2's scaling-law result will otherwise be built on top of. Don't
   start §2 until §1 has an answer, even a "not rescued under the
   bounded search" answer, since §2's writeup needs to know how to
   scope its own claim (§2.2's note on this).
2. **§2 next.** This is the strongest candidate "big claim" for the
   report and depends on §1's outcome for correct framing.
3. **§3 and §4 can happen in parallel with, or interleaved around, §1-2**
   since they don't depend on the excluded-move outcome, they're pure
   reframing/extraction of existing or cheaply-obtained data. If time
   is short, prioritize §3 over §4 (the resource-vs-quality reframe is
   a bigger narrative upgrade than adding one more baseline column),
   but both are worth doing given there's no indication of a tight
   deadline right now.

**Checkpoint suggestion, as before**: pause after §1 and §2 specifically
(not after all four items) to report back before writing up final report
language, since §2's result in particular may reshape how the whole
"results" section of the report should be structured, and that's worth
a deliberate decision point rather than writing through it.
