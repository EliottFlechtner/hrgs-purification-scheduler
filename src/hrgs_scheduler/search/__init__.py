"""
hrgs_scheduler.search
======================
Outer-loop search algorithms over the schedule space Σ.

Three tiers, per [Validated Formal Model Def, §7]:

  1. ``brute_force``  — exhaustive enumeration of a parameterised family
     of legal, budget-feasible schedules.  Tractable for N ≤ 4, E_max ≤ 40.
     Use to establish exact ground truth on small instances.

  2. ``dp``  — memoized recursive search over span-partition structures
     (Bellman-style optimal-cost-to-go over the span partial order),
     combined with brute_force's fixed families.  Always a superset of
     brute_force_search on the same inputs; see search/dp.py for the
     full design rationale and documented scope limits.

  3. Heuristic search (planned) — greedy / beam / simulated annealing once
     N, B exceed exact DP tractability.
"""

from hrgs_scheduler.search.brute_force import SearchResult, brute_force_search
from hrgs_scheduler.search.dp import dp_search
from hrgs_scheduler.search.report import (
    load_result,
    print_table,
    save_result,
    save_top,
    to_csv,
    to_json,
)

__all__ = [
    "SearchResult",
    "brute_force_search",
    "dp_search",
    "print_table",
    "to_csv",
    "to_json",
    "save_result",
    "load_result",
    "save_top",
]
