"""Tests for the DP-over-stages span-partition search (search/dp.py)."""

import pytest

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.search import SearchResult, brute_force_search, dp_search
from hrgs_scheduler.search.dp import (
    _DEFAULT_PUMP_POOL_WIDTH,
    _SpanCandidate,
    _SpanPartitionSearch,
    _dominates,
    _prune_pareto,
)
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.models.state import HeraldStatus, State
from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.stage import Span


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


def _candidate(
    cost: int, fidelity: float, success_prob: float, label: str = "c"
) -> _SpanCandidate:
    state = State(
        error_vector=ErrorVector(
            w=fidelity, x=(1 - fidelity) / 3, y=(1 - fidelity) / 3, z=(1 - fidelity) / 3
        ),
        side_effect_parity=0,
        current_time=0.0,
        generation_time=0.0,
        stage=Span(0, 1),
        purification_rounds=0,
        herald_status=HeraldStatus.PENDING,
    )
    return _SpanCandidate(
        node_id=0, state=state, cost=cost, success_prob=success_prob, label=label
    )


# ---------------------------------------------------------------------------
# Pareto dominance primitives
# ---------------------------------------------------------------------------


class TestParetoDominance:
    def test_strictly_better_in_all_dims_dominates(self):
        better = _candidate(cost=2, fidelity=0.95, success_prob=1.0)
        worse = _candidate(cost=4, fidelity=0.90, success_prob=0.9)
        assert _dominates(better, worse)
        assert not _dominates(worse, better)

    def test_equal_candidates_do_not_dominate(self):
        a = _candidate(cost=2, fidelity=0.9, success_prob=1.0)
        b = _candidate(cost=2, fidelity=0.9, success_prob=1.0)
        assert not _dominates(a, b)
        assert not _dominates(b, a)

    def test_tradeoff_neither_dominates(self):
        cheaper_worse = _candidate(cost=2, fidelity=0.85, success_prob=1.0)
        pricier_better = _candidate(cost=6, fidelity=0.95, success_prob=1.0)
        assert not _dominates(cheaper_worse, pricier_better)
        assert not _dominates(pricier_better, cheaper_worse)

    def test_prune_removes_dominated(self):
        better = _candidate(cost=2, fidelity=0.95, success_prob=1.0, label="better")
        worse = _candidate(cost=4, fidelity=0.90, success_prob=0.9, label="worse")
        pruned = _prune_pareto([better, worse])
        assert pruned == [better]

    def test_prune_keeps_tradeoffs(self):
        cheap = _candidate(cost=2, fidelity=0.85, success_prob=1.0, label="cheap")
        expensive = _candidate(
            cost=6, fidelity=0.95, success_prob=1.0, label="expensive"
        )
        pruned = _prune_pareto([cheap, expensive])
        assert set(c.label for c in pruned) == {"cheap", "expensive"}


# ---------------------------------------------------------------------------
# _SpanPartitionSearch internals
# ---------------------------------------------------------------------------


class TestSpanPartitionSearch:
    def test_hop_level_frontier_includes_raw(self):
        net = ideal_net(N=2)
        search = _SpanPartitionSearch(
            net, max_link_copies=2, max_enumerated_rounds=3, budget_cap=100
        )
        frontier = search.frontier(0, 1)
        labels = [c.label for c in frontier]
        assert "hop0" in labels

    def test_memoization_reuses_span(self):
        net = ideal_net(N=4)
        search = _SpanPartitionSearch(
            net, max_link_copies=2, max_enumerated_rounds=3, budget_cap=100
        )
        first = search.frontier(0, 1)
        second = search.frontier(0, 1)
        assert first is second  # same list object returned from memo cache

    def test_budget_cap_excludes_expensive_candidates(self):
        net = ideal_net(N=2)
        search = _SpanPartitionSearch(
            net, max_link_copies=3, max_enumerated_rounds=3, budget_cap=2
        )
        frontier = search.frontier(0, 1)
        # budget_cap=2 means only the plain raw hop (cost=2) fits
        assert all(c.cost <= 2 for c in frontier)
        assert len(frontier) == 1

    def test_wider_span_combines_narrower_frontiers(self):
        net = ideal_net(N=2)
        search = _SpanPartitionSearch(
            net, max_link_copies=2, max_enumerated_rounds=3, budget_cap=100
        )
        frontier = search.frontier(0, 2)
        assert len(frontier) >= 1
        # every candidate at width 2 must cost >= 4 (two raw hops minimum)
        assert all(c.cost >= 4 for c in frontier)

    def test_all_frontier_nodes_reachable_and_valid(self):
        net = ideal_net(N=3)
        search = _SpanPartitionSearch(
            net, max_link_copies=2, max_enumerated_rounds=3, budget_cap=100
        )
        frontier = search.frontier(0, 3)
        for cand in frontier:
            assert cand.node_id in search.nodes

    def test_exact_pumping_lifts_the_default_pumping_cap(self):
        """`exact_pumping=True` must disable the pumping-related caps
        entirely, so it should generate a much larger (fully exhaustive)
        per-span frontier than the default, beam-limited pumping mode.

        See `dp.py`'s "Exactness modes" docstring section: by default,
        `dp_search`'s pumping is a bounded heuristic, not exact - this
        test exists to confirm `exact_pumping=True` genuinely lifts that
        bound rather than being a no-op.

        Deliberately NOT using `ideal_net` here: its zero inner-error
        params leave almost nothing to Pareto-prune, so the uncapped
        exact frontier explodes to thousands of candidates and takes
        minutes just to build at N=3. A network with nonzero inner error
        (matching tests/test_heuristic.py's `uniform_net`) prunes far
        more aggressively and stays fast while still clearly exceeding
        the default cap.
        """
        net = NetworkConfig.uniform(
            N=3,
            length=2.0,
            branching=(16, 14, 1),
            arm_count=18,
            p_x_inner=0.003,
            p_z_inner=0.003,
            e_d=0.01,
            gamma=1e-3,
            c=2e5,
        )
        capped = _SpanPartitionSearch(
            net, max_link_copies=3, max_enumerated_rounds=3, budget_cap=18
        )
        exact = _SpanPartitionSearch(
            net,
            max_link_copies=3,
            max_enumerated_rounds=3,
            budget_cap=18,
            exact_pumping=True,
        )
        capped_frontier = capped.frontier(0, 3)
        exact_frontier = exact.frontier(0, 3)
        assert len(capped_frontier) == _DEFAULT_PUMP_POOL_WIDTH
        assert len(exact_frontier) > len(capped_frontier)


# ---------------------------------------------------------------------------
# dp_search public API
# ---------------------------------------------------------------------------


class TestDpSearch:
    def test_returns_sorted_best_first(self):
        net = ideal_net(N=2, e_d=0.01)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.0)
        results = dp_search(net, obj, e_max=20)
        assert results == sorted(results, key=lambda r: r.score, reverse=True)

    def test_result_type(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=12)
        for r in results:
            assert isinstance(r, SearchResult)

    def test_respects_budget(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        e_max = 12
        results = dp_search(net, obj, e_max=e_max)
        for r in results:
            assert r.eval_result.resource_cost <= e_max

    def test_superset_of_brute_force_labels(self):
        net = ideal_net(N=4, e_d=0.01)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)
        bf = brute_force_search(net, obj, e_max=24)
        dp = dp_search(net, obj, e_max=24)
        bf_labels = {r.label for r in bf}
        dp_labels = {r.label for r in dp}
        assert bf_labels.issubset(dp_labels)

    def test_dp_best_score_at_least_as_good_as_brute_force(self):
        net = ideal_net(N=4, e_d=0.01)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)
        bf = brute_force_search(net, obj, e_max=24)
        dp = dp_search(net, obj, e_max=24)
        assert dp[0].score >= bf[0].score

    def test_matches_raw_chain_exactly(self):
        # The plain "no purification" recipe must appear in both searches
        # with identical numbers (same underlying physics/evaluator).
        net = ideal_net(N=4, e_d=0.01)
        obj = ObjectiveConfig(primary="fidelity")
        dp = dp_search(net, obj, e_max=8, include_brute_force_families=False)
        bf = brute_force_search(net, obj, e_max=8)
        raw = next(r for r in bf if r.label == "raw")
        # cheapest DP candidate (cost == raw's cost) should match raw's fidelity
        cheapest = min(dp, key=lambda r: r.eval_result.resource_cost)
        assert cheapest.eval_result.resource_cost == raw.eval_result.resource_cost
        assert cheapest.eval_result.fidelity == pytest.approx(raw.eval_result.fidelity)

    def test_all_dags_validate_and_evaluate_consistently(self):
        net = ideal_net(N=3)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=18)
        evaluator = Evaluator(net)
        for r in results[:10]:
            r.dag.validate()
            recomputed = evaluator.evaluate(r.dag)
            assert recomputed.fidelity == pytest.approx(r.eval_result.fidelity)
            assert recomputed.resource_cost == r.eval_result.resource_cost

    def test_exclude_brute_force_families(self):
        net = ideal_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=20, include_brute_force_families=False)
        for r in results:
            assert r.label.startswith("dp.span.")

    def test_result_label_uniqueness(self):
        net = ideal_net(N=3)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=18)
        labels = [r.label for r in results]
        assert len(labels) == len(set(labels))

    def test_n_equals_one_network(self):
        # Degenerate single-hop network: no splits possible, only hop-level
        # base-case candidates should appear.
        net = ideal_net(N=1)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=10, include_brute_force_families=False)
        assert len(results) >= 1
        for r in results:
            r.dag.validate()

    def test_invalid_n_raises(self):
        obj = ObjectiveConfig(primary="fidelity")

        class _FakeNetwork:
            N = 0

        with pytest.raises(ValueError):
            dp_search(_FakeNetwork(), obj, e_max=10)

    def test_dp_span_partition_can_beat_uniform_link_pumping(self):
        # On a network with heterogeneous hop lengths, per-hop-variable
        # copy-count (only explorable via dp_search) should be able to
        # match or beat brute force's uniform-copy-count link family at
        # equal or lower cost for at least one feasible budget.
        net = ideal_net(N=4, e_d=0.02)
        obj = ObjectiveConfig.maximize_fidelity_with_rate_floor(r_min=0.0)
        bf = brute_force_search(net, obj, e_max=24)
        dp = dp_search(net, obj, e_max=24)
        best_bf = max(r.eval_result.fidelity for r in bf if r.score > float("-inf"))
        best_dp = max(r.eval_result.fidelity for r in dp if r.score > float("-inf"))
        assert best_dp >= best_bf - 1e-9
