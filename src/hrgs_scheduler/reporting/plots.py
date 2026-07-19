"""
hrgs_scheduler.reporting.plots
================================
Shared plotting helpers for every report-bound figure produced under
`validation/` and `outputs/`.

Rationale [Roadmap: Remaining Work, item 4]: sweep scripts 1-3 (e_d
sweep, beam_width sweep, N sweep) and the earlier Fig. 5/6 reproduction
scripts each need a "line plot with a consistent legend across schedule
variants" figure. Writing this once and importing it everywhere means:

  * the same schedule "role" (paper baseline, optimizer at matched cost,
    optimizer at relaxed budget, ...) always gets the same color/marker
    across every figure in the report, so a reader learns the legend
    once;
  * every figure is saved at the same DPI/size and in both a raster
    format (`.png`, quick preview) and a vector format (`.svg`, for
    lossless embedding in the LaTeX/Word report);
  * sweep scripts stay focused on computing data, not on plot styling.

This module requires the optional `matplotlib` dependency
(`pip install -e '.[plotting]'`); the rest of `hrgs_scheduler` does not
depend on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    import matplotlib.pyplot as plt
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - exercised only when missing
    raise ImportError(
        "hrgs_scheduler.reporting.plots requires matplotlib. Install it "
        "with `pip install -e '.[plotting]'` (or `pip install matplotlib`)."
    ) from exc

# ---------------------------------------------------------------------------
# Shared figure conventions
# ---------------------------------------------------------------------------

FIGSIZE: tuple[float, float] = (7.0, 4.5)
DPI: int = 150
SAVE_FORMATS: tuple[str, ...] = ("png", "svg")

# Canonical style per schedule "role", reused across every sweep figure so
# a reader learns the legend once. Sweep scripts should map their own
# variant labels onto one of these keys rather than inventing new colors.
VARIANT_STYLE: dict[str, dict[str, object]] = {
    "raw": dict(
        color="#7f7f7f", marker="x", linestyle=":", label="Raw (no purification)"
    ),
    "paper_baseline": dict(
        color="#7f7f7f",
        marker="s",
        linestyle="--",
        label="Paper baseline (flexible_paper)",
    ),
    "baseline_end_node_pumping": dict(
        color="#ff7f0e", marker="P", linestyle="--", label="Baseline end-node pumping"
    ),
    "optimizer_matched_cost": dict(
        color="#1f77b4", marker="o", linestyle="-", label="Optimizer (matched cost)"
    ),
    "optimizer_budget_relaxed": dict(
        color="#d62728", marker="^", linestyle="-", label="Optimizer (budget ≤ cost)"
    ),
    "optimizer_unconstrained": dict(
        color="#2ca02c", marker="D", linestyle=":", label="Optimizer (unconstrained)"
    ),
    "exact_dp": dict(color="#9467bd", marker="v", linestyle="-.", label="Exact DP"),
    "beam_search": dict(
        color="#1f77b4", marker="o", linestyle="-", label="Beam search"
    ),
    "improvement": dict(
        color="#17becf", marker="o", linestyle="-", label="% improvement"
    ),
    "runtime": dict(
        color="#8c564b", marker="o", linestyle="-", label="Wall-clock time"
    ),
}


def style_for(variant: str, **overrides: object) -> dict[str, object]:
    """Return the canonical style dict for *variant*, with any *overrides*
    (e.g. a more specific `label`) applied on top. Unknown variants get an
    empty base style so matplotlib falls back to its default cycle rather
    than erroring — callers should still add unrecognised roles to
    `VARIANT_STYLE` above so future figures stay consistent.
    """
    style = dict(VARIANT_STYLE.get(variant, {}))
    style.update(overrides)
    return style


# ---------------------------------------------------------------------------
# Figure lifecycle helpers
# ---------------------------------------------------------------------------


def new_figure(figsize: tuple[float, float] = FIGSIZE) -> tuple[Figure, Axes]:
    """Create a `(fig, ax)` pair using the shared report figure size."""
    return plt.subplots(figsize=figsize)


def save_figure(
    fig: Figure, path: str | Path, *, formats: Sequence[str] = SAVE_FORMATS
) -> list[Path]:
    """Save *fig* to *path* (extension ignored) in every format in
    *formats*, creating parent directories as needed. Returns the list of
    written file paths.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = path.with_suffix("")
    written: list[Path] = []
    for fmt in formats:
        out = stem.with_suffix(f".{fmt}")
        fig.savefig(out, dpi=DPI, bbox_inches="tight")
        written.append(out)
    return written


def plot_lines(
    ax: Axes,
    series: Mapping[str, Iterable[tuple[float, float]]],
    *,
    xlabel: str,
    ylabel: str,
    title: str | None = None,
    style_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> Axes:
    """Plot one line per `(variant -> [(x, y), ...])` entry in *series*
    onto *ax*, using `VARIANT_STYLE` for consistent styling. Per-series
    style overrides (e.g. a custom label) may be supplied via
    *style_overrides*.
    """
    style_overrides = style_overrides or {}
    for variant, points in series.items():
        xs, ys = zip(*points)
        ax.plot(xs, ys, **style_for(variant, **style_overrides.get(variant, {})))
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.legend()
    return ax


def plot_dual_axis(
    xs: Sequence[float],
    left_series: Mapping[str, Iterable[float]],
    right_series: Mapping[str, Iterable[float]],
    *,
    xlabel: str,
    left_ylabel: str,
    right_ylabel: str,
    title: str | None = None,
    figsize: tuple[float, float] = FIGSIZE,
) -> tuple[Figure, Axes, Axes]:
    """Two-panel-in-one figure: left y-axis for *left_series*, right
    y-axis (twin) for *right_series*, shared x-axis *xs*. Used by the
    beam_width sweep (runtime vs. best-rate-found) but generic enough for
    any "cost vs. quality" tradeoff figure.
    """
    fig, ax_left = plt.subplots(figsize=figsize)
    ax_right = ax_left.twinx()

    for variant, ys in left_series.items():
        ax_left.plot(xs, list(ys), **style_for(variant))
    for variant, ys in right_series.items():
        ax_right.plot(xs, list(ys), **style_for(variant, linestyle="--"))

    ax_left.set_xlabel(xlabel)
    ax_left.set_ylabel(left_ylabel)
    ax_right.set_ylabel(right_ylabel)
    if title:
        ax_left.set_title(title)
    ax_left.grid(alpha=0.3)

    handles = ax_left.get_lines() + ax_right.get_lines()
    labels = [h.get_label() for h in handles]
    ax_left.legend(handles, labels, loc="best")

    return fig, ax_left, ax_right
