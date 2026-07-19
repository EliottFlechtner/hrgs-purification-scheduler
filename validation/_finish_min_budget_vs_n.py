"""
One-off resume script: the original `sweep_min_budget_vs_n.py` background
run was killed mid-way through N=18's upward exponential search (VS Code
crash killed the owning terminal/process group despite `nohup`). N=10,
12, 14, 16 had already fully completed and their final log lines are
hardcoded below (verified against `validation/sweep_min_budget_vs_n.log`)
so they don't need to be recomputed. Only N=18 is re-run from scratch
(cheap relative to the ~20 minutes already spent on N=10-16).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "validation"))

import sweep_min_budget_vs_n as m

# Reconstructed from the completed log lines for N=10, 12, 14, 16.
KNOWN_RESULTS = [
    m.MinBudgetResult(
        N=10,
        paper_e_max=100,
        min_feasible_e_max=50,
        ratio_to_paper=0.5,
        best_label="beam.span.??",
        best_fidelity=0.8987,
        best_success_prob=float("nan"),
        best_rate=float("nan"),
        best_cost=50,
        n_beam_search_calls=7,
        wall_time_s=60.4,
    ),
    m.MinBudgetResult(
        N=12,
        paper_e_max=120,
        min_feasible_e_max=67,
        ratio_to_paper=67 / 120,
        best_label="beam.span.??",
        best_fidelity=0.8993,
        best_success_prob=float("nan"),
        best_rate=float("nan"),
        best_cost=67,
        n_beam_search_calls=7,
        wall_time_s=177.8,
    ),
    m.MinBudgetResult(
        N=14,
        paper_e_max=140,
        min_feasible_e_max=82,
        ratio_to_paper=82 / 140,
        best_label="beam.span.??",
        best_fidelity=0.8996,
        best_success_prob=float("nan"),
        best_rate=float("nan"),
        best_cost=82,
        n_beam_search_calls=7,
        wall_time_s=334.1,
    ),
    m.MinBudgetResult(
        N=16,
        paper_e_max=160,
        min_feasible_e_max=128,
        ratio_to_paper=128 / 160,
        best_label="beam.span.??",
        best_fidelity=0.8990,
        best_success_prob=float("nan"),
        best_rate=float("nan"),
        best_cost=128,
        n_beam_search_calls=8,
        wall_time_s=653.9,
    ),
]


def main() -> None:
    # Re-derive N=10..16's actual best-result objects properly (with real
    # label/success_prob/rate/cost) via a *fresh* but very cheap re-check
    # at exactly their already-known min_feasible_e_max (single cached
    # beam_search call each, not a full bisection).
    print(
        "Re-deriving exact best-result details for N=10,12,14,16 at their "
        "already-known min_feasible_e_max (single call each)...",
        flush=True,
    )
    refined = []
    for known in KNOWN_RESULTS:
        net = m._build_network(known.N)
        obj = m.ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=m.F_MIN)
        cache: dict[int, tuple[bool, m.SearchResult]] = {}
        t0 = time.time()
        feasible, best = m._check(net, obj, known.min_feasible_e_max, cache)
        assert (
            feasible
        ), f"N={known.N}: re-check at {known.min_feasible_e_max} not feasible!"
        refined.append(
            m.MinBudgetResult(
                N=known.N,
                paper_e_max=known.paper_e_max,
                min_feasible_e_max=known.min_feasible_e_max,
                ratio_to_paper=known.ratio_to_paper,
                best_label=best.label,
                best_fidelity=best.eval_result.fidelity,
                best_success_prob=best.eval_result.success_prob,
                best_rate=best.eval_result.rate,
                best_cost=best.eval_result.resource_cost,
                n_beam_search_calls=known.n_beam_search_calls,
                wall_time_s=known.wall_time_s,
            )
        )
        print(f"  N={known.N}: re-checked in {time.time() - t0:.1f}s", flush=True)

    print("N=18: starting bisection for minimum feasible e_max...", flush=True)
    n18 = m.find_min_budget(18)
    refined.append(n18)

    m.write_results_csv(refined, m.OUTPUT_DIR / "results.csv")
    fit = m.make_plot(refined)
    total_elapsed = sum(r.wall_time_s for r in refined)
    m.write_readme(refined, fit, total_elapsed)
    print(f"\nDone. Outputs written to {m.OUTPUT_DIR}")


if __name__ == "__main__":
    main()
