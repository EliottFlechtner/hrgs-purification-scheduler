"""
experiments/visualize_pumping_schedule.py
===========================================
docs/Handoff_Timing_and_Pumping_Visualization.md, Part 2: find and render
a real search-found schedule that uses pumping with a deeper
purification chain than the shallow one-or-two-round chains already
seen from the fixed builders (`flexible_paper_schedule` chains 2 rounds;
`baseline_end_node_pumping` chains 1 -- its rounds are Herald-separated,
so they never form a single unbroken Purify-* chain by this metric; see
`hrgs_scheduler.schedule.visualize`'s module docstring).

"Purification chain depth" (`purification_chain_depth`, in
`schedule/visualize.py`) is computed directly from the DAG's node/edge
structure (walking only through PurifyNode `children`), never from any
node's label text.

Selection (docs §2.1)
----------------------
Runs `beam_search` (pumping enabled, default settings) at a small
handful of small-N configs chosen to plausibly favor deeper purification
chains: N in {3, 4}, e_d on the higher end of the paper's own tested
range ([0, 0.01], see `sweep_ed.py`), and a stricter fidelity floor
(0.95-0.98) than the usual 0.9 default -- a stricter floor is more
likely to force multiple purification rounds to stack. This is a small,
bounded set of configs (5), not a full sweep.

Rendering (docs §2.2)
-----------------------
Reuses the existing DAG-visualization conventions
(`schedule.visualize.to_dot`/`render`, per-node-type color/shape coding)
rather than inventing a new, inconsistent legend. The pumping structure
itself is made visually explicit via `to_dot`'s `highlight_groups`
parameter: the deepest chain's own Purify-* nodes are boxed in one
color, and each round's "fresh" independent copy (the child NOT
continuing the chain) is boxed in a second color -- so every pumping
move along the chain is visually obvious as two subtrees converging
into one Purify-* node, not just the outermost one.

Outputs
-------
    outputs/pumping_schedule_example/schedule.dot
    outputs/pumping_schedule_example/schedule.svg   (if Graphviz `dot` is on PATH)
    outputs/pumping_schedule_example/README.md

Usage
-----
    PYTHONPATH=src python3 experiments/visualize_pumping_schedule.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.visualize import (
    deepest_purification_chain,
    purification_chain_depth,
    pumping_highlight_groups,
    to_dot,
)
from hrgs_scheduler.search import beam_search

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "pumping_schedule_example"

# Already-seen baselines (from the fixed DAG builders), for context in the
# README -- NOT from label text, computed the same way as everything else.
_BASELINE_DEPTHS = {
    "flexible_paper_schedule(N=4)": purification_chain_depth(
        ScheduleDAG.flexible_paper_schedule(N=4)
    ),
    "baseline_end_node_pumping(N=4, n_pur=5)": purification_chain_depth(
        ScheduleDAG.baseline_end_node_pumping(4, n_pur=5)
    ),
}


@dataclass
class ConfigResult:
    n: int
    e_d: float
    f_min: float
    label: str
    chain_depth: int
    score: float
    fidelity: float
    rate: float
    resource_cost: int
    dag: ScheduleDAG


# Small, bounded set of configs plausibly favoring deeper purification
# chains: small N, higher-end e_d, stricter fidelity floor.
CONFIGS: list[tuple[int, float, float]] = [
    (3, 0.008, 0.95),
    (3, 0.010, 0.98),
    (4, 0.008, 0.95),
    (4, 0.010, 0.98),
    (4, 0.010, 0.95),
]


def _build_network(n: int, e_d: float) -> NetworkConfig:
    return NetworkConfig.uniform(
        N=n,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        e_d=e_d,
        gamma=0.0,
        c=2e5,
    )


def run_configs() -> list[ConfigResult]:
    out: list[ConfigResult] = []
    for n, e_d, f_min in CONFIGS:
        net = _build_network(n, e_d)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=f_min)
        e_max = 10 * n
        results = beam_search(net, obj, e_max=e_max)
        best = results[0]
        depth = purification_chain_depth(best.dag)
        print(
            f"N={n} e_d={e_d} f_min={f_min}: label={best.label} "
            f"chain_depth={depth} score={best.score:.6g} "
            f"F={best.eval_result.fidelity:.4f} R={best.eval_result.rate:.4g}",
            flush=True,
        )
        out.append(
            ConfigResult(
                n=n,
                e_d=e_d,
                f_min=f_min,
                label=best.label,
                chain_depth=depth,
                score=best.score,
                fidelity=best.eval_result.fidelity,
                rate=best.eval_result.rate,
                resource_cost=best.eval_result.resource_cost,
                dag=best.dag,
            )
        )
    return out


def render_winner(winner: ConfigResult) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    net = _build_network(winner.n, winner.e_d)
    result = Evaluator(net).evaluate(winner.dag)

    chain = deepest_purification_chain(winner.dag)
    groups = pumping_highlight_groups(winner.dag, chain)

    dot_src = to_dot(winner.dag, result=result, highlight_groups=groups)
    dot_path = OUTPUT_DIR / "schedule.dot"
    dot_path.write_text(dot_src, encoding="utf-8")
    print(f"wrote {dot_path}", flush=True)

    rendered: dict = {"dot": dot_path, "svg": None, "png": None}
    import shutil
    import subprocess

    if shutil.which("dot") is None:
        print("(rendering skipped: Graphviz `dot` not found on PATH)", flush=True)
        return rendered

    for fmt in ("svg", "png"):
        out_path = OUTPUT_DIR / f"schedule.{fmt}"
        proc = subprocess.run(
            ["dot", f"-T{fmt}", "-o", str(out_path)],
            input=dot_src.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            rendered[fmt] = out_path
            print(f"wrote {out_path}", flush=True)
        else:
            print(
                f"(rendering to {fmt} failed: {proc.stderr.decode('utf-8', 'replace')})",
                flush=True,
            )

    return rendered


def write_readme(
    all_results: list[ConfigResult], winner: ConfigResult, rendered: dict
) -> None:
    lines = [
        "# Pumping schedule example: deepest purification chain found",
        "",
        "docs/Handoff_Timing_and_Pumping_Visualization.md, Part 2.",
        "",
        "## Already-seen baselines (fixed builders, for context)",
        "",
    ]
    for name, depth in _BASELINE_DEPTHS.items():
        lines.append(f"- `{name}`: chain depth = {depth}")
    lines += [
        "",
        "## Configs tried (beam_search, pumping enabled, default settings)",
        "",
        "| N | e_d | f_min | label | chain depth | score | F | R | cost |",
        "|---|-----|-------|-------|--------------|-------|---|---|------|",
    ]
    for r in all_results:
        marker = " **<- selected**" if r is winner else ""
        lines.append(
            f"| {r.n} | {r.e_d:.3f} | {r.f_min:.2f} | {r.label} | {r.chain_depth}{marker} | "
            f"{r.score:.6g} | {r.fidelity:.4f} | {r.rate:.4g} | {r.resource_cost} |"
        )

    max_baseline = max(_BASELINE_DEPTHS.values(), default=0)
    lines += ["", "## Result", ""]
    if winner.chain_depth > max_baseline:
        lines.append(
            f"Deepest chain found: **{winner.chain_depth}** rounds, at N={winner.n}, "
            f"e_d={winner.e_d:.3f}, f_min={winner.f_min:.2f} (label `{winner.label}`) "
            f"-- deeper than the already-seen baselines (max depth {max_baseline})."
        )
    else:
        lines.append(
            f"Deepest chain found across these 5 configs: **{winner.chain_depth}**, at N={winner.n}, "
            f"e_d={winner.e_d:.3f}, f_min={winner.f_min:.2f} (label `{winner.label}`). This is "
            f"NOT deeper than the already-seen baselines (max depth {max_baseline}) -- reported "
            "plainly, per the handoff's instruction, rather than searching further unprompted."
        )
    lines += [
        "",
        f"- Score: {winner.score:.6g}",
        f"- Fidelity F: {winner.fidelity:.4f}",
        f"- Rate R: {winner.rate:.4g}",
        f"- Resource cost C (Gen-node count): {winner.resource_cost}",
        "",
        "## Visualization",
        "",
        f"- DOT source: `{rendered['dot'].name}`",
    ]
    if rendered.get("svg") is not None:
        lines.append(f"- Rendered SVG: `{rendered['svg'].name}`")
    if rendered.get("png") is not None:
        lines.append(f"- Rendered PNG: `{rendered['png'].name}`")
    if rendered.get("svg") is None and rendered.get("png") is None:
        lines.append(
            "- Graphviz `dot` was not found on PATH; only the `.dot` source was written. "
            "Render it externally (e.g. https://dreampuf.github.io/GraphvizOnline/) or "
            "install Graphviz (`apt install graphviz`) and re-run this script."
        )
    lines += [
        "",
        "The rendering reuses the existing per-node-type color/shape convention "
        "(`schedule.visualize.to_dot`). The two independent copies converging into each "
        "Purify-* node along the deepest chain are additionally boxed in labeled clusters: "
        "the chain's own Purify-* nodes in one color, and each round's freshly-generated "
        "independent copy in a second color -- making every pumping move along the chain "
        "visually distinguishable from an ordinary split/join.",
        "",
    ]
    path = OUTPUT_DIR / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}", flush=True)


def main() -> None:
    all_results = run_configs()
    winner = max(all_results, key=lambda r: r.chain_depth)
    print(
        f"selected: N={winner.n} e_d={winner.e_d} f_min={winner.f_min} depth={winner.chain_depth}",
        flush=True,
    )
    rendered = render_winner(winner)
    write_readme(all_results, winner, rendered)


if __name__ == "__main__":
    main()
