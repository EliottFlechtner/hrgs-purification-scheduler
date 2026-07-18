"""
validation/search_results.py
==============================
Run brute-force schedule search and export / display the results.

Quick start
-----------
    # Print table to terminal (paper config, default objective)
    python validation/search_results.py

    # Tighter noise, higher fidelity floor, export CSV + JSON
    python validation/search_results.py --e_d 0.01 --f_min 0.92 \\
        --csv outputs/search/run_ed01.csv \\
        --json outputs/search/run_ed01.json

    # Custom N with uniform network, maximize raw fidelity
    python validation/search_results.py --N 3 --uniform \\
        --objective fidelity --e_max 30

    # Show only feasible results, cap at top 20
    python validation/search_results.py --top 20 --no-infeasible

CLI flags
---------
    --N INT             Number of hops (default: 10, paper config)
    --uniform           Use a uniform network instead of the paper config
    --e_d FLOAT         Depolarizing error per operation (default: 0.005)
    --e_max INT         Resource budget: max Gen-node count (default: 40)
    --f_min FLOAT       Fidelity floor for the feasibility constraint
                        (default: 0.90; set to 0 to disable)
    --objective STR     Primary objective: 'rate' (default) or 'fidelity'
    --top INT           Print only the top N results (default: all)
    --no-infeasible     Suppress infeasible rows from the printed table
    --csv PATH          Export results to CSV at this path
    --json PATH         Export results to JSON at this path
    --no-heralded       Exclude end-node heralded strategy family
    --no-optimistic     Exclude end-node optimistic strategy family
    --no-link           Exclude link-level strategy family
    --max-n-pur INT     Hard cap on purification copy count
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve project root so the script can be run from any directory.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.search import brute_force_search, print_table, to_csv, to_json


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Brute-force schedule search and result export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--N", type=int, default=10, help="Number of hops (default: 10)")
    p.add_argument(
        "--uniform",
        action="store_true",
        help="Use a uniform network (length=2km/hop) instead of the paper config",
    )
    p.add_argument("--e_d", type=float, default=0.005, help="Depolarizing error rate")
    p.add_argument("--e_max", type=int, default=40, help="Max Gen-node budget")
    p.add_argument("--f_min", type=float, default=0.90, help="Fidelity floor")
    p.add_argument(
        "--objective",
        choices=["rate", "fidelity"],
        default="rate",
        help="Primary objective (default: rate)",
    )
    p.add_argument("--top", type=int, default=None, help="Show only top N results")
    p.add_argument(
        "--no-infeasible",
        action="store_true",
        help="Hide infeasible rows from printed table",
    )
    p.add_argument("--csv", type=Path, default=None, help="Export CSV to this path")
    p.add_argument("--json", type=Path, default=None, help="Export JSON to this path")
    p.add_argument("--no-heralded", action="store_true")
    p.add_argument("--no-optimistic", action="store_true")
    p.add_argument("--no-link", action="store_true")
    p.add_argument(
        "--max-n-pur",
        type=int,
        default=None,
        dest="max_n_pur",
        help="Hard cap on purification copy count",
    )
    return p


def _build_network(args: argparse.Namespace) -> NetworkConfig:
    if args.uniform:
        return NetworkConfig.uniform(
            N=args.N,
            length=2.0,
            branching=(16, 14, 1),
            arm_count=18,
            p_x_inner=0.003,
            p_z_inner=0.003,
            e_d=args.e_d,
            gamma=1e-3,
            c=2e5,
        )
    # Paper config ignores --N when not uniform (it's fixed at 10).
    if args.N != 10:
        print(
            f"Warning: --N={args.N} is ignored when using the paper config "
            f"(N is fixed at 10). Use --uniform to vary N.",
            file=sys.stderr,
        )
    return NetworkConfig.integrating_paper_config(e_d=args.e_d)


def _build_objective(args: argparse.Namespace) -> ObjectiveConfig:
    if args.objective == "rate":
        return ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=args.f_min)
    # fidelity objective: maximise F, no rate floor
    return ObjectiveConfig(primary="fidelity", maximise=True, f_min=args.f_min)


def main() -> None:
    args = _build_parser().parse_args()

    network = _build_network(args)
    objective = _build_objective(args)

    N = network.N
    print(
        f"Network: N={N}, e_d={args.e_d}, total_length={network.total_length():.1f} km"
    )
    print(f"Objective: {args.objective}, f_min={args.f_min}, e_max={args.e_max}")
    print("Running brute-force search …", flush=True)

    results = brute_force_search(
        network,
        objective,
        e_max=args.e_max,
        max_n_pur=args.max_n_pur,
        include_heralded=not args.no_heralded,
        include_optimistic=not args.no_optimistic,
        include_link_level=not args.no_link,
    )

    feasible = [r for r in results if r.score > float("-inf")]
    print(f"Done — {len(results)} candidates evaluated, {len(feasible)} feasible.\n")

    print_table(results, top=args.top, show_infeasible=not args.no_infeasible)

    if args.csv:
        path = to_csv(results, args.csv)
        print(f"\nCSV written → {path}")

    if args.json:
        path = to_json(results, args.json)
        print(f"JSON written → {path}")


if __name__ == "__main__":
    main()
