"""Tests for the beam-search heuristic tier (search/heuristic.py)."""

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import NetworkConfig
from hrgs_scheduler.search import beam_search, dp_search
from hrgs_scheduler.search.brute_force import brute_force_search


def uniform_net(N: int, e_d: float = 0.01) -> NetworkConfig:
    return NetworkConfig.uniform(
        N=N,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.003,
        p_z_inner=0.003,
        e_d=e_d,
        gamma=1e-3,
        c=2e5,
    )


class TestBeamSearchSmallN:
    """Cross-check beam_search against exact dp_search on tractable N.

    IMPORTANT: `dp_search`'s *default* output is no longer a provable
    upper bound on `beam_search` once pumping is involved (see
    `search/dp.py`'s "Exactness modes" docstring section) - its own
    per-span pumping cap is a beam-limited heuristic, same tradeoff
    `beam_search` makes, just with a different default width. These two
    tests specifically validate the "never beaten by exact DP" invariant,
    so they must use `exact_pumping=True` (genuinely uncapped) as the
    ground truth, not the default capped `dp_search`. That mode is only
    fast at very small N, hence N=3 here rather than N=4 (this was
    manually cross-checked at N=4, e_max=24 too: both sides scored
    9241.0249 exactly, ~83s - too slow to run on every test invocation,
    so not included as an automated test, but recorded here as
    supporting evidence the invariant also holds at that size).
    """

    def test_matches_exact_dp_best_score_with_generous_beam(self):
        net = uniform_net(N=3)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)

        dp_results = dp_search(net, obj, e_max=18, exact_pumping=True)
        beam_results = beam_search(net, obj, e_max=18, beam_width=25)

        assert beam_results[0].score == dp_results[0].score

    def test_never_beats_exact_dp(self):
        """A beam-capped frontier can only be a subset of what exact DP
        considers, so its best score can never exceed the exact optimum."""
        net = uniform_net(N=3)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)

        dp_results = dp_search(net, obj, e_max=18, exact_pumping=True)
        beam_results = beam_search(net, obj, e_max=18, beam_width=6)

        assert beam_results[0].score <= dp_results[0].score

    def test_superset_of_brute_force_labels(self):
        net = uniform_net(N=4)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)

        bf_labels = {r.label for r in brute_force_search(net, obj, e_max=24)}
        beam_labels = {r.label for r in beam_search(net, obj, e_max=24)}
        assert bf_labels.issubset(beam_labels)


class TestBeamSearchScalesToLargeN:
    """The whole point of this tier: tractable at N where dp_search is not."""

    def test_runs_at_paper_scale_n10(self):
        net = NetworkConfig.integrating_paper_config(e_d=0.01)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)

        results = beam_search(
            net,
            obj,
            e_max=200,
            beam_width=25,
            max_link_copies=3,
            max_enumerated_rounds=3,
        )
        feasible = [r for r in results if r.score != float("-inf")]
        assert len(feasible) > 0

    def test_finds_own_span_partition_candidates_at_n10(self):
        """Regression test: an earlier ranking heuristic discarded every
        purified sub-span candidate at low spans (single-hop fidelity is
        trivially high regardless of purification), leaving nothing
        purified in the beam by the time N=10 hops are composed and the
        composite fidelity actually needs it. Guard against that bug by
        asserting beam_search finds feasible results of its own (not just
        the merged brute_force families)."""
        net = NetworkConfig.integrating_paper_config(e_d=0.01)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)

        results = beam_search(
            net,
            obj,
            e_max=200,
            beam_width=25,
            max_link_copies=3,
            max_enumerated_rounds=3,
        )
        beam_originated_feasible = [
            r
            for r in results
            if r.label.startswith("beam.span") and r.score != float("-inf")
        ]
        assert len(beam_originated_feasible) > 0

    def test_beam_width_validation(self):
        net = uniform_net(N=4)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)
        try:
            beam_search(net, obj, e_max=24, beam_width=0)
            assert False, "expected ValueError for beam_width < 1"
        except ValueError:
            pass
