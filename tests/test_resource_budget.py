"""Tests for hrgs_scheduler.models.resource_budget.ResourceBudget."""

import pytest

from hrgs_scheduler.models.resource_budget import ResourceBudget


@pytest.mark.parametrize(
    "n_pur, e_max, m_max",
    [(0, 2, 1), (1, 0, 1), (1, 2, 0)],
)
def test_rejects_invalid_fields(n_pur, e_max, m_max):
    with pytest.raises(ValueError):
        ResourceBudget(n_pur=n_pur, e_max=e_max, m_max=m_max)


def test_minimal_budget():
    b = ResourceBudget.minimal()
    assert b.n_pur == 1
    assert b.e_max == 2
    assert b.m_max == 1


def test_from_integrating_paper():
    b = ResourceBudget.from_integrating_paper()
    assert b.n_pur == 2
    assert b.e_max == 12
    assert b.m_max == 6


def test_resource_cost_property():
    b = ResourceBudget(n_pur=3, e_max=10, m_max=5)
    assert b.resource_cost == 3
