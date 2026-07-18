"""
hrgs_scheduler.search.brute_force
====================================
Brute-force enumeration of the schedule space for small N.

Purpose
-------
Establish exact ground truth on small network configs (N ≤ 4, E_max ≤ 40)
that can later be used to cross-check the DP-over-stages algorithm.

Search family
-------------
Rather than enumerating all possible DAG topologies (infinite), the search
enumerates a *structured family* covering the three practically important
purification strategies:

  1. **End-node heralded** (baseline-style): n_pur independent raw N-hop
     chains, pumped sequentially at the end nodes with a round-trip
     classical confirmation after each round.  Parameterised by:
     - n_pur ∈ {2 … cap} (copies count, budget-bounded)
     - circuit sequence: all combinations of {YY, ZX, XZ}^(n_pur-1),
       giving 1–81 sequences for n_pur ≤ 5 (always tractable).
     For n_pur > 5 (i.e. n_rounds > 4), circuit enumeration is capped at
     a curated set (paper's cycle + all-same variants) to keep runtime
     bounded.

  2. **End-node optimistic**: same as above but with no intermediate
     HeraldNodes — all classical communication deferred to the single
     final one-way herald.  Same parameter grid, heralded=False.

  3. **Link-level**: for each hop, generate n_copies single-hop raw edges,
     pump them at link level (κ = Span(i, i+1)), then stitch the purified
     links into an end-to-end chain.  Parameterised by:
     - n_copies ∈ {2 … cap}
     - circuit sequence at each hop: all combinations of {YY, ZX, XZ}^(n_copies-1).

Additionally, the raw chain (n_pur = 1, no purification) and the paper's
exact flexible schedule (for even N within budget) are always included.

Output
------
Returns a list of ``SearchResult`` objects, sorted best-first under the
supplied objective.  Infeasible schedules (score = -inf) appear last.

Usage
-----
    from hrgs_scheduler.models.network_config import NetworkConfig
    from hrgs_scheduler.cost_functions import ObjectiveConfig
    from hrgs_scheduler.search import brute_force_search

    net = NetworkConfig.integrating_paper_config(e_d=0.005)
    obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)
    results = brute_force_search(net, obj, e_max=40)
    best = results[0]
    print(best.label, best.eval_result.fidelity, best.eval_result.rate)
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Sequence

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import EvaluationResult, Evaluator

# Canonical set of circuits tried at each purification position.
_ALL_CIRCUITS = (
    PurificationCircuit.YY,
    PurificationCircuit.ZX,
    PurificationCircuit.XZ,
)

# The paper's entanglement-pumping circuit sequence [Integrating, §V-C].
_PAPER_CYCLE = (
    PurificationCircuit.YY,
    PurificationCircuit.ZX,
    PurificationCircuit.YY,
    PurificationCircuit.XZ,
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """A single candidate schedule with its evaluation and objective score.

    Attributes
    ----------
    label : str
        Human-readable identifier encoding the strategy and parameters,
        e.g. ``"end_heralded.n3.YY_ZX"``.
    dag : ScheduleDAG
        The schedule that was evaluated.
    eval_result : EvaluationResult
        Full cost-function output (F, R, C, L, P_success, node_states).
    score : float
        Objective score; higher is always better (−∞ if infeasible).
    """

    label: str
    dag: ScheduleDAG
    eval_result: EvaluationResult
    score: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _circuit_sequences(
    n_rounds: int,
    max_rounds_to_enumerate: int,
) -> list[tuple[PurificationCircuit, ...]]:
    """Return all circuit sequences of length *n_rounds*, or a curated subset.

    For n_rounds ≤ max_rounds_to_enumerate, returns the full Cartesian
    product {YY, ZX, XZ}^n_rounds.  For larger n_rounds (reached only when
    e_max is very large relative to N), falls back to a curated set that
    includes the paper's cycle and all-same-circuit variants.
    """
    if n_rounds == 0:
        return [()]
    if n_rounds <= max_rounds_to_enumerate:
        return list(product(_ALL_CIRCUITS, repeat=n_rounds))
    curated: set[tuple[PurificationCircuit, ...]] = set()
    curated.add(tuple(_PAPER_CYCLE[i % len(_PAPER_CYCLE)] for i in range(n_rounds)))
    for c in _ALL_CIRCUITS:
        curated.add(tuple(c for _ in range(n_rounds)))
    return list(curated)


def _seq_name(seq: tuple[PurificationCircuit, ...]) -> str:
    return "_".join(c.name for c in seq) if seq else "raw"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def brute_force_search(
    network: NetworkConfig,
    objective: ObjectiveConfig,
    e_max: int,
    *,
    max_n_pur: int | None = None,
    max_enumerated_rounds: int = 4,
    include_heralded: bool = True,
    include_optimistic: bool = True,
    include_link_level: bool = True,
) -> list[SearchResult]:
    """Enumerate a structured family of schedules and return them sorted best-first.

    Parameters
    ----------
    network : NetworkConfig
        Physical network configuration to evaluate against.
    objective : ObjectiveConfig
        Objective function (defines score and feasibility constraints).
    e_max : int
        Maximum number of Gen nodes (= half-RGS copies × 2 sides × N hops).
        The search respects ``C(Σ) ≤ e_max`` for all candidates.
    max_n_pur : int, optional
        Hard cap on the number of purification copies tried per strategy.
        Defaults to ``e_max // (2 * N)`` (the budget-derived maximum).
    max_enumerated_rounds : int
        Maximum number of pumping rounds for which all circuit combinations
        are exhaustively enumerated.  Beyond this, a curated set is used.
        Default 4 gives at most 3^4 = 81 sequences (always fast).
    include_heralded : bool
        Include the end-node heralded strategy family (default True).
    include_optimistic : bool
        Include the end-node optimistic strategy family (default True).
    include_link_level : bool
        Include the link-level purification strategy family (default True).

    Returns
    -------
    list[SearchResult]
        All evaluated candidates, sorted best-first (highest score first).
        Infeasible candidates (score = −∞) appear last.
    """
    N = network.N
    if N < 1:
        raise ValueError(f"network.N must be >= 1, got {N}")

    evaluator = Evaluator(network)
    candidates: list[SearchResult] = []
    seen_labels: set[str] = set()

    gen_per_copy = 2 * N  # one Gen per side per hop
    budget_cap = e_max // gen_per_copy if gen_per_copy > 0 else 1
    cap = min(budget_cap, max_n_pur or budget_cap)

    def record(dag: ScheduleDAG, label: str) -> None:
        if label in seen_labels:
            return
        seen_labels.add(label)
        try:
            dag.validate()
        except ValueError:
            return
        result = evaluator.evaluate(dag)
        score = objective.score(result)
        candidates.append(
            SearchResult(label=label, dag=dag, eval_result=result, score=score)
        )

    # ------------------------------------------------------------------
    # 1.  Raw chain (n_pur = 1 — always included as trivial baseline)
    # ------------------------------------------------------------------
    record(ScheduleDAG.raw_chain(N), "raw")

    # ------------------------------------------------------------------
    # 2.  End-node heralded / optimistic families
    # ------------------------------------------------------------------
    for n_pur in range(2, cap + 1):
        if gen_per_copy * n_pur > e_max:
            break
        n_rounds = n_pur - 1
        for seq in _circuit_sequences(n_rounds, max_enumerated_rounds):
            sname = _seq_name(seq)
            if include_heralded:
                dag = ScheduleDAG.generic_end_node_pumping(
                    N, n_pur, circuits=seq, heralded=True
                )
                record(dag, f"end_heralded.n{n_pur}.{sname}")
            if include_optimistic:
                dag = ScheduleDAG.generic_end_node_pumping(
                    N, n_pur, circuits=seq, heralded=False
                )
                record(dag, f"end_optimistic.n{n_pur}.{sname}")

    # ------------------------------------------------------------------
    # 3.  Link-level purification family
    # ------------------------------------------------------------------
    if include_link_level:
        for n_copies in range(2, cap + 1):
            if gen_per_copy * n_copies > e_max:
                break
            n_rounds = n_copies - 1
            for seq in _circuit_sequences(n_rounds, max_enumerated_rounds):
                sname = _seq_name(seq)
                dag = ScheduleDAG.link_level_pumped_chain(
                    N, n_copies=n_copies, circuits=seq
                )
                record(dag, f"link.n{n_copies}.{sname}")

    # ------------------------------------------------------------------
    # 4.  Paper's flexible schedule (even N only, if within budget)
    # ------------------------------------------------------------------
    if N % 2 == 0:
        n_gen_flexible = 5 * gen_per_copy  # 5 copies × 2 × N
        if n_gen_flexible <= e_max:
            dag = ScheduleDAG.flexible_paper_schedule(N)
            record(dag, "flexible_paper")

    candidates.sort(key=lambda r: r.score, reverse=True)
    return candidates
