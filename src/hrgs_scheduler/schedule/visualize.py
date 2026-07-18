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
# (fillcolor, shape, style) — fed directly into DOT node attributes.
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
        Graphviz ``rankdir`` — ``"BT"`` (bottom-to-top, leaves at the
        bottom / root at top, matching data flow) by default. Use
        ``"TB"``, ``"LR"``, or ``"RL"`` for alternate layouts.

    Returns
    -------
    str
        Complete DOT source, ready to write to a ``.dot`` file or feed
        to ``dot -Tsvg``.
    """
    lines: list[str] = [
        f"digraph {graph_name} {{",
        f'    rankdir="{rankdir}";',
        '    node [fontname="Helvetica", fontsize=10];',
        '    edge [fontname="Helvetica", fontsize=9, color="#555555"];',
    ]

    # Highlight the root with a bold border in addition to its base style.
    for nid, node in dag.nodes.items():
        fillcolor, shape, style = _NODE_STYLE.get(type(node), _DEFAULT_STYLE)
        label = _node_label(node, nid) + _result_annotation(nid, result)
        label_escaped = html.escape(label).replace("\\n", "<BR/>")
        penwidth = "3" if nid == dag.root_id else "1"
        lines.append(
            f"    n{nid} [label=<{label_escaped}>, shape={shape}, "
            f'style="{style}", fillcolor="{fillcolor}", penwidth={penwidth}];'
        )

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
