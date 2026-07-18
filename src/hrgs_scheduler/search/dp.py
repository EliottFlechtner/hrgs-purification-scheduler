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

Known scope limits (documented, not silently ignored)
-------------------------------------------------------
* Purifying "n independent copies of an already-partially-purified
  segment" (as opposed to n independent RAW hops, or n independent full
  end-to-end chains) is NOT explored recursively here — doing so
  correctly requires re-instantiating a chosen sub-recipe with fresh Gen
  nodes for each of the n copies, which is a real feature but adds
  significant complexity for a first version. `dp_search` instead reuses
  `brute_force_search`'s existing end-node pumping families (which DO
  build n_pur independent full end-to-end raw chains) so that capability
  is still available, just not fused with the span-partition search.
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

from dataclasses import dataclass
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
    ) -> None:
        self._network = network
        self._max_link_copies = max_link_copies
        self._max_enumerated_rounds = max_enumerated_rounds
        self._budget_cap = budget_cap
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

        pruned = _prune_pareto(candidates)
        self._memo[key] = pruned
        return pruned


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
