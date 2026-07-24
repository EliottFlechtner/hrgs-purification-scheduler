"""Tests for lossless ScheduleDAG / NetworkConfig ser/de (schedule/serde.py)."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from hrgs_scheduler.cost_functions import ObjectiveConfig
from hrgs_scheduler.models.network_config import HopConfig, NetworkConfig
from hrgs_scheduler.models.stage import RGSS, Span
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    IdleNode,
    JoinNode,
    PauliCorrectNode,
    PurifyNode,
)
from hrgs_scheduler.schedule.serde import (
    SERDE_VERSION,
    dag_to_dict,
    dict_to_dag,
    dict_to_network,
    load_schedule,
    network_to_dict,
    save_schedule,
)
from hrgs_scheduler.search import (
    brute_force_search,
    dp_search,
    load_result,
    save_result,
    save_top,
)
from hrgs_scheduler.search.brute_force import SearchResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def small_net(N: int = 3) -> NetworkConfig:
    return NetworkConfig.uniform(
        N=N,
        length=2.0,
        branching=(16, 14, 1),
        arm_count=18,
        p_x_inner=0.0,
        p_z_inner=0.0,
        e_d=0.01,
        gamma=0.0,
        c=2e5,
    )


def het_net() -> NetworkConfig:
    """Heterogeneous network: tests non-uniform hop serialization."""
    return NetworkConfig(
        hops=(
            HopConfig(
                length=1.5,
                branching=(8, 4),
                arm_count=10,
                p_x_inner=0.001,
                p_z_inner=0.002,
                eta=0.95,
            ),
            HopConfig(
                length=3.0,
                branching=(16, 14, 1),
                arm_count=18,
                p_x_inner=0.003,
                p_z_inner=0.003,
                eta=None,
                attenuation_db_per_km=0.25,
            ),
        ),
        e_d=0.005,
        gamma=1e-4,
        c=2e5,
    )


def _nodes_equal(a: ScheduleDAG, b: ScheduleDAG) -> bool:
    """Deep-compare two ScheduleDAGs (ScheduleDAG is not frozen → no __eq__)."""
    if a.root_id != b.root_id or a.N != b.N:
        return False
    if set(a.nodes) != set(b.nodes):
        return False
    return all(a.nodes[nid] == b.nodes[nid] for nid in a.nodes)


# ---------------------------------------------------------------------------
# Stage round-trip
# ---------------------------------------------------------------------------


class TestStageRoundTrip:
    from hrgs_scheduler.schedule.serde import _dict_to_stage, _stage_to_dict

    def test_rgss_roundtrip(self):
        from hrgs_scheduler.schedule.serde import _dict_to_stage, _stage_to_dict

        d = _stage_to_dict(RGSS)
        assert d == {"type": "RGSS"}
        assert _dict_to_stage(d) == RGSS

    def test_span_roundtrip(self):
        from hrgs_scheduler.schedule.serde import _dict_to_stage, _stage_to_dict

        s = Span(2, 5)
        d = _stage_to_dict(s)
        assert d == {"type": "Span", "a": 2, "b": 5}
        assert _dict_to_stage(d) == s

    def test_unknown_stage_raises(self):
        from hrgs_scheduler.schedule.serde import _dict_to_stage

        with pytest.raises(ValueError, match="Unknown stage type"):
            _dict_to_stage({"type": "BOGUS"})


# ---------------------------------------------------------------------------
# Node round-trip (each node type)
# ---------------------------------------------------------------------------


class TestNodeRoundTrip:
    from hrgs_scheduler.schedule.serde import _dict_to_node, _node_to_dict

    def _rt(self, node):
        from hrgs_scheduler.schedule.serde import _dict_to_node, _node_to_dict

        d = _node_to_dict(node)
        back = _dict_to_node(d)
        assert back == node
        return d

    def test_gen_node(self):
        node = GenNode(node_id=0, hop_index=2, gen_time=0.0, side_effect_parity=1)
        d = self._rt(node)
        assert d["type"] == "GenNode"
        assert d["side_effect_parity"] == 1

    def test_absa_bsm_node(self):
        node = AbsaBsmNode(node_id=2, children=(0, 1), hop_index=1)
        d = self._rt(node)
        assert d["type"] == "AbsaBsmNode"
        assert d["children"] == [0, 1]

    def test_join_node_span_stage(self):
        node = JoinNode(node_id=5, children=(3, 4), output_stage=Span(0, 2))
        d = self._rt(node)
        assert d["output_stage"] == {"type": "Span", "a": 0, "b": 2}

    def test_join_node_rgss_stage(self):
        node = JoinNode(node_id=5, children=(3, 4), output_stage=RGSS)
        self._rt(node)

    def test_purify_node_yy(self):
        node = PurifyNode(
            node_id=6,
            children=(3, 4),
            circuit=PurificationCircuit.YY,
            output_stage=Span(0, 1),
        )
        d = self._rt(node)
        assert d["circuit"] == "YY"

    def test_purify_node_zx(self):
        node = PurifyNode(
            node_id=6,
            children=(3, 4),
            circuit=PurificationCircuit.ZX,
            output_stage=Span(1, 2),
        )
        d = self._rt(node)
        assert d["circuit"] == "ZX"

    def test_purify_node_xz(self):
        node = PurifyNode(
            node_id=6,
            children=(3, 4),
            circuit=PurificationCircuit.XZ,
            output_stage=Span(0, 1),
        )
        d = self._rt(node)
        assert d["circuit"] == "XZ"

    def test_idle_node(self):
        node = IdleNode(node_id=7, children=(5,), until=1.234)
        d = self._rt(node)
        assert d["until"] == pytest.approx(1.234)

    def test_herald_node_default_prop_time(self):
        node = HeraldNode(node_id=8, children=(7,))
        d = self._rt(node)
        assert d["propagation_time"] == 1.0

    def test_herald_node_custom_prop_time(self):
        node = HeraldNode(node_id=8, children=(7,), propagation_time=2.0)
        d = self._rt(node)
        assert d["propagation_time"] == 2.0

    def test_pauli_correct_node(self):
        node = PauliCorrectNode(node_id=9, children=(8,), N=4)
        d = self._rt(node)
        assert d["N"] == 4

    def test_unknown_node_raises(self):
        from hrgs_scheduler.schedule.serde import _node_to_dict

        with pytest.raises(ValueError, match="Unknown node type"):
            _node_to_dict(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DAG round-trip
# ---------------------------------------------------------------------------


class TestDagRoundTrip:
    def test_raw_chain_roundtrip(self):
        dag = ScheduleDAG.raw_chain(N=3)
        d = dag_to_dict(dag)
        back = dict_to_dag(d)
        back.validate()
        assert _nodes_equal(dag, back)

    def test_single_hop_yy_roundtrip(self):
        dag = ScheduleDAG.single_hop_yy_purified(N=1)
        d = dag_to_dict(dag)
        back = dict_to_dag(d)
        back.validate()
        assert _nodes_equal(dag, back)

    def test_baseline_end_node_roundtrip(self):
        dag = ScheduleDAG.baseline_end_node_pumping(N=3, n_pur=3)
        d = dag_to_dict(dag)
        back = dict_to_dag(d)
        back.validate()
        assert _nodes_equal(dag, back)

    def test_flexible_paper_roundtrip(self):
        dag = ScheduleDAG.flexible_paper_schedule(N=4)
        d = dag_to_dict(dag)
        back = dict_to_dag(d)
        back.validate()
        assert _nodes_equal(dag, back)

    def test_node_ids_are_ints_after_load(self):
        dag = ScheduleDAG.raw_chain(N=2)
        d = dag_to_dict(dag)
        # JSON encodes dict keys as strings; dict_to_dag must convert back
        json_str = json.dumps(d)
        d2 = json.loads(json_str)
        back = dict_to_dag(d2)
        for nid in back.nodes:
            assert isinstance(nid, int)

    def test_roundtrip_preserves_evaluation(self):
        net = small_net(N=3)
        dag = ScheduleDAG.flexible_paper_schedule(N=4)
        ev_orig = Evaluator(
            NetworkConfig.uniform(
                N=4,
                length=2.0,
                branching=(16, 14, 1),
                arm_count=18,
                p_x_inner=0.0,
                p_z_inner=0.0,
                e_d=0.01,
                gamma=0.0,
                c=2e5,
            )
        ).evaluate(dag)
        d = dag_to_dict(dag)
        back = dict_to_dag(d)
        ev_back = Evaluator(
            NetworkConfig.uniform(
                N=4,
                length=2.0,
                branching=(16, 14, 1),
                arm_count=18,
                p_x_inner=0.0,
                p_z_inner=0.0,
                e_d=0.01,
                gamma=0.0,
                c=2e5,
            )
        ).evaluate(back)
        assert ev_orig.fidelity == pytest.approx(ev_back.fidelity)
        assert ev_orig.resource_cost == ev_back.resource_cost
        assert ev_orig.success_prob == pytest.approx(ev_back.success_prob)


# ---------------------------------------------------------------------------
# NetworkConfig round-trip
# ---------------------------------------------------------------------------


class TestNetworkRoundTrip:
    def test_uniform_network_roundtrip(self):
        net = small_net(N=4)
        d = network_to_dict(net)
        back = dict_to_network(d)
        assert back.e_d == net.e_d
        assert back.gamma == net.gamma
        assert back.c == net.c
        assert back.N == net.N
        for i in range(net.N):
            h, b = net.hop(i), back.hop(i)
            assert h.length == b.length
            assert h.branching == b.branching
            assert h.arm_count == b.arm_count
            assert h.p_x_inner == b.p_x_inner
            assert h.p_z_inner == b.p_z_inner
            assert h.eta == pytest.approx(b.eta)

    def test_heterogeneous_network_roundtrip(self):
        net = het_net()
        d = network_to_dict(net)
        back = dict_to_network(d)
        assert back.N == 2
        # eta for hop 0 was given explicitly; must round-trip exactly
        assert back.hop(0).eta == pytest.approx(net.hop(0).eta)
        # eta for hop 1 was computed from length/attenuation; must also match
        assert back.hop(1).eta == pytest.approx(net.hop(1).eta)
        assert back.hop(1).attenuation_db_per_km == net.hop(1).attenuation_db_per_km

    def test_network_physics_unchanged_after_roundtrip(self):
        """Re-evaluating the same DAG on original vs. deserialized net gives same result."""
        net = small_net(N=3)
        dag = ScheduleDAG.raw_chain(N=3)
        ev_orig = Evaluator(net).evaluate(dag)
        ev_back = Evaluator(dict_to_network(network_to_dict(net))).evaluate(dag)
        assert ev_orig.fidelity == pytest.approx(ev_back.fidelity, rel=1e-12)
        assert ev_orig.latency == pytest.approx(ev_back.latency, rel=1e-12)


# ---------------------------------------------------------------------------
# save_schedule / load_schedule file I/O
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_roundtrip_raw_chain(self):
        net = small_net(N=3)
        dag = ScheduleDAG.raw_chain(N=3)
        with tempfile.TemporaryDirectory() as tmp:
            p = save_schedule(
                dag,
                Path(tmp) / "raw.json",
                network=net,
                label="raw",
                score=42.0,
                fidelity=0.9,
                rate=1000.0,
                resource_cost=6,
                latency_s=1e-4,
                success_prob=1.0,
            )
            back_dag, back_net, meta = load_schedule(p)
        back_dag.validate()
        assert _nodes_equal(dag, back_dag)
        assert meta["label"] == "raw"
        assert meta["score"] == pytest.approx(42.0)
        assert meta["eval"]["fidelity"] == pytest.approx(0.9)
        assert meta["eval"]["resource_cost"] == 6

    def test_file_has_schema_and_version(self):
        net = small_net(N=2)
        dag = ScheduleDAG.raw_chain(N=2)
        with tempfile.TemporaryDirectory() as tmp:
            p = save_schedule(dag, Path(tmp) / "test.json", network=net)
            d = json.loads(p.read_text())
        assert d["_schema"] == "hrgs_schedule"
        assert d["_version"] == SERDE_VERSION

    def test_load_wrong_schema_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text(json.dumps({"_schema": "OTHER", "_version": 1}))
            with pytest.raises(ValueError, match="schema"):
                load_schedule(p)

    def test_load_wrong_version_raises(self):
        net = small_net(N=2)
        dag = ScheduleDAG.raw_chain(N=2)
        with tempfile.TemporaryDirectory() as tmp:
            p = save_schedule(dag, Path(tmp) / "test.json", network=net)
            d = json.loads(p.read_text())
            d["_version"] = 999
            p.write_text(json.dumps(d))
            with pytest.raises(ValueError, match="version"):
                load_schedule(p)

    def test_nulls_allowed_in_optional_fields(self):
        net = small_net(N=2)
        dag = ScheduleDAG.raw_chain(N=2)
        with tempfile.TemporaryDirectory() as tmp:
            p = save_schedule(dag, Path(tmp) / "minimal.json", network=net)
            _, _, meta = load_schedule(p)
        assert meta["score"] is None
        for v in meta["eval"].values():
            assert v is None

    def test_parent_dirs_created(self):
        net = small_net(N=2)
        dag = ScheduleDAG.raw_chain(N=2)
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp) / "a" / "b" / "c" / "schedule.json"
            assert not deep.parent.exists()
            save_schedule(dag, deep, network=net)
            assert deep.exists()


# ---------------------------------------------------------------------------
# save_result / load_result  (SearchResult wrapper)
# ---------------------------------------------------------------------------


class TestSearchResultRoundTrip:
    def _run_search(self, N=3):
        net = small_net(N=N)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.9)
        results = dp_search(net, obj, e_max=18)
        return results, net

    def test_label_preserved(self):
        results, net = self._run_search()
        orig = results[0]
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(orig, Path(tmp) / "r.json", network=net)
            loaded, _ = load_result(p)
        assert loaded.label == orig.label

    def test_eval_scalars_preserved(self):
        results, net = self._run_search()
        orig = results[0]
        ev = orig.eval_result
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(orig, Path(tmp) / "r.json", network=net)
            loaded, _ = load_result(p)
        assert loaded.eval_result.fidelity == pytest.approx(ev.fidelity, rel=1e-12)
        assert loaded.eval_result.rate == pytest.approx(ev.rate, rel=1e-12)
        assert loaded.eval_result.resource_cost == ev.resource_cost
        assert loaded.eval_result.latency == pytest.approx(ev.latency, rel=1e-12)
        assert loaded.eval_result.success_prob == pytest.approx(
            ev.success_prob, rel=1e-12
        )

    def test_score_preserved_feasible(self):
        results, net = self._run_search()
        orig = next(r for r in results if r.score > float("-inf"))
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(orig, Path(tmp) / "r.json", network=net)
            loaded, _ = load_result(p)
        assert loaded.score == pytest.approx(orig.score, rel=1e-12)

    def test_score_preserved_infeasible(self):
        results, net = self._run_search()
        infeasible = next((r for r in results if r.score == float("-inf")), None)
        if infeasible is None:
            pytest.skip("no infeasible result in test run")
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(infeasible, Path(tmp) / "r.json", network=net)
            loaded, _ = load_result(p)
        assert loaded.score == float("-inf")

    def test_dag_validates_after_load(self):
        results, net = self._run_search()
        with tempfile.TemporaryDirectory() as tmp:
            for res in results[:5]:
                p = save_result(res, Path(tmp) / f"{res.label[:30]}.json", network=net)
                loaded, _ = load_result(p)
                loaded.dag.validate()

    def test_reeval_matches_stored(self):
        results, net = self._run_search()
        orig = results[0]
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(orig, Path(tmp) / "r.json", network=net)
            loaded_dag, loaded_net, meta = __import__(
                "hrgs_scheduler.schedule.serde", fromlist=["load_schedule"]
            ).load_schedule(p)
        ev = Evaluator(loaded_net).evaluate(loaded_dag)
        assert ev.fidelity == pytest.approx(meta["eval"]["fidelity"], rel=1e-12)
        assert ev.resource_cost == meta["eval"]["resource_cost"]
        assert ev.success_prob == pytest.approx(meta["eval"]["success_prob"], rel=1e-12)

    def test_loaded_node_states_empty(self):
        """node_states is not stored; returned as empty dict."""
        results, net = self._run_search()
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(results[0], Path(tmp) / "r.json", network=net)
            loaded, _ = load_result(p)
        assert loaded.eval_result.node_states == {}

    def test_network_roundtrip_via_result(self):
        results, net = self._run_search()
        with tempfile.TemporaryDirectory() as tmp:
            p = save_result(results[0], Path(tmp) / "r.json", network=net)
            _, loaded_net = load_result(p)
        assert loaded_net.N == net.N
        assert loaded_net.e_d == pytest.approx(net.e_d)
        assert loaded_net.c == pytest.approx(net.c)


# ---------------------------------------------------------------------------
# save_top
# ---------------------------------------------------------------------------


class TestSaveTop:
    def test_saves_n_files(self):
        net = small_net(N=3)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=18)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "top"
            paths = save_top(results, out_dir, network=net, n=3)
        assert len(paths) == 3

    def test_filenames_rank_prefixed(self):
        net = small_net(N=3)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=18)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "top"
            paths = save_top(results, out_dir, network=net, n=3)
        assert paths[0].name.startswith("rank_001_")
        assert paths[1].name.startswith("rank_002_")
        assert paths[2].name.startswith("rank_003_")

    def test_all_saved_files_are_valid(self):
        net = small_net(N=3)
        obj = ObjectiveConfig(primary="fidelity")
        results = dp_search(net, obj, e_max=18)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "top"
            paths = save_top(results, out_dir, network=net, n=5)
            for p in paths:
                dag, _, meta = load_schedule(p)
                dag.validate()
                assert meta["label"] != ""

    def test_infeasible_excluded_by_default(self):
        net = small_net(N=3)
        obj = ObjectiveConfig.maximize_rate_with_fidelity_floor(f_min=0.99)
        results = dp_search(net, obj, e_max=12)
        infeasible = [r for r in results if r.score == float("-inf")]
        if not infeasible:
            pytest.skip("no infeasible results with this config")
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "top"
            paths = save_top(
                results, out_dir, network=net, n=len(results), include_infeasible=False
            )
            for p in paths:
                _, _, meta = load_schedule(p)
                assert meta["score"] is not None

    def test_n_larger_than_results_saves_all(self):
        net = small_net(N=2)
        obj = ObjectiveConfig(primary="fidelity")
        results = brute_force_search(net, obj, e_max=8)
        feasible = [r for r in results if r.score > float("-inf")]
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "top"
            paths = save_top(results, out_dir, network=net, n=9999)
        assert len(paths) == len(feasible)
