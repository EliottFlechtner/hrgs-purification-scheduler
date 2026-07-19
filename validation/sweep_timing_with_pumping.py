"""
validation/sweep_timing_with_pumping.py
==========================================
docs/Handoff_Timing_and_Pumping_Visualization.md, Part 1: real wall-clock
timing numbers for `dp_search`/`beam_search`, both with pumping enabled
(default settings, i.e. `exact_pumping=False`), across
N in {2, 4, 6, 8, 10, 12, 14, 16, 18}.

Only three ad-hoc points existed before this script (N=6/10/18, from the
Handoff_Integrate_Pumping_Into_Search.md validation checks) -- this
produces a full, reproducible sweep.

Config
------
`NetworkConfig.uniform(N=N, length=2.0, branching=(16,14,1), arm_count=18,
p_x_inner=0.0, p_z_inner=0.0, e_d=0.01, gamma=0.0, c=2e5)` -- the paper's
own `integrating_paper_config` shape, generalized to variable N exactly
as `sweep_hop_count.py` already does (`integrating_paper_config` itself
is fixed at N=10). `e_max = 10*N`, `beam_width=25` (beam_search default).

Safety (all requirements from the handoff, verbatim rationale below)
----------------------------------------------------------------------
- HARD per-point timeout, not a soft one: each `(N, method)` call runs in
  its own `multiprocessing.Process`; the parent does
  `proc.join(TIMEOUT_S)` and `proc.terminate()`/`.kill()`s the child if
  it's still alive afterwards. `signal.alarm` was considered and
  rejected: it can't reliably interrupt long stretches of pure-Python/
  memoized recursion inside `dp_search`/`beam_search` (no guaranteed
  interrupt point), whereas a separate process can always be killed from
  outside.
- Once a method exceeds the cap at some N, it is never tried again at any
  larger N in this run (checked independently per method -- `beam_search`
  keeps being tried at larger N even after `dp_search` has capped out,
  matching the earlier hop-count sweep's own finding that dp_search stops
  scaling long before beam_search does).
- Memory caution carried over from the earlier OOM incident (see
  `sweep_min_budget_vs_n.py`'s module docstring and repo notes): each
  child process sets a hard `RLIMIT_AS` cap (`MEMORY_CAP_BYTES`) via
  `resource.setrlimit` *before* importing/running any search code, so a
  runaway allocation raises `MemoryError` inside that one process instead
  of paging the whole machine into swap. The script itself should also be
  *launched* with `setsid ... nohup ...` (see Usage) so it survives if the
  launching terminal/session is torn down, per the same incident's
  lesson.
- Runs as a background-friendly script with incremental per-point
  logging (`flush=True` prints as each point starts/finishes) -- run it
  under `nohup`/`setsid` and `tail -f` the log; do not run it blocking in
  the foreground.

Outputs
-------
    outputs/sweep_timing_pumping/results.csv
    outputs/sweep_timing_pumping/runtime_vs_n.{png,svg}
    outputs/sweep_timing_pumping/README.md

Usage
-----
    cd /home/shark/Documents/hrgs-purification-scheduler
    source .venv/bin/activate
    setsid nohup env PYTHONPATH=src python3 -u validation/sweep_timing_with_pumping.py \\
        > validation/sweep_timing_with_pumping.log 2>&1 < /dev/null &
    echo $! > validation/sweep_timing_with_pumping.pid
    tail -f validation/sweep_timing_with_pumping.log
"""

from __future__ import annotations

import csv
import multiprocessing
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

N_VALUES: list[int] = [2, 4, 6, 8, 10, 12, 14, 16, 18]
F_MIN = 0.9
BEAM_WIDTH = 25
TIMEOUT_S = 300  # hard per-point cap: 5 minutes
MEMORY_CAP_BYTES = 3 * 1024**3  # 3 GiB per child process

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "sweep_timing_pumping"


def _build_network(n: int):
    from hrgs_scheduler.models.network_config import NetworkConfig

    return NetworkConfig.uniform(
        N=n,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        e_d=0.01,
        gamma=0.0,
        c=2e5,
    )


def _limit_memory() -> None:
    """Best-effort hard memory cap for this process only (see module docstring)."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_CAP_BYTES, MEMORY_CAP_BYTES))
    except (ValueError, OSError):
        pass  # some platforms/containers disallow lowering RLIMIT_AS; best-effort only


def _dp_worker(n: int, e_max: int, f_min: float, q: "multiprocessing.Queue") -> None:
    _limit_memory()
    try:
        from hrgs_scheduler.cost_functions import ObjectiveConfig
        from hrgs_scheduler.search import dp_search

        net = _build_network(n)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=f_min)
        t0 = time.time()
        results = dp_search(net, obj, e_max=e_max)
        elapsed = time.time() - t0
        best_score = results[0].score if results else float("-inf")
        q.put(("ok", elapsed, best_score))
    except BaseException as exc:  # noqa: BLE001 - must report, not crash silently
        q.put(("error", None, repr(exc)))


def _beam_worker(
    n: int, e_max: int, f_min: float, beam_width: int, q: "multiprocessing.Queue"
) -> None:
    _limit_memory()
    try:
        from hrgs_scheduler.cost_functions import ObjectiveConfig
        from hrgs_scheduler.search import beam_search

        net = _build_network(n)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=f_min)
        t0 = time.time()
        results = beam_search(net, obj, e_max=e_max, beam_width=beam_width)
        elapsed = time.time() - t0
        best_score = results[0].score if results else float("-inf")
        q.put(("ok", elapsed, best_score))
    except BaseException as exc:  # noqa: BLE001
        q.put(("error", None, repr(exc)))


@dataclass
class Row:
    n: int
    method: str
    e_max: int
    status: str  # "ok" | "exceeded_cap" | "error" | "skipped"
    elapsed_s: float | None
    best_score: float | None
    note: str = ""


def _run_with_timeout(
    worker, args, timeout_s: float
) -> tuple[str, float | None, float | None, str]:
    """Run *worker(*args, queue)* in a subprocess with a hard timeout.

    Returns (status, elapsed_s, best_score, note).
    """
    q: multiprocessing.Queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=worker, args=(*args, q))
    proc.start()
    proc.join(timeout_s)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        return "exceeded_cap", None, None, f"exceeded {timeout_s:g}s cap"

    if not q.empty():
        status, elapsed, payload = q.get()
        if status == "ok":
            return "ok", elapsed, payload, ""
        return "error", None, None, str(payload)

    # Process exited but put nothing on the queue -- e.g. killed by our own
    # RLIMIT_AS (MemoryError may itself be unable to allocate the traceback)
    # or an external OOM killer.
    return "error", None, None, f"process exited with code {proc.exitcode}, no result"


def run_sweep() -> list[Row]:
    rows: list[Row] = []
    dp_capped = False
    beam_capped = False

    for n in N_VALUES:
        e_max = 10 * n
        print(f"=== N={n}, e_max={e_max} ===", flush=True)

        if dp_capped:
            print(
                f"[dp_search]   N={n}: skipped (already exceeded cap at smaller N)",
                flush=True,
            )
            rows.append(Row(n, "dp_search", e_max, "skipped", None, None))
        else:
            print(
                f"[dp_search]   N={n}: starting (timeout={TIMEOUT_S}s)...", flush=True
            )
            status, elapsed, score, note = _run_with_timeout(
                _dp_worker, (n, e_max, F_MIN), TIMEOUT_S
            )
            print(
                f"[dp_search]   N={n}: {status} elapsed={elapsed} score={score} {note}",
                flush=True,
            )
            rows.append(Row(n, "dp_search", e_max, status, elapsed, score, note))
            if status != "ok":
                dp_capped = True

        if beam_capped:
            print(
                f"[beam_search] N={n}: skipped (already exceeded cap at smaller N)",
                flush=True,
            )
            rows.append(Row(n, "beam_search", e_max, "skipped", None, None))
        else:
            print(
                f"[beam_search] N={n}: starting (timeout={TIMEOUT_S}s)...", flush=True
            )
            status, elapsed, score, note = _run_with_timeout(
                _beam_worker, (n, e_max, F_MIN, BEAM_WIDTH), TIMEOUT_S
            )
            print(
                f"[beam_search] N={n}: {status} elapsed={elapsed} score={score} {note}",
                flush=True,
            )
            rows.append(Row(n, "beam_search", e_max, status, elapsed, score, note))
            if status != "ok":
                beam_capped = True

    return rows


def write_csv(rows: list[Row]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "results.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["N", "method", "e_max", "status", "elapsed_s", "best_score", "note"]
        )
        for r in rows:
            writer.writerow(
                [
                    r.n,
                    r.method,
                    r.e_max,
                    r.status,
                    f"{r.elapsed_s:.4f}" if r.elapsed_s is not None else "",
                    f"{r.best_score:.6g}" if r.best_score is not None else "",
                    r.note,
                ]
            )
    print(f"wrote {path}", flush=True)
    return path


def write_plot(rows: list[Row]) -> None:
    from hrgs_scheduler.reporting.plots import new_figure, save_figure

    fig, ax = new_figure()
    colors = {"dp_search": "#9467bd", "beam_search": "#1f77b4"}
    for method, color in colors.items():
        ok_pts = [
            (r.n, r.elapsed_s) for r in rows if r.method == method and r.status == "ok"
        ]
        capped_pts = [
            (r.n, TIMEOUT_S)
            for r in rows
            if r.method == method and r.status == "exceeded_cap"
        ]
        if ok_pts:
            xs, ys = zip(*sorted(ok_pts))
            ax.plot(xs, ys, marker="o", linestyle="-", color=color, label=method)
        if capped_pts:
            xs, ys = zip(*sorted(capped_pts))
            ax.scatter(
                xs,
                ys,
                marker="x",
                s=80,
                color=color,
                label=f"{method} (exceeded {TIMEOUT_S:g}s cap)",
                zorder=5,
            )
    ax.set_yscale("log")
    ax.set_xlabel("N (number of hops)")
    ax.set_ylabel("Wall-clock time (s), log scale")
    ax.set_title("dp_search / beam_search runtime vs. N (pumping enabled)")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    written = save_figure(fig, OUTPUT_DIR / "runtime_vs_n")
    for p in written:
        print(f"wrote {p}", flush=True)


def _practical_ceiling(rows: list[Row], method: str) -> str:
    ok_ns = sorted(r.n for r in rows if r.method == method and r.status == "ok")
    capped_ns = sorted(
        r.n for r in rows if r.method == method and r.status == "exceeded_cap"
    )
    if not ok_ns:
        return (
            f"{method}: did not complete even at the smallest N tried ({N_VALUES[0]})."
        )
    ceiling = ok_ns[-1]
    if capped_ns:
        return (
            f"{method}: practical N ceiling under the {TIMEOUT_S:g}s cap is N={ceiling} "
            f"(first exceeded the cap at N={capped_ns[0]})."
        )
    return f"{method}: completed at every N tried (up to N={ceiling}), never hit the {TIMEOUT_S:g}s cap."


def write_readme(rows: list[Row]) -> None:
    lines = [
        "# Timing sweep: dp_search / beam_search with pumping enabled",
        "",
        "docs/Handoff_Timing_and_Pumping_Visualization.md, Part 1.",
        "",
        "## Config",
        "",
        "- Network: paper's own `integrating_paper_config` shape, generalized to variable N",
        "  (`length=2.0, branching=(16,14,1), arm_count=18, p_x_inner=p_z_inner=0.0, e_d=0.01,",
        "  gamma=0.0, c=2e5`).",
        f"- `e_max = 10*N`, objective = maximize rate with fidelity floor f_min={F_MIN}.",
        f"- `beam_search(beam_width={BEAM_WIDTH})` (default); `dp_search` at its default settings",
        "  (pumping enabled, `exact_pumping=False`, i.e. heuristic-capped pumping frontier).",
        f"- Hard per-point timeout: {TIMEOUT_S:g}s, enforced via a separate `multiprocessing.Process`",
        "  killed on timeout. Once a method exceeds the cap at some N, it is skipped at every",
        "  larger N (checked independently per method).",
        f"- Per-child-process memory cap: {MEMORY_CAP_BYTES / 1024**3:.0f} GiB (`RLIMIT_AS`).",
        "",
        "## Practical N ceiling",
        "",
        f"- {_practical_ceiling(rows, 'dp_search')}",
        f"- {_practical_ceiling(rows, 'beam_search')}",
        "",
        "## Consistency check against earlier ad-hoc points",
        "",
        "docs/Handoff_Integrate_Pumping_Into_Search.md's validation checks earlier reported,",
        "for `beam_search` under this exact paper config: N=10 -> 15.22s (score=6195.95),",
        "N=18 -> 139.70s (score=1214.41). (Its N=6 number, 6.75s, used a *different*,",
        "nonzero-inner-error network, so it is not expected to match here.) See `results.csv`",
        "for whether N=10/N=18 in this sweep land close to those figures.",
        "",
        "## Full results",
        "",
        "See `results.csv` for the raw per-point data and `runtime_vs_n.png`/`.svg` for the plot",
        "(log-scale time axis; points that exceeded the cap are marked with an `x` at the cap",
        "value rather than omitted).",
        "",
    ]
    path = OUTPUT_DIR / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}", flush=True)


def main() -> None:
    multiprocessing.set_start_method("fork", force=True)
    t_start = time.time()
    rows = run_sweep()
    write_csv(rows)
    write_plot(rows)
    write_readme(rows)
    print(f"=== done in {time.time() - t_start:.1f}s total ===", flush=True)


if __name__ == "__main__":
    main()
