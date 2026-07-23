"""
hrgs_scheduler.search.dp
==========================
DP-over-stages: memoized recursive search over span-partition structures.

Motivation [Validated Formal Model Def, §7, tier 2]
----------------------------------------------------
κ has a natural partial order: RGSS, then increasing-width spans, then the
final Span(0, N).  This module exploits that order with a Bellman-style
optimal-cost-to-go computation, memoized by span:

    V(Span(a, b)) = Pareto-optimal set of (cost, fidelity, success_prob)
                    achievable for ONE resource at Span(a, b)

built bottom-up from single hops.  Each span's frontier is computed once
and reused by every wider span built on top of it — the actual asymptotic
win over brute force, which re-evaluates whole end-to-end schedules from
scratch for every candidate rather than sharing hop-level/sub-span work.

What's new here vs. brute_force.py
-----------------------------------
`brute_force_search` enumerates three *fixed* structural families (raw,
end-node pumping, link-level pumping with UNIFORM copy-count applied to
every hop, always stitched left-to-right).  The recursive search in this
module additionally explores:

  * variable purification copy-count *per hop* (not uniform across all N
    hops),
  * arbitrary split points / stitching order (not just left-to-right),

by trying every split point m ∈ (a, b) and combining the memoized
frontiers of Span(a, m) and Span(m, b).  This is a strict generalisation
of `link_level_pumped_chain`, not a heuristic approximation: Pareto
pruning only discards candidates that are simultaneously worse in cost,
fidelity, AND success probability, so no useful candidate is ever lost
(within the enumerated circuit-combination grid, same caveat as brute
force's `max_enumerated_rounds`).

Multi-objective (Pareto) DP, not a single-objective Bellman recursion
----------------------------------------------------------------------
A schedule's FINAL score depends on fidelity, success probability
(→ rate), AND resource cost jointly, and combining two branches multiplies
success probabilities and sums costs — so a single scalar "value" per
state would not compose correctly across joins.  Instead, each state
(a, b) stores a *Pareto frontier*: the set of (cost, fidelity,
success_prob) triples not dominated by any other candidate at that span.
This is standard multi-criteria DP and is exact given the enumerated
circuit grid.

Latency and Herald placement are handled outside this recursion (see
`dp_search` below) because, in the current evaluator model, only
HeraldNode placement contributes non-zero latency [repo notes: Gen/Join/
AbsaBsm/Purify all cost zero simulated time].  All span-partition
candidates built here are Herald-free (optimistic) until wrapped by
`dp_search`, matching `link_level_pumped_chain`'s "single final herald"
structure.

Pumping: two independent copies of the same span, purified together
---------------------------------------------------------------------
In addition to "split at m and join the two halves", `frontier(a, b)`
also considers "pump": take two candidates already known for THIS SAME
span (a, b) — drawn from this span's own pre-pump frontier, i.e. before
any pumping is applied — and purify them together with each of the three
circuits (YY, ZX, XZ). Because `purify()`'s success-probability formula
assumes independent inputs, the second copy is never reused as-is: its
entire reachable subtree is cloned with fresh node IDs (`_clone_candidate`,
using the same disjoint-node-id technique validated in
`experiments/optimality_gap_example.py` and `experiments/
excluded_move_at_scale.py`) before it is purified against the first.
Two things keep this tractable and non-recursive-without-bound:

  * Pump inputs are drawn only from this span's PRE-pump frontier (the
    ordinary leaf/join candidates), never from pump candidates already
    produced for this same span — so a span pumps at most once. Its
    children may still be pump results from narrower spans (pumping
    composes across spans via ordinary joins), but a single span never
    pumps its own pumped output.
  * Both the pairing pool (the inputs to pumping) and pumping's own
    contribution to the final frontier (its output) are beam-limited to
    at most `max_frontier_size` (under `beam_search`) or
    `_DEFAULT_PUMP_POOL_WIDTH` (under `dp_search`, which otherwise has
    no beam width of its own) — never the full exact Pareto set. Both
    caps are needed: capping only the pairing pool still lets pump's
    O(pool^2) output balloon the *stored* per-span frontier, which then
    compounds combinatorially at every join built on top of it
    (confirmed empirically: even N=4 failed to finish in 20s with only
    the pairing pool capped). Capping pump's contribution keeps its
    per-span cost — and the frontier size it feeds forward — bounded by
    a constant, regardless of recursion depth. This makes `dp_search`'s
    *pumping* move a bounded heuristic rather than exact, same tradeoff
    `beam_search` already makes for its whole frontier; `dp_search`'s
    pre-existing join-only enumeration is otherwise left exact/uncapped,
    unchanged from before this feature existed.

Two copies only (no n>2 pumping) is a deliberate first-version scope
limit, matching what has actually been validated so far.

Exactness modes: `dp_search`'s pumping is heuristic by default
------------------------------------------------------------------
**Important, do not assume otherwise:** once pumping is enabled (the
default), `dp_search` is no longer provably exact — the beam-limiting
above means its per-span frontier can, in principle, drop a candidate
that some `beam_search` configuration happens to keep, so `dp_search`'s
default output is NOT a guaranteed upper bound on every `beam_search`
result once both use pumping (confirmed empirically at N=4: default
`dp_search` occasionally scores *below* `beam_search`). `dp_search`
remains exact ONLY for the pre-existing pumping-free split/join
enumeration (`enable_pumping=False`, not exposed publicly, or any
schedule that happens not to involve a pump move).

For a genuine, fully-exhaustive ground truth, pass `exact_pumping=True`
to `dp_search`/`_SpanPartitionSearch` — this lifts every pumping-related
cap (pairing pool, pump's own contribution, final frontier) entirely,
restoring full exactness at the cost of tractability: usable only at
very small N (empirically N=2-3 fast, N=4 can take minutes). This mode
exists specifically to validate that the default *capped* `dp_search`
and `beam_search` both still track the true optimum closely at sizes
small enough to check directly — the same role
`experiments/sweep_beam_width.py`'s DP cross-check already plays for
beam_search alone, extended to also cover dp_search's own pumping cap.
Do not use `exact_pumping=True` as a general-purpose search mode.

**Even "very small N" is not a reliable safety margin on its own**:
`exact_pumping=True`'s cost scales steeply with `budget_cap`
independently of `N` — confirmed at `N=3`, `budget_cap=24` finished in
~37s but `budget_cap=36` did not finish within 300s. Practically, this
means `exact_pumping=True` cannot be relied on as a general ground-truth
check even at `N=3`; it must be tried at the *specific* `budget_cap`
needed, with no guarantee it will finish. See `docs/Optimality Scope.md`
§7 for a worked example where this made pumping's own optimality
unverifiable even in the smallest counterexample in this repo — the
practical conclusion there is that pumping-enabled results should be
validated by agreement between independent heuristic methods (e.g.
`dp_search` vs. `beam_search` at matching settings), not by exact
ground truth.

Known scope limits (documented, not silently ignored)
-------------------------------------------------------
* Pumping combines exactly two copies of the SAME span (a, b); n>2-way
  pumping, and pumping across DIFFERENT spans, are not explored.
* M_max (concurrent open branches) is not modeled, consistent with the
  rest of the codebase (see repo notes on `ResourceBudget`).

Cross-check
-----------
Because `dp_search` returns the UNION of this module's span-partition
candidates and `brute_force_search`'s three families, `dp_search(...)`
is always a superset of `brute_force_search(...)` on the same inputs —
the exact cross-check relationship called for in the WbW plan.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from itertools import count
from typing import Sequence

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.models.stage import Span
from hrgs_scheduler.models.state import State
from hrgs_scheduler.operations.backbone import absa_bsm, gen, join
from hrgs_scheduler.operations.purification import PurificationCircuit, purify
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    JoinNode,
    NodeId,
    PauliCorrectNode,
    PurifyNode,
    ScheduleNode,
)
from hrgs_scheduler.search.brute_force import (
    SearchResult,
    _circuit_sequences,
    _seq_name,
    brute_force_search,
)

# ---------------------------------------------------------------------------
# Pareto-frontier candidate type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SpanCandidate:
    """One non-dominated way to build a resource at a given Span(a, b).

    Attributes
    ----------
    node_id : NodeId
        Root node of this candidate's subtree in the shared node pool.
    state : State
        The resulting State (error vector, side effects, times) — a pure
        value, safe to reuse/reference from multiple parent candidates.
    cost : int
        Number of Gen leaves in this candidate's subtree.
    success_prob : float
        Cumulative product of Purify success probabilities in this subtree.
    label : str
        Human-readable recipe description.
    """

    node_id: NodeId
    state: State
    cost: int
    success_prob: float
    label: str


def _dominates(a: _SpanCandidate, b: _SpanCandidate) -> bool:
    """True when *a* is at least as good as *b* in every dimension, and
    strictly better in at least one (cost lower is better; fidelity and
    success_prob higher are better)."""
    at_least_as_good = (
        a.cost <= b.cost
        and a.state.fidelity >= b.state.fidelity
        and a.success_prob >= b.success_prob
    )
    strictly_better = (
        a.cost < b.cost
        or a.state.fidelity > b.state.fidelity
        or a.success_prob > b.success_prob
    )
    return at_least_as_good and strictly_better


def _prune_pareto(candidates: list[_SpanCandidate]) -> list[_SpanCandidate]:
    """Discard candidates dominated by another candidate in the same list."""
    return [
        c
        for c in candidates
        if not any(_dominates(o, c) for o in candidates if o is not c)
    ]


def _beam_key(
    c: _SpanCandidate, f_min_hint: float | None
) -> tuple[int, float, float, int]:
    """Ranking key used as a *secondary* tiebreak by `_beam_select` (larger
    is better): prioritises success probability (the main per-resource
    efficiency signal), then fidelity, then lower cost."""
    meets_floor = 1 if (f_min_hint is None or c.state.fidelity >= f_min_hint) else 0
    return (meets_floor, c.success_prob, c.state.fidelity, -c.cost)


def _beam_select(
    candidates: list[_SpanCandidate],
    beam_width: int,
    f_min_hint: float | None,
) -> list[_SpanCandidate]:
    """Keep only `beam_width` candidates, split across two rankings.

    A single ranking is not safe here: at a single hop, fidelity is
    always close to 1 regardless of purification, so any fidelity-floor
    filter is trivially satisfied at that scale — ranking purely by
    success_prob (i.e. preferring cheap/unpurified candidates) would then
    discard every purified sub-candidate at low spans, even though
    composing many such spans (e.g. N=10 hops) is exactly what later
    drops the *composite* fidelity below the floor, with no purified
    fallback left in the beam.

    To avoid this, half the beam is reserved for the highest-fidelity
    candidates (so purification survives pruning and remains available
    for wide spans that need it) and half for the highest-success_prob
    candidates (so cheap/efficient candidates survive for spans that
    already comfortably clear the floor). This is a heuristic, not an
    exactness guarantee — see module docstring.
    """
    if len(candidates) <= beam_width:
        return candidates

    half = max(1, beam_width // 2)
    by_fidelity = sorted(
        candidates, key=lambda c: (c.state.fidelity, -c.cost), reverse=True
    )
    by_efficiency = sorted(
        candidates, key=lambda c: _beam_key(c, f_min_hint), reverse=True
    )

    kept: dict[NodeId, _SpanCandidate] = {}
    for c in by_fidelity[:half]:
        kept[c.node_id] = c
    for c in by_efficiency:
        if len(kept) >= beam_width:
            break
        kept[c.node_id] = c
    return list(kept.values())


def _remap_node(node: ScheduleNode, remap: dict[NodeId, NodeId]) -> ScheduleNode:
    """Return a copy of *node* with node_id and any children remapped.

    Used by `_SpanPartitionSearch._clone_candidate` to build a fresh,
    node-id-disjoint clone of a candidate's subtree — the same technique
    validated in `experiments/optimality_gap_example.py` and
    `experiments/excluded_move_at_scale.py`, reused here rather than
    re-derived so the search can apply it inline.
    """
    field_names = {f.name for f in fields(node)}
    updates: dict = {"node_id": remap[node.node_id]}
    if "children" in field_names and getattr(node, "children", None) is not None:
        updates["children"] = tuple(remap[c] for c in node.children)
    return replace(node, **updates)


# Bound on the pump-pairing pool size when the search itself is exact
# (`max_frontier_size=None`, i.e. `dp_search`), which has no beam width of
# its own to reuse. Matches the codebase's existing default `beam_width`
# so pumping's cost is consistent across both search tiers.
_DEFAULT_PUMP_POOL_WIDTH = 25


# ---------------------------------------------------------------------------
# Memoized recursive span-partition search
# ---------------------------------------------------------------------------


class _SpanPartitionSearch:
    """Builds and memoizes Pareto frontiers for every span of one network.

    All ScheduleNode objects created during the search are accumulated in
    a single shared ``nodes`` pool with monotonically increasing IDs; the
    caller extracts only the reachable subset for each finalist it wants
    to keep (see ``dp_search``).
    """

    def __init__(
        self,
        network: NetworkConfig,
        *,
        max_link_copies: int,
        max_enumerated_rounds: int,
        budget_cap: int,
        max_frontier_size: int | None = None,
        f_min_hint: float | None = None,
        enable_pumping: bool = True,
        exact_pumping: bool = False,
    ) -> None:
        self._network = network
        self._max_link_copies = max_link_copies
        self._max_enumerated_rounds = max_enumerated_rounds
        self._budget_cap = budget_cap
        self._max_frontier_size = max_frontier_size
        self._f_min_hint = f_min_hint
        self._enable_pumping = enable_pumping
        self._exact_pumping = exact_pumping
        self.nodes: dict[NodeId, ScheduleNode] = {}
        self._counter = count()
        self._memo: dict[tuple[int, int], list[_SpanCandidate]] = {}

    def next_id(self) -> NodeId:
        """Return a fresh, unused node_id from the shared counter."""
        return next(self._counter)

    def _build_hop(self, hop_index: int) -> tuple[NodeId, State]:
        """Build one fresh raw single-hop edge (Gen×2 + AbsaBsm)."""
        hop_cfg = self._network.hop(hop_index)
        g_l = GenNode(node_id=self.next_id(), hop_index=hop_index)
        g_r = GenNode(node_id=self.next_id(), hop_index=hop_index)
        self.nodes[g_l.node_id] = g_l
        self.nodes[g_r.node_id] = g_r
        state_l = gen(hop_cfg)
        state_r = gen(hop_cfg)
        bsm = AbsaBsmNode(
            node_id=self.next_id(),
            children=(g_l.node_id, g_r.node_id),
            hop_index=hop_index,
        )
        self.nodes[bsm.node_id] = bsm
        state = absa_bsm(state_l, state_r, hop_index=hop_index, e_d=self._network.e_d)
        return bsm.node_id, state

    def _build_link_pumped(
        self,
        hop_index: int,
        n_copies: int,
        circuits: Sequence[PurificationCircuit],
    ) -> tuple[NodeId, State, float]:
        """Build n_copies fresh single-hop edges, chain-purified via *circuits*."""
        copy_ids: list[NodeId] = []
        copy_states: list[State] = []
        for _ in range(n_copies):
            node_id, state = self._build_hop(hop_index)
            copy_ids.append(node_id)
            copy_states.append(state)

        current_id, current_state = copy_ids[0], copy_states[0]
        success_prob = 1.0
        for i, circuit in enumerate(circuits):
            result = purify(circuit, current_state, copy_states[i + 1])
            pur = PurifyNode(
                node_id=self.next_id(),
                children=(current_id, copy_ids[i + 1]),
                circuit=circuit,
                output_stage=Span(hop_index, hop_index + 1),
            )
            self.nodes[pur.node_id] = pur
            current_id = pur.node_id
            current_state = result.output_state
            success_prob *= result.success_prob

        return current_id, current_state, success_prob

    def _clone_candidate(self, candidate: _SpanCandidate) -> NodeId:
        """Clone *candidate*'s entire reachable subtree with fresh node IDs.

        Guarantees the clone shares zero node_ids (in particular zero Gen
        nodes) with anything already in ``self.nodes`` — the independence
        requirement `purify()`'s success-probability formula relies on —
        since every remapped ID comes from ``self.next_id()`` and has
        never been issued before. Returns the clone's new root node_id;
        the candidate's ``state`` is unchanged (state values don't
        reference node IDs) and can be reused as-is.
        """
        reachable = _extract_reachable(self.nodes, candidate.node_id)
        remap: dict[NodeId, NodeId] = {nid: self.next_id() for nid in reachable}
        for old_id, node in reachable.items():
            self.nodes[remap[old_id]] = _remap_node(node, remap)
        return remap[candidate.node_id]

    def _generate_pump_candidates(
        self, a: int, b: int, base_pool: list[_SpanCandidate]
    ) -> list[_SpanCandidate]:
        """Pump: purify two independent copies drawn from *base_pool*.

        *base_pool* is this span's own pre-pump frontier (leaf or
        split/join candidates), so pumping is applied at most once per
        span — see module docstring. The pool is always capped to a
        beam-limited width before pairing (never exhaustive, even under
        exact `dp_search`) since pairing is O(pool^2) per span. Unordered
        pairs (i, j) with i <= j are considered, including i == j (two
        copies of the identical recipe); the second copy is always
        cloned via `_clone_candidate` so the pair is node-id-disjoint
        regardless.
        """
        pool_width = self._pump_width()
        if pool_width is not None and len(base_pool) > pool_width:
            base_pool = _beam_select(base_pool, pool_width, self._f_min_hint)

        span = Span(a, b)
        pump_candidates: list[_SpanCandidate] = []
        n = len(base_pool)
        for i in range(n):
            left = base_pool[i]
            for j in range(i, n):
                right = base_pool[j]
                cost = left.cost + right.cost
                if cost > self._budget_cap:
                    continue
                right_clone_id = self._clone_candidate(right)
                for circuit in (
                    PurificationCircuit.YY,
                    PurificationCircuit.ZX,
                    PurificationCircuit.XZ,
                ):
                    result = purify(circuit, left.state, right.state)
                    pur = PurifyNode(
                        node_id=self.next_id(),
                        children=(left.node_id, right_clone_id),
                        circuit=circuit,
                        output_stage=span,
                    )
                    self.nodes[pur.node_id] = pur
                    pump_candidates.append(
                        _SpanCandidate(
                            pur.node_id,
                            result.output_state,
                            cost=cost,
                            success_prob=left.success_prob
                            * right.success_prob
                            * result.success_prob,
                            label=f"pump[{circuit.name}]({left.label},{right.label})",
                        )
                    )
        return pump_candidates

    def frontier(self, a: int, b: int) -> list[_SpanCandidate]:
        """Return the Pareto-optimal candidates for building Span(a, b).

        Memoized: each span is computed once, regardless of how many wider
        spans are built on top of it.
        """
        key = (a, b)
        if key in self._memo:
            return self._memo[key]

        candidates: list[_SpanCandidate] = []

        if b - a == 1:
            node_id, state = self._build_hop(a)
            candidates.append(
                _SpanCandidate(
                    node_id, state, cost=2, success_prob=1.0, label=f"hop{a}"
                )
            )
            for n_copies in range(2, self._max_link_copies + 1):
                cost = 2 * n_copies
                if cost > self._budget_cap:
                    break
                for seq in _circuit_sequences(
                    n_copies - 1, self._max_enumerated_rounds
                ):
                    node_id, state, success_prob = self._build_link_pumped(
                        a, n_copies, seq
                    )
                    candidates.append(
                        _SpanCandidate(
                            node_id,
                            state,
                            cost=cost,
                            success_prob=success_prob,
                            label=f"hop{a}.n{n_copies}.{_seq_name(seq)}",
                        )
                    )
        else:
            for m in range(a + 1, b):
                left = self.frontier(a, m)
                right = self.frontier(m, b)
                for L in left:
                    for R in right:
                        cost = L.cost + R.cost
                        if cost > self._budget_cap:
                            continue
                        jn = JoinNode(
                            node_id=self.next_id(),
                            children=(L.node_id, R.node_id),
                            output_stage=Span(a, b),
                        )
                        self.nodes[jn.node_id] = jn
                        state = join(L.state, R.state)
                        candidates.append(
                            _SpanCandidate(
                                jn.node_id,
                                state,
                                cost=cost,
                                success_prob=L.success_prob * R.success_prob,
                                label=f"({L.label}+{R.label})",
                            )
                        )

        base_pruned = _prune_pareto(candidates)
        if (
            self._max_frontier_size is not None
            and len(base_pruned) > self._max_frontier_size
        ):
            base_pruned = _beam_select(
                base_pruned, self._max_frontier_size, self._f_min_hint
            )

        if self._enable_pumping:
            pump_candidates = _prune_pareto(
                self._generate_pump_candidates(a, b, base_pruned)
            )
            pump_pool_width = self._pump_width()
            if pump_pool_width is not None and len(pump_candidates) > pump_pool_width:
                pump_candidates = _beam_select(
                    pump_candidates, pump_pool_width, self._f_min_hint
                )
        else:
            pump_candidates = []

        pruned = _prune_pareto(base_pruned + pump_candidates)
        frontier_width = self._pump_width() if self._enable_pumping else None
        if frontier_width is not None and len(pruned) > frontier_width:
            # Pumping's outputs feed forward into every wider span's joins
            # AND its own pump-pairing pool, so leaving a span's *stored*
            # frontier exact/unbounded lets pumping's growth compound
            # multiplicatively across recursion depth (confirmed
            # empirically: uncapped, N=4 frontier sizes reach the tens of
            # thousands and Pareto-pruning them alone becomes intractable).
            # Once pumping is enabled, every span's frontier is therefore
            # beam-limited even under `dp_search`, same as `beam_search` -
            # UNLESS `exact_pumping=True`, which lifts this cap entirely
            # (see `_pump_width`) at the cost of only being usable at very
            # small N.
            pruned = _beam_select(pruned, frontier_width, self._f_min_hint)
        self._memo[key] = pruned
        return pruned

    def _pump_width(self) -> int | None:
        """Return the cap applied to pumping's pools/output, or None.

        `max_frontier_size` (set by `beam_search`) always wins when
        present. Otherwise, `_DEFAULT_PUMP_POOL_WIDTH` applies UNLESS
        `exact_pumping=True`, which returns None (no cap at all) - this is
        the genuinely exhaustive mode, only tractable at very small N (see
        module docstring's "Exactness modes" section).
        """
        if self._max_frontier_size is not None:
            return self._max_frontier_size
        if self._exact_pumping:
            return None
        return _DEFAULT_PUMP_POOL_WIDTH


# ---------------------------------------------------------------------------
# DAG extraction helper
# ---------------------------------------------------------------------------


def _extract_reachable(
    nodes: dict[NodeId, ScheduleNode], root_id: NodeId
) -> dict[NodeId, ScheduleNode]:
    """Return the subset of *nodes* reachable from *root_id* (inclusive).

    The shared node pool built by `_SpanPartitionSearch` accumulates nodes
    from every candidate ever created, including Pareto-pruned ones; a
    final `ScheduleDAG` must contain only nodes reachable from its own
    root (`validate()` rejects unreachable nodes), so each finalist needs
    its own filtered copy.
    """
    keep: dict[NodeId, ScheduleNode] = {}
    stack = [root_id]
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        node = nodes[nid]
        keep[nid] = node
        stack.extend(node.children)
    return keep


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def dp_search(
    network: NetworkConfig,
    objective: ObjectiveConfig,
    e_max: int,
    *,
    max_link_copies: int = 3,
    max_enumerated_rounds: int = 3,
    include_brute_force_families: bool = True,
    exact_pumping: bool = False,
) -> list[SearchResult]:
    """Search schedules via memoized span-partition DP, sorted best-first.

    Combines two candidate sources:

    1. The new recursive span-partition search (this module): explores
       variable per-hop purification copy-count and arbitrary split
       points/stitching order, memoized by span so hop-level and sub-span
       results are computed once and reused.
    2. `brute_force_search`'s three fixed families (raw, end-node
       heralded/optimistic pumping, flexible-paper), reused as-is so
       ``dp_search`` results are always a superset of
       ``brute_force_search`` on the same inputs.

    Exactness: **exact only for pumping-free schedules; a bounded
    heuristic once pumping is involved, unless `exact_pumping=True`.**
    See module docstring's "Exactness modes" section — the split/join
    dimension explored here has always been exact, but pumping's
    pairing step is O(pool^2) and compounds multiplicatively across the
    span recursion, so by default (`exact_pumping=False`) it is capped
    to `_DEFAULT_PUMP_POOL_WIDTH`, same as `beam_search` caps its whole
    frontier. Do not treat `dp_search`'s default output as a provable
    upper bound on `beam_search` once both use pumping — use
    `exact_pumping=True` for that, and only at small N (see below).

    Parameters
    ----------
    network : NetworkConfig
        Physical network configuration to evaluate against.
    objective : ObjectiveConfig
        Objective function (defines score and feasibility constraints).
    e_max : int
        Maximum number of Gen nodes.  Both candidate sources respect this.
    max_link_copies : int
        Cap on purification copy-count tried per span in the recursive
        search (default 3, i.e. up to 2 pumping rounds per span).
    max_enumerated_rounds : int
        Cap on exhaustive circuit-combination enumeration; passed through
        to both candidate sources (see `brute_force._circuit_sequences`).
    include_brute_force_families : bool
        When False, only the new span-partition candidates are returned
        (useful for isolating the DP contribution, e.g. in tests).
    exact_pumping : bool
        When True, pumping's pairing pool and its contribution to each
        span's frontier are left completely uncapped — genuinely
        exhaustive, matching this function's pre-pumping exactness
        guarantee in full. Only tractable at very small N (confirmed:
        N=2-3 fast; N=4 can take minutes; do not use at larger N).
        Intended as a narrow ground-truth check for validating that the
        default capped `dp_search`/`beam_search` are still tracking the
        true optimum closely at sizes where this remains affordable —
        not as a general-purpose search mode.

    Returns
    -------
    list[SearchResult]
        All evaluated candidates, sorted best-first.  Infeasible
        candidates (score = −∞) appear last.
    """
    N = network.N
    if N < 1:
        raise ValueError(f"network.N must be >= 1, got {N}")

    evaluator = Evaluator(network)
    search = _SpanPartitionSearch(
        network,
        max_link_copies=max_link_copies,
        max_enumerated_rounds=max_enumerated_rounds,
        budget_cap=e_max,
        exact_pumping=exact_pumping,
    )
    top_frontier = search.frontier(0, N)

    results: list[SearchResult] = []
    seen_labels: set[str] = set()

    for cand in top_frontier:
        if cand.cost > e_max:
            continue
        label = f"dp.span.{cand.label}"
        if label in seen_labels:
            continue
        seen_labels.add(label)

        sub_nodes = _extract_reachable(search.nodes, cand.node_id)
        herald_id = search.next_id()
        sub_nodes[herald_id] = HeraldNode(node_id=herald_id, children=(cand.node_id,))
        root_id = search.next_id()
        sub_nodes[root_id] = PauliCorrectNode(
            node_id=root_id, children=(herald_id,), N=N
        )

        dag = ScheduleDAG(nodes=sub_nodes, root_id=root_id, N=N)
        try:
            dag.validate()
        except ValueError:
            continue
        result = evaluator.evaluate(dag)
        score = objective.score(result)
        results.append(
            SearchResult(label=label, dag=dag, eval_result=result, score=score)
        )

    if include_brute_force_families:
        bf_results = brute_force_search(
            network,
            objective,
            e_max,
            max_enumerated_rounds=max_enumerated_rounds,
        )
        for r in bf_results:
            if r.label in seen_labels:
                continue
            seen_labels.add(r.label)
            results.append(r)

    results.sort(key=lambda r: r.score, reverse=True)
    return results
