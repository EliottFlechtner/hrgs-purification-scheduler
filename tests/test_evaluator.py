"""Tests for hrgs_scheduler.schedule.evaluator.Evaluator."""

import pytest

from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator


def ideal_network(N=4, e_d=0.0):
    return NetworkConfig.uniform(
        N=N,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        e_d=e_d,
        gamma=0.0,
        c=2e5,
    )


def test_raw_chain_ideal_network_gives_perfect_fidelity():
    net = ideal_network(N=4, e_d=0.0)
    dag = ScheduleDAG.raw_chain(N=4)
    result = Evaluator(net).evaluate(dag)
    assert result.fidelity == pytest.approx(1.0)
    assert result.success_prob == pytest.approx(1.0)  # no Purify nodes
    assert result.resource_cost == dag.gen_node_count


def test_noisy_network_reduces_fidelity_below_one():
    net = ideal_network(N=4, e_d=0.01)
    dag = ScheduleDAG.raw_chain(N=4)
    result = Evaluator(net).evaluate(dag)
    assert 0.0 < result.fidelity < 1.0


def test_flexible_beats_raw_and_baseline_in_fidelity():
    net = ideal_network(N=4, e_d=0.01)
    ev = Evaluator(net)
    raw = ev.evaluate(ScheduleDAG.raw_chain(N=4))
    baseline = ev.evaluate(ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5))
    flexible = ev.evaluate(ScheduleDAG.flexible_paper_schedule(N=4))
    assert baseline.fidelity > raw.fidelity
    assert flexible.fidelity > baseline.fidelity


def test_latency_only_accrues_from_herald_nodes():
    # raw_chain has a single final one-way Herald (propagation_time=1.0);
    # latency should equal exactly L_total/c since Gen/Join/AbsaBsm add
    # zero latency in the current model.
    net = ideal_network(N=4, e_d=0.0)
    dag = ScheduleDAG.raw_chain(N=4)
    result = Evaluator(net).evaluate(dag)
    l_over_c = net.total_length() / net.c
    assert result.latency == pytest.approx(l_over_c)


def test_baseline_latency_is_nine_times_flexible_when_n_pur_five():
    # Regression test for the documented Fig 6 mechanism: baseline's
    # latency = (n_pur - 1) round-trip heralds (2x) + 1 final one-way (1x)
    # = 4*2 + 1 = 9 units of L_total/c; flexible = 1 unit.
    net = ideal_network(N=4, e_d=0.0)
    ev = Evaluator(net)
    baseline = ev.evaluate(ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5))
    flexible = ev.evaluate(ScheduleDAG.flexible_paper_schedule(N=4))
    l_over_c = net.total_length() / net.c
    assert baseline.latency == pytest.approx(9 * l_over_c)
    assert flexible.latency == pytest.approx(1 * l_over_c)


def test_success_prob_is_product_of_purify_success_probs():
    net = ideal_network(N=2, e_d=0.005)
    dag = ScheduleDAG.baseline_end_node_pumping(N=2, n_pur=3)
    result = Evaluator(net).evaluate(dag)
    assert dag.purify_node_count == 2
    assert 0.0 < result.success_prob <= 1.0


def test_rate_is_success_prob_over_latency():
    net = ideal_network(N=4, e_d=0.005)
    dag = ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5)
    result = Evaluator(net).evaluate(dag)
    assert result.rate == pytest.approx(result.success_prob / result.latency)


def test_node_states_cache_includes_every_node():
    net = ideal_network(N=3, e_d=0.0)
    dag = ScheduleDAG.raw_chain(N=3)
    result = Evaluator(net).evaluate(dag)
    assert set(result.node_states.keys()) == set(dag.nodes.keys())
