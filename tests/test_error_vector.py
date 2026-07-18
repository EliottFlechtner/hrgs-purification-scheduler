"""Tests for hrgs_scheduler.models.error_vector.ErrorVector."""

import math

import pytest

from hrgs_scheduler.models.error_vector import ErrorVector


def test_ideal_is_pure_w():
    ev = ErrorVector.ideal()
    assert ev == ErrorVector(1.0, 0.0, 0.0, 0.0)
    assert ev.fidelity == 1.0
    assert ev.is_normalised


def test_maximally_mixed_is_uniform():
    ev = ErrorVector.maximally_mixed()
    assert ev == ErrorVector(0.25, 0.25, 0.25, 0.25)
    assert ev.is_normalised


def test_from_independent_z_flips_zero_noise():
    ev = ErrorVector.from_independent_z_flips(0.0, 0.0)
    assert ev == ErrorVector(1.0, 0.0, 0.0, 0.0)


def test_from_independent_z_flips_matches_formula():
    p_a, p_b = 0.1, 0.2
    ev = ErrorVector.from_independent_z_flips(p_a, p_b)
    assert ev.w == pytest.approx((1 - p_a) * (1 - p_b))
    assert ev.x == pytest.approx(p_a * (1 - p_b))
    assert ev.y == pytest.approx(p_a * p_b)
    assert ev.z == pytest.approx((1 - p_a) * p_b)
    assert ev.is_normalised


def test_from_independent_z_flips_second_marginal_zero_gives_no_y_or_z():
    # gen() relies on this: from_independent_z_flips(p_in, 0.0) must not
    # produce any ZZ (y) component.
    ev = ErrorVector.from_independent_z_flips(0.3, 0.0)
    assert ev.y == 0.0
    assert ev.z == 0.0


def test_marginal_properties():
    ev = ErrorVector(w=0.5, x=0.2, y=0.1, z=0.2)
    assert ev.p_za == pytest.approx(0.2 + 0.1)
    assert ev.p_zb == pytest.approx(0.2 + 0.1)


def test_bsm_compose_ideal_identity():
    ideal = ErrorVector.ideal()
    other = ErrorVector(w=0.7, x=0.1, y=0.1, z=0.1)
    composed = ideal.bsm_compose(other)
    assert composed == pytest.approx(other, abs=1e-12)


def test_bsm_compose_is_commutative():
    e1 = ErrorVector(w=0.6, x=0.2, y=0.1, z=0.1)
    e2 = ErrorVector(w=0.5, x=0.3, y=0.1, z=0.1)
    c1 = e1.bsm_compose(e2)
    c2 = e2.bsm_compose(e1)
    assert c1.w == pytest.approx(c2.w)
    assert c1.x == pytest.approx(c2.x)
    assert c1.y == pytest.approx(c2.y)
    assert c1.z == pytest.approx(c2.z)


def test_bsm_compose_preserves_normalisation():
    e1 = ErrorVector(w=0.6, x=0.2, y=0.1, z=0.1)
    e2 = ErrorVector(w=0.5, x=0.3, y=0.1, z=0.1)
    composed = e1.bsm_compose(e2)
    assert composed.is_normalised


def test_bsm_compose_exact_values():
    # [Bridging, eq. (5)] / [Integrating, eq. (14)] direct formula check.
    e1 = ErrorVector(w=0.9, x=0.05, y=0.03, z=0.02)
    e2 = ErrorVector(w=0.8, x=0.1, y=0.05, z=0.05)
    composed = e1.bsm_compose(e2)
    assert composed.w == pytest.approx(
        0.9 * 0.8 + 0.05 * 0.1 + 0.03 * 0.05 + 0.02 * 0.05
    )
    assert composed.x == pytest.approx(
        0.9 * 0.1 + 0.05 * 0.8 + 0.02 * 0.05 + 0.03 * 0.05
    )
    assert composed.y == pytest.approx(
        0.9 * 0.05 + 0.03 * 0.8 + 0.05 * 0.05 + 0.02 * 0.1
    )
    assert composed.z == pytest.approx(
        0.9 * 0.05 + 0.02 * 0.8 + 0.05 * 0.05 + 0.03 * 0.1
    )


def test_decohere_zero_delta_t_is_identity():
    ev = ErrorVector(w=0.8, x=0.1, y=0.05, z=0.05)
    decohered = ev.decohere(gamma=0.5, delta_t=0.0)
    assert decohered.w == pytest.approx(ev.w)
    assert decohered.x == pytest.approx(ev.x)
    assert decohered.y == pytest.approx(ev.y)
    assert decohered.z == pytest.approx(ev.z)


def test_decohere_infinite_time_reaches_maximally_mixed():
    ev = ErrorVector(w=0.9, x=0.05, y=0.03, z=0.02)
    decohered = ev.decohere(gamma=1.0, delta_t=50.0)
    assert decohered.w == pytest.approx(0.25, abs=1e-6)
    assert decohered.x == pytest.approx(0.25, abs=1e-6)
    assert decohered.y == pytest.approx(0.25, abs=1e-6)
    assert decohered.z == pytest.approx(0.25, abs=1e-6)


def test_decohere_zero_gamma_is_identity():
    ev = ErrorVector(w=0.8, x=0.1, y=0.05, z=0.05)
    decohered = ev.decohere(gamma=0.0, delta_t=100.0)
    assert decohered.w == pytest.approx(ev.w)
    assert decohered.x == pytest.approx(ev.x)
    assert decohered.y == pytest.approx(ev.y)
    assert decohered.z == pytest.approx(ev.z)


def test_decohere_matches_exponential_relaxation_formula():
    ev = ErrorVector(w=0.9, x=0.05, y=0.03, z=0.02)
    gamma, delta_t = 0.3, 2.0
    decohered = ev.decohere(gamma=gamma, delta_t=delta_t)
    decay = math.exp(-gamma * delta_t)
    assert decohered.w == pytest.approx(0.25 + decay * (ev.w - 0.25))
    assert decohered.x == pytest.approx(0.25 + decay * (ev.x - 0.25))
    assert decohered.y == pytest.approx(0.25 + decay * (ev.y - 0.25))
    assert decohered.z == pytest.approx(0.25 + decay * (ev.z - 0.25))
