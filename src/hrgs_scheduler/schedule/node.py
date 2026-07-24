"""
hrgs_scheduler.schedule.node
==============================
Schedule DAG node types.

A schedule Σ = (T, φ) is a rooted DAG where
  - leaves  are GenNode instances
  - internal nodes are backbone or scheduling-layer operation nodes
  - root    is a PauliCorrectNode at κ = Span(0, N)

Every node carries:
  - a node_id  (unique within the DAG, for graph bookkeeping)
  - children   (ordered list of input node_ids for multi-input ops)
  - a stage κ  stored on the node's output (φ mapping)

Node types mirror the operation catalog [Validated Formal Model Def, §2.5 + §3.2]:

    GenNode:            leaf; produces an RGSS-local resource
    JoinNode:           Join/EntSwap; 2 inputs
    AbsaBsmNode:        outer-photon BSM at ABSA; 2 RGSS inputs → single-hop edge
    IdleNode:           decoherence wait; 1 input
    HeraldNode:         heralding resolution; 1 input
    PurifyNode:         2-to-1 purification; 2 inputs, same κ
    PauliCorrectNode:   terminal; 1 input at κ = Span(0, N)

Each node is an immutable frozen dataclass; mutation happens by rebuilding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, Union

from hrgs_scheduler.models.stage import Stage, RGSS, Span
from hrgs_scheduler.operations.purification import PurificationCircuit

# ---------------------------------------------------------------------------
# Type alias for node ID (int handles arbitrarily large DAGs)
# ---------------------------------------------------------------------------
NodeId = int


# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenNode:
    """Leaf node: produces a fresh RGSS-local resource.

    Parameters
    ----------
    node_id : NodeId
        Unique identifier within the DAG.
    hop_index : int
        Which hop (0-indexed) this generator belongs to.  Determines
        which HopConfig is used when evaluating the node.
    gen_time : float
        Simulation timestamp at which this Gen fires.
    side_effect_parity : int
        Initial s^gen ∈ {0, 1}.  0 for the ideal/deterministic case.
    """

    node_id: NodeId
    hop_index: int
    gen_time: float = field(default=0.0)
    side_effect_parity: int = field(default=0)

    @property
    def children(self) -> tuple[NodeId, ...]:
        """Gen nodes have no children (they are leaves)."""
        return ()

    @property
    def output_stage(self) -> Stage:
        return RGSS


@dataclass(frozen=True)
class AbsaBsmNode:
    """Outer-photon BSM at the ABSA: creates a single-hop edge.

    Consumes two RGSS-local resources (one from each side of a hop) and
    produces a State at κ = Span(hop_index, hop_index + 1).

    Parameters
    ----------
    node_id : NodeId
    children : tuple[NodeId, NodeId]
        (left_gen_id, right_gen_id): both must produce RGSS-local States.
    hop_index : int
        0-indexed hop number.  Determines κ_out = Span(hop_index, hop_index+1).
    """

    node_id: NodeId
    children: tuple[NodeId, NodeId]
    hop_index: int

    @property
    def output_stage(self) -> Span:
        return Span(self.hop_index, self.hop_index + 1)


@dataclass(frozen=True)
class JoinNode:
    """Join / EntSwap: entanglement swap between two adjacent resources.

    Inputs may be:
      - Two RGSS-local States → output at RGSS  (pre-transmission pairing)
      - Span(a, b) + Span(b, d) → Span(a, d)    (post-transmission stitching)

    Parameters
    ----------
    node_id : NodeId
    children : tuple[NodeId, NodeId]
        The two input node IDs (order: left, right).
    output_stage : Stage
        Pre-computed output stage, for fast lookup without re-evaluating
        children.  Set by the DAG builder after stage-consistency checking.
    """

    node_id: NodeId
    children: tuple[NodeId, NodeId]
    output_stage: Stage


@dataclass(frozen=True)
class PurifyNode:
    """2-to-1 purification: consumes two States at the same κ.

    Parameters
    ----------
    node_id : NodeId
    children : tuple[NodeId, NodeId]
        (primary_id, ancilla_id): both must be at the same κ.
    circuit : PurificationCircuit
        Which stabilizer circuit to apply: YY, ZX, or XZ.
    output_stage : Stage
        Same κ as both inputs (set by the DAG builder).
    """

    node_id: NodeId
    children: tuple[NodeId, NodeId]
    circuit: PurificationCircuit
    output_stage: Stage


@dataclass(frozen=True)
class IdleNode:
    """Idle / decoherence wait: advances the clock without an operation.

    Parameters
    ----------
    node_id : NodeId
    children : tuple[NodeId]
        Single input node ID.
    until : float
        Target clock value; must be ≥ the child's output time.
    """

    node_id: NodeId
    children: tuple[NodeId]
    until: float

    @property
    def output_stage(self) -> None:
        # Stage is inherited from the child; resolved at evaluation time.
        return None


@dataclass(frozen=True)
class HeraldNode:
    """Classical heralding resolution.

    Parameters
    ----------
    node_id : NodeId
    children : tuple[NodeId]
        Single input node ID.
    propagation_time : float
        Dimensionless multiplier of the network's one-way propagation time
        L_total/c, e.g. 1.0 for a single one-way herald (raw/optimistic
        final resolution) or 2.0 for a full round-trip confirmation
        (heralded/sequential pumping round).  The Evaluator multiplies
        this by the actual network's L_total/c to get physical time,
        keeping the DAG structure itself network-agnostic.
    """

    node_id: NodeId
    children: tuple[NodeId]
    propagation_time: float = field(default=1.0)


@dataclass(frozen=True)
class PauliCorrectNode:
    """Terminal Pauli-frame correction: root of the schedule DAG.

    Parameters
    ----------
    node_id : NodeId
    children : tuple[NodeId]
        Single input node ID; must be at κ = Span(0, N) and RESOLVED.
    N : int
        Number of hops in the network.
    """

    node_id: NodeId
    children: tuple[NodeId]
    N: int

    @property
    def output_stage(self) -> Span:
        return Span(0, self.N)


# ---------------------------------------------------------------------------
# Union type for all node types
# ---------------------------------------------------------------------------

ScheduleNode = Union[
    GenNode,
    AbsaBsmNode,
    JoinNode,
    PurifyNode,
    IdleNode,
    HeraldNode,
    PauliCorrectNode,
]
