"""Tests for hrgs_scheduler.operations.backbone."""

import math

import pytest

from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.network_config import HopConfig
from hrgs_scheduler.models.stage import RGSS, Span
from hrgs_scheduler.models.state import HeraldStatus, State
from hrgs_scheduler.operations.backbone import (
    absa_bsm,
    gen,
    herald,
    idle,
    join,
    pauli_correct,
)


def ideal_hop(**overrides):
    defaults = dict(
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        eta=0.5,
    )
    defaults.update(overrides)
    return HopConfig(**defaults)


# ---------------------------------------------------------------------------
# gen()
# ---------------------------------------------------------------------------


def test_gen_ideal_hop_gives_perfect_fidelity():
    hop = ideal_hop()
    s = gen(hop, t=0.0)
    assert s.stage is RGSS
    assert s.error_vector == ErrorVector.ideal()
    assert s.current_time == 0.0
    assert s.generation_time == 0.0
    assert s.herald_status is HeraldStatus.PENDING


def test_gen_noisy_hop_only_produces_x_component_never_y_or_z():
    # Regression test for the "spurious ZZ at Gen time" bug fix: inner-qubit
    # errors must contribute independent ZI only, never ZZ/IZ.
    hop = ideal_hop(p_x_inner=0.05, p_z_inner=0.05)
    s = gen(hop, t=1.0)
    assert s.error_vector.y == 0.0
    assert s.error_vector.z == 0.0
    assert s.error_vector.x == pytest.approx(hop.inner_error_per_hop)
    assert s.error_vector.w == pytest.approx(1.0 - hop.inner_error_per_hop)


def test_gen_side_effect_parity_passthrough():
    hop = ideal_hop()
    s = gen(hop, t=0.0, side_effect_parity=1)
    assert s.side_effect_parity == 1


# ---------------------------------------------------------------------------
# join()
# ---------------------------------------------------------------------------


def test_join_two_rgss_states_stays_at_rgss():
    hop = ideal_hop()
    a = gen(hop, t=0.0)
    b = gen(hop, t=0.0)
    out = join(a, b)
    assert out.stage is RGSS


def test_join_adjacent_spans_merges_correctly():
    a = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=1.0,
        generation_time=0.0,
        stage=Span(0, 1),
    )
    b = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=2.0,
        generation_time=0.5,
        stage=Span(1, 2),
    )
    out = join(a, b)
    assert out.stage == Span(0, 2)
    assert out.current_time == 2.0  # max
    assert out.generation_time == 0.0  # min


def test_join_non_adjacent_spans_raises():
    a = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=0.0,
        generation_time=0.0,
        stage=Span(0, 1),
    )
    b = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=0.0,
        generation_time=0.0,
        stage=Span(2, 3),
    )
    with pytest.raises(ValueError):
        join(a, b)


def test_join_xors_side_effect_parity():
    hop = ideal_hop()
    a = gen(hop, t=0.0, side_effect_parity=1)
    b = gen(hop, t=0.0, side_effect_parity=1)
    out = join(a, b)
    assert out.side_effect_parity == 0

    c = gen(hop, t=0.0, side_effect_parity=1)
    d = gen(hop, t=0.0, side_effect_parity=0)
    out2 = join(c, d)
    assert out2.side_effect_parity == 1


def test_join_herald_status_resolved_only_if_both_resolved():
    hop = ideal_hop()
    a = gen(hop, t=0.0).with_herald_resolved()
    b = gen(hop, t=0.0).with_herald_resolved()
    out = join(a, b)
    assert out.herald_status is HeraldStatus.RESOLVED

    c = gen(hop, t=0.0).with_herald_resolved()
    d = gen(hop, t=0.0)  # still PENDING
    out2 = join(c, d)
    assert out2.herald_status is HeraldStatus.PENDING


# ---------------------------------------------------------------------------
# absa_bsm()
# ---------------------------------------------------------------------------


def test_absa_bsm_requires_rgss_inputs():
    a = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=0.0,
        generation_time=0.0,
        stage=Span(0, 1),
    )
    b = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=0.0,
        generation_time=0.0,
        stage=RGSS,
    )
    with pytest.raises(ValueError):
        absa_bsm(a, b, hop_index=0, e_d=0.0)


def test_absa_bsm_output_stage_is_single_hop_span():
    hop = ideal_hop()
    a = gen(hop, t=0.0)
    b = gen(hop, t=0.0)
    out = absa_bsm(a, b, hop_index=3, e_d=0.0)
    assert out.stage == Span(3, 4)


def test_absa_bsm_zero_e_d_and_ideal_hop_gives_ideal_fidelity():
    hop = ideal_hop()
    a = gen(hop, t=0.0)
    b = gen(hop, t=0.0)
    out = absa_bsm(a, b, hop_index=0, e_d=0.0)
    assert out.error_vector.w == pytest.approx(1.0)


def test_absa_bsm_depolarizing_noise_reduces_fidelity_symmetrically():
    hop = ideal_hop()
    a = gen(hop, t=0.0)
    b = gen(hop, t=0.0)
    out_noisy = absa_bsm(a, b, hop_index=0, e_d=0.05)
    out_ideal = absa_bsm(a, b, hop_index=0, e_d=0.0)
    assert out_noisy.error_vector.w < out_ideal.error_vector.w
    assert out_noisy.error_vector.is_normalised


def test_absa_bsm_depolarizing_channel_is_full_single_qubit_channel():
    # Regression test: e_d must be modeled as a full depolarizing channel
    # [1-e_d, e_d/3, e_d/3, e_d/3] composed via bsm_compose, not independent
    # Z-flips. With ideal inputs, single-side noisy vector should match
    # the isotropic depolarizing vector composed with itself.
    hop = ideal_hop()
    a = gen(hop, t=0.0)
    b = gen(hop, t=0.0)
    e_d = 0.09
    depol = ErrorVector(w=1 - e_d, x=e_d / 3, y=e_d / 3, z=e_d / 3)
    expected = depol.bsm_compose(depol)
    out = absa_bsm(a, b, hop_index=0, e_d=e_d)
    assert out.error_vector.w == pytest.approx(expected.w)
    assert out.error_vector.x == pytest.approx(expected.x)
    assert out.error_vector.y == pytest.approx(expected.y)
    assert out.error_vector.z == pytest.approx(expected.z)


# ---------------------------------------------------------------------------
# idle()
# ---------------------------------------------------------------------------


def test_idle_advances_time_and_decoheres():
    hop = ideal_hop(p_x_inner=0.1, p_z_inner=0.1)
    s = gen(hop, t=0.0)
    out = idle(s, until=5.0, gamma=0.2)
    assert out.current_time == 5.0
    decay = math.exp(-0.2 * 5.0)
    assert out.error_vector.w == pytest.approx(0.25 + decay * (s.error_vector.w - 0.25))


def test_idle_rejects_going_backwards_in_time():
    hop = ideal_hop()
    s = gen(hop, t=5.0)
    with pytest.raises(ValueError):
        idle(s, until=1.0, gamma=0.1)


def test_idle_zero_gamma_no_decoherence():
    hop = ideal_hop(p_x_inner=0.1, p_z_inner=0.1)
    s = gen(hop, t=0.0)
    out = idle(s, until=10.0, gamma=0.0)
    assert out.error_vector == pytest.approx(s.error_vector)


# ---------------------------------------------------------------------------
# herald()
# ---------------------------------------------------------------------------


def test_herald_resolves_status_and_advances_time():
    hop = ideal_hop()
    s = gen(hop, t=1.0)
    out = herald(s, propagation_time=0.5)
    assert out.herald_status is HeraldStatus.RESOLVED
    assert out.current_time == pytest.approx(1.5)


def test_herald_zero_propagation_time_default():
    hop = ideal_hop()
    s = gen(hop, t=1.0)
    out = herald(s)
    assert out.current_time == pytest.approx(1.0)
    assert out.herald_status is HeraldStatus.RESOLVED


# ---------------------------------------------------------------------------
# pauli_correct()
# ---------------------------------------------------------------------------


def test_pauli_correct_requires_full_span():
    s = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=1,
        current_time=1.0,
        generation_time=0.0,
        stage=Span(0, 1),
        herald_status=HeraldStatus.RESOLVED,
    )
    with pytest.raises(ValueError):
        pauli_correct(s, N=10)


def test_pauli_correct_requires_herald_resolved():
    s = State(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=1.0,
        generation_time=0.0,
        stage=Span(0, 10),
        herald_status=HeraldStatus.PENDING,
    )
    with pytest.raises(ValueError):
        pauli_correct(s, N=10)


def test_pauli_correct_resets_parity_and_preserves_error_vector():
    ev = ErrorVector(w=0.9, x=0.05, y=0.03, z=0.02)
    s = State(
        error_vector=ev,
        side_effect_parity=1,
        current_time=3.0,
        generation_time=0.0,
        stage=Span(0, 10),
        herald_status=HeraldStatus.RESOLVED,
    )
    out = pauli_correct(s, N=10)
    assert out.side_effect_parity == 0
    assert out.error_vector == ev
    assert out.stage == Span(0, 10)
