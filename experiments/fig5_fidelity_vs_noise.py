"""
experiments/fig5_fidelity_vs_noise.py
=====================================
Reproduce [Integrating, Fig. 5]: fidelity F vs. outer-qubit depolarizing
error probability e_d for the paper's exact network configuration:

    N=10, ell=2 km, b=(16,14,1), k=18, e_d in [0, 0.01]

Three curves are compared, exactly mirroring [Integrating, Sec. V-VI, Fig. 4]:

  1. raw       - ScheduleDAG.raw_chain(N=10): no purification, 1 copy/hop.
  2. baseline  - ScheduleDAG.baseline_end_node_pumping(N=10, n_pur=5):
                 5 independent raw end-to-end pairs, pumped via
                 YY -> ZX -> YY -> XZ at the end nodes.
  3. flexible  - ScheduleDAG.flexible_paper_schedule(N=10): the
                 purification-enhanced scheme from Fig. 4 (link-level YY
                 + two 5-hop-segment YY + 1 raw pair, combined via
                 ZX then YY at the end nodes).

Both purified schemes consume exactly 5 half-RGS copies per side per hop
(100 Gen nodes total for N=10), matching the paper's resource-normalized
comparison.

Expected results (read from Fig. 5, e_d=0.01)
----------------------------------------------
    raw      ~ 0.823 - 0.825
    baseline ~ 0.917 - 0.918
    flexible ~ 0.928 - 0.930

Usage
-----
    python3 experiments/fig5_fidelity_vs_noise.py

Optional matplotlib output: set PLOT=True below.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrgs_scheduler.models import NetworkConfig
from hrgs_scheduler.schedule import Evaluator, ScheduleDAG, render

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
PLOT = False  # set True if matplotlib is available
N_HOPS = 10
N_PUR = 5  # half-RGS copies per side per hop (paper: 5)
N_POINTS = 20  # number of e_d sample points

e_d_values = [i * 0.01 / (N_POINTS - 1) for i in range(N_POINTS)]

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "reproduction_figures"

# Paper reference values read off Fig. 5 at e_d = 0.000 and e_d = 0.010
PAPER_REFERENCE = {
    "raw": {0.000: 1.000, 0.010: 0.823},
    "baseline": {0.000: 1.000, 0.010: 0.917},
    "flexible": {0.000: 1.000, 0.010: 0.929},
}


# ------------------------------------------------------------------
# Core computation
# ------------------------------------------------------------------


def compute_curves() -> dict[str, list[tuple[float, float]]]:
    """Compute (e_d, fidelity) pairs for raw, baseline, and flexible schedules."""
    curves: dict[str, list[tuple[float, float]]] = {
        "raw": [],
        "baseline": [],
        "flexible": [],
    }

    for e_d in e_d_values:
        cfg = NetworkConfig.integrating_paper_config(e_d=e_d)
        ev = Evaluator(cfg)

        dag_raw = ScheduleDAG.raw_chain(N=N_HOPS)
        dag_base = ScheduleDAG.baseline_end_node_pumping(N=N_HOPS, n_pur=N_PUR)
        dag_flex = ScheduleDAG.flexible_paper_schedule(N=N_HOPS)

        curves["raw"].append((e_d, ev.evaluate(dag_raw).fidelity))
        curves["baseline"].append((e_d, ev.evaluate(dag_base).fidelity))
        curves["flexible"].append((e_d, ev.evaluate(dag_flex).fidelity))

    return curves


def export_dag_artifacts() -> None:
    """Write PNG exports for the three canonical Fig. 5 DAGs."""
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
            render(dag, str(OUTPUT_DIR / f"fig5_{label}.png"), result=result)
        except RuntimeError as exc:
            print(f"  [warn] skipped fig5_{label}.png export: {exc}")


# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------


def print_table(curves: dict[str, list[tuple[float, float]]]) -> None:
    labels = list(curves.keys())
    header = f"{'e_d':>8}" + "".join(f"  {lb:>10}" for lb in labels)
    print(header)
    print("-" * len(header))
    for i, e_d in enumerate(e_d_values):
        row = f"{e_d:8.5f}"
        for lb in labels:
            _, f = curves[lb][i]
            row += f"  {f:10.6f}"
        print(row)


def main() -> None:
    print(f"Computing Fig. 5 curves (N={N_HOPS}, n_pur={N_PUR})...")
    curves = compute_curves()

    export_dag_artifacts()

    print()
    print_table(curves)

    print()
    print("Spot checks vs. paper Fig. 5:")
    for label in ("raw", "baseline", "flexible"):
        f0 = curves[label][0][1]
        f_max = curves[label][-1][1]
        ref0 = PAPER_REFERENCE[label][0.000]
        ref_max = PAPER_REFERENCE[label][0.010]
        print(
            f"  {label:<10} e_d=0.000: {f0:.4f} (paper ~{ref0:.3f})   "
            f"e_d=0.010: {f_max:.4f} (paper ~{ref_max:.3f})   "
            f"diff={f_max - ref_max:+.4f}"
        )

    if PLOT:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(7, 4))
            styles = {"raw": "--", "baseline": "-", "flexible": "-"}
            for label, curve in curves.items():
                xs, ys = zip(*curve)
                ax.plot(xs, ys, styles[label], marker="o", markersize=3, label=label)
            ax.set_xlabel(r"Depolarizing Error Probability $e_d$")
            ax.set_ylabel("Fidelity")
            ax.set_title(
                "Fidelity vs Depolarizing Error Probability with (16, 14, 1) code"
            )
            ax.legend()
            ax.grid(alpha=0.3)
            plt.tight_layout()
            plt.savefig("fig5_fidelity.png", dpi=150)
            print("\nSaved fig5_fidelity.png")
        except ImportError:
            print("matplotlib not available; set PLOT=True once installed")

    print()
    print(f"Exported Fig. 5 DAG artifacts to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
