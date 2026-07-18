"""
desktop_app.controller
========================
Tk-free logic layer for the desktop UI.

Wraps ``hrgs_scheduler``'s network/objective configuration, brute-force and
DP search, schedule persistence (save/load), verification, and Graphviz
rendering behind a small set of plain functions that the Tkinter view
(``app.py``) calls into. Keeping this module free of any ``tkinter`` import
means it can be exercised directly by any interpreter (including the one
used to run the project's test suite), independent of whether that
interpreter has Tk bindings available.

Import strategy
----------------
Following the convention already used by the ``validation/`` scripts in
this repository, the project's ``src/`` directory is inserted at the front
of ``sys.path`` rather than requiring ``hrgs_scheduler`` to be pip-installed
into whichever interpreter runs the desktop app. This keeps the desktop app
a self-contained sibling project that simply *reuses* the core package.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hrgs_scheduler.cost_functions import ObjectiveConfig  # noqa: E402
from hrgs_scheduler.models.network_config import NetworkConfig  # noqa: E402
from hrgs_scheduler.schedule.dag import ScheduleDAG  # noqa: E402
from hrgs_scheduler.schedule.evaluator import EvaluationResult, Evaluator  # noqa: E402
from hrgs_scheduler.schedule.visualize import render as _render_dag  # noqa: E402
from hrgs_scheduler.schedule.visualize import to_dot as _to_dot  # noqa: E402
from hrgs_scheduler.search import (  # noqa: E402
    SearchResult,
    brute_force_search,
    dp_search,
    load_result,
    save_result,
    save_top,
    to_csv,
    to_json,
)

NETWORK_KINDS = ("uniform", "paper")
OBJECTIVE_KINDS = ("rate", "fidelity")
ALGORITHMS = ("brute_force", "dp")

DEFAULT_SAVE_DIR = PROJECT_ROOT / "outputs" / "schedules"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "outputs" / "search"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "reproduction_figures"


# ---------------------------------------------------------------------------
# Network / objective construction
# ---------------------------------------------------------------------------


def build_network(
    kind: str,
    *,
    N: int = 10,
    e_d: float = 0.0,
    length: float = 2.0,
    gamma: float = 0.0,
    c: float = 2e5,
    branching: Sequence[int] = (16, 14, 1),
    arm_count: int = 18,
    p_x_inner: float = 0.0,
    p_z_inner: float = 0.0,
) -> NetworkConfig:
    """Build a :class:`NetworkConfig` from simple scalar parameters.

    ``kind='paper'`` reproduces the exact [Integrating, §V.A] reference
    configuration (only *e_d* is honoured); ``kind='uniform'`` builds a
    custom uniform network from all the supplied parameters.
    """
    if kind == "paper":
        return NetworkConfig.integrating_paper_config(e_d=e_d)
    if kind == "uniform":
        return NetworkConfig.uniform(
            N=N,
            length=length,
            branching=tuple(branching),
            arm_count=arm_count,
            p_x_inner=p_x_inner,
            p_z_inner=p_z_inner,
            e_d=e_d,
            gamma=gamma,
            c=c,
        )
    raise ValueError(
        f"unknown network kind: {kind!r} (expected one of {NETWORK_KINDS})"
    )


def build_objective(
    kind: str, *, f_min: float | None = None, r_min: float | None = None
) -> ObjectiveConfig:
    """Build an :class:`ObjectiveConfig` for the two most common variants."""
    if kind == "rate":
        return ObjectiveConfig.maximize_rate_with_fidelity_floor(
            f_min=f_min if f_min is not None else 0.9
        )
    if kind == "fidelity":
        return ObjectiveConfig.maximize_fidelity_with_rate_floor(
            r_min=r_min if r_min is not None else 0.0
        )
    raise ValueError(
        f"unknown objective kind: {kind!r} (expected one of {OBJECTIVE_KINDS})"
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def run_search(
    algorithm: str,
    network: NetworkConfig,
    objective: ObjectiveConfig,
    e_max: int,
    **kwargs: Any,
) -> list[SearchResult]:
    """Dispatch to :func:`brute_force_search` or :func:`dp_search`."""
    if algorithm == "brute_force":
        return brute_force_search(
            network,
            objective,
            e_max,
            max_n_pur=kwargs.get("max_n_pur"),
            max_enumerated_rounds=kwargs.get("max_enumerated_rounds", 4),
            include_heralded=kwargs.get("include_heralded", True),
            include_optimistic=kwargs.get("include_optimistic", True),
            include_link_level=kwargs.get("include_link_level", True),
        )
    if algorithm == "dp":
        return dp_search(
            network,
            objective,
            e_max,
            max_link_copies=kwargs.get("max_link_copies", 3),
            max_enumerated_rounds=kwargs.get("max_enumerated_rounds", 3),
            include_brute_force_families=kwargs.get(
                "include_brute_force_families", True
            ),
        )
    raise ValueError(f"unknown algorithm: {algorithm!r} (expected one of {ALGORITHMS})")


# ---------------------------------------------------------------------------
# Persistence (thin re-exports kept here so app.py has one import surface)
# ---------------------------------------------------------------------------


def save_selected(
    result: SearchResult, path: str | Path, *, network: NetworkConfig
) -> Path:
    return save_result(result, path, network=network)


def save_top_n(
    results: Sequence[SearchResult],
    directory: str | Path,
    *,
    network: NetworkConfig,
    n: int,
    include_infeasible: bool = False,
) -> list[Path]:
    return save_top(
        results, directory, network=network, n=n, include_infeasible=include_infeasible
    )


def export_csv(
    results: Sequence[SearchResult],
    path: str | Path,
    *,
    include_infeasible: bool = True,
) -> Path:
    return to_csv(results, path, include_infeasible=include_infeasible)


def export_json(
    results: Sequence[SearchResult],
    path: str | Path,
    *,
    include_infeasible: bool = True,
) -> Path:
    return to_json(results, path, include_infeasible=include_infeasible)


def load_artifact(path: str | Path) -> tuple[SearchResult, NetworkConfig]:
    return load_result(path)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifyRow:
    field: str
    recomputed: float
    stored: float | None
    ok: bool


_VERIFY_TOL = 1e-9


def verify_against_stored(
    dag: ScheduleDAG, network: NetworkConfig, result: SearchResult
) -> list[VerifyRow]:
    """Re-evaluate *dag* and compare against the (loaded) *result*'s stored metrics."""
    recomputed = Evaluator(network).evaluate(dag)
    pairs = (
        ("fidelity", recomputed.fidelity, result.eval_result.fidelity),
        ("rate", recomputed.rate, result.eval_result.rate),
        (
            "resource_cost",
            float(recomputed.resource_cost),
            float(result.eval_result.resource_cost),
        ),
        ("latency_s", recomputed.latency, result.eval_result.latency),
        ("success_prob", recomputed.success_prob, result.eval_result.success_prob),
    )
    rows = []
    for field, got, want in pairs:
        ok = abs(got - want) < _VERIFY_TOL
        rows.append(VerifyRow(field=field, recomputed=got, stored=want, ok=ok))
    return rows


def evaluate(dag: ScheduleDAG, network: NetworkConfig) -> EvaluationResult:
    return Evaluator(network).evaluate(dag)


def node_counts(dag: ScheduleDAG) -> dict[str, int]:
    """Return a ``{node type name: count}`` summary for *dag*."""
    counts: dict[str, int] = {}
    for node in dag.nodes.values():
        name = type(node).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


def render_dag(
    dag: ScheduleDAG,
    out_path: str | Path,
    *,
    network: NetworkConfig | None = None,
    annotate: bool = False,
) -> Path:
    """Render *dag* to an image file (format inferred from *out_path*'s extension).

    When *annotate* is True and *network* is given, the schedule is
    re-evaluated and per-node fidelity/time annotations are included.
    Raises ``RuntimeError`` if the Graphviz ``dot`` executable is missing.
    """
    result = (
        Evaluator(network).evaluate(dag) if (annotate and network is not None) else None
    )
    out_path = Path(out_path)
    _render_dag(dag, str(out_path), result=result)
    return out_path


def dag_to_dot(
    dag: ScheduleDAG, *, network: NetworkConfig | None = None, annotate: bool = False
) -> str:
    """Return the Graphviz DOT source for *dag* (no external ``dot`` binary required)."""
    result = (
        Evaluator(network).evaluate(dag) if (annotate and network is not None) else None
    )
    return _to_dot(dag, result=result)


def network_summary(network: NetworkConfig) -> str:
    """Return a short human-readable summary of *network*."""
    hop0 = network.hop(0)
    lines = [
        f"N (hops)      : {network.N}",
        f"hop length    : {hop0.length} km",
        f"branching     : {hop0.branching}",
        f"arm_count     : {hop0.arm_count}",
        f"p_x_inner     : {hop0.p_x_inner}",
        f"p_z_inner     : {hop0.p_z_inner}",
        f"eta (hop 0)   : {hop0.eta:.6f}",
        f"e_d           : {network.e_d}",
        f"gamma         : {network.gamma}",
        f"c             : {network.c}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Figures browser (read-only convenience; no subprocess execution of the
# validation scripts is attempted here since a frozen/packaged executable
# has no bundled Python interpreter to invoke them with).
# ---------------------------------------------------------------------------


def list_figures() -> list[Path]:
    """Return all ``.png``/``.svg`` files anywhere under ``outputs/``, sorted."""
    outputs_dir = PROJECT_ROOT / "outputs"
    if not outputs_dir.exists():
        return []
    found = [p for p in outputs_dir.rglob("*") if p.suffix.lower() in (".png", ".svg")]
    return sorted(found)


def open_externally(path: str | Path) -> None:
    """Open *path* with the OS's default viewer (best-effort, cross-platform)."""
    path = str(path)
    if sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform.startswith("win"):
        import os

        os.startfile(path)  # type: ignore[attr-defined]
    else:
        raise RuntimeError(
            f"Don't know how to open files externally on {sys.platform!r}"
        )
