"""
hrgs_scheduler.schedule.dag
=============================
Schedule DAG — the formal schedule object Σ = (T, φ).

A ScheduleDAG wraps a dictionary of ScheduleNode objects connected by
node_id references.  The root is always a PauliCorrectNode.

Design
------
Nodes are stored in a flat dict keyed by node_id.  Edges are implicit
via the ``children`` attribute of each node.  This gives O(1) lookup
by ID and a clean separation between structure (DAG) and evaluation
(handled by the Evaluator).

``validate()`` performs the legality checks from
[Validated Formal Model Def, §4.1]:
  - Single root (PauliCorrectNode)
  - No cycles (topological sort), no unreachable nodes
  - Stage consistency: Gen only at RGSS, Purify requires identical κ on
    both children, Join/EntSwap requires two RGSS-local resources or two
    adjacent Spans (span-consistency: Span(a,b)+Span(b,d) -> Span(a,d)),
    PauliCorrect requires κ = Span(0, N).
  - Resource-budget feasibility (E_max/M_max, §5) is NOT checked here —
    see ``cost_functions.satisfies_budget`` for the E_max (Gen-count) part;
    M_max (max concurrent open branches) has no enforcement yet.

Convenience builders
--------------------
``ScheduleDAG.raw_chain``               — no purification, N-hop chain.
``ScheduleDAG.baseline_end_node_pumping``— end-node entanglement pumping
                                           [Integrating, §V-C/§VI].
``ScheduleDAG.flexible_paper_schedule`` — the flexible schedule from
                                           [Integrating, Fig. 4].
``ScheduleDAG.single_hop_yy_purified``  — single-hop YY pumping demo.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterator, Sequence

from hrgs_scheduler.models.stage import RGSS, RGSSStage, Span, Stage
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    IdleNode,
    JoinNode,
    NodeId,
    PauliCorrectNode,
    PurifyNode,
    ScheduleNode,
)


@dataclass
class ScheduleDAG:
    """Rooted directed acyclic graph representing a purification schedule Σ = (T, φ).

    Parameters
    ----------
    nodes : dict[NodeId, ScheduleNode]
        All nodes in the DAG, keyed by node_id.
    root_id : NodeId
        The node_id of the PauliCorrectNode (unique root).
    N : int
        Number of hops in the target network.  Used for legality checks.

    Attributes
    ----------
    nodes       see above
    root_id     see above
    N           see above
    """

    nodes: dict[NodeId, ScheduleNode]
    root_id: NodeId
    N: int

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Run all structural legality checks on this DAG.

        Raises
        ------
        ValueError
            On any structural violation: missing node, cycle, stage mismatch,
            wrong root type, etc.
        """
        self._check_root()
        order = self._topological_order()
        self._check_no_extra_roots(order)
        self._check_stage_consistency(order)

    def _check_root(self) -> None:
        root = self.nodes.get(self.root_id)
        if root is None:
            raise ValueError(f"root_id {self.root_id} not found in nodes")
        if not isinstance(root, PauliCorrectNode):
            raise ValueError(
                f"Root node must be PauliCorrectNode, got {type(root).__name__}"
            )

    def _check_no_extra_roots(self, order: list[NodeId]) -> None:
        """Ensure every non-root node is referenced by at least one parent."""
        referenced: set[NodeId] = set()
        for nid in order:
            node = self.nodes[nid]
            if hasattr(node, "children"):
                for child_id in node.children:
                    referenced.add(child_id)
        for nid in order:
            if nid != self.root_id and nid not in referenced:
                raise ValueError(
                    f"Node {nid} ({type(self.nodes[nid]).__name__}) is unreachable "
                    "(not referenced by any parent)"
                )

    def _check_stage_consistency(self, order: list[NodeId]) -> None:
        """Statically verify φ's legality [Validated Formal Model Def, §4.1].

        Walks the DAG bottom-up computing each node's *declared* κ purely
        from structure (no error vectors / State objects involved) and
        checks:
          - Gen only at RGSS (trivially true by construction).
          - Join/EntSwap: both children RGSS, or both children adjacent
            Spans; declared ``output_stage`` must match the computed
            result of the join.
          - Purify: both children must share an identical declared κ, and
            the declared ``output_stage`` must equal that shared κ.
          - PauliCorrect: child must be at κ = Span(0, N).
        Idle/Herald pass their child's declared κ through unchanged.

        This mirrors the runtime legality already enforced by
        ``operations.backbone.join``/``purify``/``pauli_correct`` on
        actual ``State`` objects, but catches structural mistakes (e.g. a
        builder computing the wrong ``output_stage``) before evaluation.
        """
        declared: dict[NodeId, Stage] = {}
        for nid in order:
            node = self.nodes[nid]

            if isinstance(node, GenNode):
                declared[nid] = RGSS

            elif isinstance(node, AbsaBsmNode):
                declared[nid] = Span(node.hop_index, node.hop_index + 1)

            elif isinstance(node, (IdleNode, HeraldNode)):
                (child_id,) = node.children
                declared[nid] = declared[child_id]

            elif isinstance(node, JoinNode):
                left_id, right_id = node.children
                left_stage, right_stage = declared[left_id], declared[right_id]
                expected = self._join_output_stage(left_stage, right_stage, nid)
                if expected != node.output_stage:
                    raise ValueError(
                        f"JoinNode {nid}: declared output_stage "
                        f"{node.output_stage!r} does not match the stage "
                        f"{expected!r} computed from children {left_stage!r}, "
                        f"{right_stage!r} [§4.1]"
                    )
                declared[nid] = node.output_stage

            elif isinstance(node, PurifyNode):
                left_id, right_id = node.children
                left_stage, right_stage = declared[left_id], declared[right_id]
                if left_stage != right_stage:
                    raise ValueError(
                        f"PurifyNode {nid}: children must share identical "
                        f"\u03ba [\u00a73.2], got {left_stage!r} and {right_stage!r}"
                    )
                if node.output_stage != left_stage:
                    raise ValueError(
                        f"PurifyNode {nid}: declared output_stage "
                        f"{node.output_stage!r} != input \u03ba {left_stage!r}"
                    )
                declared[nid] = node.output_stage

            elif isinstance(node, PauliCorrectNode):
                (child_id,) = node.children
                child_stage = declared[child_id]
                expected_root = Span(0, node.N)
                if child_stage != expected_root:
                    raise ValueError(
                        f"PauliCorrectNode {nid}: requires \u03ba = "
                        f"{expected_root!r} [§4.1], got {child_stage!r}"
                    )
                declared[nid] = expected_root

            else:
                raise ValueError(
                    f"Unknown node type {type(node).__name__} at node {nid}"
                )

    @staticmethod
    def _join_output_stage(stage_a: Stage, stage_b: Stage, nid: NodeId) -> Stage:
        """Compute the legal Join/EntSwap output κ from two input κ's.

        RGSS + RGSS -> RGSS (pre-transmission pairing); Span(a,b) +
        Span(b,d) -> Span(a,d) (span-consistency, §4.1).
        """
        if isinstance(stage_a, RGSSStage) and isinstance(stage_b, RGSSStage):
            return RGSS
        if isinstance(stage_a, Span) and isinstance(stage_b, Span):
            try:
                return stage_a.join(stage_b)
            except ValueError as exc:
                raise ValueError(f"JoinNode {nid}: {exc}") from exc
        raise ValueError(
            f"JoinNode {nid}: illegal stage combination {stage_a!r}, "
            f"{stage_b!r}; both must be RGSS or both must be adjacent "
            "Span instances [§4.1]."
        )

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def _topological_order(self) -> list[NodeId]:
        """Return nodes in topological order (leaves first, root last).

        Uses Kahn's algorithm (BFS from in-degree 0 nodes).

        Raises
        ------
        ValueError
            If a cycle is detected.
        """
        # Build in-degree map and adjacency list (child → parents)
        in_degree: dict[NodeId, int] = {nid: 0 for nid in self.nodes}
        children_of: dict[NodeId, list[NodeId]] = {nid: [] for nid in self.nodes}

        for nid, node in self.nodes.items():
            for child_id in node.children:
                if child_id not in self.nodes:
                    raise ValueError(f"Node {nid} references unknown child {child_id}")
                in_degree[nid] = in_degree.get(nid, 0)
                children_of[child_id].append(nid)

        # Recompute in_degree properly
        in_degree = {nid: 0 for nid in self.nodes}
        for nid, node in self.nodes.items():
            for child_id in node.children:
                in_degree[nid] += 1

        queue: deque[NodeId] = deque(nid for nid, deg in in_degree.items() if deg == 0)
        order: list[NodeId] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for parent_id in children_of[nid]:
                in_degree[parent_id] -= 1
                if in_degree[parent_id] == 0:
                    queue.append(parent_id)

        if len(order) != len(self.nodes):
            raise ValueError("Cycle detected in schedule DAG")

        return order

    def topological_order(self) -> list[NodeId]:
        """Return all node IDs in topological order (leaves first, root last)."""
        return self._topological_order()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def gen_node_count(self) -> int:
        """Number of Gen leaves — the resource cost C(Σ)."""
        return sum(1 for n in self.nodes.values() if isinstance(n, GenNode))

    @property
    def purify_node_count(self) -> int:
        """Total number of Purify nodes in the DAG."""
        return sum(1 for n in self.nodes.values() if isinstance(n, PurifyNode))

    def gen_nodes(self) -> Iterator[GenNode]:
        """Iterate over all GenNode instances."""
        for node in self.nodes.values():
            if isinstance(node, GenNode):
                yield node

    # ------------------------------------------------------------------
    # Internal building blocks (shared by convenience builders)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_raw_segment(
        nodes: dict[NodeId, ScheduleNode],
        nid: int,
        hop_start: int,
        hop_count: int,
        gen_time: float,
    ) -> tuple[NodeId, Stage, int]:
        """Build one raw (unpurified) chain spanning *hop_count* hops.

        Mutates *nodes* in place, adding Gen/AbsaBsm/Join nodes for a raw
        stitched chain covering hops [hop_start, hop_start + hop_count).

        Parameters
        ----------
        nodes : dict[NodeId, ScheduleNode]
            Node dict to populate (mutated in place).
        nid : int
            Next free node_id to use.
        hop_start : int
            0-indexed first hop covered by this segment.
        hop_count : int
            Number of hops in this segment.
        gen_time : float
            Simulation timestamp for all Gen nodes.

        Returns
        -------
        (final_node_id, final_stage, next_nid)
            The node_id and Span of the segment's final stitched edge,
            and the next free node_id.
        """
        hop_edge_ids: list[NodeId] = []
        for offset in range(hop_count):
            hop_i = hop_start + offset
            g_l = GenNode(node_id=nid, hop_index=hop_i, gen_time=gen_time)
            nid += 1
            g_r = GenNode(node_id=nid, hop_index=hop_i, gen_time=gen_time)
            nid += 1
            nodes[g_l.node_id] = g_l
            nodes[g_r.node_id] = g_r
            bsm = AbsaBsmNode(
                node_id=nid, children=(g_l.node_id, g_r.node_id), hop_index=hop_i
            )
            nid += 1
            nodes[bsm.node_id] = bsm
            hop_edge_ids.append(bsm.node_id)

        current_id = hop_edge_ids[0]
        current_stage: Stage = Span(hop_start, hop_start + 1)
        for offset in range(1, hop_count):
            hop_i = hop_start + offset
            right_stage = Span(hop_i, hop_i + 1)
            merged_stage = current_stage.join(right_stage)  # type: ignore[union-attr]
            jn = JoinNode(
                node_id=nid,
                children=(current_id, hop_edge_ids[offset]),
                output_stage=merged_stage,
            )
            nid += 1
            nodes[jn.node_id] = jn
            current_id = jn.node_id
            current_stage = merged_stage

        return current_id, current_stage, nid

    @staticmethod
    def _wrap_herald_and_correct(
        nodes: dict[NodeId, ScheduleNode],
        nid: int,
        final_id: NodeId,
        N: int,
        propagation_time: float = 1.0,
    ) -> tuple[NodeId, int]:
        """Append a HeraldNode + PauliCorrectNode (root) after *final_id*.

        Parameters
        ----------
        propagation_time : float
            Multiplier of the network's one-way L_total/c passed to the
            HeraldNode (default 1.0 = single one-way herald, matching the
            final resolution step shared by raw/baseline/flexible schemes
            [Integrating, eqs. 1-2, 5-6]).
        """
        herald_node = HeraldNode(
            node_id=nid, children=(final_id,), propagation_time=propagation_time
        )
        nid += 1
        nodes[herald_node.node_id] = herald_node
        root = PauliCorrectNode(node_id=nid, children=(herald_node.node_id,), N=N)
        nid += 1
        nodes[root.node_id] = root
        return root.node_id, nid

    # ------------------------------------------------------------------
    # Convenience builders
    # ------------------------------------------------------------------

    @classmethod
    def raw_chain(cls, N: int, gen_time: float = 0.0) -> ScheduleDAG:
        """Build a raw (no purification) N-hop chain schedule.

        For each hop i, generates two RGSS resources and combines them
        via an AbsaBsmNode.  All single-hop edges are then stitched
        left-to-right via JoinNodes, and the result is wrapped in
        HeraldNode + PauliCorrectNode.

        Structure (N=3):
            Gen Gen   Gen Gen   Gen Gen
             \\ /       \\ /       \\ /
            BSM(0)    BSM(1)    BSM(2)
               \\        |        /
               Join(0,1,2→0,2)  /
                    \\          /
                     Join(0,3)
                         |
                       Herald
                         |
                    PauliCorrect

        Parameters
        ----------
        N : int
            Number of hops.
        gen_time : float
            Simulation timestamp for all Gen nodes.

        Returns
        -------
        ScheduleDAG
            A valid raw-chain schedule with no purification.
        """
        nodes: dict[NodeId, ScheduleNode] = {}
        final_id, _, nid = cls._build_raw_segment(nodes, 0, 0, N, gen_time)
        root_id, _ = cls._wrap_herald_and_correct(nodes, nid, final_id, N)
        return cls(nodes=nodes, root_id=root_id, N=N)

    @classmethod
    def baseline_end_node_pumping(
        cls, N: int, n_pur: int = 5, gen_time: float = 0.0
    ) -> ScheduleDAG:
        """Build the baseline end-node entanglement-pumping schedule [Integrating, §V-C, §VI].

        Generates *n_pur* independent raw N-hop end-to-end Bell pairs, then
        purifies them via entanglement pumping using the same circuit
        sequence as the paper: YY, ZX, YY, XZ, repeating if n_pur > 5.

        This models "Baseline purification at end nodes": all copies are
        distributed raw across the full path, then purified only after
        full end-to-end BSMs/joins -- i.e. purification happens entirely
        at κ = Span(0, N).

        Heralding structure [Integrating, §III-B, §VI]: entanglement
        pumping via heralded (two-way) purification is inherently
        *sequential* -- each round must wait for a full round-trip
        classical confirmation (2·L_total/c) of the previous round's
        success before the next round can begin. This is modeled by
        inserting an intermediate HeraldNode (propagation_time=2.0, i.e.
        2×L_total/c) after every PurifyNode in the pumping chain, in
        addition to the final one-way herald shared by all schemes. This
        is the DAG-structural difference from `flexible_paper_schedule`,
        whose internal purifications have NO intermediate Heralds (per
        [Validated Formal Model Def, §3.3]: "'Optimistic' vs. 'heralded'
        purification is determined by where Herald nodes sit in the
        schedule DAG relative to Purify nodes").

        Parameters
        ----------
        N : int
            Number of hops.
        n_pur : int
            Number of independent raw end-to-end copies generated
            (paper uses n_pur=5, giving 4 pumping rounds).
        gen_time : float
            Simulation timestamp for all Gen nodes.

        Returns
        -------
        ScheduleDAG
            The baseline pumping schedule with (n_pur - 1) Purify nodes
            and (n_pur - 1) intermediate round-trip Herald nodes.
        """
        if n_pur < 1:
            raise ValueError(f"n_pur must be >= 1, got {n_pur}")

        nodes: dict[NodeId, ScheduleNode] = {}
        nid = 0
        circuit_cycle = [
            PurificationCircuit.YY,
            PurificationCircuit.ZX,
            PurificationCircuit.YY,
            PurificationCircuit.XZ,
        ]

        copy_ids: list[NodeId] = []
        for _ in range(n_pur):
            final_id, _, nid = cls._build_raw_segment(nodes, nid, 0, N, gen_time)
            copy_ids.append(final_id)

        current_id = copy_ids[0]
        for round_i, sacrificial_id in enumerate(copy_ids[1:]):
            circuit = circuit_cycle[round_i % len(circuit_cycle)]
            pur = PurifyNode(
                node_id=nid,
                children=(current_id, sacrificial_id),
                circuit=circuit,
                output_stage=Span(0, N),
            )
            nid += 1
            nodes[pur.node_id] = pur
            # Heralded round-trip confirmation before the next pumping
            # round may begin (see docstring above).
            round_herald = HeraldNode(
                node_id=nid, children=(pur.node_id,), propagation_time=2.0
            )
            nid += 1
            nodes[round_herald.node_id] = round_herald
            current_id = round_herald.node_id

        root_id, _ = cls._wrap_herald_and_correct(nodes, nid, current_id, N)
        return cls(nodes=nodes, root_id=root_id, N=N)

    @classmethod
    def flexible_paper_schedule(cls, N: int = 10, gen_time: float = 0.0) -> ScheduleDAG:
        """Build the "flexible" purification-enhanced schedule from [Integrating, Fig. 4].

        Constructs three end-to-end Bell pairs using 5 half-RGS copies per
        side per hop, then combines them at the end nodes:

          Pair A (link-level):   at each hop, 2 copies are YY-purified
                                  locally, then the 10 purified hop edges
                                  are stitched into one end-to-end pair.
          Pair B (segment-level): the path is split into two N/2-hop
                                  segments; each segment is built from 2
                                  independent raw chains, YY-purified
                                  together, then the two purified segments
                                  are stitched.
          Pair C (raw):          one raw N-hop chain, unpurified.

        Final combination [Integrating, §VI]: ZX-purify(A, B) with B as
        the sacrificial pair, then YY-purify(result, C) with C sacrificial.

        Requires N to be even (paper uses N=10, split into two 5-hop
        segments).

        Parameters
        ----------
        N : int
            Number of hops (must be even).
        gen_time : float
            Simulation timestamp for all Gen nodes.

        Returns
        -------
        ScheduleDAG
            The flexible schedule, consuming 5 half-RGS copies per hop.
        """
        if N % 2 != 0:
            raise ValueError(f"flexible_paper_schedule requires even N, got {N}")
        half = N // 2

        nodes: dict[NodeId, ScheduleNode] = {}
        nid = 0

        # --- Pair A: link-level YY purification, then stitch ---
        purified_hop_ids: list[NodeId] = []
        for hop_i in range(N):
            copy1, _, nid = cls._build_raw_segment(nodes, nid, hop_i, 1, gen_time)
            copy2, _, nid = cls._build_raw_segment(nodes, nid, hop_i, 1, gen_time)
            pur = PurifyNode(
                node_id=nid,
                children=(copy1, copy2),
                circuit=PurificationCircuit.YY,
                output_stage=Span(hop_i, hop_i + 1),
            )
            nid += 1
            nodes[pur.node_id] = pur
            purified_hop_ids.append(pur.node_id)

        current_id = purified_hop_ids[0]
        current_stage: Stage = Span(0, 1)
        for hop_i in range(1, N):
            right_stage = Span(hop_i, hop_i + 1)
            merged_stage = current_stage.join(right_stage)  # type: ignore[union-attr]
            jn = JoinNode(
                node_id=nid,
                children=(current_id, purified_hop_ids[hop_i]),
                output_stage=merged_stage,
            )
            nid += 1
            nodes[jn.node_id] = jn
            current_id = jn.node_id
            current_stage = merged_stage
        pair_a_id = current_id

        # --- Pair B: two half-segments, each from 2 raw copies YY-purified ---
        segment_ids: list[NodeId] = []
        for seg_start in (0, half):
            seg_copy1, seg_stage, nid = cls._build_raw_segment(
                nodes, nid, seg_start, half, gen_time
            )
            seg_copy2, _, nid = cls._build_raw_segment(
                nodes, nid, seg_start, half, gen_time
            )
            pur = PurifyNode(
                node_id=nid,
                children=(seg_copy1, seg_copy2),
                circuit=PurificationCircuit.YY,
                output_stage=seg_stage,
            )
            nid += 1
            nodes[pur.node_id] = pur
            segment_ids.append(pur.node_id)

        left_stage = Span(0, half)
        right_stage = Span(half, N)
        merged_stage = left_stage.join(right_stage)
        jn = JoinNode(
            node_id=nid,
            children=(segment_ids[0], segment_ids[1]),
            output_stage=merged_stage,
        )
        nid += 1
        nodes[jn.node_id] = jn
        pair_b_id = jn.node_id

        # --- Pair C: one raw N-hop chain ---
        pair_c_id, _, nid = cls._build_raw_segment(nodes, nid, 0, N, gen_time)

        # --- Final combination: ZX-purify(A, B), then YY-purify(result, C) ---
        zx_pur = PurifyNode(
            node_id=nid,
            children=(pair_a_id, pair_b_id),
            circuit=PurificationCircuit.ZX,
            output_stage=Span(0, N),
        )
        nid += 1
        nodes[zx_pur.node_id] = zx_pur

        yy_pur = PurifyNode(
            node_id=nid,
            children=(zx_pur.node_id, pair_c_id),
            circuit=PurificationCircuit.YY,
            output_stage=Span(0, N),
        )
        nid += 1
        nodes[yy_pur.node_id] = yy_pur

        root_id, _ = cls._wrap_herald_and_correct(nodes, nid, yy_pur.node_id, N)
        return cls(nodes=nodes, root_id=root_id, N=N)

    @classmethod
    def single_hop_yy_purified(
        cls,
        N: int,
        n_pur: int = 1,
        gen_time: float = 0.0,
    ) -> ScheduleDAG:
        """Build a schedule with YY purification at end nodes, N=1 or multi-hop raw chain.

        For a single hop (N=1), generates (n_pur + 1) copies, purifies
        them via a YY pumping sequence at the end node, then heralds and
        corrects.

        For N > 1, builds raw single-hop edges for all hops and applies
        (n_pur + 1) copies with YY pumping only on hop 0 as a demonstration.

        Parameters
        ----------
        N : int
            Number of hops.
        n_pur : int
            Number of additional copies for end-node YY purification (≥ 1).
        gen_time : float
            Simulation timestamp for all Gen nodes.
        """
        if N != 1:
            raise NotImplementedError(
                "single_hop_yy_purified currently only supports N=1. "
                "Use ScheduleDAG.raw_chain for multi-hop raw schedules."
            )

        nodes: dict[NodeId, ScheduleNode] = {}
        nid = 0

        def make_single_hop_edge(hop_i: int) -> NodeId:
            nonlocal nid
            g_l = GenNode(node_id=nid, hop_index=hop_i, gen_time=gen_time)
            nid += 1
            g_r = GenNode(node_id=nid, hop_index=hop_i, gen_time=gen_time)
            nid += 1
            nodes[g_l.node_id] = g_l
            nodes[g_r.node_id] = g_r
            bsm = AbsaBsmNode(
                node_id=nid,
                children=(g_l.node_id, g_r.node_id),
                hop_index=hop_i,
            )
            nid += 1
            nodes[bsm.node_id] = bsm
            return bsm.node_id

        # Build (n_pur + 1) independent single-hop edges
        edge_ids = [make_single_hop_edge(0) for _ in range(n_pur + 1)]

        # YY pumping sequence: purify edge_ids[0] with each successive copy
        current_id = edge_ids[0]
        for extra_id in edge_ids[1:]:
            pur = PurifyNode(
                node_id=nid,
                children=(current_id, extra_id),
                circuit=PurificationCircuit.YY,
                output_stage=Span(0, 1),
            )
            nid += 1
            nodes[pur.node_id] = pur
            current_id = pur.node_id

        # Herald + PauliCorrect
        herald_node = HeraldNode(
            node_id=nid,
            children=(current_id,),
            propagation_time=0.0,
        )
        nid += 1
        nodes[herald_node.node_id] = herald_node

        root = PauliCorrectNode(
            node_id=nid,
            children=(herald_node.node_id,),
            N=N,
        )
        nodes[root.node_id] = root

        return cls(nodes=nodes, root_id=root.node_id, N=N)
