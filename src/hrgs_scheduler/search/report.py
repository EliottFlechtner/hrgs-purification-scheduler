"""
hrgs_scheduler.search.report
==============================
Utilities for displaying and exporting search results.

Typical usage
-------------
    from hrgs_scheduler.search import brute_force_search, print_table, to_csv

    results = brute_force_search(net, obj, e_max=40)
    print_table(results)
    to_csv(results, "outputs/search/my_run.csv")
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import IO, Sequence

from hrgs_scheduler.search.brute_force import SearchResult

# ---------------------------------------------------------------------------
# ASCII table
# ---------------------------------------------------------------------------

_HEADERS = ("Rank", "Label", "F", "R", "C", "L (ms)", "P_succ", "Score")
_COL_WIDTHS = (5, 48, 8, 14, 5, 10, 8, 14)
_SEP = "  "


def _row(
    rank: int | str,
    label: str,
    f: str,
    r: str,
    c: str,
    l_ms: str,
    p: str,
    score: str,
) -> str:
    vals = (rank, label, f, r, c, l_ms, p, score)
    return _SEP.join(
        str(v).ljust(w) if i < 2 else str(v).rjust(w)
        for i, (v, w) in enumerate(zip(vals, _COL_WIDTHS))
    )


def print_table(
    results: Sequence[SearchResult],
    *,
    top: int | None = None,
    show_infeasible: bool = True,
    file: IO[str] | None = None,
) -> None:
    """Print a formatted ASCII table of search results to *file* (default stdout).

    Parameters
    ----------
    results : sequence of SearchResult
        Ordered list as returned by ``brute_force_search`` (best-first).
    top : int, optional
        If given, print only the first *top* rows.
    show_infeasible : bool
        When False, rows with score == -inf are suppressed.
    file : writable text stream, optional
        Output destination.  Defaults to ``sys.stdout``.
    """
    import sys

    out = file or sys.stdout
    rows = list(results)
    if not show_infeasible:
        rows = [r for r in rows if r.score > float("-inf")]
    if top is not None:
        rows = rows[:top]

    header = _row(*_HEADERS)
    divider = "-" * len(header)
    print(header, file=out)
    print(divider, file=out)

    for i, res in enumerate(rows, 1):
        ev = res.eval_result
        inf = res.score == float("-inf")
        score_str = "-inf" if inf else f"{res.score:.2f}"
        r_str = "N/A" if ev.rate == 0 else f"{ev.rate:.2f}"
        print(
            _row(
                i,
                res.label,
                f"{ev.fidelity:.4f}",
                r_str,
                ev.resource_cost,  # type: ignore[format]
                f"{ev.latency * 1e3:.4f}",
                f"{ev.success_prob:.4f}",
                score_str,
            ),
            file=out,
        )

    print(f"\n{len(rows)} result(s) shown.", file=out)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "rank",
    "label",
    "fidelity",
    "rate",
    "resource_cost",
    "latency_s",
    "p_success",
    "score",
]


def to_csv(
    results: Sequence[SearchResult],
    path: str | Path,
    *,
    include_infeasible: bool = True,
) -> Path:
    """Write search results to a CSV file and return the resolved path.

    Parameters
    ----------
    results : sequence of SearchResult
        Results to export (any ordering).
    path : str or Path
        Destination file path.  Parent directories are created if needed.
    include_infeasible : bool
        When False, rows with score == -inf are omitted.

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    rows_to_write = list(results)
    if not include_infeasible:
        rows_to_write = [r for r in rows_to_write if r.score > float("-inf")]

    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for rank, res in enumerate(rows_to_write, 1):
            ev = res.eval_result
            writer.writerow(
                {
                    "rank": rank,
                    "label": res.label,
                    "fidelity": ev.fidelity,
                    "rate": ev.rate,
                    "resource_cost": ev.resource_cost,
                    "latency_s": ev.latency,
                    "p_success": ev.success_prob,
                    "score": res.score,
                }
            )

    return out


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def to_json(
    results: Sequence[SearchResult],
    path: str | Path,
    *,
    include_infeasible: bool = True,
) -> Path:
    """Write search results to a JSON file and return the resolved path.

    Each entry is a flat dict with the same fields as ``to_csv``, plus a
    ``"feasible"`` boolean for convenient filtering in downstream scripts.

    Parameters
    ----------
    results : sequence of SearchResult
        Results to export.
    path : str or Path
        Destination file path.  Parent directories are created if needed.
    include_infeasible : bool
        When False, infeasible results are omitted.

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    rows_to_write = list(results)
    if not include_infeasible:
        rows_to_write = [r for r in rows_to_write if r.score > float("-inf")]

    records = []
    for rank, res in enumerate(rows_to_write, 1):
        ev = res.eval_result
        score = res.score
        records.append(
            {
                "rank": rank,
                "label": res.label,
                "fidelity": ev.fidelity,
                "rate": ev.rate,
                "resource_cost": ev.resource_cost,
                "latency_s": ev.latency,
                "p_success": ev.success_prob,
                "score": score if score != float("-inf") else None,
                "feasible": score > float("-inf"),
            }
        )

    with out.open("w") as f:
        json.dump(records, f, indent=2)

    return out
