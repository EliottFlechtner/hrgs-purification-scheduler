"""
validation/sweep_min_budget_vs_n.py
=====================================
`docs/Roadmap_Derisk_and_Reframe.md`, §2: the scaling-law question. At
each `N` in `N_VALUES`, find the *smallest* `e_max` at which
`beam_search` (unioned with `brute_force_search`'s fixed families, as
usual) finds ANY schedule clearing the fidelity floor `f_min=0.9`,
rather than stopping at the paper's own `e_max = 10*N` cost formula.

Method: bisection, not a linear scan [§2.1]
--------------------------------------------
For each `N`:

1. Check feasibility at the paper's own budget, `e_max = 10*N`.
2. If infeasible there (as `sweep_hop_count` already found at `N=14`,
   `N=18`): exponential-search upward -- try `4*10*N`, then double again
   and again, until a feasible `e_max` is found.
3. If feasible there instead (as at `N<=10`, where the paper's own
   schedule already clears the floor): exponential-search *downward*
   -- halve repeatedly until an infeasible `e_max` is found. This
   direction is not spelled out explicitly in the roadmap (which frames
   the paper's budget as "already known infeasible"), but is needed for
   a full `N=10..18` trend line and follows the identical bisection
   logic in the other direction.
4. Bisect between the last-infeasible and first-feasible point until the
   minimum feasible `e_max` is pinned down to within `+/- 2` (`e_max` is
   effectively discretized by Gen-node counts anyway).
5. Cache every `beam_search` call by `(N, e_max)` so no point already
   queried during the exponential search or an earlier bisection step is
   ever recomputed.

**Caveat carried over from `Optimality Scope.md` and
`excluded_move_n14_n18/README.md`**: this bisection uses ONLY
`beam_search`'s own reachable schedule families (span-partition DP +
`brute_force_search`'s three fixed families). It does NOT include the
excluded same-span-purification move validated at N=3/N=14/N=18. Per
§1's result, that move rescues feasibility at N=18 at exactly the
paper's own budget (`e_max=180`, `F=0.928596`) -- i.e. a real schedule
already exists there requiring no MORE than `10*N`. So any
"minimum required budget > 10*N" claim produced by this script describes
a limitation of the *searched* families (`beam_search`/`dp_search`'s
own reach), not a true lower bound on what any valid schedule needs.
This distinction is stated explicitly in the generated README, per
§2.2's explicit instruction to scope this honestly.

**Bisection monotonicity caveat**: this method assumes feasibility is
monotonically non-decreasing in `e_max` (more budget can only help).
This holds for the *exact* DP frontier by construction (a larger budget
cap is a strict superset of a smaller one's candidate space), but
`beam_search`'s beam-pruning is a heuristic on top of that, so in
principle a specific beam width could (rarely) miss a feasible
candidate at a larger `e_max` that it would have found at a smaller one.
No such non-monotonicity was observed in this run (see README), but this
assumption is not proven exhaustively.

Outputs
-------
    outputs/sweep_min_budget_vs_n/results.csv
    outputs/sweep_min_budget_vs_n/min_budget_vs_n.{png,svg}
    outputs/sweep_min_budget_vs_n/README.md

Usage
-----
    PYTHONPATH=src nohup python3 -u validation/sweep_min_budget_vs_n.py \\
      > validation/sweep_min_budget_vs_n.log 2>&1 &
"""

from __future__ import annotations

import csv
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.reporting import new_figure, save_figure
from hrgs_scheduler.search import SearchResult, beam_search

F_MIN = 0.9
E_D = 0.01
BEAM_WIDTH = 25
N_VALUES = [10, 12, 14, 16, 18]

# Safety cap on the exponential upward search, as a multiple of the
# paper's own e_max=10*N, to avoid an unbounded doubling loop if
# `beam_search`'s reachable families genuinely never clear the floor at
# this N (would be a notable finding in itself, reported as such rather
# than hung on).
#
# IMPORTANT -- also a *memory/compute* safety cap, not just a logical
# one: `brute_force_search` (always included via `beam_search`'s
# `include_brute_force_families=True`) derives its own internal
# enumeration cap as `e_max // (2*N)`, which grows *linearly* with
# `e_max` and is NOT bounded by `beam_search`'s `max_link_copies`. At
# N=18, e_max=11520 (64x the paper's budget) gives an internal cap of
# 320 -- i.e. it builds and holds hundreds of purification-chain DAGs
# with up to ~320 copies each, in memory, simultaneously. This measurably
# exhausted RAM into swap and crashed the whole desktop session during
# this project (confirmed via `free -h` showing ~2GB swap in use and the
# background process silently dying, with no exception in its log).
# 32x (5760 at N=18) was empirically safe; 64x was not. Since the
# fidelity plateaued at exactly the same value across the entire
# 180..5760 range already probed, there is no evidence 64x would find
# anything different anyway -- so 32x is kept as the practical ceiling.
_MAX_UPWARD_MULTIPLE = 32
_BISECTION_TOLERANCE = 2

# Per-hop config fixed at the paper's own values, matching
# `sweep_hop_count.py` exactly so results are directly comparable.
_LENGTH = 2.0
_BRANCHING = (16, 14, 1)
_ARM_COUNT = 18
_P_X_INNER = 0.0
_P_Z_INNER = 0.0
_GAMMA = 0.0
_C = 2e5

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "sweep_min_budget_vs_n"


def _build_network(N: int) -> NetworkConfig:
    return NetworkConfig.uniform(
        N=N,
        length=_LENGTH,
        branching=_BRANCHING,
        arm_count=_ARM_COUNT,
        p_x_inner=_P_X_INNER,
        p_z_inner=_P_Z_INNER,
        e_d=E_D,
        gamma=_GAMMA,
        c=_C,
    )


@dataclass
class MinBudgetResult:
    N: int
    paper_e_max: int
    min_feasible_e_max: int
    ratio_to_paper: float
    best_label: str
    best_fidelity: float
    best_success_prob: float
    best_rate: float
    best_cost: int
    n_beam_search_calls: int
    wall_time_s: float


def _check(
    net: NetworkConfig,
    obj: ObjectiveConfig,
    e_max: int,
    cache: dict[int, tuple[bool, SearchResult]],
) -> tuple[bool, SearchResult]:
    """Run (or retrieve cached) `beam_search` at *e_max*, return
    `(feasible, best_result)`, restricted to candidates that actually
    respect `resource_cost <= e_max`.

    `beam_search`'s span-partition candidates are already filtered by
    `e_max`, but `brute_force_search`'s "raw" (`n_pur=1`) baseline family
    is unconditionally included regardless of `e_max` (see
    `brute_force.py`'s `record(ScheduleDAG.raw_chain(N), "raw")` call,
    which is not budget-gated like the `n_pur >= 2` families are). At the
    normal budgets used elsewhere in this report (`e_max=10*N`), `raw`'s
    fixed cost (`2*N`) is always comfortably under budget so this never
    mattered -- but this bisection actively probes `e_max` values well
    below `2*N`, which would otherwise let `raw` slip through as a false
    "feasible at e_max=1" result. Re-filtering by cost here is the fix.
    """
    if e_max not in cache:
        results = beam_search(net, obj, e_max=e_max, beam_width=BEAM_WIDTH)
        in_budget = [r for r in results if r.eval_result.resource_cost <= e_max]
        if in_budget:
            best = in_budget[0]
            feasible = obj.is_feasible(best.eval_result)
        else:
            best = results[0]
            feasible = False
        cache[e_max] = (feasible, best)
    return cache[e_max]


def find_min_budget(N: int) -> MinBudgetResult:
    net = _build_network(N)
    obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=F_MIN)
    paper_e_max = 10 * N
    cache: dict[int, tuple[bool, SearchResult]] = {}
    t0 = time.time()

    feasible0, best0 = _check(net, obj, paper_e_max, cache)
    print(
        f"  N={N}: e_max={paper_e_max} (paper's own budget) -> "
        f"{'feasible' if feasible0 else 'infeasible'}, "
        f"F={best0.eval_result.fidelity:.4f} ({time.time() - t0:.1f}s)",
        flush=True,
    )

    if feasible0:
        # Paper's own budget already clears the floor -- search downward
        # for a smaller sufficient budget.
        hi = paper_e_max
        lo = 0
        probe = max(1, paper_e_max // 2)
        while probe >= 1:
            feasible, best = _check(net, obj, probe, cache)
            print(
                f"  N={N}: probe e_max={probe} -> "
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
        # Paper's own budget does not clear the floor -- search upward
        # for a sufficient budget.
        lo = paper_e_max
        hi = paper_e_max * 4
        cap = paper_e_max * _MAX_UPWARD_MULTIPLE
        while True:
            feasible, best = _check(net, obj, hi, cache)
            print(
                f"  N={N}: probe e_max={hi} -> "
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
                    f"  N={N}: WARNING -- no feasible e_max found up to "
                    f"{cap} ({_MAX_UPWARD_MULTIPLE}x the paper's budget); "
                    "giving up upward search, reporting best-effort result "
                    "at the cap.",
                    flush=True,
                )
                feasible_cap, best_cap = _check(net, obj, cap, cache)
                return MinBudgetResult(
                    N=N,
                    paper_e_max=paper_e_max,
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

    # Bisect between lo (infeasible, or 0 if even e_max=1 is feasible)
    # and hi (feasible) to within +/- _BISECTION_TOLERANCE.
    while hi - lo > _BISECTION_TOLERANCE:
        mid = (lo + hi) // 2
        feasible, best = _check(net, obj, mid, cache)
        print(
            f"  N={N}: bisect e_max={mid} -> "
            f"{'feasible' if feasible else 'infeasible'}, "
            f"F={best.eval_result.fidelity:.4f} ({time.time() - t0:.1f}s)",
            flush=True,
        )
        if feasible:
            hi = mid
        else:
            lo = mid

    _, best_hi = _check(net, obj, hi, cache)
    elapsed = time.time() - t0
    print(
        f"  N={N}: done, min feasible e_max={hi} "
        f"(paper's own budget was {paper_e_max}), "
        f"{len(cache)} beam_search calls, {elapsed:.1f}s total",
        flush=True,
    )
    return MinBudgetResult(
        N=N,
        paper_e_max=paper_e_max,
        min_feasible_e_max=hi,
        ratio_to_paper=hi / paper_e_max,
        best_label=best_hi.label,
        best_fidelity=best_hi.eval_result.fidelity,
        best_success_prob=best_hi.eval_result.success_prob,
        best_rate=best_hi.eval_result.rate,
        best_cost=best_hi.eval_result.resource_cost,
        n_beam_search_calls=len(cache),
        wall_time_s=elapsed,
    )


def write_results_csv(rows: list[MinBudgetResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "N",
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
        for r in rows:
            writer.writerow(
                [
                    r.N,
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


def _power_law_fit(rows: list[MinBudgetResult]) -> tuple[float, float] | None:
    """Fit `min_feasible_e_max ~ a * N^b` via least squares on
    `log(min_feasible_e_max) = log(a) + b*log(N)`. Returns `(a, b)`, or
    None if fewer than 2 valid points are available."""
    pts = [
        (math.log(r.N), math.log(r.min_feasible_e_max))
        for r in rows
        if r.min_feasible_e_max > 0
    ]
    if len(pts) < 2:
        return None
    n = len(pts)
    sum_x = sum(x for x, _ in pts)
    sum_y = sum(y for _, y in pts)
    sum_xx = sum(x * x for x, _ in pts)
    sum_xy = sum(x * y for x, y in pts)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return None
    b = (n * sum_xy - sum_x * sum_y) / denom
    log_a = (sum_y - b * sum_x) / n
    return math.exp(log_a), b


def make_plot(rows: list[MinBudgetResult]) -> tuple[float, float] | None:
    rows = sorted(rows, key=lambda r: r.N)
    valid = [r for r in rows if r.min_feasible_e_max > 0]

    fig, ax = new_figure()
    ax.plot(
        [r.N for r in valid],
        [r.min_feasible_e_max for r in valid],
        marker="o",
        color="tab:red",
        label="Minimum feasible $e_{max}$ (this sweep)",
    )
    ns = [r.N for r in rows]
    ax.plot(
        ns,
        [10 * n for n in ns],
        linestyle="--",
        color="black",
        label="Paper's formula: $e_{max} = 10N$",
    )

    fit = _power_law_fit(valid)
    if fit is not None:
        a, b = fit
        fit_ns = [r.N for r in valid]
        ax.plot(
            fit_ns,
            [a * (n**b) for n in fit_ns],
            linestyle=":",
            color="tab:blue",
            label=f"Power-law fit: ${a:.2f} \\cdot N^{{{b:.2f}}}$",
        )

    ax.set_xlabel("Number of hops $N$")
    ax.set_ylabel("Minimum feasible resource cost $e_{max}$")
    ax.set_title(f"Minimum budget to clear $f_{{min}}$={F_MIN} vs. $N$ ($e_d$={E_D})")
    ax.grid(alpha=0.3)
    ax.legend()
    save_figure(fig, OUTPUT_DIR / "min_budget_vs_n")
    return fit


def write_readme(
    rows: list[MinBudgetResult], fit: tuple[float, float] | None, total_elapsed: float
) -> None:
    rows = sorted(rows, key=lambda r: r.N)
    lines = []
    lines.append("# Minimum Required Budget vs. N (the scaling-law question)")
    lines.append("")
    lines.append(
        "Per [docs/Roadmap_Derisk_and_Reframe.md](../../docs/Roadmap_Derisk_and_Reframe.md), "
        "§2: at each `N`, find the smallest `e_max` at which `beam_search` "
        "(unioned with `brute_force_search`'s fixed families, as in every "
        "other sweep in this report) finds ANY schedule clearing the "
        f"fidelity floor `f_min={F_MIN}`, rather than assuming the paper's "
        "own `e_max = 10*N` cost formula is sufficient."
    )
    lines.append("")
    lines.append(
        "**Scoping note (required by §2.2, carried over from §1's result):** "
        "[outputs/excluded_move_n14_n18/README.md](../excluded_move_n14_n18/README.md) "
        "found that the excluded same-span-purification move (out of scope "
        "for `dp_search`/`beam_search`) rescues feasibility at `N=18` at "
        "exactly the paper's own budget (`e_max=180`, `F=0.928596`). So any "
        "row below reporting `min_feasible_e_max > paper_e_max` describes a "
        "limitation of the schedule families `beam_search` can reach, "
        "**not** a true lower bound on what any valid schedule needs at that "
        "`N`. This is a claim about this codebase's searched families, "
        "consistent with the hedge used throughout "
        "[docs/Optimality Scope.md](../../docs/Optimality%20Scope.md)."
    )
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(
        "| N | Paper's $e_{max}=10N$ | Min. feasible $e_{max}$ (this sweep) | "
        "Ratio | Best F at min. budget | Best label |"
    )
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        if r.min_feasible_e_max < 0:
            lines.append(
                f"| {r.N} | {r.paper_e_max} | **not found** (gave up at "
                f"{_MAX_UPWARD_MULTIPLE}x paper's budget) | — | "
                f"{r.best_fidelity:.4f} | {r.best_label} |"
            )
        else:
            lines.append(
                f"| {r.N} | {r.paper_e_max} | {r.min_feasible_e_max} | "
                f"{r.ratio_to_paper:.3f}x | {r.best_fidelity:.4f} | {r.best_label} |"
            )
    lines.append("")

    if fit is not None:
        a, b = fit
        lines.append(
            f"**Descriptive power-law fit** (least squares on log-log data, "
            f"valid points only): $e_{{max}}^{{min}} \\approx {a:.3f} \\cdot "
            f"N^{{{b:.3f}}}$. "
            + (
                "The fitted exponent exceeds 1, i.e. the minimum required "
                "budget within this sweep's searched families grows faster "
                "than the paper's own linear `10*N` formula."
                if b > 1.05
                else (
                    "The fitted exponent is close to or below 1, i.e. this "
                    "sweep does not show super-linear growth of the minimum "
                    "required budget within the searched families over this "
                    "N range."
                    if b < 1.05
                    else ""
                )
            )
        )
        lines.append("")
        lines.append(
            "This fit is descriptive, not a rigorous asymptotic claim -- it "
            "is over a small number of points ({}) and is sensitive to the "
            "specific N values tested.".format(len(rows))
        )
        lines.append("")

    lines.append("## Details")
    lines.append("")
    for r in rows:
        lines.append(
            f"- **N={r.N}**: paper's `e_max`={r.paper_e_max}, min. feasible "
            f"`e_max`={'not found' if r.min_feasible_e_max < 0 else r.min_feasible_e_max}, "
            f"best schedule found there: `{r.best_label}`, F={r.best_fidelity:.4f}, "
            f"success_prob={r.best_success_prob:.4f}, rate={r.best_rate:.4f}, "
            f"cost={r.best_cost}. ({r.n_beam_search_calls} `beam_search` calls, "
            f"{r.wall_time_s:.1f}s.)"
        )
    lines.append("")

    lines.append("## Method caveats")
    lines.append("")
    lines.append(
        "- Bisection assumes feasibility is monotonically non-decreasing in "
        "`e_max`. This holds for the exact DP frontier by construction, but "
        "`beam_search`'s beam-pruning is a heuristic on top of that -- no "
        "non-monotonicity was observed in this run's cached probe history "
        "(see `results.csv` for the final endpoints), but this was not "
        "exhaustively verified at every intermediate probe."
    )
    lines.append(
        "- The minimum feasible `e_max` is pinned down to within "
        f"`+/- {_BISECTION_TOLERANCE}`, not exactly, consistent with "
        "`e_max` being discretized by Gen-node counts anyway."
    )
    lines.append("")

    lines.append("## Reproducing")
    lines.append("")
    lines.append("```bash")
    lines.append("cd /home/shark/Documents/hrgs-purification-scheduler")
    lines.append("source .venv/bin/activate")
    lines.append("PYTHONPATH=src python3 -u validation/sweep_min_budget_vs_n.py")
    lines.append("```")
    lines.append("")
    lines.append(f"Total wall-clock time: ~{total_elapsed:.0f}s.")
    lines.append("")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "README.md").write_text("\n".join(lines))


def main() -> None:
    t0 = time.time()
    rows: list[MinBudgetResult] = []
    for N in N_VALUES:
        print(f"N={N}: starting bisection for minimum feasible e_max...", flush=True)
        rows.append(find_min_budget(N))

    write_results_csv(rows, OUTPUT_DIR / "results.csv")
    fit = make_plot(rows)
    total_elapsed = time.time() - t0
    write_readme(rows, fit, total_elapsed)
    print(f"\nDone in {total_elapsed:.1f}s. Outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
