"""
validation/sweep_ed.py
========================
Roadmap item 1: generalize the single-point headline experiment
(`outputs/headline_experiment_n10/`) into a sweep across the paper's full
noise range, `e_d in {0.000, 0.001, ..., 0.010}` (11 points, matching the
granularity already used by `fig5_fidelity_vs_noise.py` /
`fig6_rate_ratio.py` for visual consistency with those reproduction
figures).

Methodology (identical to the single-point headline experiment, just
repeated per e_d point) [WbW Plan, Weeks 3-4]
------------------------------------------------
For each e_d:

    net = NetworkConfig.integrating_paper_config(e_d=e_d)
    obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)
    results = beam_search(net, obj, e_max=100, beam_width=25)

`e_max=100` is the paper's own resource cost (5 half-RGS copies/side/hop
x 2 sides x N=10 hops), so this single search call yields all three
schedules needed for the resource-normalized comparison at once (no
separate brute-force call needed — `beam_search` already includes
`brute_force_search`'s fixed families by default):

  * `paper_baseline`            : the `flexible_paper` candidate (cost=100, fixed).
  * `optimizer_matched_cost`    : best-scoring candidate with resource_cost
                                   == paper's cost (like-for-like, cost=100).
  * `optimizer_budget_relaxed`  : `results[0]`, the best-scoring candidate
                                   under budget <= 100 (may spend less).

Verified to exactly reproduce the single-point headline numbers at
e_d=0.01 (4055.92 / 4158.14 / 6713.18) before writing this script.

Outputs
-------
    outputs/sweep_ed_n10/results.csv              long format, one row per (e_d, variant)
    outputs/sweep_ed_n10/improvement_summary.csv  % improvement vs. paper baseline, per e_d
    outputs/sweep_ed_n10/rate_vs_ed.{png,svg}
    outputs/sweep_ed_n10/fidelity_vs_ed.{png,svg}
    outputs/sweep_ed_n10/improvement_vs_ed.{png,svg}
    outputs/sweep_ed_n10/README.md

Usage
-----
    PYTHONPATH=src python3 validation/sweep_ed.py
"""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.reporting import new_figure, plot_lines, save_figure
from hrgs_scheduler.search import beam_search

N_HOPS = 10
F_MIN = 0.9
E_MAX = 100  # paper's own resource cost at N=10, n_pur=5
BEAM_WIDTH = 25
E_D_VALUES = [round(i * 0.001, 3) for i in range(11)]  # 0.000 .. 0.010

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "sweep_ed_n10"

VARIANT_ROLE = {
    "paper_baseline": "paper_baseline",
    "optimizer_matched_cost": "optimizer_matched_cost",
    "optimizer_budget_relaxed": "optimizer_budget_relaxed",
}


@dataclass
class Row:
    e_d: float
    variant: str
    label: str
    resource_cost: int
    fidelity: float
    success_prob: float
    rate: float
    latency_ms: float


def run_one_point(e_d: float) -> list[Row]:
    net = NetworkConfig.integrating_paper_config(e_d=e_d)
    obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=F_MIN)
    results = beam_search(net, obj, e_max=E_MAX, beam_width=BEAM_WIDTH)

    paper = next(r for r in results if r.label == "flexible_paper")
    matched = next(
        r
        for r in results
        if r.eval_result.resource_cost == paper.eval_result.resource_cost
    )
    budget = results[0]
    # [Roadmap_Derisk_and_Reframe.md §4] uniform link-level family, best
    # candidate within budget (results is sorted best-first already).
    link_best = next(
        (
            r
            for r in results
            if r.label.startswith("link.") and r.eval_result.resource_cost <= E_MAX
        ),
        None,
    )

    rows = []
    variants: list[tuple[str, object]] = [
        ("paper_baseline", paper),
        ("optimizer_matched_cost", matched),
        ("optimizer_budget_relaxed", budget),
    ]
    if link_best is not None:
        variants.append(("link_level_baseline", link_best))
    for variant, r in variants:
        rows.append(
            Row(
                e_d=e_d,
                variant=variant,
                label=r.label,
                resource_cost=r.eval_result.resource_cost,
                fidelity=r.eval_result.fidelity,
                success_prob=r.eval_result.success_prob,
                rate=r.eval_result.rate,
                latency_ms=r.eval_result.latency,
            )
        )
    return rows


def write_results_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "e_d",
                "variant",
                "label",
                "resource_cost",
                "fidelity",
                "success_prob",
                "rate",
                "latency_ms",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.e_d,
                    r.variant,
                    r.label,
                    r.resource_cost,
                    r.fidelity,
                    r.success_prob,
                    r.rate,
                    r.latency_ms,
                ]
            )


def write_improvement_csv(rows: list[Row], path: Path) -> None:
    by_ed: dict[float, dict[str, Row]] = {}
    for r in rows:
        by_ed.setdefault(r.e_d, {})[r.variant] = r

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "e_d",
                "matched_cost_rate_improvement_pct",
                "matched_cost_fidelity_delta",
                "budget_relaxed_rate_improvement_pct",
                "budget_relaxed_cost_ratio",
                "budget_relaxed_fidelity_delta",
                "link_level_cost",
                "link_level_fidelity",
                "link_level_rate",
                "budget_relaxed_vs_link_level_rate_improvement_pct",
            ]
        )
        for e_d in E_D_VALUES:
            variants = by_ed[e_d]
            paper = variants["paper_baseline"]
            matched = variants["optimizer_matched_cost"]
            budget = variants["optimizer_budget_relaxed"]
            link = variants.get("link_level_baseline")
            writer.writerow(
                [
                    e_d,
                    (matched.rate / paper.rate - 1.0) * 100.0,
                    matched.fidelity - paper.fidelity,
                    (budget.rate / paper.rate - 1.0) * 100.0,
                    budget.resource_cost / paper.resource_cost,
                    budget.fidelity - paper.fidelity,
                    link.resource_cost if link else "",
                    link.fidelity if link else "",
                    link.rate if link else "",
                    (
                        (budget.rate / link.rate - 1.0) * 100.0
                        if link and link.rate
                        else ""
                    ),
                ]
            )


def make_plots(rows: list[Row]) -> None:
    by_variant: dict[str, list[Row]] = {}
    for r in rows:
        by_variant.setdefault(r.variant, []).append(r)
    for variant_rows in by_variant.values():
        variant_rows.sort(key=lambda r: r.e_d)

    rate_series = {v: [(r.e_d, r.rate) for r in vr] for v, vr in by_variant.items()}
    fidelity_series = {
        v: [(r.e_d, r.fidelity) for r in vr] for v, vr in by_variant.items()
    }

    fig, ax = new_figure()
    plot_lines(
        ax,
        rate_series,
        xlabel=r"Depolarizing error probability $e_d$",
        ylabel="Rate (score, pairs/s-equivalent)",
        title="Rate vs. $e_d$ — paper baseline vs. optimizer (N=10)",
    )
    save_figure(fig, OUTPUT_DIR / "rate_vs_ed")

    fig, ax = new_figure()
    plot_lines(
        ax,
        fidelity_series,
        xlabel=r"Depolarizing error probability $e_d$",
        ylabel="Fidelity $F$",
        title=f"Fidelity vs. $e_d$ — paper baseline vs. optimizer (N=10, $f_{{min}}$={F_MIN})",
    )
    ax.axhline(
        F_MIN, color="black", linewidth=0.8, linestyle=":", label=f"$f_{{min}}$={F_MIN}"
    )
    ax.legend()
    save_figure(fig, OUTPUT_DIR / "fidelity_vs_ed")

    by_ed: dict[float, dict[str, Row]] = {}
    for r in rows:
        by_ed.setdefault(r.e_d, {})[r.variant] = r
    matched_improvement = []
    budget_improvement = []
    for e_d in sorted(by_ed):
        paper = by_ed[e_d]["paper_baseline"]
        matched = by_ed[e_d]["optimizer_matched_cost"]
        budget = by_ed[e_d]["optimizer_budget_relaxed"]
        matched_improvement.append((e_d, (matched.rate / paper.rate - 1.0) * 100.0))
        budget_improvement.append((e_d, (budget.rate / paper.rate - 1.0) * 100.0))

    fig, ax = new_figure()
    plot_lines(
        ax,
        {
            "optimizer_matched_cost": matched_improvement,
            "optimizer_budget_relaxed": budget_improvement,
        },
        xlabel=r"Depolarizing error probability $e_d$",
        ylabel="Rate improvement over paper baseline (%)",
        title="Optimizer rate improvement vs. $e_d$ (N=10)",
        style_overrides={
            "optimizer_matched_cost": {"label": "Matched cost (100 vs. 100)"},
            "optimizer_budget_relaxed": {"label": "Budget-relaxed (<=100)"},
        },
    )
    ax.axhline(0.0, color="black", linewidth=0.8)
    save_figure(fig, OUTPUT_DIR / "improvement_vs_ed")


def write_readme(rows: list[Row], elapsed_s: float) -> None:
    by_ed: dict[float, dict[str, Row]] = {}
    for r in rows:
        by_ed.setdefault(r.e_d, {})[r.variant] = r

    lo, hi = E_D_VALUES[0], E_D_VALUES[-1]
    paper_lo, matched_lo, budget_lo = (
        by_ed[lo]["paper_baseline"],
        by_ed[lo]["optimizer_matched_cost"],
        by_ed[lo]["optimizer_budget_relaxed"],
    )
    paper_hi, matched_hi, budget_hi = (
        by_ed[hi]["paper_baseline"],
        by_ed[hi]["optimizer_matched_cost"],
        by_ed[hi]["optimizer_budget_relaxed"],
    )

    def pct(matched: Row, paper: Row) -> float:
        return (matched.rate / paper.rate - 1.0) * 100.0

    lines = [
        "# Sweep: Optimizer vs. Paper Baseline across e_d in [0, 0.01]",
        "",
        "Generalizes `outputs/headline_experiment_n10/` (single point,"
        " e_d=0.01) into a full sweep, per [docs/Roadmap Remaining"
        " Work.md](../../docs/Roadmap%20Remaining%20Work.md), item 1.",
        "",
        f"Grid: `e_d in {{{', '.join(f'{v:.3f}' for v in E_D_VALUES)}}}`"
        f" ({len(E_D_VALUES)} points), matching the granularity used by"
        " `validation/fig5_fidelity_vs_noise.py` / `fig6_rate_ratio.py`.",
        "",
        "Network: `NetworkConfig.integrating_paper_config(e_d=e_d)` (N=10,"
        " l=2km, b=(16,14,1), k=18 arms — the paper's exact config, only"
        f" e_d varies). Objective: `maximize_rate_with_fidelity_floor(f_min={F_MIN})`."
        f" Search: `beam_search(net, obj, e_max={E_MAX}, beam_width={BEAM_WIDTH})`"
        f" (`e_max={E_MAX}` = paper's own resource cost, so a single call"
        " yields the paper baseline, matched-cost, and budget-relaxed"
        " candidates all at once — `beam_search` always includes"
        " `brute_force_search`'s fixed families, so `flexible_paper` and"
        " the matched-cost family are present regardless of beam pruning).",
        "",
        "## Headline numbers (endpoints of the sweep)",
        "",
        "| e_d | Schedule | Cost | Fidelity | Success prob | Rate |",
        "|---|---|---|---|---|---|",
        f"| {lo:.3f} | Paper baseline | {paper_lo.resource_cost} | {paper_lo.fidelity:.4f} | {paper_lo.success_prob:.4f} | {paper_lo.rate:.2f} |",
        f"| {lo:.3f} | Optimizer (matched cost) | {matched_lo.resource_cost} | {matched_lo.fidelity:.4f} | {matched_lo.success_prob:.4f} | {matched_lo.rate:.2f} |",
        f"| {lo:.3f} | Optimizer (budget<=100) | {budget_lo.resource_cost} | {budget_lo.fidelity:.4f} | {budget_lo.success_prob:.4f} | {budget_lo.rate:.2f} |",
        f"| {hi:.3f} | Paper baseline | {paper_hi.resource_cost} | {paper_hi.fidelity:.4f} | {paper_hi.success_prob:.4f} | {paper_hi.rate:.2f} |",
        f"| {hi:.3f} | Optimizer (matched cost) | {matched_hi.resource_cost} | {matched_hi.fidelity:.4f} | {matched_hi.success_prob:.4f} | {matched_hi.rate:.2f} |",
        f"| {hi:.3f} | Optimizer (budget<=100) | {budget_hi.resource_cost} | {budget_hi.fidelity:.4f} | {budget_hi.success_prob:.4f} | {budget_hi.rate:.2f} |",
        "",
        f"Matched-cost rate improvement: {pct(matched_lo, paper_lo):+.1f}% at"
        f" e_d={lo:.3f}, {pct(matched_hi, paper_hi):+.1f}% at e_d={hi:.3f}.",
        f"Budget-relaxed rate improvement: {pct(budget_lo, paper_lo):+.1f}% at"
        f" e_d={lo:.3f}, {pct(budget_hi, paper_hi):+.1f}% at e_d={hi:.3f}"
        f" (spending {budget_lo.resource_cost}/{paper_lo.resource_cost} and"
        f" {budget_hi.resource_cost}/{paper_hi.resource_cost} of the paper's cost, respectively).",
        "",
        "## Link-level baseline comparison [Roadmap_Derisk_and_Reframe.md §4]",
        "",
        "The uniform link-level family (identical purification circuit"
        " applied at every hop) is already included in every"
        " `beam_search` call above -- it's the \"reasonable default a"
        ' practitioner would actually pick" without doing any'
        " optimization, distinct from the paper's own hand-picked"
        " `flexible_paper` demonstration schedule. Extracted here as its"
        " own labeled comparison point for the first time:",
        "",
        "| e_d | Link cost | Link F | Link rate | Budget-relaxed improvement over link (%) |",
        "|---|---|---|---|---|",
    ]
    for e_d in E_D_VALUES:
        link = by_ed[e_d].get("link_level_baseline")
        budget = by_ed[e_d]["optimizer_budget_relaxed"]
        if link is None:
            lines.append(f"| {e_d:.3f} | N/A | N/A | N/A | N/A |")
            continue
        link_improvement = (
            (budget.rate / link.rate - 1.0) * 100.0 if link.rate else float("nan")
        )
        lines.append(
            f"| {e_d:.3f} | {link.resource_cost} | {link.fidelity:.4f} |"
            f" {link.rate:.2f} | {link_improvement:+.2f}% |"
        )
    _valid_link = [
        (e_d, by_ed[e_d]["link_level_baseline"])
        for e_d in E_D_VALUES
        if by_ed[e_d].get("link_level_baseline") is not None
        and by_ed[e_d]["link_level_baseline"].rate
    ]
    if _valid_link:
        _link_improvements = [
            (by_ed[e_d]["optimizer_budget_relaxed"].rate / link.rate - 1.0) * 100.0
            for e_d, link in _valid_link
        ]
        lines += [
            "",
            "The budget-relaxed optimizer's rate improvement over the"
            f" *link-level* baseline specifically ranges from"
            f" {min(_link_improvements):+.1f}% to"
            f" {max(_link_improvements):+.1f}% across the sweep -- distinct"
            " from (and generally smaller than) its improvement over the"
            " paper's `flexible_paper` demonstration schedule reported"
            " above, since the link-level family is itself already a"
            " reasonable, non-hand-picked default. The improvement is"
            " exactly 0% at e_d=0.000 and e_d=0.008: at e_d=0.000 both"
            " families reach the maximum possible rate (success_prob=1,"
            " noiseless) despite different costs (raw chain, cost=20, vs."
            " link-level's minimum cost=40, since the link-level family"
            " always applies at least one purification round); at"
            " e_d=0.008 the budget-relaxed optimizer's own global best"
            " *is* the link-level candidate (`link.n2.YY`), making the"
            " comparison trivially exact there.",
        ]

    lines += [
        "",
        "Full per-point data: [`results.csv`](results.csv) (long format,"
        " one row per `(e_d, variant)` pair) and"
        " [`improvement_summary.csv`](improvement_summary.csv) (wide"
        " format, one row per `e_d`, with pre-computed % improvements).",
        "",
        "## Figures",
        "",
        "| File | Shows |",
        "|---|---|",
        "| `rate_vs_ed.png` / `.svg` | Rate vs. e_d, one line per schedule variant. |",
        "| `fidelity_vs_ed.png` / `.svg` | Fidelity vs. e_d, one line per schedule variant, with the `f_min` floor marked. |",
        "| `improvement_vs_ed.png` / `.svg` | Optimizer's % rate improvement over the paper baseline vs. e_d, for both the matched-cost and budget-relaxed framings. |",
        "",
        "## Reproducing",
        "",
        "```bash",
        "cd /home/shark/Documents/hrgs-purification-scheduler",
        "source .venv/bin/activate",
        "PYTHONPATH=src python3 validation/sweep_ed.py",
        "```",
        "",
        f"Total wall-clock time for the 11-point sweep: ~{elapsed_s:.0f}s"
        " (11 `beam_search` calls, one per e_d point; `beam_search` reuses"
        " `brute_force_search`'s families internally, so no separate"
        " brute-force pass is needed).",
        "",
    ]
    (OUTPUT_DIR / "README.md").write_text("\n".join(lines))


def main() -> None:
    t0 = time.time()
    all_rows: list[Row] = []
    for e_d in E_D_VALUES:
        print(f"Running e_d={e_d:.3f} ...", flush=True)
        all_rows.extend(run_one_point(e_d))
    elapsed = time.time() - t0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_results_csv(all_rows, OUTPUT_DIR / "results.csv")
    write_improvement_csv(all_rows, OUTPUT_DIR / "improvement_summary.csv")
    make_plots(all_rows)
    write_readme(all_rows, elapsed)

    print(f"\nDone in {elapsed:.1f}s. Outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
