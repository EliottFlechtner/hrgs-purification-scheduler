"""
hrgs_scheduler.search.heuristic
=================================
Tier 3: beam search over span-partition structures.

Motivation [Outer Loop Search Design, §5 "What's next"; WbW Plan, Weeks
2-3; Validated Formal Model Def, §7]: the exact DP (`search/dp.py`) keeps
the *full* Pareto frontier at every span, which is exact but grows too
fast to run at the paper's actual N=10 configuration (empirically:
frontier size at width-7 spans already reaches ~1,200 candidates and
keeps growing, making the width-10 top span intractable in practice).
This module reuses the *exact same* recursive span-partition machinery
(`hrgs_scheduler.search.dp._SpanPartitionSearch`) — same node-building
calls into `operations/backbone.py` / `operations/purification.py`, same
physics — but caps each span's frontier at a fixed `beam_width` using
`_beam_select` instead of keeping every non-dominated candidate. That
turns the search from exponential-ish in N into polynomial in N for a
fixed beam width, at the cost of no longer being provably exhaustive.

This is deliberately NOT a from-scratch greedy/annealing implementation:
reusing `_SpanPartitionSearch` means beam search and `dp_search` share
100% of their node-construction and evaluation code, so any result the
beam search returns is a schedule `dp_search` would also have considered
had its frontier not been pruned early — there is no separate
"heuristic model" that could silently diverge from the real physics.

**Important:** `dp_search`'s own "pumping" move (two independently-
purified copies of the same span) is *also* beam-limited by default for
tractability (see `search/dp.py`'s "Exactness modes" docstring section)
-- so `dp_search`'s default output is NOT a guaranteed upper bound on
`beam_search` once pumping is involved. Use `dp_search(...,
exact_pumping=True)` (uncapped, only tractable at very small N) as the
genuine ground truth when validating `beam_search` against it.

Usage
-----
```python
from hrgs_scheduler.search.heuristic import beam_search

results = beam_search(network, objective, e_max=200, beam_width=25)
```

For large N (e.g. the paper's N=10 config), prefer this over `dp_search`
directly; cross-check on small N (N <= 3-6) that `beam_search`'s best
score matches or nearly matches `dp_search(..., exact_pumping=True)`'s
genuinely exact best score before trusting it at scale (see
`tests/test_heuristic.py`).
"""

from __future__ import annotations

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.node import HeraldNode, PauliCorrectNode
from hrgs_scheduler.search.brute_force import SearchResult, brute_force_search
from hrgs_scheduler.search.dp import _extract_reachable, _SpanPartitionSearch


def beam_search(
    network: NetworkConfig,
    objective: ObjectiveConfig,
    e_max: int,
    *,
    beam_width: int = 25,
    max_link_copies: int = 3,
    max_enumerated_rounds: int = 3,
    include_brute_force_families: bool = True,
) -> list[SearchResult]:
    """Search schedules via beam-capped span-partition DP, sorted best-first.

    Identical in structure to `dp_search`, except each span's frontier is
    capped at `beam_width` candidates (ranked by `objective.f_min` as a
    hint — see `search.dp._beam_key`) instead of kept in full. Use this
    when `N`/`e_max` make `dp_search`'s exact Pareto frontier intractable
    (in particular, the paper's N=10 reference configuration).

    Parameters
    ----------
    network : NetworkConfig
        Physical network configuration to evaluate against.
    objective : ObjectiveConfig
        Objective function (defines score, feasibility, and — via
        `f_min` — the beam-ranking hint).
    e_max : int
        Maximum number of Gen nodes.
    beam_width : int
        Max number of candidates kept per span after Pareto-pruning.
        Larger values approach `dp_search`'s quality at higher cost;
        smaller values run faster but may miss the true optimum.
        Default 25.
    max_link_copies : int
        Cap on purification copy-count tried per span (default 3).
    max_enumerated_rounds : int
        Cap on exhaustive circuit-combination enumeration.
    include_brute_force_families : bool
        When True (default), also includes `brute_force_search`'s three
        fixed families, so `beam_search` results remain comparable to
        (and a superset of, modulo beam pruning) `brute_force_search`.

    Returns
    -------
    list[SearchResult]
        All evaluated candidates, sorted best-first. Infeasible
        candidates (score = -inf) appear last.
    """
    N = network.N
    if N < 1:
        raise ValueError(f"network.N must be >= 1, got {N}")
    if beam_width < 1:
        raise ValueError(f"beam_width must be >= 1, got {beam_width}")

    evaluator = Evaluator(network)
    search = _SpanPartitionSearch(
        network,
        max_link_copies=max_link_copies,
        max_enumerated_rounds=max_enumerated_rounds,
        budget_cap=e_max,
        max_frontier_size=beam_width,
        f_min_hint=objective.f_min,
    )
    top_frontier = search.frontier(0, N)

    results: list[SearchResult] = []
    seen_labels: set[str] = set()

    for cand in top_frontier:
        if cand.cost > e_max:
            continue
        label = f"beam.span.{cand.label}"
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
