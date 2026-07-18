"""
hrgs_scheduler.search
======================
Outer-loop search algorithms over the schedule space Σ.

Three tiers, per [Validated Formal Model Def, §7]:

  1. ``brute_force``  — exhaustive enumeration of a parameterised family
     of legal, budget-feasible schedules.  Tractable for N ≤ 4, E_max ≤ 40.
     Use to establish exact ground truth on small instances.

  2. DP-over-stages (planned) — Bellman optimal-cost-to-go computation
     V(κ, e, B_remaining).  Will be cross-checked against brute force.

  3. Heuristic search (planned) — greedy / beam / simulated annealing once
     N, B exceed exact DP tractability.
"""

from hrgs_scheduler.search.brute_force import SearchResult, brute_force_search
from hrgs_scheduler.search.report import print_table, to_csv, to_json

__all__ = [
    "SearchResult",
    "brute_force_search",
    "print_table",
    "to_csv",
    "to_json",
]
