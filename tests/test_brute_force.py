"""Tests for the two new DAG builders and the brute_force_search function."""

import pytest

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.models.stage import Span
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.node import HeraldNode, PurifyNode
from hrgs_scheduler.search import SearchResult, brute_force_search

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YY = PurificationCircuit.YY
ZX = PurificationCircuit.ZX
XZ = PurificationCircuit.XZ


def paper_net(e_d: float = 0.005) -> NetworkConfig:
    return NetworkConfig.integrating_paper_config(e_d=e_d)


def ideal_net(N: int = 4, e_d: float = 0.01) -> NetworkConfig:
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


# ---------------------------------------------------------------------------
# generic_end_node_pumping
# ---------------------------------------------------------------------------


class TestGenericEndNodePumping:
    def test_validates(self):
        dag = ScheduleDAG.generic_end_node_pumping(N=4, n_pur=3, circuits=[YY, ZX])
        dag.validate()

    def test_default_circuits_matches_baseline_structure(self):
        # With heralded=True and the default circuit cycle, structural
        # properties (gen count, purify count, herald counts) must equal
        # those of baseline_end_node_pumping.
        n_pur, N = 5, 4
        dag_gen = ScheduleDAG.generic_end_node_pumping(N=N, n_pur=n_pur)
        dag_base = ScheduleDAG.baseline_end_node_pumping(N=N, n_pur=n_pur)

        assert dag_gen.gen_node_count == dag_base.gen_node_count
        assert dag_gen.purify_node_count == dag_base.purify_node_count

        heralds_gen = sorted(
            h.propagation_time
            for h in dag_gen.nodes.values()
            if isinstance(h, HeraldNode)
        )
        heralds_base = sorted(
            h.propagation_time
            for h in dag_base.nodes.values()
            if isinstance(h, HeraldNode)
        )
        assert heralds_gen == heralds_base

    def test_heralded_true_inserts_round_trip_heralds(self):
        dag = ScheduleDAG.generic_end_node_pumping(
            N=4, n_pur=3, circuits=[YY, ZX], heralded=True
        )
        round_trip = [
            n
            for n in dag.nodes.values()
            if isinstance(n, HeraldNode) and n.propagation_time == 2.0
        ]
        final = [
            n
            for n in dag.nodes.values()
            if isinstance(n, HeraldNode) and n.propagation_time == 1.0
        ]
        # n_pur=3 → 2 pumping rounds → 2 round-trip heralds + 1 final
        assert len(round_trip) == 2
        assert len(final) == 1

    def test_heralded_false_has_only_final_herald(self):
        dag = ScheduleDAG.generic_end_node_pumping(
            N=4, n_pur=3, circuits=[YY, ZX], heralded=False
        )
        heralds = [n for n in dag.nodes.values() if isinstance(n, HeraldNode)]
        assert len(heralds) == 1
        assert heralds[0].propagation_time == 1.0

    def test_wrong_circuits_length_raises(self):
        with pytest.raises(ValueError):
            ScheduleDAG.generic_end_node_pumping(N=4, n_pur=3, circuits=[YY])  # needs 2

    def test_n_pur_zero_raises(self):
        with pytest.raises(ValueError):
            ScheduleDAG.generic_end_node_pumping(N=4, n_pur=0)

    def test_gen_node_count(self):
        N, n_pur = 3, 4
        dag = ScheduleDAG.generic_end_node_pumping(N=N, n_pur=n_pur)
        assert dag.gen_node_count == n_pur * 2 * N

    def test_optimistic_latency_equals_one_l_over_c(self):
        net = ideal_net(N=4)
        dag = ScheduleDAG.generic_end_node_pumping(N=4, n_pur=5, heralded=False)
        result = Evaluator(net).evaluate(dag)
        l_over_c = net.total_length() / net.c
        assert result.latency == pytest.approx(1.0 * l_over_c)

    def test_heralded_latency_matches_baseline(self):
        net = ideal_net(N=4)
        dag_gen = ScheduleDAG.generic_end_node_pumping(N=4, n_pur=5, heralded=True)
        dag_base = ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5)
        ev = Evaluator(net)
        assert ev.evaluate(dag_gen).latency == pytest.approx(
            ev.evaluate(dag_base).latency
        )

    def test_single_copy_is_equivalent_to_raw_chain(self):
        net = ideal_net(N=4)
        dag = ScheduleDAG.generic_end_node_pumping(N=4, n_pur=1)
        result = Evaluator(net).evaluate(dag)
        raw_result = Evaluator(net).evaluate(ScheduleDAG.raw_chain(N=4))
        assert result.fidelity == pytest.approx(raw_result.fidelity)
        assert result.latency == pytest.approx(raw_result.latency)


# ---------------------------------------------------------------------------
# link_level_pumped_chain
# ---------------------------------------------------------------------------


class TestLinkLevelPumpedChain:
    def test_validates(self):
        dag = ScheduleDAG.link_level_pumped_chain(N=4, n_copies=2)
        dag.validate()

    def test_n_copies_one_returns_raw_chain(self):
        net = ideal_net(N=4)
        dag = ScheduleDAG.link_level_pumped_chain(N=4, n_copies=1)
        raw = ScheduleDAG.raw_chain(N=4)
        ev = Evaluator(net)
        assert ev.evaluate(dag).fidelity == pytest.approx(ev.evaluate(raw).fidelity)
        assert ev.evaluate(dag).latency == pytest.approx(ev.evaluate(raw).latency)

    def test_gen_node_count(self):
        # n_copies copies per hop, 2 Gen per single-hop edge, N hops
        N, n_copies = 4, 3
        dag = ScheduleDAG.link_level_pumped_chain(N=N, n_copies=n_copies)
        assert dag.gen_node_count == n_copies * 2 * N

    def test_purify_node_count(self):
        # (n_copies - 1) PurifyNodes per hop, N hops
        N, n_copies = 4, 3
        dag = ScheduleDAG.link_level_pumped_chain(N=N, n_copies=n_copies)
        assert dag.purify_node_count == (n_copies - 1) * N

    def test_only_final_herald(self):
        dag = ScheduleDAG.link_level_pumped_chain(N=4, n_copies=3)
        heralds = [n for n in dag.nodes.values() if isinstance(n, HeraldNode)]
        assert len(heralds) == 1
        assert heralds[0].propagation_time == 1.0

    def test_wrong_circuits_length_raises(self):
        with pytest.raises(ValueError):
            ScheduleDAG.link_level_pumped_chain(
                N=4, n_copies=3, circuits=[YY]
            )  # needs 2

    def test_custom_circuit_at_link_level(self):
        dag = ScheduleDAG.link_level_pumped_chain(N=2, n_copies=2, circuits=[ZX])
        dag.validate()
        pur_nodes = [n for n in dag.nodes.values() if isinstance(n, PurifyNode)]
        assert all(p.circuit == ZX for p in pur_nodes)

    def test_purify_nodes_at_link_span(self):
        N, n_copies = 3, 2
        dag = ScheduleDAG.link_level_pumped_chain(N=N, n_copies=n_copies)
        pur_nodes = [n for n in dag.nodes.values() if isinstance(n, PurifyNode)]
        # Each PurifyNode should be at Span(i, i+1) for some i
        for pur in pur_nodes:
            assert isinstance(pur.output_stage, Span)
            a, b = pur.output_stage.a, pur.output_stage.b
            assert b - a == 1, f"expected link-level span, got {pur.output_stage!r}"

    def test_latency_is_one_l_over_c(self):
        net = ideal_net(N=4)
        dag = ScheduleDAG.link_level_pumped_chain(N=4, n_copies=2)
        result = Evaluator(net).evaluate(dag)
        l_over_c = net.total_length() / net.c
        assert result.latency == pytest.approx(l_over_c)

    def test_fidelity_improves_over_raw(self):
        net = ideal_net(N=4, e_d=0.01)
        ev = Evaluator(net)
        raw_f = ev.evaluate(ScheduleDAG.raw_chain(N=4)).fidelity
        link_f = ev.evaluate(
            ScheduleDAG.link_level_pumped_chain(N=4, n_copies=2)
        ).fidelity
        assert link_f > raw_f


# ---------------------------------------------------------------------------
# brute_force_search
# ---------------------------------------------------------------------------


class TestBruteForceSearch:
    def test_returns_sorted_best_first(self):
        net = ideal_net(N=2, e_d=0.01)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.0)
        results = brute_force_search(net, obj, e_max=20)
        assert results == sorted(results, key=lambda r: r.score, reverse=True)

    def test_always_includes_raw(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=20)
        labels = [r.label for r in results]
        assert "raw" in labels

    def test_respects_budget(self):
        N = 2
        e_max = 12  # = 3 copies × 2 sides × 2 hops
        net = ideal_net(N=N)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=e_max)
        for r in results:
            assert (
                r.eval_result.resource_cost <= e_max
            ), f"{r.label} has C={r.eval_result.resource_cost} > e_max={e_max}"

    def test_all_results_have_positive_latency(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=20)
        for r in results:
            assert r.eval_result.latency > 0

    def test_best_beats_raw_fidelity_given_budget(self):
        net = ideal_net(N=2, e_d=0.01)
        obj = ObjectiveConfig(primary="fidelity", maximise=True)
        results = brute_force_search(net, obj, e_max=20)
        raw = next(r for r in results if r.label == "raw")
        best = results[0]
        assert best.eval_result.fidelity >= raw.eval_result.fidelity

    def test_budget_one_copy_returns_only_raw(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        # e_max = 2*2*1 = 4 → only 1 copy fits, so only raw is valid
        results = brute_force_search(net, obj, e_max=4)
        assert all(r.label == "raw" for r in results)

    def test_flexible_paper_included_for_even_n_with_enough_budget(self):
        net = ideal_net(N=4)
        obj = ObjectiveConfig(primary="fidelity")
        e_max_for_flexible = 5 * 2 * 4  # = 40
        results = brute_force_search(net, obj, e_max=e_max_for_flexible)
        labels = [r.label for r in results]
        assert "flexible_paper" in labels

    def test_flexible_paper_excluded_for_odd_n(self):
        net = ideal_net(N=3)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=60)
        labels = [r.label for r in results]
        assert "flexible_paper" not in labels

    def test_link_level_results_present(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=20, include_link_level=True)
        link_labels = [r.label for r in results if r.label.startswith("link.")]
        assert len(link_labels) > 0

    def test_exclude_flags_work(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(
            net,
            obj,
            e_max=20,
            include_heralded=False,
            include_optimistic=False,
            include_link_level=True,
        )
        for r in results:
            assert not r.label.startswith("end_heralded")
            assert not r.label.startswith("end_optimistic")

    def test_result_label_uniqueness(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=20)
        labels = [r.label for r in results]
        assert len(labels) == len(set(labels))

    def test_max_n_pur_cap_respected(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=100, max_n_pur=3)
        # All end-node results must have n_pur ≤ 3 → label contains n2 or n3 at most
        for r in results:
            if r.label.startswith("end_") or r.label.startswith("link."):
                n = int(r.label.split(".")[1][1:])
                assert n <= 3, f"n_pur={n} exceeds max_n_pur=3 in label {r.label!r}"

    def test_search_result_type(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=12)
        for r in results:
            assert isinstance(r, SearchResult)
            assert isinstance(r.label, str)
            assert r.eval_result is not None
            assert isinstance(r.score, float)
