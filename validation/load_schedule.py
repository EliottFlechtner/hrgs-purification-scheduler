"""
validation/load_schedule.py
==============================
Load a saved schedule artifact (written by ``--save-top`` or
``search.save_result``) and inspect, verify, or visualize it.

Quick start
-----------
    # Print a summary of a saved schedule
    python validation/load_schedule.py outputs/schedules/rank_001_<label>.json

    # Re-evaluate (re-runs the evaluator and checks against stored metrics)
    python validation/load_schedule.py outputs/schedules/rank_001_<label>.json --verify

    # Render the schedule DAG to an SVG (requires Graphviz)
    python validation/load_schedule.py outputs/schedules/rank_001_<label>.json \\
        --render outputs/schedules/rank_001.svg

    # Annotate the render with per-node fidelity / time values
    python validation/load_schedule.py outputs/schedules/rank_001_<label>.json \\
        --render outputs/schedules/rank_001_annotated.svg --annotate

    # Save the DOT source (no Graphviz needed)
    python validation/load_schedule.py outputs/schedules/rank_001_<label>.json \\
        --dot outputs/schedules/rank_001.dot

CLI flags
---------
    FILE                Path of a .json schedule artifact (required positional arg).
    --verify            Re-evaluate the loaded DAG against the stored network and
                        print a diff between the stored metrics and the recomputed
                        ones.  Exits with code 1 if any metric differs by > 1e-9.
    --render PATH       Render the schedule DAG to an image file (SVG/PNG/PDF).
                        Format is inferred from the file extension.  Requires the
                        Graphviz `dot` command on PATH.
    --annotate          When used with --render, annotate each node with its
                        evaluated fidelity and time (re-evaluates the DAG
                        automatically).
    --dot PATH          Write Graphviz DOT source to this path (does NOT require
                        `dot` to be installed).
    --print-nodes       Print a summary of all node types and their counts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.serde import load_schedule
from hrgs_scheduler.schedule.visualize import render, save_dot, to_dot
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    IdleNode,
    JoinNode,
    PauliCorrectNode,
    PurifyNode,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Load and inspect a saved schedule artifact.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("file", type=Path, help="Path to a .json schedule artifact")
    p.add_argument(
        "--verify",
        action="store_true",
        help="Re-evaluate the DAG and check against stored metrics",
    )
    p.add_argument(
        "--render",
        type=Path,
        default=None,
        dest="render_path",
        help="Render the DAG to an image (SVG/PNG/PDF)",
    )
    p.add_argument(
        "--annotate",
        action="store_true",
        help="Annotate render with per-node fidelity/time (re-evaluates automatically)",
    )
    p.add_argument(
        "--dot",
        type=Path,
        default=None,
        dest="dot_path",
        help="Write Graphviz DOT source to this file",
    )
    p.add_argument(
        "--print-nodes",
        action="store_true",
        dest="print_nodes",
        help="Print a count of each node type in the DAG",
    )
    return p


_NODE_TYPE_NAMES = {
    GenNode: "GenNode",
    AbsaBsmNode: "AbsaBsmNode",
    JoinNode: "JoinNode",
    PurifyNode: "PurifyNode",
    IdleNode: "IdleNode",
    HeraldNode: "HeraldNode",
    PauliCorrectNode: "PauliCorrectNode",
}


def _node_counts(dag) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in dag.nodes.values():
        name = _NODE_TYPE_NAMES.get(type(node), type(node).__name__)
        counts[name] = counts.get(name, 0) + 1
    return counts


def main() -> int:
    args = _build_parser().parse_args()
    path: Path = args.file

    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    dag, network, meta = load_schedule(path)

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    label = meta["label"] or "(no label)"
    score = meta["score"]
    ev = meta["eval"]

    print(f"Schedule: {label}")
    print(f"  File:          {path.resolve()}")
    print(f"  Nodes:         {len(dag.nodes)}  (root_id={dag.root_id}, N={dag.N})")
    print(
        f"  Network:       N={network.N}, e_d={network.e_d}, "
        f"total_length={network.total_length():.1f} km, c={network.c:.3g} km/s"
    )
    print(f"  Score:         {score!r}")
    if ev:
        f_str = f"{ev['fidelity']:.6f}" if ev.get("fidelity") is not None else "N/A"
        r_str = f"{ev['rate']:.4g}" if ev.get("rate") is not None else "N/A"
        c_str = str(ev.get("resource_cost", "N/A"))
        l_str = (
            f"{ev['latency_s']*1e3:.4f} ms"
            if ev.get("latency_s") is not None
            else "N/A"
        )
        p_str = (
            f"{ev['success_prob']:.4f}" if ev.get("success_prob") is not None else "N/A"
        )
        print(f"  Stored eval:   F={f_str}  R={r_str}  C={c_str}  L={l_str}  P={p_str}")

    # ------------------------------------------------------------------ #
    # Node counts
    # ------------------------------------------------------------------ #
    if args.print_nodes:
        print("\nNode type counts:")
        for name, count in sorted(_node_counts(dag).items()):
            print(f"  {name:<22} {count}")

    # ------------------------------------------------------------------ #
    # Verify: re-evaluate and compare
    # ------------------------------------------------------------------ #
    recomputed = None
    if args.verify or args.annotate or args.render_path:
        evaluator = Evaluator(network)
        recomputed = evaluator.evaluate(dag)

    if args.verify:
        stored = meta["eval"]
        ok = True
        print("\nVerification (re-evaluated vs. stored):")
        pairs = [
            ("fidelity", recomputed.fidelity, stored.get("fidelity")),
            ("rate", recomputed.rate, stored.get("rate")),
            ("resource_cost", recomputed.resource_cost, stored.get("resource_cost")),
            ("latency_s", recomputed.latency, stored.get("latency_s")),
            ("success_prob", recomputed.success_prob, stored.get("success_prob")),
        ]
        for field, got, want in pairs:
            if want is None:
                print(f"  {field:<16}  {got!r:>22}  (not stored)")
                continue
            diff = abs(float(got) - float(want))
            status = "OK" if diff < 1e-9 else f"MISMATCH  Δ={diff:.3e}"
            print(f"  {field:<16}  {got!r:>22}  stored={want!r}  {status}")
            if diff >= 1e-9:
                ok = False
        if ok:
            print("\nAll metrics match within 1e-9.")
        else:
            print(
                "\nVerification FAILED — stored metrics differ from re-evaluation.",
                file=sys.stderr,
            )
            return 1

    # ------------------------------------------------------------------ #
    # DOT export
    # ------------------------------------------------------------------ #
    if args.dot_path:
        result_for_dot = recomputed if args.annotate else None
        dot_src = to_dot(dag, result=result_for_dot)
        args.dot_path.parent.mkdir(parents=True, exist_ok=True)
        args.dot_path.write_text(dot_src, encoding="utf-8")
        print(f"\nDOT written → {args.dot_path.resolve()}")

    # ------------------------------------------------------------------ #
    # Image render
    # ------------------------------------------------------------------ #
    if args.render_path:
        if recomputed is None:
            evaluator = Evaluator(network)
            recomputed = evaluator.evaluate(dag)
        result_for_render = recomputed if args.annotate else None
        try:
            render(dag, str(args.render_path), result=result_for_render)
            print(f"\nRendered → {args.render_path.resolve()}")
        except RuntimeError as exc:
            print(f"\nRender failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
