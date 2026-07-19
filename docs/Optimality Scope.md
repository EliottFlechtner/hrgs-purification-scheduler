# Optimality Scope

This document states precisely what `dp_search` (the DP-over-stages
recursion in [src/hrgs_scheduler/search/dp.py](../src/hrgs_scheduler/search/dp.py),
unioned with `brute_force_search`'s fixed families) is and is not
guaranteed to find, and demonstrates with a small, reproducible example
that the known gap is real and exploitable, not merely theoretical.

This is a documentation/precision task, not new code: no `src/` files
were changed. The one new artifact is
[validation/optimality_gap_example.py](../validation/optimality_gap_example.py),
a standalone script that reproduces the counterexample below.

## 1. What the DP recursion searches natively

`_SpanPartitionSearch.frontier(a, b)` (in `dp.py`) computes a Pareto
frontier of `(cost, fidelity, success_prob)` candidates for `Span(a, b)`,
memoized so each sub-span is computed once and reused:

- **Leaf level** (`b - a == 1`, a single hop): the raw single-hop
  resource, or a link-level purification of that hop with a variable
  number of copies (`n_copies` from 1 up to `max_link_copies`) and a
  circuit sequence enumerated up to `max_enumerated_rounds`. This choice
  is made **independently per hop**.
- **Recursive level** (`b - a > 1`): for every split point
  `m ∈ (a, b)`, `join(frontier(a, m), frontier(m, b))` — pure
  error-vector composition (`operations.backbone.join`), never
  purification — combining one candidate from each side into a
  candidate for `Span(a, b)`.

This is a strict generalisation of `brute_force_search`'s
`link_level_pumped_chain` (per-hop copy-count and circuit choice can
vary hop-to-hop, and stitching order is not fixed left-to-right), and it
subsumes the `raw` family trivially (0 copies at every leaf).

## 2. What is only available via the merged brute-force families

`dp_search` returns the union of the DP-native frontier for `Span(0, N)`
and `brute_force_search`'s three additional fixed families, so nothing
brute force finds is ever lost:

| Family | What it builds | Why the DP recursion can't reach it |
|---|---|---|
| `raw` | Trivial raw chain | Redundant with the DP-native leaf case (0 copies everywhere) |
| `end_heralded` / `end_optimistic` | `n_pur` independent **full raw N-hop chains**, purified end-to-end | The DP recursion never purifies two candidates that both cover the same span — see §3 |
| `link_level` | **Uniform** `n_copies`/circuit sequence applied identically at every hop, then stitched | The DP-native leaf choice is per-hop and unconstrained, so it can approximate but isn't forced to reproduce the "same choice everywhere" structure exactly the same way (in practice it usually finds an equal-or-better per-hop-tuned alternative, but the exact uniform recipe itself is a distinct point brute force always contributes) |
| `flexible_paper` | One hardcoded structure from `ScheduleDAG.flexible_paper_schedule(N)` | Not expressible as span-partition joins/leaf choices at all; only defined for even `N` within budget |

## 3. The excluded move, precisely

The DP recursion's own module docstring already flags this
(`dp.py`, "Known scope limits"):

> Purifying "n independent copies of an already-partially-purified
> segment" ... is NOT explored recursively here.

Concretely: `frontier(a, b)`'s recursive case only ever **joins** across
**disjoint** sub-ranges `Span(a, m)` and `Span(m, b)`. It never takes two
candidates that are **both already `Span(a, b)`** — i.e. two different
(or differently-shaped) already-purified recipes for the *same* span —
and purifies them together to get a better `Span(a, b)` candidate.

`brute_force_search`'s `end_heralded`/`end_optimistic` families cover a
*narrow* special case of this move (purifying `n_pur` copies together),
but only when every copy is the trivial **raw** chain. They do not cover
purifying two distinct, already-partially-purified, non-uniform
recipes together.

So the precise gap is: **`dp_search` is not guaranteed to find any
schedule whose optimal structure requires purifying two different
non-raw, non-uniform, already-composed candidates that both cover the
same span**, unless that exact pair happens to coincide with one of the
four brute-force fixed shapes.

## 4. Concrete counterexample

Reproducible via:

```
PYTHONPATH=src python3 validation/optimality_gap_example.py
```

**Setup**: `N=3` network, `NetworkConfig.uniform(N=3, length=2.0,
branching=(16,14,1), arm_count=18, p_x_inner=0.003, p_z_inner=0.003,
e_d=0.01, gamma=1e-3, c=2e5)` — the generic small-N testbed convention
used elsewhere in this repo's cross-check scripts (not the paper's own
zero-inner-error parameters). Objective:
`ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.98)`.

`_SpanPartitionSearch.frontier(0, 3)` natively finds two distinct
cost-18 candidates for the full `Span(0, 3)`, each a link-level
purification with a *different, heterogeneous* per-hop circuit sequence:

- `A = (hop0.n3.XZ_YY+(hop1.n3.YY_YY+hop2.n3.XZ_YY))`, fidelity 0.952604
- `B = (hop0.n3.XZ_YY+(hop1.n3.YY_XZ+hop2.n3.XZ_YY))`, fidelity 0.953753

Taking the excluded move — purifying `A` and `B` together via the `XZ`
circuit, built as **two genuinely independent Gen-node subtrees** (see
the correctness note below) — yields a single validated
`ScheduleDAG` for `Span(0, 3)` at total cost `18 + 18 = 36`:

| | cost | fidelity | success_prob | rate |
|---|---|---|---|---|
| Excluded-move schedule (A purify-XZ B) | 36 | **0.989693** | 0.112945 | 3764.82 |
| Best `dp_search` finds at cost ≤ 36, `f_min=0.98` | — | 0.971736 | — | infeasible (score = −∞) |

At `f_min = 0.98`, `dp_search(net, obj, e_max=36)` reports **zero
feasible schedules** (best score is `-inf`) because its best achievable
fidelity at that budget is 0.971736 (from `brute_force_search`'s
`link_level` family, `link.n6.YY_ZX_YY_XZ_YY`) — below the floor. But a
genuinely valid, `ScheduleDAG.validate()`-passing schedule with fidelity
0.989693 exists at that exact cost. **`dp_search` incorrectly reports
"no feasible schedule" in a regime where a feasible one exists.**

### Correctness pitfall caught during construction

An earlier construction attempt purified two candidates taken directly
from a *single* `_SpanPartitionSearch` instance's memoized frontier list.
That silently under-counted cost (evaluated to cost 24, not 36) because
`frontier()`'s memoization is by span, so two different-looking
full-span candidates can share underlying Gen-node subtrees (e.g. both
reusing the same memoized `hop0` leaf). Purifying such candidates
together would double-count one physical resource as if it were two
independent ones, invalidating the independence assumption behind
`purify()`'s success-probability formula. The script in
`validation/optimality_gap_example.py` avoids this by building the two
copies from **two separate `_SpanPartitionSearch` instances** with
disjoint node-id pools and asserting no id collision before evaluating.
This is the same "fresh Gen nodes per independent copy" requirement the
`dp.py` docstring already anticipates as a real implementation cost of
closing this gap (see §3's quoted scope-limit note).

## 5. Interpretation

- The gap is **real and demonstrable at a small, easily-reproducible
  problem size** (`N=3`), not just a theoretical possibility — it took
  four attempts to find a working circuit/pair combination (`YY` and
  `ZX` combinations of the same two candidates did *not* beat
  `dp_search`'s union; only `XZ` did), so the effect is real but was not
  trivial to trigger.
- This single example does not establish how *common* or *large* the
  gap is at scale — it demonstrates existence, not prevalence. A full
  characterization (e.g. sweeping over `N` and network parameters to see
  how often the excluded move would win, and by how much) is future
  work and is explicitly out of scope here.
- Consistent with the roadmap's own risk/timebox guidance, actually
  *closing* this gap (extending `_SpanPartitionSearch` to explore
  same-span purification, with correctly independent Gen-node subtrees
  per copy) is a separate, larger implementation item and is not
  attempted in this document.
- Practical takeaway for anyone citing `dp_search` results: fidelity/
  feasibility figures near a floor should be read as **upper bounds on
  what the implemented search finds**, not as proof that no better
  schedule exists — as shown concretely above, "infeasible" can mean
  "infeasible for the searched families," not "infeasible in general."

## 6. Addendum — the gap is not just theoretical at production scale either

Per [docs/Roadmap_Derisk_and_Reframe.md](Roadmap_Derisk_and_Reframe.md)
§1, a targeted (beam-limited, not exhaustive) check of this same
excluded move was run at `N=14` and `N=18` — the two hop counts where
[outputs/sweep_hop_count/README.md](../outputs/sweep_hop_count/README.md)
reports the paper's own fixed-cost schedule and/or every schedule
`dp_search`/`beam_search` can reach failing the fidelity floor. Full
results: [outputs/excluded_move_n14_n18/README.md](../outputs/excluded_move_n14_n18/README.md).

- **`N=18` (the actual infeasibility case in that sweep): rescued.** The
  excluded move finds a valid schedule at exactly the paper's own
  budget (`e_max=180`) with F=0.928596 — clearing the `f_min=0.9` floor
  that every variant `sweep_hop_count` searched misses at that budget.
  This means the earlier report of "no feasible schedule within the
  paper's own budget at `N=18`" describes a limit of the *searched
  families*, not a true resource-insufficiency result, exactly the
  caveat this document's §5 anticipated.
- **`N=14`: also finds a feasible excluded-move schedule** (F=0.904348
  at cost 116), but a feasible schedule already existed there via
  `optimizer_matched_cost` (F=0.9121), so this is a secondary
  confirmation of the gap's reality at scale, not a rescue.
- This remains an *existence* result from a bounded (`beam_width=25`)
  search, not a claim about how often or how easily this move helps in
  general — consistent with §5's scope limits above.
