#!/usr/bin/env bash
# Build a standalone local executable for the desktop UI using PyInstaller.
#
# Why a dedicated venv with --system-site-packages:
#   The project's pinned interpreter (/usr/local/bin/python3.13) was built
#   without Tcl/Tk support (`import tkinter` fails: no `_tkinter` module),
#   so it cannot run or package this GUI. The system `python3` on this
#   machine DOES have tkinter (`python3-tk` is installed) as well as
#   Pillow, so the build venv is created from `python3` with
#   --system-site-packages to inherit both without needing to compile Tk
#   bindings. If tkinter is missing on your system, install it first,
#   e.g. `sudo apt install python3-tk`.
#
# hrgs_scheduler itself is NOT pip-installed here: `--paths` below adds
# the repo's src/ directory to PyInstaller's analysis path so the pure
# stdlib package is discovered and bundled directly from source, exactly
# like the existing validation/*.py scripts already do at runtime via
# sys.path.insert(...).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
VENV="$HERE/.build-venv"

echo "== Setting up build environment (system python3, tkinter-enabled) =="
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$HERE/requirements.txt"

echo "== Verifying tkinter is importable in the build venv =="
"$VENV/bin/python" -c "import tkinter; print('tkinter OK', tkinter.TkVersion)"

echo "== Building standalone executable with PyInstaller =="
cd "$HERE"
"$VENV/bin/pyinstaller" \
  --name hrgs-scheduler-ui \
  --onefile \
  --paths "$REPO_ROOT/src" \
  app.py

echo
echo "== Done =="
echo "Executable: $HERE/dist/hrgs-scheduler-ui"
echo "NOTE: the Graphviz 'dot' CLI must be installed separately on any"
echo "machine that runs this executable (visualization features need it;"
echo "search/save/load/verify work without it)."
