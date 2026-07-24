"""
hrgs_scheduler.schedule.visualize
====================================
Graphical export/visualization of a ScheduleDAG (Σ = (T, φ)).

Produces Graphviz DOT source with node color/shape coded by node type,
so the structure of a schedule (Gen/Join/AbsaBsm/Purify/Idle/Herald/
PauliCorrect, §2.5/§3.2/§3.3 of [Validated Formal Model Def]) can be
inspected visually.

No hard dependency on the ``graphviz`` PyPI package or a system Graphviz
install is required to *generate* DOT text (``to_dot`` is pure stdlib).
Rendering to an image (``render``) shells out to the ``dot`` CLI if
present on PATH, and raises a clear error otherwise.

Node style legend
------------------
    GenNode            light blue  ellipse   (leaf)
    AbsaBsmNode        orange      box
    JoinNode           green       box
    PurifyNode         purple      box        (label includes circuit)
    IdleNode           gray        box, dashed
    HeraldNode         yellow      diamond
    PauliCorrectNode   red         doublecircle (root)

Edges are drawn child -> parent, i.e. in the direction of data flow
from Gen leaves up to the PauliCorrect root, matching the DAG's own
``children`` convention (a node's children are its inputs).

Usage
-----
    from hrgs_scheduler.schedule.visualize import to_dot, save_dot, render

    dot_src = to_dot(dag)
    save_dot(dag, "schedule.dot")
    render(dag, "schedule.svg")               # requires Graphviz `dot` on PATH
    render(dag, "schedule.png", fmt="png")

Annotating with evaluation results
-----------------------------------
Pass an ``EvaluationResult`` (from ``schedule.evaluator.Evaluator``) to
annotate each node's label with its fidelity and current_time:

    result = Evaluator(network).evaluate(dag)
    to_dot(dag, result=result)

Highlighting a pumping move
----------------------------
``to_dot``'s ``highlight_groups`` parameter wraps chosen node subsets in
labeled, colored cluster subgraphs on top of the normal type-based
color/shape coding, used to make a pumping move's two independent
copies visually obvious as distinct subtrees converging into one
``Purify-*`` node (see ``experiments/visualize_pumping_schedule.py``).

Purification chain depth
--------------------------
``purification_chain_depth``/``deepest_purification_chain`` compute the
longest run of directly-chained ``Purify-*`` nodes in a DAG (how many
purification rounds stack before hitting a Gen/Join boundary), read
directly from the DAG's node/edge structure, NOT from any node's
human-readable label text.
"""

from __future__ import annotations

import html
import shutil
import subprocess
from typing import TYPE_CHECKING, Optional

from hrgs_scheduler.models.stage import RGSSStage, Span
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

if TYPE_CHECKING:
    from hrgs_scheduler.schedule.dag import ScheduleDAG
    from hrgs_scheduler.schedule.evaluator import EvaluationResult

# ---------------------------------------------------------------------------
# Style table: one entry per node type.
# (fillcolor, shape, style), fed directly into DOT node attributes.
# ---------------------------------------------------------------------------

_NODE_STYLE: dict[type, tuple[str, str, str]] = {
    GenNode: ("#AED6F1", "ellipse", "filled"),
    AbsaBsmNode: ("#F5B041", "box", "filled"),
    JoinNode: ("#82E0AA", "box", "filled"),
    PurifyNode: ("#C39BD3", "box", "filled"),
    IdleNode: ("#D5D8DC", "box", "filled,dashed"),
    HeraldNode: ("#F7DC6F", "diamond", "filled"),
    PauliCorrectNode: ("#F1948A", "doublecircle", "filled"),
}

_DEFAULT_STYLE = ("#FFFFFF", "box", "filled")


def _stage_label(stage: object) -> str:
    """Short, human-readable label for a stage/κ value (or ``None``)."""
    if stage is None:
        return ""
    if isinstance(stage, RGSSStage):
        return "RGSS"
    if isinstance(stage, Span):
        return f"({stage.a},{stage.b})"
    return str(stage)


def _node_label(node: ScheduleNode, nid: NodeId) -> str:
    """Build the multi-line label text for a single node."""
    lines = [f"#{nid} {type(node).__name__}"]

    if isinstance(node, GenNode):
        lines.append(f"hop={node.hop_index}  t={node.gen_time:g}")
        lines.append(f"s_gen={node.side_effect_parity}")
    elif isinstance(node, AbsaBsmNode):
        lines.append(f"hop={node.hop_index}")
        lines.append(f"\u03ba={_stage_label(node.output_stage)}")
    elif isinstance(node, JoinNode):
        lines.append(f"\u03ba={_stage_label(node.output_stage)}")
    elif isinstance(node, PurifyNode):
        lines.append(f"circuit={node.circuit.name}")
        lines.append(f"\u03ba={_stage_label(node.output_stage)}")
    elif isinstance(node, IdleNode):
        lines.append(f"until={node.until:g}")
    elif isinstance(node, HeraldNode):
        lines.append(f"prop_t={node.propagation_time:g}\u00d7(L/c)")
    elif isinstance(node, PauliCorrectNode):
        lines.append(f"\u03ba=(0,{node.N})  [root]")

    return "\\n".join(lines)


def _result_annotation(nid: NodeId, result: Optional["EvaluationResult"]) -> str:
    """Extra label lines from an EvaluationResult's per-node State cache."""
    if result is None:
        return ""
    state = result.node_states.get(nid)
    if state is None:
        return ""
    return f"\\nF={state.fidelity:.4f}  t={state.current_time:.3g}"


def to_dot(
    dag: "ScheduleDAG",
    *,
    result: Optional["EvaluationResult"] = None,
    graph_name: str = "Sigma",
    rankdir: str = "BT",
    highlight_groups: Optional[dict[str, tuple[set[NodeId], str]]] = None,
    annotate_nodes: Optional[set[NodeId]] = None,
) -> str:
    """Render *dag* to Graphviz DOT source.

    Parameters
    ----------
    dag : ScheduleDAG
        The schedule to visualize.
    result : EvaluationResult, optional
        If provided, annotates each node's label with its evaluated
        fidelity and current_time (from ``result.node_states``).
    graph_name : str
        DOT graph name (must be a valid DOT identifier).
    rankdir : str
        Graphviz ``rankdir`` (``"BT"`` by default, bottom-to-top, leaves at the
        bottom / root at top, matching data flow). Use
        ``"TB"``, ``"LR"``, or ``"RL"`` for alternate layouts.
    highlight_groups : dict[str, (set[NodeId], str)], optional
        Extra visual grouping layered on top of the normal per-node-type
        color/shape coding; for example, to make a pumping move's two
        independent copies visually obvious as distinct subtrees
        converging into one ``Purify-*`` node. Maps a group label
        (used as the cluster's DOT ``label``) to ``(node_ids, color)``.
        Each group is drawn as a dashed Graphviz cluster subgraph in
        *color*, and its member nodes get a matching colored border.
        Groups must be disjoint; nodes not in any group render exactly
        as they would without this parameter.
    annotate_nodes : set[NodeId], optional
        When *result* is provided, limit fidelity/time annotations to
        only the node ids in this set.  ``None`` (default) annotates
        every node; an empty set suppresses all annotations even when
        *result* is supplied.  Useful for keeping large DAGs readable
        while still showing the root's quality metrics.

    Returns
    -------
    str
        Complete DOT source, ready to write to a ``.dot`` file or feed
        to ``dot -Tsvg``.
    """
    highlight_groups = highlight_groups or {}
    node_to_group: dict[NodeId, tuple[str, str]] = {}
    for group_label, (node_ids, color) in highlight_groups.items():
        for nid in node_ids:
            node_to_group[nid] = (group_label, color)

    lines: list[str] = [
        f"digraph {graph_name} {{",
        f'    rankdir="{rankdir}";',
        '    node [fontname="Helvetica", fontsize=10];',
        '    edge [fontname="Helvetica", fontsize=9, color="#555555"];',
    ]

    def _node_decl(nid: NodeId, node: ScheduleNode) -> str:
        fillcolor, shape, style = _NODE_STYLE.get(type(node), _DEFAULT_STYLE)
        _eff_result = (
            result
            if result is not None and (annotate_nodes is None or nid in annotate_nodes)
            else None
        )
        label = _node_label(node, nid) + _result_annotation(nid, _eff_result)
        label_escaped = html.escape(label).replace("\\n", "<BR/>")
        penwidth = "3" if nid == dag.root_id else "1"
        border = ""
        group = node_to_group.get(nid)
        if group is not None:
            _, color = group
            penwidth = "4"
            border = f', color="{color}"'
        return (
            f"    n{nid} [label=<{label_escaped}>, shape={shape}, "
            f'style="{style}", fillcolor="{fillcolor}", penwidth={penwidth}{border}];'
        )

    # Nodes belonging to a highlight group are wrapped in a dashed cluster
    # subgraph (with a legend label) so the grouping is visible even before
    # reading individual node borders.
    grouped_ids: set[NodeId] = set(node_to_group)
    for i, (group_label, (node_ids, color)) in enumerate(highlight_groups.items()):
        present = [nid for nid in node_ids if nid in dag.nodes]
        if not present:
            continue
        lines.append(f"    subgraph cluster_{i} {{")
        lines.append(f'        label="{html.escape(group_label)}";')
        lines.append('        style="dashed";')
        lines.append(f'        color="{color}";')
        lines.append('        fontname="Helvetica"; fontsize=11;')
        for nid in present:
            lines.append("        " + _node_decl(nid, dag.nodes[nid]))
        lines.append("    }")

    for nid, node in dag.nodes.items():
        if nid in grouped_ids:
            continue
        lines.append(_node_decl(nid, node))

    for nid, node in dag.nodes.items():
        children = getattr(node, "children", ())
        for child_id in children:
            lines.append(f"    n{child_id} -> n{nid};")

    lines.append("}")
    return "\n".join(lines)


def save_dot(
    dag: "ScheduleDAG",
    path: str,
    *,
    result: Optional["EvaluationResult"] = None,
    graph_name: str = "Sigma",
    rankdir: str = "BT",
) -> None:
    """Write *dag*'s DOT source to *path*.

    Thin wrapper around ``to_dot`` that also writes the file to disk.
    """
    dot_src = to_dot(dag, result=result, graph_name=graph_name, rankdir=rankdir)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dot_src)


def render(
    dag: "ScheduleDAG",
    path: str,
    *,
    fmt: Optional[str] = None,
    result: Optional["EvaluationResult"] = None,
    graph_name: str = "Sigma",
    rankdir: str = "BT",
    engine: str = "dot",
) -> None:
    """Render *dag* directly to an image file via the Graphviz ``dot`` CLI.

    Parameters
    ----------
    dag : ScheduleDAG
        The schedule to visualize.
    path : str
        Output file path (e.g. ``"schedule.svg"``, ``"schedule.png"``).
    fmt : str, optional
        Graphviz output format (``"svg"``, ``"png"``, ``"pdf"``, ...).
        If omitted, inferred from *path*'s file extension.
    result : EvaluationResult, optional
        See ``to_dot``.
    graph_name : str
        See ``to_dot``.
    rankdir : str
        See ``to_dot``.
    engine : str
        Graphviz layout engine to invoke (``"dot"``, ``"neato"``, ...).

    Raises
    ------
    RuntimeError
        If the requested Graphviz *engine* executable is not found on
        PATH. Install Graphviz (e.g. ``apt install graphviz`` or
        ``brew install graphviz``) to enable rendering, or use
        ``save_dot``/``to_dot`` and render the ``.dot`` file elsewhere
        (e.g. https://dreampuf.github.io/GraphvizOnline/).
    subprocess.CalledProcessError
        If the Graphviz process itself fails (e.g. malformed DOT).
    """
    if shutil.which(engine) is None:
        raise RuntimeError(
            f"Graphviz executable '{engine}' not found on PATH. Install "
            "Graphviz (e.g. `apt install graphviz` / `brew install "
            "graphviz`) to render images, or use `save_dot`/`to_dot` and "
            "render the .dot file with an external tool/viewer."
        )

    if fmt is None:
        fmt = path.rsplit(".", 1)[-1] if "." in path else "svg"

    dot_src = to_dot(dag, result=result, graph_name=graph_name, rankdir=rankdir)
    proc = subprocess.run(
        [engine, f"-T{fmt}", "-o", path],
        input=dot_src.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
        )


# ---------------------------------------------------------------------------
# Purification chain depth
# ---------------------------------------------------------------------------
#
# "Chain depth" = the longest run of directly-chained PurifyNodes, i.e. how
# many purification rounds stack on top of each other (each consuming the
# previous round's output plus one fresh independent copy) before hitting a
# Gen/Join boundary. Computed purely from (T, φ) structure, via a node's
# `children`, never from label text, per
# docs/Handoff_Timing_and_Pumping_Visualization.md §2.1.


def _purify_depths(dag: "ScheduleDAG") -> dict[NodeId, int]:
    """Per-PurifyNode chain depth, memoized bottom-up over *dag*.nodes.

    depth(p) = 1 + max(depth(c) for c in p.children if c is a PurifyNode,
    default 0). Non-PurifyNode nodes have no entry (they are chain
    boundaries, not chain members).
    """
    depths: dict[NodeId, int] = {}

    def _depth(nid: NodeId) -> int:
        if nid in depths:
            return depths[nid]
        node = dag.nodes[nid]
        if not isinstance(node, PurifyNode):
            return 0
        best_child = 0
        for child_id in node.children:
            child = dag.nodes[child_id]
            if isinstance(child, PurifyNode):
                best_child = max(best_child, _depth(child_id))
        depths[nid] = 1 + best_child
        return depths[nid]

    for nid, node in dag.nodes.items():
        if isinstance(node, PurifyNode):
            _depth(nid)
    return depths


def purification_chain_depth(dag: "ScheduleDAG") -> int:
    """Longest run of directly-chained ``Purify-*`` nodes in *dag*.

    Returns 0 if *dag* contains no PurifyNode at all.
    """
    depths = _purify_depths(dag)
    return max(depths.values(), default=0)


def _reachable(dag: "ScheduleDAG", root_id: NodeId) -> set[NodeId]:
    """All node ids reachable from *root_id* (inclusive), via `children`."""
    keep: set[NodeId] = set()
    stack = [root_id]
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        keep.add(nid)
        stack.extend(getattr(dag.nodes[nid], "children", ()))
    return keep


def deepest_purification_chain(dag: "ScheduleDAG") -> list[NodeId]:
    """The node-id path of *dag*'s deepest purification chain.

    Returns a list of PurifyNode ids ``[top, ..., bottom]`` where ``top``
    is the shallowest (closest-to-root) PurifyNode achieving
    ``purification_chain_depth(dag)``, and each subsequent entry is
    whichever child continues the chain (the other child at each round is
    a "fresh" branch feeding into that round's pumping move, not part of
    the chain itself). Empty list if *dag* has no PurifyNode.
    """
    depths = _purify_depths(dag)
    if not depths:
        return []
    max_depth = max(depths.values())
    top = max(nid for nid, d in depths.items() if d == max_depth)

    chain = [top]
    current = top
    while depths[current] > 1:
        node = dag.nodes[current]
        assert isinstance(node, PurifyNode)
        next_id = None
        for child_id in node.children:
            child = dag.nodes[child_id]
            if (
                isinstance(child, PurifyNode)
                and depths.get(child_id) == depths[current] - 1
            ):
                next_id = child_id
                break
        assert next_id is not None, "chain depth accounting inconsistency"
        chain.append(next_id)
        current = next_id
    return chain


def pumping_highlight_groups(
    dag: "ScheduleDAG",
    chain: list[NodeId],
    *,
    chain_color: str = "#1F618D",
    fresh_color: str = "#B03A2E",
) -> dict[str, tuple[set[NodeId], str]]:
    """Build ``to_dot(..., highlight_groups=...)`` groups for *chain*.

    For every PurifyNode in *chain*, its "fresh" child (the one NOT
    continuing the chain) is grouped as an independent copy pumped in at
    that round, in *fresh_color*. The chain's own PurifyNodes are grouped
    together in *chain_color*, so the DAG rendering makes each pumping
    move's two converging copies: "accumulated chain so far" vs. "this
    round's fresh copy", visually obvious.
    """
    groups: dict[str, tuple[set[NodeId], str]] = {}
    if chain:
        groups[f"Purification chain (depth={len(chain)})"] = (set(chain), chain_color)

    chain_set = set(chain)
    for i, purify_id in enumerate(chain):
        node = dag.nodes[purify_id]
        assert isinstance(node, PurifyNode)
        # "Accumulated" child is either a PurifyNode in chain_set (optimistic
        # chaining) OR a HeraldNode (heralded pumping: each round separated by
        # a round-trip Herald, so the chain depth is 1 but the accumulated side
        # is the Herald that wraps the previous round's output).  The "fresh"
        # child is the one that is neither in the chain nor a HeraldNode.
        fresh_child = next(
            (
                c
                for c in node.children
                if c not in chain_set and not isinstance(dag.nodes[c], HeraldNode)
            ),
            None,
        )
        if fresh_child is None:
            continue
        subtree = _reachable(dag, fresh_child) - chain_set
        if subtree:
            groups[f"Fresh copy, round {i + 1}"] = (subtree, fresh_color)
    return groups
