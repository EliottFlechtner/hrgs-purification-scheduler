"""Tests for hrgs_scheduler.models.stage (RGSSStage, Span)."""

import pytest

from hrgs_scheduler.models.stage import RGSS, RGSSStage, Span


def test_rgss_singleton_repr():
    assert isinstance(RGSS, RGSSStage)
    assert repr(RGSS) == "RGSS"


def test_span_valid_construction():
    s = Span(2, 5)
    assert s.a == 2
    assert s.b == 5
    assert s.width == 3


@pytest.mark.parametrize("a, b", [(0, 0), (5, 3), (-1, 2)])
def test_span_rejects_invalid_bounds(a, b):
    with pytest.raises(ValueError):
        Span(a, b)


def test_span_is_adjacent_shared_right_boundary():
    left = Span(0, 3)
    right = Span(3, 6)
    assert left.is_adjacent(right)
    assert right.is_adjacent(left)


def test_span_is_not_adjacent_when_disjoint():
    left = Span(0, 2)
    right = Span(3, 6)
    assert not left.is_adjacent(right)


def test_span_join_left_to_right():
    left = Span(0, 3)
    right = Span(3, 6)
    assert left.join(right) == Span(0, 6)


def test_span_join_right_to_left():
    left = Span(0, 3)
    right = Span(3, 6)
    # calling join the other way around should still merge correctly
    assert right.join(left) == Span(0, 6)


def test_span_join_non_adjacent_raises():
    left = Span(0, 2)
    right = Span(3, 6)
    with pytest.raises(ValueError):
        left.join(right)


def test_span_equality_and_hash():
    assert Span(1, 2) == Span(1, 2)
    assert hash(Span(1, 2)) == hash(Span(1, 2))
    assert Span(1, 2) != Span(1, 3)
