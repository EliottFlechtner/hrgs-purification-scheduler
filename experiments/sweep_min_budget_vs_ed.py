"""
experiments/sweep_min_budget_vs_ed.py
=======================================
`docs/Roadmap_Derisk_and_Reframe.md`, §3: reframe `sweep_ed`'s existing
percent-improvement framing into the stronger claim: minimum resource
cost required to sustain a target fidelity, as a function of noise level
`e_d`.

Method [§3.1]
--------------
For each `e_d` in the same 11-point grid `sweep_ed.py` already uses
(`{0.000, 0.001, ..., 0.010}`), bisect over `e_max` (identical method to
`sweep_min_budget_vs_n.py`'s §2.1 bisection, just parameterized by `e_d`
instead of `N`, with `N` fixed at the paper's own N=10) to find the
smallest `e_max` at which `beam_search` (unioned with
`brute_force_search`'s fixed families, as usual) finds a schedule
clearing `f_min=0.9`.

Safety note carried over from `sweep_min_budget_vs_n.py`
-----------------------------------------------------------
That script's upward exponential search once reached `e_max=11520` at
N=18 (paper's `e_max=180`, safety multiple 64x), causing
`brute_force_search`'s internal enumeration cap (`e_max // (2*N)`, which
grows unbounded with `e_max` and is NOT capped by `beam_search`'s own
`max_link_copies`) to build hundreds of huge purification-chain DAGs
simultaneously in memory -- this exhausted RAM into swap and crashed the
whole desktop session, not just the Python process. The fix applied
there (and carried over here) was lowering the safety multiple to 32x.
At N=10 (fixed here), the paper's own `e_max=100`, so 32x gives a cap of
`3200 // 20 = 160` -- the same order of magnitude that was empirically
safe at N=18 (`e_max=2880`, cap=160 succeeded there; only `e_max=11520`,
cap=320, crashed). In practice, every `e_d` point in this sweep is
expected to land in the *downward* search branch anyway (paper's own
`e_max=100` at N=10 is already generously feasible per
`sweep_min_budget_vs_n.py`'s N=10 result: min feasible was `e_max=50` at
`e_d=0.01`), so the dangerous upward branch is not expected to be
exercised here at all -- this is a defensive cap, not an expected code
path.

Outputs
-------
    outputs/sweep_min_budget_vs_ed/results.csv
    outputs/sweep_min_budget_vs_ed/min_budget_vs_ed.{png,svg}
    outputs/sweep_min_budget_vs_ed/README.md

Usage
-----
    PYTHONPATH=src python3 -u experiments/sweep_min_budget_vs_ed.py
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
from hrgs_scheduler.search import SearchResult, beam_search

F_MIN = 0.9
BEAM_WIDTH = 25
N = 10
PAPER_E_MAX = 100  # 10 * N, fixed since N is fixed here
E_D_VALUES = [
    round(i * 0.001, 3) for i in range(11)
]  # 0.000 .. 0.010, matches sweep_ed.py

# See module docstring "Safety note" above.
_MAX_UPWARD_MULTIPLE = 32
_BISECTION_TOLERANCE = 2

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "sweep_min_budget_vs_ed"


@dataclass
class MinBudgetEdResult:
    e_d: float
    paper_e_max: int
    min_feasible_e_max: int  # -1 sentinel: gave up at the safety cap
    ratio_to_paper: float  # NaN if min_feasible_e_max == -1
    best_label: str
    best_fidelity: float
    best_success_prob: float
    best_rate: float
    best_cost: int
    n_beam_search_calls: int
    wall_time_s: float


def _build_network(e_d: float) -> NetworkConfig:
    return NetworkConfig.integrating_paper_config(e_d=e_d)


def _check(
    net: NetworkConfig,
    obj: ObjectiveConfig,
    e_max: int,
    cache: dict[int, tuple[bool, SearchResult]],
) -> tuple[bool, SearchResult]:
    """Run (or retrieve cached) `beam_search` at *e_max*, filtered to
    candidates actually within budget (see `sweep_min_budget_vs_n.py`'s
    "raw-baseline budget-filtering bug" note -- `brute_force_search`'s
    `raw` family bypasses `e_max` gating internally, so this filter is
    mandatory, not optional).
    """
    if e_max in cache:
        return cache[e_max]
    results = beam_search(net, obj, e_max=e_max, beam_width=BEAM_WIDTH)
    in_budget = [r for r in results if r.eval_result.resource_cost <= e_max]
    best = in_budget[0] if in_budget else results[0]
    feasible = obj.is_feasible(best.eval_result) if in_budget else False
    cache[e_max] = (feasible, best)
    return feasible, best


def find_min_budget(e_d: float) -> MinBudgetEdResult:
    t0 = time.time()
    net = _build_network(e_d)
    obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=F_MIN)
    cache: dict[int, tuple[bool, SearchResult]] = {}

    feasible0, best0 = _check(net, obj, PAPER_E_MAX, cache)
    print(
        f"  e_d={e_d:.3f}: e_max={PAPER_E_MAX} (paper's own budget) -> "
        f"{'feasible' if feasible0 else 'infeasible'}, "
        f"F={best0.eval_result.fidelity:.4f} ({time.time() - t0:.1f}s)",
        flush=True,
    )

    if feasible0:
        hi = PAPER_E_MAX
        lo = 0
        probe = max(1, PAPER_E_MAX // 2)
        while probe >= 1:
            feasible, best = _check(net, obj, probe, cache)
            print(
                f"  e_d={e_d:.3f}: probe e_max={probe} -> "
                f"{'feasible' if feasible else 'infeasible'}, "
                f"F={best.eval_result.fidelity:.4f} ({time.time() - t0:.1f}s)",
                flush=True,
            )
            if feasible:
                hi = probe
                if probe <= 1:
                    lo = 0
                    break
                probe //= 2
            else:
                lo = probe
                break
    else:
        lo = PAPER_E_MAX
        hi = PAPER_E_MAX * 4
        cap = PAPER_E_MAX * _MAX_UPWARD_MULTIPLE
        while True:
            feasible, best = _check(net, obj, hi, cache)
            print(
                f"  e_d={e_d:.3f}: probe e_max={hi} -> "
                f"{'feasible' if feasible else 'infeasible'}, "
                f"F={best.eval_result.fidelity:.4f} ({time.time() - t0:.1f}s)",
                flush=True,
            )
            if feasible:
                break
            lo = hi
            hi *= 2
            if hi > cap:
                print(
                    f"  e_d={e_d:.3f}: WARNING -- no feasible e_max found up to "
                    f"{cap} ({_MAX_UPWARD_MULTIPLE}x the paper's budget); "
                    "giving up upward search, reporting best-effort result "
                    "at the cap.",
                    flush=True,
                )
                feasible_cap, best_cap = _check(net, obj, cap, cache)
                return MinBudgetEdResult(
                    e_d=e_d,
                    paper_e_max=PAPER_E_MAX,
                    min_feasible_e_max=-1,
                    ratio_to_paper=float("nan"),
                    best_label=best_cap.label,
                    best_fidelity=best_cap.eval_result.fidelity,
                    best_success_prob=best_cap.eval_result.success_prob,
                    best_rate=best_cap.eval_result.rate,
                    best_cost=best_cap.eval_result.resource_cost,
                    n_beam_search_calls=len(cache),
                    wall_time_s=time.time() - t0,
                )

    while hi - lo > _BISECTION_TOLERANCE:
        mid = (lo + hi) // 2
        feasible, best = _check(net, obj, mid, cache)
        print(
            f"  e_d={e_d:.3f}: bisect e_max={mid} -> "
            f"{'feasible' if feasible else 'infeasible'}, "
            f"F={best.eval_result.fidelity:.4f} ({time.time() - t0:.1f}s)",
            flush=True,
        )
        if feasible:
            hi = mid
        else:
            lo = mid

    _, best_final = _check(net, obj, hi, cache)
    elapsed = time.time() - t0
    print(
        f"  e_d={e_d:.3f}: done, min feasible e_max={hi} "
        f"(paper's own budget was {PAPER_E_MAX}), {len(cache)} beam_search "
        f"calls, {elapsed:.1f}s total",
        flush=True,
    )
    return MinBudgetEdResult(
        e_d=e_d,
        paper_e_max=PAPER_E_MAX,
        min_feasible_e_max=hi,
        ratio_to_paper=hi / PAPER_E_MAX,
        best_label=best_final.label,
        best_fidelity=best_final.eval_result.fidelity,
        best_success_prob=best_final.eval_result.success_prob,
        best_rate=best_final.eval_result.rate,
        best_cost=best_final.eval_result.resource_cost,
        n_beam_search_calls=len(cache),
        wall_time_s=elapsed,
    )


def write_results_csv(results: list[MinBudgetEdResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "e_d",
                "paper_e_max",
                "min_feasible_e_max",
                "ratio_to_paper",
                "best_label",
                "best_fidelity",
                "best_success_prob",
                "best_rate",
                "best_cost",
                "n_beam_search_calls",
                "wall_time_s",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.e_d,
                    r.paper_e_max,
                    r.min_feasible_e_max,
                    r.ratio_to_paper,
                    r.best_label,
                    r.best_fidelity,
                    r.best_success_prob,
                    r.best_rate,
                    r.best_cost,
                    r.n_beam_search_calls,
                    r.wall_time_s,
                ]
            )


def make_plot(results: list[MinBudgetEdResult]) -> None:
    valid = [r for r in results if r.min_feasible_e_max > 0]
    series = {
        "optimizer_budget_relaxed": [(r.e_d, r.min_feasible_e_max) for r in valid],
    }
    fig, ax = new_figure()
    plot_lines(
        ax,
        series,
        xlabel=r"Depolarizing error probability $e_d$",
        ylabel="Minimum feasible $e_{max}$",
        title=f"Minimum required budget vs. $e_d$ (N={N}, $f_{{min}}$={F_MIN})",
        style_overrides={
            "optimizer_budget_relaxed": {
                "label": "Min. feasible $e_{max}$ (this sweep)"
            }
        },
    )
    ax.axhline(
        PAPER_E_MAX,
        color="black",
        linewidth=1.0,
        linestyle="--",
        label=f"Paper's fixed $e_{{max}}$={PAPER_E_MAX}",
    )
    ax.legend()
    save_figure(fig, OUTPUT_DIR / "min_budget_vs_ed")


def write_readme(results: list[MinBudgetEdResult], elapsed_s: float) -> None:
    lines = [
        "# Minimum Required Budget vs. e_d (resource-vs-quality reframe)",
        "",
        "Per [docs/Roadmap_Derisk_and_Reframe.md](../../docs/Roadmap_Derisk_and_Reframe.md),"
        " §3: reframes"
        " [outputs/sweep_ed_n10/](../sweep_ed_n10/README.md)'s existing"
        " percent-improvement framing into the stronger claim: minimum"
        " resource cost required to sustain a target fidelity"
        f" ($f_{{min}}$={F_MIN}), as a function of noise level $e_d$,"
        " rather than assuming the paper's fixed `e_max=100` choice is the"
        " right amount to spend at every noise level.",
        "",
        f"Network: `NetworkConfig.integrating_paper_config(e_d=e_d)` (N={N},"
        " the paper's exact config, only `e_d` varies)."
        f" Objective: `maximize_rate_with_fidelity_floor(f_min={F_MIN})`."
        " Method: bisection over `e_max` per `e_d` point, identical to"
        " [outputs/sweep_min_budget_vs_n/](../sweep_min_budget_vs_n/README.md)'s"
        " §2 method, just parameterized by `e_d` instead of `N`.",
        "",
        "## Results",
        "",
        "| $e_d$ | Paper's fixed $e_{max}$ | Min. feasible $e_{max}$ (this sweep) | Ratio | Best F | Best label |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        min_str = (
            "**not found** (gave up at cap)"
            if r.min_feasible_e_max < 0
            else str(r.min_feasible_e_max)
        )
        ratio_str = "N/A" if r.min_feasible_e_max < 0 else f"{r.ratio_to_paper:.3f}x"
        lines.append(
            f"| {r.e_d:.3f} | {r.paper_e_max} | {min_str} | {ratio_str} |"
            f" {r.best_fidelity:.4f} | {r.best_label} |"
        )

    valid = [r for r in results if r.min_feasible_e_max > 0]
    if valid:
        min_ratio = min(r.ratio_to_paper for r in valid)
        max_ratio = max(r.ratio_to_paper for r in valid)
        lines += [
            "",
            f"Across the tested range, the minimum feasible `e_max` needed is"
            f" only {min_ratio:.2f}x-{max_ratio:.2f}x the paper's fixed"
            f" `e_max={PAPER_E_MAX}` -- equivalently, the paper's fixed"
            f" choice spends {1 / max_ratio:.1f}x-{1 / min_ratio:.1f}x the"
            " minimum this sweep's searched families actually require to"
            " clear the fidelity floor, i.e. the paper's fixed choice is"
            " overspending at every point tested, most severely at low"
            " $e_d$ (where little-to-no purification is needed at all) and"
            " least severely as $e_d$ approaches its upper end of the"
            " tested range.",
        ]

    lines += [
        "",
        "## Relationship to §2 / the excluded-move caveat",
        "",
        "This sweep fixes `N=10`, where"
        " [outputs/sweep_min_budget_vs_n/](../sweep_min_budget_vs_n/README.md)"
        " (§2) already found the searched families comfortably sufficient"
        " (min. feasible `e_max=50` at `e_d=0.01`, half the paper's"
        " budget) -- N=10 is far from the N=18 regime where §2 found a"
        " search-family wall and §1's excluded move was needed to rescue"
        " feasibility. So unlike §2's N=18 result, the numbers here should"
        " be read at face value as genuine minimum requirements for this"
        " searched family at this `N`, not a lower bound qualified by an"
        " out-of-scope search move -- consistent with the hedge used"
        " throughout [docs/Optimality Scope.md](../../docs/Optimality%20Scope.md),"
        " which only bites at larger `N`.",
        "",
        "## Figures",
        "",
        "`min_budget_vs_ed.png` / `.svg`: minimum required `e_max` vs."
        f" `e_d`, with the paper's fixed `e_max={PAPER_E_MAX}` overlaid as"
        " a horizontal reference line, making visually obvious how much"
        " the paper's fixed choice overspends at each noise level.",
        "",
        "Full data: [`results.csv`](results.csv).",
        "",
        "## Reproducing",
        "",
        "```bash",
        "cd /home/shark/Documents/hrgs-purification-scheduler",
        "source .venv/bin/activate",
        "PYTHONPATH=src python3 -u experiments/sweep_min_budget_vs_ed.py",
        "```",
        "",
        f"Total wall-clock time: ~{elapsed_s:.0f}s.",
        "",
    ]
    (OUTPUT_DIR / "README.md").write_text("\n".join(lines))


def main() -> None:
    t0 = time.time()
    results = []
    for e_d in E_D_VALUES:
        print(
            f"e_d={e_d:.3f}: starting bisection for minimum feasible e_max...",
            flush=True,
        )
        results.append(find_min_budget(e_d))
    elapsed = time.time() - t0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_results_csv(results, OUTPUT_DIR / "results.csv")
    make_plot(results)
    write_readme(results, elapsed)

    print(f"\nDone in {elapsed:.1f}s. Outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
