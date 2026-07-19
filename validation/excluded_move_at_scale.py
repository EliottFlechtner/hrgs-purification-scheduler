"""
validation/excluded_move_at_scale.py
=======================================
Roadmap "De-risking" doc, item 1: targeted excluded-move check at N=14
and N=18 -- the two points where [outputs/sweep_hop_count/README.md]
reports no feasible schedule found (N=18) or only the paper baseline
failing the floor (N=14), at the paper's own budget `e_max = 10*N`.

This is NOT a general attempt to close the DP gap documented in
[docs/Optimality Scope.md] (that remains out of scope). It is a narrow,
targeted spot-check reusing the exact technique validated at N=3 in
`validation/optimality_gap_example.py`: build two independently-searched
candidates that both cover the full span, and purify them together via
each of {YY, ZX, XZ} -- a move `dp_search`/`beam_search` never take
themselves (see Optimality Scope.md, §3).

Bounded, not exhaustive (see roadmap §1.2)
--------------------------------------------
At N=3 the frontier was small enough to search exactly. At N=14/N=18 an
*exact* frontier is expected to be intractable (per
`sweep_beam_width.py`'s own finding that frontier-join cost is at least
quadratic in candidate count per span and compounds across the span
tree). This script therefore sources each of the two independent copies
from a **beam-limited** `_SpanPartitionSearch` (`max_frontier_size=
BEAM_WIDTH`, the same width used throughout this report's other sweeps),
not an unbounded exact frontier.

Per-copy budget is capped at `e_max // 2` (not `e_max`), for a reason
discovered empirically while writing this script: `_beam_select`'s
tie-break ranks any candidate meeting the LOCAL fidelity floor above any
candidate that doesn't, regardless of cost or success_prob (see
`dp.py`'s `_beam_key`/`_beam_select`). At `N=14`/`N=18`, plenty of
candidates clear the floor locally once enough budget is available, so
a per-copy search capped at the *full* `e_max` converges the beam onto
a narrow band of already-fairly-expensive, floor-clearing candidates,
pruning out the cheap/diverse ones an excluded-move combination actually
needs (empirically: at `N=14`, `budget_cap=140` left only cost∈{82,84}
survivors, so no two-copy pair ever fit under 140 -- 0 combined
candidates were evaluable). Capping each copy's own search at `e_max //
2` keeps the local floor out of reach for most sub-spans, which keeps
the beam's success_prob/cost diversity intact (as `_beam_select` always
intends it to be, see its own docstring) and *guarantees* by construction
that any pair's combined cost is <= `e_max`.

Consequently: a *positive* result (the excluded move finds a feasible
schedule) is a real, unconditional existence proof -- any single
`ScheduleDAG.validate()`-passing schedule found is real regardless of
how it was found. A *negative* result (no feasible schedule found this
way) must be read as "not rescued by the excluded move within this
bounded search", not "the excluded move cannot rescue this" -- the exact
frontier might still contain a rescuing pair this bounded search missed.

Correctness pitfall (carried over from optimality_gap_example.py)
---------------------------------------------------------------------
The two copies being purified together MUST come from two entirely
separate `_SpanPartitionSearch` instances with disjoint node-id pools.
Drawing both from the same instance's frontier is unsafe: its
memoization is by span, so two different-looking full-span candidates
can silently share underlying Gen-node subtrees, under-counting cost and
violating the independence assumption behind `purify()`'s
success-probability formula. This script asserts zero node-id collision
before evaluating any combined candidate.

Outputs
-------
    outputs/excluded_move_n14_n18/results.csv
    outputs/excluded_move_n14_n18/README.md

Usage
-----
    PYTHONPATH=src python3 -u validation/excluded_move_at_scale.py
"""

from __future__ import annotations

import csv
import dataclasses
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.models.stage import Span
from hrgs_scheduler.operations.purification import PurificationCircuit, purify
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.node import (
    HeraldNode,
    NodeId,
    PauliCorrectNode,
    PurifyNode,
)
from hrgs_scheduler.search.dp import _SpanPartitionSearch, _extract_reachable

F_MIN = 0.9
E_D = 0.01
BEAM_WIDTH = 25
N_VALUES = [14, 18]
CIRCUITS = (PurificationCircuit.YY, PurificationCircuit.ZX, PurificationCircuit.XZ)

# Per-hop config fixed at the paper's own values, matching
# validation/sweep_hop_count.py exactly (only N varies).
_LENGTH = 2.0
_BRANCHING = (16, 14, 1)
_ARM_COUNT = 18
_P_X_INNER = 0.0
_P_Z_INNER = 0.0
_GAMMA = 0.0
_C = 2e5

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "excluded_move_n14_n18"

# Existing sweep_hop_count best-known results at each N, for comparison
# (read from outputs/sweep_hop_count/results.csv, hardcoded here since
# that sweep is already complete and this script is a narrow follow-up
# check, not a rerun of it).
EXISTING_BEST = {
    14: {
        "label": "optimizer_matched_cost: link.n5.XZ_XZ_XZ_XZ",
        "cost": 140,
        "fidelity": 0.9120923358835828,
        "meets_floor": True,
        "rate": 1931.5582977864237,
    },
    18: {
        "label": "optimizer_budget_relaxed: beam.span....",
        "cost": 108,
        "fidelity": 0.8878371722536087,
        "meets_floor": False,
        "rate": 2134.3383809006054,
    },
}


def _build_network(N: int) -> NetworkConfig:
    return NetworkConfig.uniform(
        N=N,
        length=_LENGTH,
        branching=_BRANCHING,
        arm_count=_ARM_COUNT,
        p_x_inner=_P_X_INNER,
        p_z_inner=_P_Z_INNER,
        e_d=E_D,
        gamma=_GAMMA,
        c=_C,
    )


def _remap_node(node, remap: dict[NodeId, NodeId]):
    fields = {f.name for f in dataclasses.fields(node)}
    updates: dict = {"node_id": remap[node.node_id]}
    if "children" in fields and getattr(node, "children", None) is not None:
        updates["children"] = tuple(remap[c] for c in node.children)
    return dataclasses.replace(node, **updates)


@dataclass
class ExcludedMoveResult:
    N: int
    e_max: int
    n_candidates_a: int
    n_candidates_b: int
    n_pairs_evaluated: int
    rescued: bool
    best_label: str
    best_cost: int
    best_fidelity: float
    best_success_prob: float
    best_rate: float
    best_score: float
    wall_time_s: float


def find_best_excluded_move(
    net: NetworkConfig, obj: ObjectiveConfig, N: int, e_max: int
) -> ExcludedMoveResult:
    t0 = time.time()
    evaluator = Evaluator(net)
    per_copy_budget = e_max // 2

    search_a = _SpanPartitionSearch(
        net,
        max_link_copies=3,
        max_enumerated_rounds=3,
        budget_cap=per_copy_budget,
        max_frontier_size=BEAM_WIDTH,
        f_min_hint=obj.f_min,
    )
    frontier_a = search_a.frontier(0, N)
    print(
        f"  N={N}: frontier_a built, {len(frontier_a)} candidates ({time.time()-t0:.1f}s)",
        flush=True,
    )

    search_b = _SpanPartitionSearch(
        net,
        max_link_copies=3,
        max_enumerated_rounds=3,
        budget_cap=per_copy_budget,
        max_frontier_size=BEAM_WIDTH,
        f_min_hint=obj.f_min,
    )
    frontier_b = search_b.frontier(0, N)
    print(
        f"  N={N}: frontier_b built, {len(frontier_b)} candidates ({time.time()-t0:.1f}s)",
        flush=True,
    )

    # Remap search_b's entire node pool once, to guarantee zero collision
    # with search_a's pool for every pair tried below.
    offset = max(search_a.nodes.keys()) + 1
    remap = {nid: nid + offset for nid in search_b.nodes}
    b_nodes_remapped = {
        remap[nid]: _remap_node(node, remap) for nid, node in search_b.nodes.items()
    }

    # Pre-extract each side's reachable node set once, reused across every
    # pairing/circuit combination it appears in.
    a_reachable_cache = {
        a.node_id: _extract_reachable(search_a.nodes, a.node_id) for a in frontier_a
    }
    b_reachable_cache = {
        b.node_id: _extract_reachable(b_nodes_remapped, remap[b.node_id])
        for b in frontier_b
    }

    best_score = float("-inf")
    best_result = None
    best_label = ""
    n_evaluated = 0

    for a in frontier_a:
        a_reachable = a_reachable_cache[a.node_id]
        for b in frontier_b:
            combined_cost = a.cost + b.cost
            if combined_cost > e_max:
                continue
            b_root_id = remap[b.node_id]
            b_reachable = b_reachable_cache[b.node_id]
            assert not (
                set(a_reachable) & set(b_reachable)
            ), "node id collision between independent copies -- must never happen"

            for circuit in CIRCUITS:
                combined_nodes = {**a_reachable, **b_reachable}
                pur_id = max(combined_nodes) + 1
                combined_nodes[pur_id] = PurifyNode(
                    node_id=pur_id,
                    children=(a.node_id, b_root_id),
                    circuit=circuit,
                    output_stage=Span(0, N),
                )
                herald_id = pur_id + 1
                combined_nodes[herald_id] = HeraldNode(
                    node_id=herald_id, children=(pur_id,)
                )
                root_id = herald_id + 1
                combined_nodes[root_id] = PauliCorrectNode(
                    node_id=root_id, children=(herald_id,), N=N
                )

                dag = ScheduleDAG(nodes=combined_nodes, root_id=root_id, N=N)
                try:
                    dag.validate()
                except ValueError:
                    continue
                result = evaluator.evaluate(dag)
                score = obj.score(result)
                n_evaluated += 1
                if score > best_score:
                    best_score = score
                    best_result = result
                    best_label = f"excluded_move.{circuit.name}({a.label}, {b.label})"

    elapsed = time.time() - t0
    print(
        f"  N={N}: done, {n_evaluated} combined candidates evaluated"
        f" ({elapsed:.1f}s total)",
        flush=True,
    )

    if best_result is None:
        return ExcludedMoveResult(
            N=N,
            e_max=e_max,
            n_candidates_a=len(frontier_a),
            n_candidates_b=len(frontier_b),
            n_pairs_evaluated=n_evaluated,
            rescued=False,
            best_label="(none found within budget)",
            best_cost=0,
            best_fidelity=0.0,
            best_success_prob=0.0,
            best_rate=0.0,
            best_score=float("-inf"),
            wall_time_s=elapsed,
        )

    return ExcludedMoveResult(
        N=N,
        e_max=e_max,
        n_candidates_a=len(frontier_a),
        n_candidates_b=len(frontier_b),
        n_pairs_evaluated=n_evaluated,
        rescued=best_result.fidelity >= F_MIN,
        best_label=best_label,
        best_cost=best_result.resource_cost,
        best_fidelity=best_result.fidelity,
        best_success_prob=best_result.success_prob,
        best_rate=best_result.rate,
        best_score=best_score,
        wall_time_s=elapsed,
    )


def write_results_csv(rows: list[ExcludedMoveResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "N",
                "e_max",
                "n_candidates_a",
                "n_candidates_b",
                "n_pairs_evaluated",
                "rescued",
                "best_label",
                "best_cost",
                "best_fidelity",
                "best_success_prob",
                "best_rate",
                "best_score",
                "wall_time_s",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.N,
                    r.e_max,
                    r.n_candidates_a,
                    r.n_candidates_b,
                    r.n_pairs_evaluated,
                    r.rescued,
                    r.best_label,
                    r.best_cost,
                    r.best_fidelity,
                    r.best_success_prob,
                    r.best_rate,
                    r.best_score,
                    f"{r.wall_time_s:.2f}",
                ]
            )


def write_readme(rows: list[ExcludedMoveResult], total_elapsed: float) -> None:
    lines = [
        "# Excluded-Move Check at N=14 and N=18",
        "",
        "Per [docs/Roadmap_Derisk_and_Reframe.md](../../docs/Roadmap_Derisk_and_Reframe.md),"
        " §1: does the excluded same-span-purification move (demonstrated"
        " at N=3 in [docs/Optimality Scope.md](../../docs/Optimality%20Scope.md))"
        " rescue feasibility at the paper's own budget"
        " (`e_max = 10*N`) for the two `N` values where"
        " [outputs/sweep_hop_count/README.md](../sweep_hop_count/README.md)"
        " reports the paper baseline and/or every searched variant failing"
        " the fidelity floor.",
        "",
        "**Bounded, not exhaustive**: each of the two independent copies"
        f" being purified together is sourced from a beam-limited frontier"
        f" (`beam_width={BEAM_WIDTH}`, matching the rest of this report's"
        " convention), not an exact/exhaustive one -- an exact frontier at"
        " this `N` is expected to be intractable (see module docstring)."
        " A **positive** result below is an unconditional existence proof"
        " (any validated schedule found is real). A **negative** result"
        ' means "not rescued by the excluded move within this bounded'
        ' search", not "cannot be rescued" -- the true exact frontier'
        " might still contain a rescuing pair this search missed.",
        "",
        "## Results",
        "",
        "| N | e_max | Rescued? | Best excluded-move F | Best excluded-move cost | vs. existing best (sweep_hop_count) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        existing = EXISTING_BEST[r.N]
        lines.append(
            f"| {r.N} | {r.e_max} | {'**YES**' if r.rescued else 'no'} |"
            f" {r.best_fidelity:.6f} | {r.best_cost} |"
            f" existing best F={existing['fidelity']:.6f}"
            f" (meets_floor={existing['meets_floor']}), cost={existing['cost']} |"
        )

    lines += ["", "## Details", ""]
    for r in rows:
        lines += [
            f"### N={r.N}",
            "",
            f"- Frontier sizes (beam-limited, width={BEAM_WIDTH}): {r.n_candidates_a}"
            f" (copy A) x {r.n_candidates_b} (copy B).",
            f"- Combined candidates evaluated (within `e_max={r.e_max}`,"
            f" across {{YY, ZX, XZ}}): {r.n_pairs_evaluated}.",
            f"- Best found: `{r.best_label}`, cost={r.best_cost},"
            f" F={r.best_fidelity:.6f}, success_prob={r.best_success_prob:.6f},"
            f" rate={r.best_rate:.4f}.",
            f"- Wall time: {r.wall_time_s:.1f}s.",
            "",
        ]

    n14 = next(r for r in rows if r.N == 14)
    n18 = next(r for r in rows if r.N == 18)
    lines += [
        "## Interpretation",
        "",
        f"**N=14**: a feasible schedule already existed at this budget before"
        f" this check (`sweep_hop_count`'s `optimizer_matched_cost`,"
        f" F={EXISTING_BEST[14]['fidelity']:.4f}), so this is not an"
        " infeasibility case -- the excluded-move search here is a"
        f" secondary check on whether it finds something *better*."
        f" {'It does: F=' + format(n14.best_fidelity, '.6f') + ' beats the existing best.' if n14.rescued and n14.best_fidelity > EXISTING_BEST[14]['fidelity'] else 'It does not improve on the existing best within this bounded search.'}",
        "",
        f"**N=18**: this is the actual infeasibility case -- every variant"
        " `sweep_hop_count` searched (paper baseline, matched-cost,"
        " budget-relaxed) fails the fidelity floor at `e_max=180`. The"
        f" excluded-move search {'**does** find a feasible schedule here (F=' + format(n18.best_fidelity, '.6f') + ' >= ' + str(F_MIN) + '), rescuing feasibility.' if n18.rescued else '**does not** find a feasible schedule within this bounded search (best F=' + format(n18.best_fidelity, '.6f') + ' < ' + str(F_MIN) + ').'}",
        "",
        (
            "Given N=18 was rescued, `sweep_hop_count/README.md`'s"
            ' "no feasible schedule at all" claim for N=18 needs the'
            " explicit correction that a feasible schedule does exist,"
            " found by the excluded move -- it just isn't reachable by"
            " `dp_search`/`beam_search` themselves. See the addenda added"
            " to both `sweep_hop_count/README.md` and `Optimality"
            " Scope.md` alongside this result."
            if n18.rescued
            else (
                "Given N=18 was **not** rescued under this bounded search,"
                " `sweep_hop_count/README.md`'s \"no feasible schedule at"
                ' all" claim should be qualified as "no feasible schedule'
                " found by any of dp_search/beam_search/this bounded"
                ' excluded-move check" -- weak evidence (not proof) that'
                " the paper's own `10*N` budget is genuinely tight at"
                " N=18, not merely an artifact of the searched families'"
                " blind spot. See the addenda added to both"
                " `sweep_hop_count/README.md` and `Optimality Scope.md`"
                " alongside this result."
            )
        ),
        "",
        "## Reproducing",
        "",
        "```bash",
        "cd /home/shark/Documents/hrgs-purification-scheduler",
        "source .venv/bin/activate",
        "PYTHONPATH=src python3 -u validation/excluded_move_at_scale.py",
        "```",
        "",
        f"Total wall-clock time: ~{total_elapsed:.0f}s.",
        "",
    ]
    (OUTPUT_DIR / "README.md").write_text("\n".join(lines))


def main() -> None:
    t0 = time.time()
    rows = []
    for N in N_VALUES:
        print(f"N={N}: building network + running excluded-move check...", flush=True)
        net = _build_network(N)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=F_MIN)
        e_max = 10 * N
        result = find_best_excluded_move(net, obj, N, e_max)
        rows.append(result)
        print(
            f"N={N}: rescued={result.rescued}, best_fidelity={result.best_fidelity:.6f},"
            f" best_cost={result.best_cost}",
            flush=True,
        )

    elapsed = time.time() - t0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_results_csv(rows, OUTPUT_DIR / "results.csv")
    write_readme(rows, elapsed)
    print(f"\nDone in {elapsed:.1f}s. Outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
