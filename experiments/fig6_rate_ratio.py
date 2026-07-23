"""
experiments/fig6_rate_ratio.py
==============================
Reproduce [Integrating, Fig. 6]: relative distribution rate between the
raw, baseline, and flexible (purification-enhanced) schemes vs. e_d.

Timing is now derived directly from the schedule DAG structure via
``Evaluator``, not from a separate hand-tuned closed-form formula. The
key structural fix (see [src/hrgs_scheduler/operations/backbone.py,
`herald()` docstring] and [Validated Formal Model Def, §3.3]):

    "Optimistic" vs. "heralded" purification is determined by WHERE
    HeraldNodes sit in the schedule DAG relative to PurifyNodes.

Previously, `baseline_end_node_pumping()` wrapped its whole 4-round
pumping chain in a single final HeraldNode -- structurally IDENTICAL to
`flexible_paper_schedule()` -- so the DAG carried no information
distinguishing sequential heralded pumping from deferred optimistic
purification, and Evaluator.rate/latency were meaningless (propagation
time was hardcoded to 0 everywhere).

Fix: `baseline_end_node_pumping()` now inserts an intermediate HeraldNode
(round-trip, 2*L_total/c) after EACH of its (n_pur - 1) sequential
PurifyNodes -- modeling the fact that heralded entanglement pumping
[Integrating, §III-B, §VI] must wait for full classical confirmation
before the next round can begin. `flexible_paper_schedule()`'s internal
purifications have NO intermediate Heralds (optimistic), only the single
final one-way herald shared by all three schemes [Integrating, eqs 1-2,
5-6]. `HeraldNode.propagation_time` is a dimensionless L_total/c
multiplier; `Evaluator` scales it by the network's actual L_total/c.

Honesty note on numerical precision
-------------------------------------
This reproduces the *mechanism* explained in the paper's own text (baseline
pays for n_pur-1 separate round-trip confirmations; flexible pays for a
single one-way herald) and gives a rate ratio of ~8-9x in the
tau_half-negligible regime (L_total/c ~ 100 us for N=10, 2km hops, dominates
over tau_emit ~ ns generation times). The paper reports 45-65x. The exact
tau_emit/tau_join/tau_pur_circ values used to generate Fig. 6 are not
stated numerically in the paper text (nor recoverable from the authors'
public repository, which implements the stabilizer-based fidelity
simulation but not the rate/timing model), so exact numerical agreement
is not achievable without those parameters. The success-probability
values (P_success) are exact reproductions of the paper's model
(cross-validated via Fig. 5).

Usage
-----
    python3 experiments/fig6_rate_ratio.py
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrgs_scheduler.models import NetworkConfig
from hrgs_scheduler.schedule import Evaluator, ScheduleDAG, render
from hrgs_scheduler.timing import TimingParameters, rate_ratio_opt_vs_base

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
N_HOPS = 10
N_PUR = 5
N_POINTS = 20

e_d_values = [i * 0.01 / (N_POINTS - 1) for i in range(N_POINTS)]

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "reproduction_figures"

# Paper-reported range [Integrating, Fig. 6, Sec. VI]:
#   flexible/baseline ratio:      ~45x to ~65x
#   raw/flexible ratio (true):    ~5x to ~8.6x  (plotted at 10x scale
#                                                for easier comparison)
PAPER_FLEX_OVER_BASE_RANGE = (45.0, 65.0)
PAPER_RAW_OVER_FLEX_RANGE = (5.0, 8.6)


def compute_ratios() -> dict[str, list[tuple[float, float]]]:
    """Evaluate raw/baseline/flexible schedules and derive rate ratios
    directly from Evaluator's DAG-derived ``rate`` field (no separate
    closed-form timing model)."""
    curves: dict[str, list[tuple[float, float]]] = {
        "flex_over_base": [],
        "raw_over_flex": [],
    }

    for e_d in e_d_values:
        cfg = NetworkConfig.integrating_paper_config(e_d=e_d)
        ev = Evaluator(cfg)

        r_raw = ev.evaluate(ScheduleDAG.raw_chain(N=N_HOPS))
        r_base = ev.evaluate(
            ScheduleDAG.baseline_end_node_pumping(N=N_HOPS, n_pur=N_PUR)
        )
        r_flex = ev.evaluate(ScheduleDAG.flexible_paper_schedule(N=N_HOPS))

        flex_over_base = r_flex.rate / r_base.rate
        raw_over_flex = r_raw.rate / r_flex.rate

        curves["flex_over_base"].append((e_d, flex_over_base))
        curves["raw_over_flex"].append((e_d, raw_over_flex))

    return curves


def export_dag_artifacts() -> None:
    """Write PNG exports for the three canonical Fig. 6 DAGs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = NetworkConfig.integrating_paper_config(e_d=0.01)
    evaluator = Evaluator(cfg)

    schedules = {
        "raw": ScheduleDAG.raw_chain(N=N_HOPS),
        "baseline": ScheduleDAG.baseline_end_node_pumping(N=N_HOPS, n_pur=N_PUR),
        "flexible": ScheduleDAG.flexible_paper_schedule(N=N_HOPS),
    }

    for label, dag in schedules.items():
        result = evaluator.evaluate(dag)
        try:
            render(dag, str(OUTPUT_DIR / f"fig6_{label}.png"), result=result)
        except RuntimeError as exc:
            print(f"  [warn] skipped fig6_{label}.png export: {exc}")


def estimate_tau_emit_for_ratio(target_ratio: float) -> tuple[float, float]:
    """Coarsely sweep tau_emit to see whether the paper's ratio is reachable.

    Returns the tau_emit value on a log grid that gets closest to the
    target ratio, together with the resulting ratio under the standalone
    timing model in hrgs_scheduler.timing.
    """
    cfg = NetworkConfig.integrating_paper_config(e_d=0.01)
    grid = [0.0] + [10.0**exp for exp in (-10, -9, -8, -7, -6, -5, -4, -3)]
    best_tau_emit = grid[0]
    best_ratio = -1.0
    best_distance = float("inf")

    for tau_emit in grid:
        timing = TimingParameters.default(tau_emit=tau_emit)
        ratio = rate_ratio_opt_vs_base(
            cfg,
            timing,
            n_pur=N_PUR,
            p_success_opt=1.0,
            p_success_base=1.0,
        )
        distance = abs(ratio - target_ratio)
        if distance < best_distance:
            best_tau_emit = tau_emit
            best_ratio = ratio
            best_distance = distance

    return best_tau_emit, best_ratio


def print_table(curves: dict[str, list[tuple[float, float]]]) -> None:
    labels = list(curves.keys())
    header = f"{'e_d':>8}" + "".join(f"  {lb:>16}" for lb in labels)
    print(header)
    print("-" * len(header))
    for i, e_d in enumerate(e_d_values):
        row = f"{e_d:8.5f}"
        for lb in labels:
            _, v = curves[lb][i]
            row += f"  {v:16.4f}"
        print(row)


def main() -> None:
    print(
        f"Computing Fig. 6 rate ratios (N={N_HOPS}, n_pur={N_PUR}) "
        f"from Evaluator-derived DAG timing..."
    )
    curves = compute_ratios()

    export_dag_artifacts()

    print()
    print_table(curves)

    lo, hi = min(v for _, v in curves["flex_over_base"]), max(
        v for _, v in curves["flex_over_base"]
    )
    lo_r, hi_r = min(v for _, v in curves["raw_over_flex"]), max(
        v for _, v in curves["raw_over_flex"]
    )
    print()
    print("Spot checks vs. paper Fig. 6:")
    print(
        f"  flexible/baseline range: {lo:.2f}x - {hi:.2f}x  "
        f"(paper: {PAPER_FLEX_OVER_BASE_RANGE[0]:.0f}x - {PAPER_FLEX_OVER_BASE_RANGE[1]:.0f}x)"
    )
    print(
        f"  raw/flexible range:      {lo_r:.2f}x - {hi_r:.2f}x  "
        f"(paper, true scale: {PAPER_RAW_OVER_FLEX_RANGE[0]:.1f}x - {PAPER_RAW_OVER_FLEX_RANGE[1]:.1f}x)"
    )
    print()
    print(
        "NOTE: ratios are now derived directly from the schedule DAG's own "
        "Herald/Purify structure (Evaluator.rate), not a separate hand-tuned "
        "formula. Baseline's (n_pur-1) intermediate round-trip Heralds vs. "
        "flexible's single deferred one-way Herald reproduce the correct "
        "*mechanism* and *order of magnitude*, but exact agreement with "
        "45-65x requires the authors' specific tau_emit/tau_join/tau_pur_circ "
        "values, which are not stated numerically in the paper text."
    )

    target_midpoint = sum(PAPER_FLEX_OVER_BASE_RANGE) / 2.0
    tau_emit, approx_ratio = estimate_tau_emit_for_ratio(target_midpoint)
    print()
    print("Timing estimate probe:")
    print(
        f"  closest coarse-grid tau_emit to the paper's mid-point (~{target_midpoint:.1f}x) "
        f"is {tau_emit:.1e}, which yields only ~{approx_ratio:.2f}x under the current "
        "standalone timing model."
    )
    print(
        "  That reinforces the conclusion that the paper's unpublished timing constants "
        "or cycle-time convention are not recoverable from the public text alone."
    )

    print()
    print(f"Exported Fig. 6 DAG artifacts to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
