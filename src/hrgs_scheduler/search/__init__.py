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
     full design rationale and documented scope limits. **Exact only
     for pumping-free schedules by default** — its "pumping" move (two
     independently-purified copies of the same span) is beam-limited for
     tractability by default, same tradeoff as tier 3, unless called
     with ``exact_pumping=True`` (uncapped, only tractable at very small
     N; see search/dp.py's "Exactness modes" docstring section).

  3. ``heuristic`` (``beam_search``) — same span-partition recursion as
     tier 2, but each span's frontier is capped at a fixed beam width
     instead of kept in full, trading Pareto-exactness for tractability
     at N/e_max beyond DP's reach (e.g. the paper's N=10 config). Since
     tier 2's own pumping is now also beam-limited by default, tier 2's
     default output is not a guaranteed upper bound on tier 3 once
     pumping is involved — see ``dp_search(..., exact_pumping=True)``
     for that comparison at small N.
     See search/heuristic.py.
"""

from hrgs_scheduler.search.brute_force import SearchResult, brute_force_search
from hrgs_scheduler.search.dp import dp_search
from hrgs_scheduler.search.heuristic import beam_search
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
    "beam_search",
    "print_table",
    "to_csv",
    "to_json",
    "save_result",
    "load_result",
    "save_top",
]
