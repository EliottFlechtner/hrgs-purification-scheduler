"""Tests for hrgs_scheduler.schedule.dag.ScheduleDAG."""

import pytest

from hrgs_scheduler.models.stage import RGSS, Span
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    JoinNode,
    PauliCorrectNode,
    PurifyNode,
)

# ---------------------------------------------------------------------------
# raw_chain
# ---------------------------------------------------------------------------


def test_raw_chain_validates():
    dag = ScheduleDAG.raw_chain(N=4)
    dag.validate()  # must not raise


def test_raw_chain_gen_node_count():
    dag = ScheduleDAG.raw_chain(N=4)
    assert dag.gen_node_count == 2 * 4  # two Gen leaves per hop


def test_raw_chain_no_purify_nodes():
    dag = ScheduleDAG.raw_chain(N=4)
    assert dag.purify_node_count == 0


def test_raw_chain_root_is_pauli_correct_at_full_span():
    dag = ScheduleDAG.raw_chain(N=5)
    root = dag.nodes[dag.root_id]
    assert isinstance(root, PauliCorrectNode)
    assert root.output_stage == Span(0, 5)


def test_raw_chain_topological_order_root_last():
    dag = ScheduleDAG.raw_chain(N=3)
    order = dag.topological_order()
    assert order[-1] == dag.root_id
    assert len(order) == len(dag.nodes)


# ---------------------------------------------------------------------------
# baseline_end_node_pumping
# ---------------------------------------------------------------------------


def test_baseline_validates():
    dag = ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5)
    dag.validate()


def test_baseline_gen_node_count():
    # n_pur independent raw N-hop chains, 2 Gen leaves per hop each.
    dag = ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5)
    assert dag.gen_node_count == 5 * 2 * 4


def test_baseline_purify_node_count():
    dag = ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5)
    assert dag.purify_node_count == 4  # n_pur - 1 pumping rounds


def test_baseline_has_intermediate_round_trip_heralds():
    dag = ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=5)
    herald_nodes = [n for n in dag.nodes.values() if isinstance(n, HeraldNode)]
    # 4 intermediate round-trip heralds (2.0) + 1 final one-way herald (1.0)
    round_trip = [h for h in herald_nodes if h.propagation_time == 2.0]
    final_heralds = [h for h in herald_nodes if h.propagation_time == 1.0]
    assert len(round_trip) == 4
    assert len(final_heralds) == 1


def test_baseline_rejects_n_pur_below_one():
    with pytest.raises(ValueError):
        ScheduleDAG.baseline_end_node_pumping(N=4, n_pur=0)


# ---------------------------------------------------------------------------
# flexible_paper_schedule
# ---------------------------------------------------------------------------


def test_flexible_validates():
    dag = ScheduleDAG.flexible_paper_schedule(N=10)
    dag.validate()


def test_flexible_requires_even_n():
    with pytest.raises(ValueError):
        ScheduleDAG.flexible_paper_schedule(N=5)


def test_flexible_gen_node_count_matches_five_copies_per_side_per_hop():
    # [Integrating, Fig. 5 caption]: "five half-RGSs per side...instead of
    # one" -- Pair A (2 copies/hop x N hops) + Pair B (2 copies/half-segment
    # x 2 segments = 2 copies/hop equivalent x N hops via 2 half segments)
    # + Pair C (1 copy/hop x N hops) = 5 copies per hop per side... verified
    # numerically against the paper's reproduction script rather than
    # re-derived combinatorially here.
    dag = ScheduleDAG.flexible_paper_schedule(N=10)
    assert dag.gen_node_count == 100  # 5 copies x 10 hops x 2 sides


def test_flexible_only_final_herald_present():
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    herald_nodes = [n for n in dag.nodes.values() if isinstance(n, HeraldNode)]
    assert len(herald_nodes) == 1
    assert herald_nodes[0].propagation_time == 1.0


def test_flexible_purify_node_count():
    # N link-level YY purifications + 2 segment-level YY purifications
    # + 2 final combination purifications (ZX then YY).
    dag = ScheduleDAG.flexible_paper_schedule(N=4)
    assert dag.purify_node_count == 4 + 2 + 2


# ---------------------------------------------------------------------------
# single_hop_yy_purified
# ---------------------------------------------------------------------------


def test_single_hop_yy_purified_validates():
    dag = ScheduleDAG.single_hop_yy_purified(N=1, n_pur=2)
    dag.validate()


def test_single_hop_yy_purified_rejects_multi_hop():
    with pytest.raises(NotImplementedError):
        ScheduleDAG.single_hop_yy_purified(N=2, n_pur=1)


# ---------------------------------------------------------------------------
# validate() legality checks
# ---------------------------------------------------------------------------


def test_validate_rejects_non_pauli_correct_root():
    dag = ScheduleDAG.raw_chain(N=2)
    # Point root_id at a non-PauliCorrectNode.
    non_root_id = next(
        nid for nid, n in dag.nodes.items() if not isinstance(n, PauliCorrectNode)
    )
    broken = ScheduleDAG(nodes=dag.nodes, root_id=non_root_id, N=2)
    with pytest.raises(ValueError):
        broken.validate()


def test_validate_rejects_unreachable_node():
    dag = ScheduleDAG.raw_chain(N=2)
    nodes = dict(dag.nodes)
    stray = GenNode(node_id=9999, hop_index=0, gen_time=0.0)
    nodes[stray.node_id] = stray
    broken = ScheduleDAG(nodes=nodes, root_id=dag.root_id, N=2)
    with pytest.raises(ValueError):
        broken.validate()


def test_validate_rejects_non_adjacent_span_join():
    # Deliberately build a JoinNode combining two non-adjacent spans.
    nodes = {}
    g0l = GenNode(node_id=0, hop_index=0, gen_time=0.0)
    g0r = GenNode(node_id=1, hop_index=0, gen_time=0.0)
    g2l = GenNode(node_id=2, hop_index=2, gen_time=0.0)
    g2r = GenNode(node_id=3, hop_index=2, gen_time=0.0)
    nodes[0], nodes[1], nodes[2], nodes[3] = g0l, g0r, g2l, g2r
    bsm0 = AbsaBsmNode(node_id=4, children=(0, 1), hop_index=0)
    bsm2 = AbsaBsmNode(node_id=5, children=(2, 3), hop_index=2)
    nodes[4], nodes[5] = bsm0, bsm2
    # Illegally join Span(0,1) with Span(2,3) -- not adjacent.
    bad_join = JoinNode(node_id=6, children=(4, 5), output_stage=Span(0, 3))
    nodes[6] = bad_join
    herald_node = HeraldNode(node_id=7, children=(6,), propagation_time=1.0)
    nodes[7] = herald_node
    root = PauliCorrectNode(node_id=8, children=(7,), N=3)
    nodes[8] = root

    broken = ScheduleDAG(nodes=nodes, root_id=8, N=3)
    with pytest.raises(ValueError):
        broken.validate()


def test_validate_rejects_purify_with_mismatched_stages():
    nodes = {}
    g_rgss = GenNode(node_id=0, hop_index=0, gen_time=0.0)
    g_rgss2 = GenNode(node_id=1, hop_index=0, gen_time=0.0)
    nodes[0], nodes[1] = g_rgss, g_rgss2
    bsm = AbsaBsmNode(node_id=2, children=(0, 1), hop_index=0)
    nodes[2] = bsm
    g_extra = GenNode(node_id=3, hop_index=0, gen_time=0.0)
    nodes[3] = g_extra
    # Purify a Span(0,1) resource against an RGSS resource -- illegal.
    bad_pur = PurifyNode(
        node_id=4,
        children=(2, 3),
        circuit=PurificationCircuit.YY,
        output_stage=Span(0, 1),
    )
    nodes[4] = bad_pur
    herald_node = HeraldNode(node_id=5, children=(4,), propagation_time=1.0)
    nodes[5] = herald_node
    root = PauliCorrectNode(node_id=6, children=(5,), N=1)
    nodes[6] = root

    broken = ScheduleDAG(nodes=nodes, root_id=6, N=1)
    with pytest.raises(ValueError):
        broken.validate()
