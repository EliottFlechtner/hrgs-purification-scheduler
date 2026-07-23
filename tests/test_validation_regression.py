"""Regression tests locking in the validation/ scripts' reproduction of
[Integrating, Fig. 5] and [Fig. 6] numbers.

These import the validation scripts directly (both are import-safe:
top-level code only defines constants/functions, all printing happens
inside ``main()`` behind ``if __name__ == "__main__"``) and assert the
computed values stay within a small tolerance of the currently-verified
numbers recorded in docs/Fig6 Rate Ratio Non-Reproducibility.md and the
validation scripts' own docstrings/PAPER_REFERENCE constants.

If these tests start failing, it means a change to models/operations/
schedule has altered the underlying physics -- re-verify against the
papers before "fixing" the test tolerances.
"""

import importlib.util
import pathlib

import pytest

VALIDATION_DIR = pathlib.Path(__file__).resolve().parents[1] / "experiments"


def _import_validation_module(filename: str):
    path = VALIDATION_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fig5_module():
    return _import_validation_module("fig5_fidelity_vs_noise.py")


@pytest.fixture(scope="module")
def fig6_module():
    return _import_validation_module("fig6_rate_ratio.py")


# ---------------------------------------------------------------------------
# Fig. 5 -- fidelity vs. e_d
# ---------------------------------------------------------------------------


def test_fig5_e_d_zero_gives_perfect_fidelity(fig5_module):
    curves = fig5_module.compute_curves()
    for label in ("raw", "baseline", "flexible"):
        e_d0, f0 = curves[label][0]
        assert e_d0 == pytest.approx(0.0)
        assert f0 == pytest.approx(1.0, abs=1e-9)


def test_fig5_matches_paper_reference_at_e_d_001(fig5_module):
    curves = fig5_module.compute_curves()
    tolerance = 0.002  # absolute fidelity tolerance vs. hand-read Fig. 5 values
    for label in ("raw", "baseline", "flexible"):
        _, f_final = curves[label][-1]
        ref = fig5_module.PAPER_REFERENCE[label][0.010]
        assert f_final == pytest.approx(ref, abs=tolerance), (
            f"{label} fidelity at e_d=0.01 ({f_final:.4f}) drifted from "
            f"paper reference ({ref:.3f}) by more than {tolerance}"
        )


def test_fig5_ordering_flexible_beats_baseline_beats_raw(fig5_module):
    curves = fig5_module.compute_curves()
    _, raw_final = curves["raw"][-1]
    _, base_final = curves["baseline"][-1]
    _, flex_final = curves["flexible"][-1]
    assert flex_final > base_final > raw_final


def test_fig5_purified_schemes_stay_above_point_nine(fig5_module):
    # [Integrating, §VI]: both purified schemes achieve fidelities above 0.9
    # across the full e_d in [0, 0.01] sweep.
    curves = fig5_module.compute_curves()
    for label in ("baseline", "flexible"):
        for _, f in curves[label]:
            assert f > 0.9


# ---------------------------------------------------------------------------
# Fig. 6 -- rate ratio vs. e_d
# ---------------------------------------------------------------------------


def test_fig6_flex_over_base_matches_documented_order_of_magnitude(fig6_module):
    ratios = fig6_module.compute_ratios()
    flex_over_base = [r for _, r in ratios["flex_over_base"]]
    # Documented current (correct, non-reproducible-exactly) behaviour:
    # ~8.78x - 9.00x, dominated by the 9:1 structural Herald-count ratio.
    for value in flex_over_base:
        assert 8.5 <= value <= 9.5, (
            f"flex_over_base={value:.3f} outside the documented ~9x "
            "structural range -- see docs/Fig6 Rate Ratio "
            "Non-Reproducibility.md"
        )


def test_fig6_flex_over_base_does_not_reach_paper_range(fig6_module):
    # Documents (rather than "fixes") the known gap: our ratio must NOT
    # accidentally land in the paper's 45-65x range, which would indicate
    # an unverified change rather than genuine reproduction (see docs/Fig6
    # Rate Ratio Non-Reproducibility.md for why exact agreement isn't
    # achievable without the paper's unpublished timing constants).
    ratios = fig6_module.compute_ratios()
    flex_over_base = [r for _, r in ratios["flex_over_base"]]
    lo, hi = fig6_module.PAPER_FLEX_OVER_BASE_RANGE
    for value in flex_over_base:
        assert not (lo <= value <= hi)


def test_fig6_flexible_always_faster_than_baseline(fig6_module):
    ratios = fig6_module.compute_ratios()
    for _, value in ratios["flex_over_base"]:
        assert value > 1.0
