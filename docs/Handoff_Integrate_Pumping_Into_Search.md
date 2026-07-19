# Handoff: Make Pumping a Real, Searched Move Inside the Optimizer

**Audience:** the coding assistant working in this repo. Assumes full
familiarity with the codebase, `Optimality Scope.md`, and
`excluded_move_at_scale.py`.

**Scope discipline, read this first:** this handoff has exactly one
goal. Do not expand it into a general "explore all possible search
extensions" task, and do not chase any new anomalies this turns up
without reporting back first. If something surprising shows up while
doing this (a big score jump, a case that looks wrong, a runtime
blowup), stop, note it, and report back rather than investigating
further unprompted. We have already gone down one unplanned rabbit hole
this project and are deliberately avoiding a second one.

---

## The problem, explained plainly

The paper this project is built on (`Integrating`) describes purification
scheduling as flexible in two distinct ways:

1. **Where** purification happens (generation, single link, arbitrary
   multi-hop segment, end node) — call this the "split/join" dimension.
2. **How** a given stretch of the connection gets purified in the first
   place — including, critically, **pumping**: building two (or more)
   independently-generated copies of the same stretch, then purifying
   them against each other, as opposed to purifying only within a
   single build of that stretch.

Our search code (`dp_search`, `beam_search`, both built on
`_SpanPartitionSearch.frontier`) handles dimension 1 well: it recursively
splits any span into two parts, builds each part optimally, and joins
them. This is real, exhaustive-within-its-own-family search.

It does **not** handle dimension 2 as a real, searched choice. Pumping
only exists in the codebase today as a handful of rigid, hardcoded
presets inside `brute_force_search` (uniform copies, same circuit
applied everywhere, fixed to a few shapes like `end_heralded`/
`end_optimistic`), plus one standalone validation script
(`excluded_move_at_scale.py`) that manually constructs one specific
pumped candidate outside the normal search path.

This means: right now, whenever pumping two *non-uniform* or
*partially-optimized* candidates together would actually be the best
strategy, our search cannot find it on its own. It can only stumble
onto pumping via the handful of frozen presets, or via a one-off script
run by hand. This is not a minor edge case, pumping is one of the two
central mechanisms the paper itself describes, so a search that can't
really explore it isn't yet searching the space the paper is about.

We saw a concrete symptom of this already: at large N, the split/join
search alone could not find any feasible schedule even at a large
resource budget, while a manually-constructed pumped candidate found
one easily at a much smaller budget. That gap is the direct consequence
of this missing capability, not a separate bug.

---

## What to build

Add pumping as a genuine option **inside** `_SpanPartitionSearch`'s own
recursive search, so it is evaluated on equal footing with the existing
split/join option at every span, not bolted on afterward.

### Concretely

At each span `(a, b)` (the same spans the recursion already computes a
frontier for), in addition to the existing "split at some point `m` and
join the two halves" option, add a **"pump" option**:

- Take **two independent candidates for this same span `(a, b)`**,
  each built from a *fresh, non-overlapping* set of Gen nodes (this is
  the exact independence requirement already correctly implemented in
  `excluded_move_at_scale.py`, reuse that logic directly rather than
  re-deriving it, including its disjoint-node-id check, that check is
  not optional).
- Purify the two together with each of the three circuits (YY, ZX, XZ),
  same as the existing purification step elsewhere in the code.
- Add whichever of these three results are non-dominated to this span's
  frontier, exactly as split/join candidates already are.

**Where do the two independent candidates come from?** Reuse this
span's own frontier, recursively, i.e. the same frontier this function
is in the middle of building. This is the self-referential structure
the existing `dp.py` docstring already flags as the excluded move. To
keep this tractable and avoid infinite recursion:

- Only allow pumping using candidates that are strictly cheaper than
  the pumped result's budget allows (standard recursive-search
  bounding, the two copies plus the purification cost must fit under
  whatever cost ceiling this call is working within).
- Cap the recursion depth of pumping specifically, e.g. a span may pump
  at most once (its own two children may themselves use split/join
  freely, but do not allow pumped-pumped-pumped nesting beyond one
  level) as a first version. This keeps the state space bounded and
  matches what's actually been validated (`excluded_move_at_scale.py`
  only ever pumps once, at the top span). If this cap turns out to be
  too restrictive later, that's a separate future step, not part of
  this one.
- Keep this behind a beam-limited frontier (same `beam_width` the rest
  of the search already uses), not an exact/exhaustive frontier, for
  the same tractability reasons already documented in the existing
  beam-width sweep.

### What NOT to do

- Do not remove or change the existing split/join logic, pumping is an
  *additional* option per span, not a replacement.
- Do not attempt unlimited pumping depth or pumping with more than 2
  copies in this pass, keep the scope to what's specified above.
- Do not build a new standalone script for this, integrate it into the
  existing `_SpanPartitionSearch` class so `dp_search` and `beam_search`
  both get it automatically, since they share this class.
- Do not go looking for or trying to explain anomalies beyond what's
  asked for in the validation section below.

---

## Validation, in order

Do these in order and stop to report if any of them fail or look wrong,
don't proceed past a failing check.

1. **Existing test suite still passes** (233 tests), unchanged, since
   this is an additive change to the frontier computation.
2. **Sanity check at N=3**: re-run (or adapt) the exact scenario from
   `optimality_gap_example.py`. Before this change, that script had to
   manually construct the pumped candidate because the search couldn't
   find it. After this change, `dp_search`/`beam_search` should find a
   schedule **at least as good** as that manually-constructed one, on
   their own, with no special-casing. This is the core proof the
   integration actually works, not just compiles.
3. **Re-run the existing `sweep_beam_width.py` DP cross-check** (N=6):
   confirm beam search still matches exact DP exactly, now that both
   have a larger space to search. This checks the new option doesn't
   break the beam/DP agreement that was already validated.
4. **Re-run the N=18 case** from `excluded_move_at_scale.py`'s scenario,
   but now via plain `beam_search`, no manual script. Report whether it
   finds a feasible schedule at the paper's own budget on its own. This
   is the direct test of whether the original symptom is actually
   fixed by proper integration, rather than needing a side script.
5. **Report runtime** for a couple of representative sizes (N=6, N=10,
   N=18, at the existing default beam width) so we know the practical
   cost of turning this on. If it's dramatically slower than before,
   report that plainly rather than trying to optimize it further
   without checking in first.

---

## What I'm expecting back

A short report (not a new roadmap, not new sweeps) covering exactly:

- Confirmation the 233 tests still pass.
- The N=3 result: does unmodified `dp_search`/`beam_search` now find
  the pumped candidate on its own, and does its score match or beat
  the manually-constructed one from `optimality_gap_example.py`.
- The N=6 DP-vs-beam cross-check result.
- The N=18 result: does plain `beam_search` (no special script) now
  find a feasible schedule at the paper's own budget.
- Runtime numbers at N=6, 10, 18.
- Nothing else. No new sweeps, no new claims, no new plots. Just: does
  the optimizer now actually search this properly, yes or no, with
  these four checks as the evidence either way.

Once I have that back, we'll decide together what sweeps are actually
worth re-running now that the search itself is trustworthy.
