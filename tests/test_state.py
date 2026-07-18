"""Tests for hrgs_scheduler.models.state.State."""

from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.stage import RGSS, Span
from hrgs_scheduler.models.state import HeraldStatus, State


def make_state(**overrides) -> State:
    defaults = dict(
        error_vector=ErrorVector.ideal(),
        side_effect_parity=0,
        current_time=1.0,
        generation_time=0.0,
        stage=RGSS,
        purification_rounds=0,
        herald_status=HeraldStatus.PENDING,
    )
    defaults.update(overrides)
    return State(**defaults)


def test_fresh_rgss_factory():
    ev = ErrorVector(w=0.9, x=0.05, y=0.03, z=0.02)
    s = State.fresh_rgss(ev, t=2.5)
    assert s.stage is RGSS
    assert s.current_time == 2.5
    assert s.generation_time == 2.5
    assert s.side_effect_parity == 0
    assert s.herald_status is HeraldStatus.PENDING


def test_idle_duration():
    s = make_state(current_time=5.0, generation_time=2.0)
    assert s.idle_duration == 3.0


def test_fidelity_is_error_vector_w():
    ev = ErrorVector(w=0.87, x=0.05, y=0.03, z=0.05)
    s = make_state(error_vector=ev)
    assert s.fidelity == ev.w


def test_is_herald_resolved():
    pending = make_state(herald_status=HeraldStatus.PENDING)
    resolved = make_state(herald_status=HeraldStatus.RESOLVED)
    assert not pending.is_herald_resolved
    assert resolved.is_herald_resolved


def test_with_error_vector_only_changes_error_vector():
    s = make_state()
    new_ev = ErrorVector(w=0.5, x=0.2, y=0.15, z=0.15)
    updated = s.with_error_vector(new_ev)
    assert updated.error_vector == new_ev
    assert updated.current_time == s.current_time
    assert updated.stage == s.stage
    assert updated.side_effect_parity == s.side_effect_parity


def test_with_stage_only_changes_stage():
    s = make_state(stage=RGSS)
    updated = s.with_stage(Span(0, 1))
    assert updated.stage == Span(0, 1)
    assert updated.error_vector == s.error_vector


def test_with_time_only_changes_current_time():
    s = make_state(current_time=1.0)
    updated = s.with_time(9.0)
    assert updated.current_time == 9.0
    assert updated.generation_time == s.generation_time


def test_with_herald_resolved():
    s = make_state(herald_status=HeraldStatus.PENDING)
    updated = s.with_herald_resolved()
    assert updated.herald_status is HeraldStatus.RESOLVED
    assert s.herald_status is HeraldStatus.PENDING  # original untouched


def test_with_parity_xor():
    s = make_state(side_effect_parity=1)
    assert s.with_parity_xor(1).side_effect_parity == 0
    assert s.with_parity_xor(0).side_effect_parity == 1


def test_state_is_mutable_via_copy_not_in_place():
    s = make_state(side_effect_parity=0)
    updated = s.with_parity_xor(1)
    assert s is not updated
    assert s.side_effect_parity == 0
