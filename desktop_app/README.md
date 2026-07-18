# HRGS Purification Scheduler — Desktop UI

A standalone Tkinter desktop application that wraps the full capability
set of the `hrgs_scheduler` package (in `../src/hrgs_scheduler`) with a
graphical interface: network/objective configuration, brute-force and DP
outer-loop search, results browsing, schedule-artifact save/load/verify,
Graphviz-based DAG visualization, and a browser for previously generated
figures.

This lives outside `src/hrgs_scheduler/` on purpose: it is a separate,
optional sibling project that *reuses* the core package's search /
schedule / cost-function logic (via `controller.py`) rather than
reimplementing any of it. The core package keeps its intentional
zero-dependency, pure-stdlib philosophy; only this UI subproject depends
on Tkinter, Pillow, and PyInstaller.

## Why a different Python interpreter than the rest of the repo

The project's pinned interpreter, `/usr/local/bin/python3.13`, was built
without Tcl/Tk support:

```
$ /usr/local/bin/python3.13 -c "import tkinter"
ModuleNotFoundError: No module named '_tkinter'
```

The system `python3` (3.12) on a typical desktop Linux install DOES have
tkinter (via the `python3-tk` package) plus Pillow, so this subproject is
designed to run under that interpreter instead — see prerequisites below.

## Prerequisites

- A Python 3 interpreter with **Tkinter** available. On Debian/Ubuntu:
  ```bash
  sudo apt install python3-tk
  ```
  Verify with: `python3 -c "import tkinter; print(tkinter.TkVersion)"`
- **Pillow** (image preview). Usually already present as
  `python3-pil.imagetk` on Debian/Ubuntu, or `pip install pillow`.
- **Graphviz** `dot` CLI on `PATH`, for the "Visualize" features:
  ```bash
  sudo apt install graphviz   # or: brew install graphviz
  ```
  (Search, save, load, and verify all work without Graphviz; only
  rendering DAGs to images requires it.)

## Running in development mode

No build step needed — just run the script with a Tk-enabled Python:

```bash
cd desktop_app
python3 app.py
```

`app.py` inserts the repo's `src/` directory onto `sys.path` at import
time (the same convention already used by `validation/*.py`), so no
`pip install` of `hrgs_scheduler` is required.

## Application layout

- **Search tab** — configure a network (`uniform` or the paper's
  reference `paper` config), an objective (`rate` with fidelity floor, or
  `fidelity` with rate floor), and an algorithm (`brute_force` or `dp`,
  each with their own tuning knobs), then run the search in a background
  thread. Results populate a sortable-by-click table (Rank/Label/F/R/C/
  L/P_succ/Score). Select a row to visualize it, save it as a standalone
  artifact, save the top-N results, or export the whole table as CSV/JSON.
- **Load / Verify Artifact tab** — browse for a `.json` schedule artifact
  saved by this app (or by `validation/search_results.py --save-top`),
  view its summary, re-evaluate and diff its stored metrics ("Verify"),
  list per-node-type counts, visualize it, or export its Graphviz DOT
  source.
- **Figures tab** — browse and preview any `.png`/`.svg` file already
  present under `outputs/` (e.g. from `validation/fig5_fidelity_vs_noise.py`
  or `validation/fig6_rate_ratio.py`), or open it with the OS's default
  viewer.

## Building a standalone executable

```bash
cd desktop_app
./build_executable.sh
./dist/hrgs-scheduler-ui
```

The build script creates a dedicated venv (`.build-venv/`, gitignored)
using the system `python3` with `--system-site-packages` (to inherit
tkinter/Pillow without needing to compile Tk bindings), installs
PyInstaller, and bundles `app.py` into a single executable at
`dist/hrgs-scheduler-ui`. The `hrgs_scheduler` package itself is not
pip-installed — PyInstaller's `--paths` analysis option points directly
at `../src` so the pure-Python package is bundled from source.

Graphviz's `dot` binary is an external OS dependency and is **not**
bundled into the executable; install it separately on any machine that
needs the visualization features.

## Architecture notes

- `controller.py` contains all business logic and has **no** `tkinter`
  import, so it can be exercised (and in principle unit-tested) with any
  interpreter, independent of Tk availability.
- `app.py` contains only widget/layout/event-handling code and delegates
  every non-trivial operation to `controller.py`.
- Long-running search calls run on a background thread (see
  `_run_in_background` in `app.py`) so the UI never freezes during a
  brute-force/DP search.
