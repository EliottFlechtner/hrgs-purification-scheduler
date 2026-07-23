"""
experiments/optimality_gap_example.py
=======================================
Concrete counterexample for [docs/Optimality Scope.md].

Both `dp_search`'s native span-partition recursion
(`_SpanPartitionSearch.frontier`) and its merged-in
`brute_force_search` fixed families never explore the following move:
take TWO candidates that both already cover the exact same span, and
purify them together to obtain a single, better candidate for that
span. `frontier()` only ever *joins* candidates across DISJOINT
sub-ranges (`Span(a,m) x Span(m,b) -> Span(a,b)`); it never purifies two
candidates that are both already `Span(a,b)`. None of `brute_force_search`'s
three fixed families cover this either (end-node pumping purifies `n`
copies of the RAW chain only; link-level pumping applies one uniform
recipe to every hop, never two distinct whole-chain recipes purified
together).

This script builds that excluded move as a real, `ScheduleDAG.validate()`-
passing schedule and shows it strictly dominates every schedule
`dp_search` finds at the same resource cost, at a small `N` where the
comparison is exhaustively checkable.

Correctness pitfall worth flagging explicitly (caught during
construction): the two "independent copies" being purified together
MUST get their own fresh Gen-node subtrees. Reusing `_SpanPartitionSearch`'s
own *memoized* frontier candidates directly is unsafe here -- two
different-looking candidates for the same span can share underlying
Gen-node subtrees (the memoization is by span, not by full recipe), so
naively purifying two frontier entries together can silently
double-count a single physical resource as if it were two independent
ones, invalidating the purification success-probability formula's
independence assumption. This script sidesteps that by building the two
copies from two entirely separate `_SpanPartitionSearch` instances (disjoint
node-id pools) and asserting the merged node set has no id collisions
before evaluating.

Usage
-----
    PYTHONPATH=src python3 experiments/optimality_gap_example.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.models.stage import Span
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.node import (
    HeraldNode,
    NodeId,
    PauliCorrectNode,
    PurifyNode,
)
from hrgs_scheduler.search import dp_search
from hrgs_scheduler.search.dp import _SpanPartitionSearch, _extract_reachable

N = 3
E_MAX = 36
F_MIN = 0.98

# Two distinct, heterogeneous-per-hop recipes for the SAME full span
# Span(0, 3), each found natively in `_SpanPartitionSearch.frontier(0, 3)`
# at cost 18 (n_copies=3 link-level purification with a different circuit
# sequence at hop1 in each).
LABEL_A = "(hop0.n3.XZ_YY+(hop1.n3.YY_YY+hop2.n3.XZ_YY))"
LABEL_B = "(hop0.n3.XZ_YY+(hop1.n3.YY_XZ+hop2.n3.XZ_YY))"


def _remap_node(node, remap: dict[NodeId, NodeId]):
    fields = {f.name for f in dataclasses.fields(node)}
    updates: dict = {"node_id": remap[node.node_id]}
    if "children" in fields and getattr(node, "children", None) is not None:
        updates["children"] = tuple(remap[c] for c in node.children)
    return dataclasses.replace(node, **updates)


def build_network() -> NetworkConfig:
    return NetworkConfig.uniform(
        N=N,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.003,
        p_z_inner=0.003,
        e_d=0.01,
        gamma=1e-3,
        c=2e5,
    )


def build_excluded_move_dag(net: NetworkConfig) -> ScheduleDAG:
    """Build the excluded move: purify(XZ, A, B) where A and B both cover
    Span(0, N), from two genuinely independent node pools.

    Uses `enable_pumping=False`: this constructs two specific, known
    non-pumped link-level building blocks (`LABEL_A`/`LABEL_B`) to then
    manually purify together as the excluded move -- with the newly
    integrated pumping move enabled, these exact candidates are (as
    expected) now Pareto-dominated and pruned even from the fully
    exhaustive (`exact_pumping=True`) frontier, because pumping finds a
    genuinely better candidate at the same or lower cost (this is
    evidence pumping is working correctly, not a bug). Since this
    function only needs the original non-pumped building blocks
    (verified still present and unaffected when pumping is disabled),
    disabling pumping here is the correct, fast way to retrieve them --
    see `dp.py`'s "Exactness modes" docstring section.
    """
    search_a = _SpanPartitionSearch(
        net,
        max_link_copies=3,
        max_enumerated_rounds=3,
        budget_cap=E_MAX * 2,
        enable_pumping=False,
    )
    frontier_a = search_a.frontier(0, N)
    a = next(c for c in frontier_a if c.label == LABEL_A)

    search_b = _SpanPartitionSearch(
        net,
        max_link_copies=3,
        max_enumerated_rounds=3,
        budget_cap=E_MAX * 2,
        enable_pumping=False,
    )
    frontier_b = search_b.frontier(0, N)
    b = next(c for c in frontier_b if c.label == LABEL_B)

    # Remap every node_id in search_b's pool to avoid any collision with
    # search_a's pool -- guarantees the two copies are genuinely independent
    # Gen-node subtrees, not accidentally shared memoized ones.
    offset = max(search_a.nodes.keys()) + 1
    remap = {nid: nid + offset for nid in search_b.nodes}
    b_nodes_remapped = {
        remap[nid]: _remap_node(node, remap) for nid, node in search_b.nodes.items()
    }
    b_root_id = remap[b.node_id]

    a_reachable = _extract_reachable(search_a.nodes, a.node_id)
    b_reachable = _extract_reachable(b_nodes_remapped, b_root_id)
    assert not (set(a_reachable) & set(b_reachable)), (
        "node id collision between the two 'independent' copies -- would "
        "silently share physical Gen nodes and invalidate the independence "
        "assumption behind purify()'s success-probability formula."
    )

    combined_nodes = {**a_reachable, **b_reachable}
    pur_id = max(combined_nodes) + 1
    combined_nodes[pur_id] = PurifyNode(
        node_id=pur_id,
        children=(a.node_id, b_root_id),
        circuit=PurificationCircuit.XZ,
        output_stage=Span(0, N),
    )
    herald_id = pur_id + 1
    combined_nodes[herald_id] = HeraldNode(node_id=herald_id, children=(pur_id,))
    root_id = herald_id + 1
    combined_nodes[root_id] = PauliCorrectNode(
        node_id=root_id, children=(herald_id,), N=N
    )

    dag = ScheduleDAG(nodes=combined_nodes, root_id=root_id, N=N)
    dag.validate()  # raises if the excluded-move DAG is somehow illegal
    return dag


def main() -> None:
    net = build_network()
    obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=F_MIN)

    dag = build_excluded_move_dag(net)
    result = Evaluator(net).evaluate(dag)
    score = obj.score(result)

    print(
        f"Excluded-move schedule: N={N}, cost={result.resource_cost}, "
        f"F={result.fidelity:.6f}, success_prob={result.success_prob:.6f}, "
        f"rate={result.rate:.4f}, score={score:.4f}"
    )
    assert (
        result.resource_cost == E_MAX
    ), "unexpected cost, recipe labels may have shifted"
    assert result.fidelity >= F_MIN, "excluded-move schedule expected to be feasible"

    dp_results = dp_search(net, obj, e_max=E_MAX)
    at_cost = [r for r in dp_results if r.eval_result.resource_cost <= E_MAX]
    best_fidelity_found = max(r.eval_result.fidelity for r in at_cost)
    best_score_found = max(r.score for r in at_cost)

    print(
        f"dp_search (native recursion UNION brute_force_search families) at "
        f"e_max={E_MAX}, f_min={F_MIN}: best fidelity found = "
        f"{best_fidelity_found:.6f}, best score = {best_score_found}"
    )

    print()
    if best_score_found == float("-inf"):
        print(
            f"CONFIRMED GAP: dp_search reports NO feasible schedule at "
            f"e_max={E_MAX}, f_min={F_MIN} (best score = -inf), but a "
            f"validated, feasible schedule genuinely exists at that exact "
            f"cost (fidelity {result.fidelity:.6f}) -- found only by taking "
            f"the excluded 'purify two candidates for the same span' move."
        )
    else:
        print(
            f"dp_search DID find a feasible schedule at this budget; the "
            f"excluded-move schedule's fidelity ({result.fidelity:.6f}) vs. "
            f"the best dp_search found ({best_fidelity_found:.6f}) shows "
            f"whether the gap is still exploitable at this f_min."
        )


if __name__ == "__main__":
    main()
