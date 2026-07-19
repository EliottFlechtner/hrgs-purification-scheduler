"""
hrgs_scheduler.reporting
==========================
Report-support utilities: shared plotting helpers (`plots.py`) used by
every sweep script under `validation/` so figures share one consistent
visual language (colors, markers, DPI, output formats) instead of each
sweep script rolling its own one-off `matplotlib` code.

This subpackage is optional: it is only imported by scripts that need
plotting, and requires the `plotting` extra (`pip install -e '.[plotting]'`).
The rest of `hrgs_scheduler` remains pure-stdlib.
"""

from hrgs_scheduler.reporting.plots import (
    VARIANT_STYLE,
    new_figure,
    plot_dual_axis,
    plot_lines,
    save_figure,
    style_for,
)

__all__ = [
    "VARIANT_STYLE",
    "new_figure",
    "plot_dual_axis",
    "plot_lines",
    "save_figure",
    "style_for",
]
