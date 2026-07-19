# Outer-Loop Search: Design and Rationale

**Status:** both tiers implemented and cross-checked. `search/brute_force.py`
(exhaustive enumeration, exact ground truth for small `N`) and
`search/dp.py` (memoized recursive DP over span-partition structures,
strictly more expressive, always a superset of brute force on the same
inputs). This document explains what each algorithm searches, why the DP
is structured the way it is, and what it deliberately does *not* cover.

> **Note (added after this doc was written):** `dp_search()` later gained
> a "pumping" move (two independently-purified copies of the same span,
> see `search/dp.py`'s module docstring, "Pumping" and "Exactness modes"
> sections). That move's own per-span frontier is beam-limited by
> default for tractability — so `dp_search`'s output is only
> unconditionally exact for the pumping-free split/join search described
> in this document below; it is a bounded heuristic once pumping is
> involved, unless called with `exact_pumping=True` (uncapped, only
> tractable at very small `N`). The "superset of brute force" and
> split/join exactness claims below are unaffected by this and remain
> true as written.

See [`Validated Formal Model Def.md`](Validated%20Formal%20Model%20Def.md#7-search-algorithm)
§7 for the formal three-tier plan this implements, and
[`WbW Plan.md`](WbW%20Plan.md) for the week-by-week schedule this
satisfies ("Weeks 2-3: outer loop … DP-over-stages master algorithm …
cross-check DP against brute force on the small cases").

## 1. The search problem

Given a `NetworkConfig`, an `ObjectiveConfig`, and a resource budget
`e_max` (max `GenNode` count), find the schedule DAG `Σ` maximizing (or
minimizing) the objective's score, subject to the objective's feasibility
constraint (typically a fidelity floor). A schedule is legal iff it
passes `ScheduleDAG.validate()` — root reachability, no cycles, no extra
roots, and `κ`-stage consistency (`Gen` at `RGSS`, `Join` only between
adjacent/consistent spans, `Purify` only between same-stage states,
`PauliCorrect` only at the top-level `Span(0, N)`).

Both algorithms return the same `SearchResult` type
(`label`, `dag`, `eval_result`, `score`), so both share the display/export
tooling in `search/report.py` (`print_table`, `to_csv`, `to_json`) and the
`validation/search_results.py` CLI (`--algorithm brute_force|dp`).

## 2. Tier 1: brute force (`search/brute_force.py`)

Exhaustively enumerates three **fixed structural families**:

1. **Raw** — no purification, single `raw_chain`.
2. **End-node pumping** — `n_pur` independent full end-to-end raw chains,
   purified together at the end, in both heralded (`baseline_end_node_pumping`,
   sequential round-trip heralding between rounds) and optimistic
   (single deferred herald) variants.
3. **Link-level pumping** — every hop pumped with the *same* copy-count
   `n_copies` and the *same* circuit sequence, stitched left-to-right.

For each family, every combination of circuit sequence
(`PurificationCircuit` ∈ {YY, ZX, XZ} per round, up to
`max_enumerated_rounds` rounds enumerated exhaustively, curated fallback
beyond that) is built, evaluated, and scored. This is exact and complete
*for those three families* — it is "brute force" only within a
deliberately restricted search space, which is what keeps it tractable
and useful as ground truth (`N ≤ 4`, `e_max ≤ 40` in practice).

## 3. Tier 2: DP-over-stages (`search/dp.py`)

### 3.1 What's new vs. brute force

`κ` (the stage / span lattice) has a natural partial order: `RGSS`, then
increasing-width spans, then the final `Span(0, N)`. The DP exploits this
directly with a **Bellman-style optimal-cost-to-go computation, memoized
by span**:

$$V(\mathrm{Span}(a,b)) = \text{Pareto-optimal set of } (\text{cost}, F, P_{\text{succ}}) \text{ achievable at Span}(a,b)$$

computed bottom-up from single hops. Each span's frontier is computed
**once** and reused by every wider span built on top of it — this is the
actual algorithmic win over brute force, which re-evaluates whole
end-to-end schedules from scratch for every candidate rather than
sharing hop-level/sub-span work.

Concretely, this lets the DP explore two things brute force's fixed
link-level family cannot:

- **Variable per-hop copy-count** — hop 0 might get 3 copies purified
  while hop 3 gets 1, rather than every hop using the same `n_copies`.
- **Arbitrary split points and stitching order** — `Span(0,4)` can be
  built as `(0,2)+(2,4)`, `(0,1)+(1,4)`, `(0,3)+(3,4)`, etc., each
  recursively built from its own optimal sub-frontiers, rather than
  always joining strictly left-to-right.

This is a strict generalization of `link_level_pumped_chain`, not a
heuristic approximation of it.

### 3.2 Why multi-objective (Pareto), not a single-scalar Bellman value

A classical Bellman recursion memoizes a single scalar value per state.
That doesn't work here: a schedule's final score depends on fidelity,
success probability (→ rate), *and* resource cost jointly, and **joining
two branches multiplies success probabilities and sums costs** — there
is no single scalar "goodness" for a sub-span that composes correctly
under both operations for every possible downstream objective. Instead,
each span stores a **Pareto frontier**: the set of `(cost, fidelity,
success_prob)` triples not dominated by any other candidate at that span.
Domination (`_dominates` in `dp.py`):

```
A dominates B  ⟺  A.cost ≤ B.cost  ∧  A.fidelity ≥ B.fidelity  ∧  A.success_prob ≥ B.success_prob
                   ∧ at least one strict inequality
```

`_prune_pareto` keeps only non-dominated candidates (O(n²) skyline
filter). This is exact — pruning only discards candidates that cannot
possibly be optimal for *any* monotone objective — given the enumerated
circuit-combination grid (same caveat as brute force's
`max_enumerated_rounds`).

### 3.3 Building real `ScheduleDAG` nodes during search

Rather than a separate abstract "recipe, then materialize" two-pass
design, `_SpanPartitionSearch` builds actual `ScheduleNode` objects
(`GenNode`, `AbsaBsmNode`, `PurifyNode`, `JoinNode`) directly during the
recursive search, into one shared `nodes: dict[NodeId, ScheduleNode]`
pool with a monotonically increasing `itertools.count()` id counter. It
calls the *same* `gen`/`absa_bsm`/`join`/`purify` functions from
`operations/backbone.py` and `operations/purification.py` that the final
`Evaluator` walk uses. This eliminates an entire class of potential bugs
where search-time scoring could silently diverge from the final
evaluator's output — the search literally *is* building the schedule, not
a separate model of it.

The cost of this choice: the shared pool accumulates nodes from every
candidate ever created, including ones later pruned by Pareto dominance.
Each finalist therefore needs its own filtered subgraph before
constructing a `ScheduleDAG`, since `ScheduleDAG.validate()` rejects
unreachable nodes. `_extract_reachable` does a stack-based DFS from a
candidate's root to produce that filtered `dict[NodeId, ScheduleNode]`.

**Important subtlety — why independent copies need fresh Gen nodes, not
a reused node_id:** reusing a memoized `node_id` to represent "n
independent copies" of a resource would silently undercount
`ScheduleDAG`'s resource cost `C(Σ)` (the `nodes` dict has unique keys —
one `node_id` reused for n copies is invisible to counting). Genuine
physical duplication (fresh `Gen`/`AbsaBsm`/`Join`/`Purify` node
instances) is required wherever independent copies are purified together.
`_build_link_pumped` gets this right by calling `_build_hop` fresh
`n_copies` times for the base-case link-level candidates within a single
hop's span.

### 3.4 Latency / Herald placement

Per the existing evaluator model (see
[`Fig6 Rate Ratio Non-Reproducibility.md`](Fig6%20Rate%20Ratio%20Non-Reproducibility.md)),
only `HeraldNode` placement contributes non-zero simulated time — `Gen`,
`Join`, `AbsaBsm`, and `Purify` all cost zero time in the current model.
All span-partition candidates built by `frontier()` are therefore
Herald-free (optimistic) internally, and `dp_search()` wraps each
finalist with exactly one final `HeraldNode(propagation_time=1.0)` +
`PauliCorrectNode`, matching `flexible_paper_schedule`/
`link_level_pumped_chain`'s "single final herald" structure. This keeps
DP candidates on equal footing with brute force's optimistic/link
families rather than introducing an inconsistent latency model.

### 3.5 Known scope limits (deliberate, not silent omissions)

- **Purifying copies of an already-partially-purified segment.**
  End-node pumping purifies `n_pur` independent *full end-to-end raw*
  chains; the DP's span-partition recursion purifies independent *raw
  hops* within a span. Neither explores "take a chosen partially-purified
  sub-recipe and re-run it n independent times, then purify those
  copies" — doing that correctly requires re-instantiating a chosen
  sub-recipe with fresh `Gen` nodes per copy, a real feature deferred for
  complexity. `dp_search()` sidesteps this gap by merging in
  `brute_force_search`'s existing end-node-pumping families as-is (they
  already build fresh independent chains correctly), rather than
  reimplementing that capability inside the recursion.
- **`M_max` (concurrent open branches)** is not modeled, consistent with
  the rest of the codebase — `ResourceBudget.m_max` is not currently
  enforced by either search tier or by `ScheduleDAG.validate()`.

### 3.6 Cross-check against brute force

`dp_search()` returns the **union** of:

1. the new span-partition candidates (this module), and
2. `brute_force_search()`'s three families, reused unchanged.

By construction, `dp_search(network, objective, e_max)` is always a
superset of `brute_force_search(network, objective, e_max)` on identical
inputs — this *is* the "cross-check DP against brute force on the small
cases where both are tractable" requirement from the WbW plan, satisfied
structurally rather than by a separate equivalence proof. It is asserted
directly in `tests/test_dp.py`:

```python
def test_superset_of_brute_force_labels(self):
    bf_labels = {r.label for r in brute_force_search(net, obj, e_max=24)}
    dp_labels = {r.label for r in dp_search(net, obj, e_max=24)}
    assert bf_labels.issubset(dp_labels)
```

together with a companion test that the DP's best score is never worse
than brute force's best score on the same inputs
(`test_dp_best_score_at_least_as_good_as_brute_force`), and a test that
the DP's cheapest (no-purification) candidate reproduces `raw`'s
fidelity/cost exactly (`test_matches_raw_chain_exactly`) — confirming
both searches share the identical underlying physics, as they must,
since both call the same `operations/backbone.py`/`operations/purification.py`
functions.

## 4. Usage

```bash
# Exact ground truth on a small network
python3 validation/search_results.py --algorithm brute_force --N 4 --uniform --e_max 24

# Broader search on the same network (superset of the above)
python3 validation/search_results.py --algorithm dp --N 4 --uniform --e_max 24
```

Or from Python:

```python
from hrgs_scheduler.search import brute_force_search, dp_search, print_table

results = dp_search(network, objective, e_max=24)
print_table(results, top=10, show_infeasible=False)
```

## 5. What's next

Tier 3 (heuristic search — greedy/beam/simulated annealing) for `N` and
`e_max` beyond exact DP tractability, per the WbW plan's Weeks 3+ target.
