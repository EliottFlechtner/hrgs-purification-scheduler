"""
hrgs_scheduler.schedule.evaluator
====================================
Inner-loop evaluator: bottom-up DAG pass computing F, R, C, L.

Algorithm [Validated Formal Model Def, §7]
-----------------------------------------
Given a concrete schedule Σ = (T, φ), computing F, R, C, L is a
*bottom-up pass* over the DAG T.  Each node's output depends only on
its children's outputs, giving O(|T|) dynamic-programming evaluation.

The evaluator traverses nodes in topological order (leaves → root),
materialises a ``State`` for each node, then extracts cost functions
from the root State.

Cost function extraction
------------------------
    F(Σ; N) = w_root         (fidelity, w component of root error vector)
    C(Σ)    = |Gen leaves|    (resource cost, count of GenNodes)
    L(Σ; N) = root.current_time (latency / makespan)
    R(Σ; N) = P_success / E[wall-clock time]
               under a renewal-theory restart model; P_success is the
               product of all PurifyNode success probabilities along
               the critical path (pessimistic: product over all Purify
               nodes in the DAG, which is an outer bound valid for
               non-adaptive schedules).

The evaluator also returns a per-node ``State`` cache so callers can
inspect intermediate results.

EvaluationResult
----------------
Named tuple returned by ``Evaluator.evaluate``:

    fidelity        : float    F(Σ)
    rate            : float    R(Σ)  (unnormalised; requires time unit)
    resource_cost   : int      C(Σ)  (Gen node count)
    latency         : float    L(Σ)  (makespan of T)
    success_prob    : float    P[Σ succeeds] (product of Purify probs)
    node_states     : dict     NodeId → State (full per-node cache)
"""

from __future__ import annotations

from typing import NamedTuple

from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.models.stage import RGSS, Span
from hrgs_scheduler.models.state import HeraldStatus, State
from hrgs_scheduler.operations.backbone import (
    absa_bsm,
    gen,
    herald,
    idle,
    join,
    pauli_correct,
)
from hrgs_scheduler.operations.purification import purify
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    IdleNode,
    JoinNode,
    NodeId,
    PauliCorrectNode,
    PurifyNode,
)


class EvaluationResult(NamedTuple):
    """Result of evaluating a schedule Σ against a network configuration N.

    Attributes
    ----------
    fidelity : float
        F(Σ; N) = w component of the root error vector.
        The probability of the ideal Bell state in the output.
    rate : float
        R(Σ; N) = success_prob / latency, under renewal-theory restart.
        Units: [1 / time_unit].  Time unit is determined by the c and
        gamma values in NetworkConfig (typically seconds or μs).
    resource_cost : int
        C(Σ) = number of Gen nodes = total half-RGS copies used.
    latency : float
        L(Σ; N) = makespan of T = root.current_time.
    success_prob : float
        P[Σ succeeds] = product of all PurifyNode success probabilities.
        For a schedule with no purification, success_prob = 1.
    node_states : dict[NodeId, State]
        Full per-node State cache; useful for debugging and visualisation.
    """

    fidelity: float
    rate: float
    resource_cost: int
    latency: float
    success_prob: float
    node_states: dict[NodeId, State]


class Evaluator:
    """Inner-loop schedule evaluator.

    Evaluates a concrete ScheduleDAG against a NetworkConfig by performing
    a bottom-up (leaves-first) traversal and materialising a State for
    each node.

    Parameters
    ----------
    network : NetworkConfig
        Physical network configuration N.
    """

    def __init__(self, network: NetworkConfig) -> None:
        self._network = network

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, dag: ScheduleDAG) -> EvaluationResult:
        """Evaluate schedule *dag* and return all cost functions.

        Performs the O(|T|) bottom-up pass described in
        [Validated Formal Model Def, §7].

        Parameters
        ----------
        dag : ScheduleDAG
            The schedule to evaluate.  Must pass ``dag.validate()``.

        Returns
        -------
        EvaluationResult
            Fidelity, rate, resource cost, latency, success probability,
            and full per-node State cache.

        Raises
        ------
        ValueError
            If the DAG contains an unknown or illegal node type, or a
            legality constraint is violated during evaluation.
        """
        topo_order = dag.topological_order()
        node_states: dict[NodeId, State] = {}
        success_prob = 1.0  # product over all Purify nodes

        for nid in topo_order:
            node = dag.nodes[nid]

            if isinstance(node, GenNode):
                state = self._eval_gen(node)

            elif isinstance(node, AbsaBsmNode):
                child_l, child_r = node.children
                state = self._eval_absa_bsm(
                    node, node_states[child_l], node_states[child_r]
                )

            elif isinstance(node, JoinNode):
                child_l, child_r = node.children
                state = join(node_states[child_l], node_states[child_r])

            elif isinstance(node, PurifyNode):
                child_p, child_a = node.children
                result = purify(
                    node.circuit,
                    node_states[child_p],
                    node_states[child_a],
                )
                state = result.output_state
                success_prob *= result.success_prob

            elif isinstance(node, IdleNode):
                (child_id,) = node.children
                state = idle(
                    node_states[child_id],
                    until=node.until,
                    gamma=self._network.gamma,
                )

            elif isinstance(node, HeraldNode):
                (child_id,) = node.children
                # node.propagation_time is a dimensionless multiplier of the
                # network's one-way light-propagation time L_total/c (e.g.
                # 1.0 = one-way herald, 2.0 = full round-trip confirmation).
                # This keeps the DAG structure network-agnostic while the
                # Evaluator supplies the actual physical time scale.
                l_over_c = self._network.total_length() / self._network.c
                state = herald(
                    node_states[child_id],
                    propagation_time=node.propagation_time * l_over_c,
                )

            elif isinstance(node, PauliCorrectNode):
                (child_id,) = node.children
                state = pauli_correct(node_states[child_id], N=node.N)

            else:
                raise ValueError(
                    f"Unknown node type {type(node).__name__} at node {nid}"
                )

            node_states[nid] = state

        # Extract root state and cost functions
        root_state = node_states[dag.root_id]
        fidelity = root_state.fidelity
        latency = root_state.current_time
        resource_cost = dag.gen_node_count

        # Rate: renewal-theory model R = P_success / E[latency]
        # For the non-adaptive case, E[latency] = latency (deterministic schedule)
        rate = success_prob / latency if latency > 0.0 else float("inf")

        return EvaluationResult(
            fidelity=fidelity,
            rate=rate,
            resource_cost=resource_cost,
            latency=latency,
            success_prob=success_prob,
            node_states=node_states,
        )

    # ------------------------------------------------------------------
    # Per-node evaluation helpers
    # ------------------------------------------------------------------

    def _eval_gen(self, node: GenNode) -> State:
        """Evaluate a GenNode using the hop config for node.hop_index."""
        hop_config = self._network.hop(node.hop_index)
        return gen(
            hop_config=hop_config,
            t=node.gen_time,
            side_effect_parity=node.side_effect_parity,
        )

    def _eval_absa_bsm(
        self, node: AbsaBsmNode, state_l: State, state_r: State
    ) -> State:
        """Evaluate an AbsaBsmNode using the network's e_d parameter."""
        return absa_bsm(
            state_a=state_l,
            state_b=state_r,
            hop_index=node.hop_index,
            e_d=self._network.e_d,
        )
