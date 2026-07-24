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
import re
from pathlib import Path
from typing import IO, Sequence

from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.schedule.evaluator import EvaluationResult
from hrgs_scheduler.schedule.serde import load_schedule as _load_schedule
from hrgs_scheduler.schedule.serde import save_schedule as _save_schedule
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


# ---------------------------------------------------------------------------
# Schedule artifact: structural save / load
# ---------------------------------------------------------------------------

_LABEL_UNSAFE = re.compile(r"[^\w\-]")


def _safe_filename(label: str, rank: int, ext: str = ".json") -> str:
    """Convert a (potentially long, symbol-heavy) label to a safe filename."""
    safe = _LABEL_UNSAFE.sub("_", label)[:80].rstrip("_")
    return f"rank_{rank:03d}_{safe}{ext}"


def save_result(
    result: SearchResult,
    path: str | Path,
    *,
    network: NetworkConfig,
) -> Path:
    """Save a complete *SearchResult* to a self-contained JSON artifact.

    The file stores the full DAG (node-level structure), the network
    config, and all scalar evaluation metrics.  It can be loaded back
    with :func:`load_result` without re-running the search.

    Per-node ``State`` caches (``eval_result.node_states``) are NOT
    persisted; they are large and fully recomputable::

        dag, network, _ = load_schedule(path)
        full_eval = Evaluator(network).evaluate(dag)

    Parameters
    ----------
    result : SearchResult
        The candidate to save.
    path : str or Path
        Destination file path.  Parent directories are created if needed.
    network : NetworkConfig
        The network the search was run against.

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    ev = result.eval_result
    score = result.score
    return _save_schedule(
        result.dag,
        path,
        network=network,
        label=result.label,
        score=score if score != float("-inf") else None,
        fidelity=ev.fidelity,
        rate=ev.rate,
        resource_cost=ev.resource_cost,
        latency_s=ev.latency,
        success_prob=ev.success_prob,
    )


def load_result(
    path: str | Path,
) -> tuple[SearchResult, NetworkConfig]:
    """Load a :class:`SearchResult` artifact saved by :func:`save_result`.

    The returned ``SearchResult.eval_result.node_states`` is an empty dict
    (not stored).  To get the full per-node state cache, re-evaluate::

        result, network = load_result(path)
        full_eval = Evaluator(network).evaluate(result.dag)

    Parameters
    ----------
    path : str or Path
        Path of a file previously written by :func:`save_result`.

    Returns
    -------
    result : SearchResult
    network : NetworkConfig

    Raises
    ------
    ValueError
        If the file format is unrecognised or from an incompatible version.
    """
    dag, network, meta = _load_schedule(path)
    ev_raw = meta.get("eval") or {}
    eval_result = EvaluationResult(
        fidelity=float(ev_raw.get("fidelity") or 0.0),
        rate=float(ev_raw.get("rate") or 0.0),
        resource_cost=int(ev_raw.get("resource_cost") or 0),
        latency=float(ev_raw.get("latency_s") or 0.0),
        success_prob=float(ev_raw.get("success_prob") or 0.0),
        node_states={},
    )
    raw_score = meta.get("score")
    score = float("-inf") if raw_score is None else float(raw_score)
    return (
        SearchResult(
            label=meta.get("label", ""),
            dag=dag,
            eval_result=eval_result,
            score=score,
        ),
        network,
    )


def save_top(
    results: Sequence[SearchResult],
    directory: str | Path,
    *,
    network: NetworkConfig,
    n: int = 1,
    include_infeasible: bool = False,
) -> list[Path]:
    """Save the top-*n* results as individual schedule artifacts.

    Files are named ``rank_001_<sanitized_label>.json`` etc.  Each file
    can be loaded independently with :func:`load_result`.

    Parameters
    ----------
    results : sequence of SearchResult
        Ordered list as returned by a search function (best-first).
    directory : str or Path
        Output directory.  Created if it does not exist.
    network : NetworkConfig
        The network the search was run against.
    n : int
        Number of top results to save (default 1).
    include_infeasible : bool
        When False (default), infeasible results (score = -∞) are skipped.

    Returns
    -------
    list[Path]
        Absolute paths of the written files, in rank order.
    """
    rows = list(results)
    if not include_infeasible:
        rows = [r for r in rows if r.score > float("-inf")]
    rows = rows[:n]

    out_dir = Path(directory).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for rank, res in enumerate(rows, 1):
        fname = _safe_filename(res.label, rank)
        p = save_result(res, out_dir / fname, network=network)
        paths.append(p)
    return paths
