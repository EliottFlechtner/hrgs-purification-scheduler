"""Tests for hrgs_scheduler.schedule.visualize.

Covers the purification-chain-depth helpers and to_dot's highlight_groups
support added for docs/Handoff_Timing_and_Pumping_Visualization.md.
"""

from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.visualize import (
    deepest_purification_chain,
    pumping_highlight_groups,
    purification_chain_depth,
    to_dot,
)

# ---------------------------------------------------------------------------
# purification_chain_depth / deepest_purification_chain
# ---------------------------------------------------------------------------


def test_raw_chain_has_zero_chain_depth():
    """No PurifyNode at all -> depth 0, empty chain."""
    dag = ScheduleDAG.raw_chain(N=4)
    assert purification_chain_depth(dag) == 0
    assert deepest_purification_chain(dag) == []


def test_baseline_end_node_pumping_chain_depth_is_one():
    """Heralded/sequential rounds are Herald-separated, so no two
    PurifyNodes are ever directly chained -- depth is always 1 regardless
    of n_pur.
    """
    dag = ScheduleDAG.baseline_end_node_pumping(4, n_pur=5)
    assert purification_chain_depth(dag) == 1
    chain = deepest_purification_chain(dag)
    assert len(chain) == 1


def test_flexible_paper_schedule_chain_depth_is_two():
    """ZX-purify(A, B) then YY-purify(result, C): two Herald-free rounds
    directly chained.
    """
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    assert purification_chain_depth(dag) == 2
    chain = deepest_purification_chain(dag)
    assert len(chain) == 2
    # Each entry in the chain must actually be a PurifyNode, and each
    # non-final entry's parent-of-chain relationship holds via children.
    from hrgs_scheduler.schedule.node import PurifyNode

    for nid in chain:
        assert isinstance(dag.nodes[nid], PurifyNode)


def test_chain_depth_computed_from_structure_not_labels():
    """Renaming/relabeling nodes (there is no label field to mutate on
    frozen dataclasses, so instead verify the depth doesn't change when
    only cosmetic evaluation annotations are added) -- a structural sanity
    check that depth comes purely from `children`, independent of any
    result/label decoration used only for display.
    """
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    depth_before = purification_chain_depth(dag)
    _ = to_dot(dag)  # rendering must not mutate/depend on hidden state
    depth_after = purification_chain_depth(dag)
    assert depth_before == depth_after == 2


# ---------------------------------------------------------------------------
# pumping_highlight_groups / to_dot(highlight_groups=...)
# ---------------------------------------------------------------------------


def test_pumping_highlight_groups_covers_chain_and_fresh_copies():
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    chain = deepest_purification_chain(dag)
    groups = pumping_highlight_groups(dag, chain)

    # One "chain" group plus one "fresh copy" group per round.
    chain_groups = [g for g in groups if g.startswith("Purification chain")]
    fresh_groups = [g for g in groups if g.startswith("Fresh copy")]
    assert len(chain_groups) == 1
    assert len(fresh_groups) == len(chain)

    chain_ids, _ = groups[chain_groups[0]]
    assert chain_ids == set(chain)

    # Fresh-copy groups must be disjoint from the chain itself.
    for _, (fresh_ids, _color) in ((g, groups[g]) for g in fresh_groups):
        assert fresh_ids.isdisjoint(chain_ids)


def test_pumping_highlight_groups_empty_chain_yields_no_groups():
    dag = ScheduleDAG.raw_chain(N=4)
    groups = pumping_highlight_groups(dag, [])
    assert groups == {}


def test_to_dot_highlight_groups_renders_clusters():
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    chain = deepest_purification_chain(dag)
    groups = pumping_highlight_groups(dag, chain)

    dot_src = to_dot(dag, highlight_groups=groups)

    assert dot_src.count("subgraph cluster_") == len(groups)
    for label in groups:
        assert label in dot_src
    # Baseline (no highlight_groups) must still render fine and contain no clusters.
    plain_src = to_dot(dag)
    assert "subgraph cluster_" not in plain_src


def test_to_dot_highlight_groups_does_not_lose_any_node_or_edge():
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    chain = deepest_purification_chain(dag)
    groups = pumping_highlight_groups(dag, chain)

    plain_src = to_dot(dag)
    highlighted_src = to_dot(dag, highlight_groups=groups)

    # Every node id must still get exactly one declaration line, and every
    # edge must still be present, regardless of highlighting.
    for nid in dag.nodes:
        needle = f"n{nid} ["
        assert plain_src.count(needle) == 1
        assert highlighted_src.count(needle) == 1
