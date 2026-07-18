"""Tests for hrgs_scheduler.cost_functions."""

import pytest

from hrgs_scheduler import cost_functions as cf
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator


@pytest.fixture
def flexible_result():
    net = NetworkConfig.integrating_paper_config(e_d=0.005)
    dag = ScheduleDAG.flexible_paper_schedule(N=10)
    return Evaluator(net).evaluate(dag)


def test_extractors_match_result_fields(flexible_result):
    assert cf.fidelity(flexible_result) == flexible_result.fidelity
    assert cf.rate(flexible_result) == flexible_result.rate
    assert cf.resource_cost(flexible_result) == flexible_result.resource_cost
    assert cf.latency(flexible_result) == flexible_result.latency


def test_satisfies_fidelity_floor(flexible_result):
    assert cf.satisfies_fidelity_floor(flexible_result, flexible_result.fidelity)
    assert not cf.satisfies_fidelity_floor(
        flexible_result, flexible_result.fidelity + 0.01
    )


def test_satisfies_rate_floor(flexible_result):
    assert cf.satisfies_rate_floor(flexible_result, flexible_result.rate)
    assert not cf.satisfies_rate_floor(flexible_result, flexible_result.rate + 1.0)


def test_satisfies_budget(flexible_result):
    assert cf.satisfies_budget(flexible_result, flexible_result.resource_cost)
    assert not cf.satisfies_budget(flexible_result, flexible_result.resource_cost - 1)


def test_objective_config_feasibility_and_score(flexible_result):
    obj = cf.ObjectiveConfig(primary="fidelity", maximise=True, f_min=0.9)
    assert obj.is_feasible(flexible_result)
    assert obj.score(flexible_result) == pytest.approx(flexible_result.fidelity)

    infeasible_obj = cf.ObjectiveConfig(primary="fidelity", f_min=0.999)
    assert not infeasible_obj.is_feasible(flexible_result)
    assert infeasible_obj.score(flexible_result) == float("-inf")


def test_objective_config_minimise_negates_score(flexible_result):
    obj = cf.ObjectiveConfig(primary="latency", maximise=False)
    assert obj.score(flexible_result) == pytest.approx(-flexible_result.latency)


def test_objective_config_unknown_primary_raises(flexible_result):
    obj = cf.ObjectiveConfig(primary="not_a_real_metric")
    with pytest.raises(ValueError):
        obj.score(flexible_result)
