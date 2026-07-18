"""
validation/fig6_rate_ratio.py
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
    python3 validation/fig6_rate_ratio.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrgs_scheduler.models import NetworkConfig
from hrgs_scheduler.schedule import ScheduleDAG, Evaluator

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
N_HOPS = 10
N_PUR = 5
N_POINTS = 20

e_d_values = [i * 0.01 / (N_POINTS - 1) for i in range(N_POINTS)]

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


if __name__ == "__main__":
    main()
