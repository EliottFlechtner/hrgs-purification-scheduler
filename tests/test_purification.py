"""Tests for hrgs_scheduler.operations.purification."""

import pytest

from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.stage import RGSS, Span
from hrgs_scheduler.models.state import State
from hrgs_scheduler.operations.purification import (
    PurificationCircuit,
    purify,
    success_prob,
)


def make_state(ev: ErrorVector, stage=RGSS, t=0.0) -> State:
    return State(
        error_vector=ev,
        side_effect_parity=0,
        current_time=t,
        generation_time=0.0,
        stage=stage,
    )


@pytest.mark.parametrize(
    "circuit", [PurificationCircuit.ZX, PurificationCircuit.XZ, PurificationCircuit.YY]
)
def test_purify_ideal_inputs_gives_success_prob_one_and_stays_ideal(circuit):
    ideal = ErrorVector.ideal()
    p = success_prob(circuit, ideal, ideal)
    assert p == pytest.approx(1.0)

    s1 = make_state(ideal)
    s2 = make_state(ideal)
    result = purify(circuit, s1, s2)
    assert result.success_prob == pytest.approx(1.0)
    assert result.output_state.error_vector == pytest.approx(ideal)


@pytest.mark.parametrize(
    "circuit", [PurificationCircuit.ZX, PurificationCircuit.XZ, PurificationCircuit.YY]
)
def test_purify_output_error_vector_is_normalised(circuit):
    e1 = ErrorVector(w=0.85, x=0.06, y=0.05, z=0.04)
    e2 = ErrorVector(w=0.8, x=0.08, y=0.07, z=0.05)
    s1 = make_state(e1)
    s2 = make_state(e2)
    result = purify(circuit, s1, s2)
    assert result.output_state.error_vector.is_normalised


def test_purify_zx_matches_closed_form():
    e1 = ErrorVector(w=0.85, x=0.06, y=0.05, z=0.04)
    e2 = ErrorVector(w=0.8, x=0.08, y=0.07, z=0.05)
    p_expected = (e1.w + e1.x) * (e2.w + e2.x) + (e1.z + e1.y) * (e2.z + e2.y)
    p = success_prob(PurificationCircuit.ZX, e1, e2)
    assert p == pytest.approx(p_expected)

    s1, s2 = make_state(e1), make_state(e2)
    result = purify(PurificationCircuit.ZX, s1, s2)
    assert result.success_prob == pytest.approx(p_expected)
    out = result.output_state.error_vector
    assert out.w == pytest.approx((e1.w * e2.w + e1.x * e2.x) / p_expected)
    assert out.x == pytest.approx((e1.z * e2.z + e1.y * e2.y) / p_expected)
    assert out.y == pytest.approx((e1.z * e2.y + e1.y * e2.z) / p_expected)
    assert out.z == pytest.approx((e1.x * e2.w + e1.w * e2.x) / p_expected)


def test_purify_xz_matches_closed_form():
    e1 = ErrorVector(w=0.85, x=0.06, y=0.05, z=0.04)
    e2 = ErrorVector(w=0.8, x=0.08, y=0.07, z=0.05)
    p_expected = (e1.w + e1.z) * (e2.w + e2.z) + (e1.x + e1.y) * (e2.x + e2.y)
    p = success_prob(PurificationCircuit.XZ, e1, e2)
    assert p == pytest.approx(p_expected)

    s1, s2 = make_state(e1), make_state(e2)
    result = purify(PurificationCircuit.XZ, s1, s2)
    out = result.output_state.error_vector
    assert out.w == pytest.approx((e1.w * e2.w + e1.z * e2.z) / p_expected)
    assert out.x == pytest.approx((e1.z * e2.w + e1.w * e2.z) / p_expected)
    assert out.y == pytest.approx((e1.x * e2.y + e1.y * e2.x) / p_expected)
    assert out.z == pytest.approx((e1.x * e2.x + e1.y * e2.y) / p_expected)


def test_purify_yy_matches_closed_form():
    e1 = ErrorVector(w=0.85, x=0.06, y=0.05, z=0.04)
    e2 = ErrorVector(w=0.8, x=0.08, y=0.07, z=0.05)
    p_expected = (e1.w + e1.y) * (e2.w + e2.y) + (e1.x + e1.z) * (e2.x + e2.z)
    p = success_prob(PurificationCircuit.YY, e1, e2)
    assert p == pytest.approx(p_expected)

    s1, s2 = make_state(e1), make_state(e2)
    result = purify(PurificationCircuit.YY, s1, s2)
    out = result.output_state.error_vector
    assert out.w == pytest.approx((e1.w * e2.w + e1.y * e2.y) / p_expected)
    assert out.x == pytest.approx((e1.x * e2.z + e1.z * e2.x) / p_expected)
    assert out.y == pytest.approx((e1.y * e2.w + e1.w * e2.y) / p_expected)
    assert out.z == pytest.approx((e1.x * e2.x + e1.z * e2.z) / p_expected)


def test_purify_rejects_mismatched_stages():
    ideal = ErrorVector.ideal()
    s1 = make_state(ideal, stage=RGSS)
    s2 = make_state(ideal, stage=Span(0, 1))
    with pytest.raises(ValueError):
        purify(PurificationCircuit.YY, s1, s2)


def test_purify_output_time_and_parity_and_rounds():
    ideal = ErrorVector.ideal()
    s1 = State(
        error_vector=ideal,
        side_effect_parity=1,
        current_time=2.0,
        generation_time=0.0,
        stage=RGSS,
        purification_rounds=1,
    )
    s2 = State(
        error_vector=ideal,
        side_effect_parity=1,
        current_time=3.0,
        generation_time=0.5,
        stage=RGSS,
        purification_rounds=0,
    )
    result = purify(PurificationCircuit.YY, s1, s2)
    out = result.output_state
    assert out.current_time == 3.0  # max
    assert out.generation_time == 0.0  # min
    assert out.side_effect_parity == 0  # 1 xor 1
    assert out.purification_rounds == 2  # max(1, 0) + 1
