"""
hrgs_scheduler.schedule.serde
================================
Lossless JSON serialization / deserialization for ScheduleDAG and
NetworkConfig objects: the two components needed to fully reproduce
any schedule found by the outer-loop search.

Format
------
Each saved artifact is a single JSON file with the following top-level
structure::

    {
      "_schema":  "hrgs_schedule",
      "_version": 1,
      "label":    "<search label>",
      "score":    <float|null>,
      "eval": {
        "fidelity":      <float>,
        "rate":          <float>,
        "resource_cost": <int>,
        "latency_s":     <float>,
        "success_prob":  <float>
      },
      "network": { ... },
      "dag":     { ... }
    }

Version history
---------------
  1: initial format (current).

Stability guarantees
--------------------
* All fields are named (no positional encoding).  Adding optional fields
  in a future version will not break loading version-1 files.
* When the format changes in a backward-incompatible way, ``_version``
  will be bumped and a migration function will be provided.
* Node IDs are stored as JSON string keys (JSON objects require string
  keys) and round-trip to ``int`` on load.  This is transparent to
  callers.

Public API
----------
``dag_to_dict(dag)``          Serialize a ScheduleDAG to a plain dict.
``dict_to_dag(d)``            Deserialize a ScheduleDAG from a plain dict.
``network_to_dict(network)``  Serialize a NetworkConfig to a plain dict.
``dict_to_network(d)``        Deserialize a NetworkConfig from a plain dict.
``save_schedule(...)``        Write a complete schedule artifact to JSON.
``load_schedule(path)``       Load a schedule artifact; return
                               ``(dag, network, meta)`` where *meta* is a
                               dict with keys ``label``, ``score``, ``eval``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hrgs_scheduler.models.network_config import HopConfig, NetworkConfig
from hrgs_scheduler.models.stage import RGSS, RGSSStage, Span, Stage
from hrgs_scheduler.operations.purification import PurificationCircuit
from hrgs_scheduler.schedule.dag import ScheduleDAG
from hrgs_scheduler.schedule.node import (
    AbsaBsmNode,
    GenNode,
    HeraldNode,
    IdleNode,
    JoinNode,
    NodeId,
    PauliCorrectNode,
    PurifyNode,
    ScheduleNode,
)

SERDE_VERSION: int = 1
_SCHEMA: str = "hrgs_schedule"

# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _stage_to_dict(stage: Stage) -> dict[str, Any]:
    if isinstance(stage, RGSSStage):
        return {"type": "RGSS"}
    if isinstance(stage, Span):
        return {"type": "Span", "a": stage.a, "b": stage.b}
    raise ValueError(f"Unknown stage: {stage!r}")


def _dict_to_stage(d: dict[str, Any]) -> Stage:
    t = d["type"]
    if t == "RGSS":
        return RGSS
    if t == "Span":
        return Span(d["a"], d["b"])
    raise ValueError(f"Unknown stage type: {t!r}")


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------


def _node_to_dict(node: ScheduleNode) -> dict[str, Any]:
    """Serialize one ScheduleNode to a plain dict (lossless)."""
    if isinstance(node, GenNode):
        return {
            "type": "GenNode",
            "node_id": node.node_id,
            "hop_index": node.hop_index,
            "gen_time": node.gen_time,
            "side_effect_parity": node.side_effect_parity,
        }
    if isinstance(node, AbsaBsmNode):
        return {
            "type": "AbsaBsmNode",
            "node_id": node.node_id,
            "children": list(node.children),
            "hop_index": node.hop_index,
        }
    if isinstance(node, JoinNode):
        return {
            "type": "JoinNode",
            "node_id": node.node_id,
            "children": list(node.children),
            "output_stage": _stage_to_dict(node.output_stage),
        }
    if isinstance(node, PurifyNode):
        return {
            "type": "PurifyNode",
            "node_id": node.node_id,
            "children": list(node.children),
            "circuit": node.circuit.name,
            "output_stage": _stage_to_dict(node.output_stage),
        }
    if isinstance(node, IdleNode):
        return {
            "type": "IdleNode",
            "node_id": node.node_id,
            "children": list(node.children),
            "until": node.until,
        }
    if isinstance(node, HeraldNode):
        return {
            "type": "HeraldNode",
            "node_id": node.node_id,
            "children": list(node.children),
            "propagation_time": node.propagation_time,
        }
    if isinstance(node, PauliCorrectNode):
        return {
            "type": "PauliCorrectNode",
            "node_id": node.node_id,
            "children": list(node.children),
            "N": node.N,
        }
    raise ValueError(f"Unknown node type: {type(node).__name__!r}")


def _dict_to_node(d: dict[str, Any]) -> ScheduleNode:
    """Deserialize one ScheduleNode from a plain dict."""
    t = d["type"]
    nid: NodeId = d["node_id"]
    if t == "GenNode":
        return GenNode(
            node_id=nid,
            hop_index=d["hop_index"],
            gen_time=d["gen_time"],
            side_effect_parity=d["side_effect_parity"],
        )
    if t == "AbsaBsmNode":
        return AbsaBsmNode(
            node_id=nid,
            children=tuple(d["children"]),
            hop_index=d["hop_index"],
        )
    if t == "JoinNode":
        return JoinNode(
            node_id=nid,
            children=tuple(d["children"]),
            output_stage=_dict_to_stage(d["output_stage"]),
        )
    if t == "PurifyNode":
        return PurifyNode(
            node_id=nid,
            children=tuple(d["children"]),
            circuit=PurificationCircuit[d["circuit"]],
            output_stage=_dict_to_stage(d["output_stage"]),
        )
    if t == "IdleNode":
        return IdleNode(
            node_id=nid,
            children=tuple(d["children"]),
            until=d["until"],
        )
    if t == "HeraldNode":
        return HeraldNode(
            node_id=nid,
            children=tuple(d["children"]),
            propagation_time=d["propagation_time"],
        )
    if t == "PauliCorrectNode":
        return PauliCorrectNode(
            node_id=nid,
            children=tuple(d["children"]),
            N=d["N"],
        )
    raise ValueError(f"Unknown node type in serialized data: {t!r}")


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------


def dag_to_dict(dag: ScheduleDAG) -> dict[str, Any]:
    """Serialize *dag* to a plain, JSON-safe dict.

    Node IDs are stored as string keys (required by the JSON spec for
    object keys); they are converted back to ``int`` by ``dict_to_dag``.
    """
    return {
        "N": dag.N,
        "root_id": dag.root_id,
        "nodes": {str(nid): _node_to_dict(node) for nid, node in dag.nodes.items()},
    }


def dict_to_dag(d: dict[str, Any]) -> ScheduleDAG:
    """Reconstruct a :class:`ScheduleDAG` from a plain dict.

    Raises
    ------
    ValueError
        On malformed input (unknown node type, bad stage, etc.).
    """
    nodes: dict[NodeId, ScheduleNode] = {
        int(k): _dict_to_node(v) for k, v in d["nodes"].items()
    }
    return ScheduleDAG(nodes=nodes, root_id=d["root_id"], N=d["N"])


# ---------------------------------------------------------------------------
# NetworkConfig
# ---------------------------------------------------------------------------


def network_to_dict(network: NetworkConfig) -> dict[str, Any]:
    """Serialize *network* to a plain, JSON-safe dict."""
    return {
        "e_d": network.e_d,
        "gamma": network.gamma,
        "c": network.c,
        "hops": [
            {
                "length": h.length,
                "branching": list(h.branching),
                "arm_count": h.arm_count,
                "p_x_inner": h.p_x_inner,
                "p_z_inner": h.p_z_inner,
                # Always store the resolved eta (never None at this point)
                # so that the deserialized HopConfig reproduces the exact
                # same eta without recomputing from length/attenuation.
                "eta": h.eta,
                "attenuation_db_per_km": h.attenuation_db_per_km,
            }
            for h in network.hops
        ],
    }


def dict_to_network(d: dict[str, Any]) -> NetworkConfig:
    """Reconstruct a :class:`NetworkConfig` from a plain dict."""
    hops = tuple(
        HopConfig(
            length=h["length"],
            branching=tuple(h["branching"]),
            arm_count=h["arm_count"],
            p_x_inner=h["p_x_inner"],
            p_z_inner=h["p_z_inner"],
            # Pass eta explicitly so __post_init__ skips recomputation;
            # attenuation_db_per_km is stored for reference / completeness.
            eta=h["eta"],
            attenuation_db_per_km=h["attenuation_db_per_km"],
        )
        for h in d["hops"]
    )
    return NetworkConfig(hops=hops, e_d=d["e_d"], gamma=d["gamma"], c=d["c"])


# ---------------------------------------------------------------------------
# Full schedule artifact  (dag + network + metadata)
# ---------------------------------------------------------------------------


def save_schedule(
    dag: ScheduleDAG,
    path: str | Path,
    *,
    network: NetworkConfig,
    label: str = "",
    score: float | None = None,
    fidelity: float | None = None,
    rate: float | None = None,
    resource_cost: int | None = None,
    latency_s: float | None = None,
    success_prob: float | None = None,
) -> Path:
    """Write a complete schedule artifact to a JSON file.

    The artifact is fully self-contained: it stores the DAG (node-level
    structure), the network config (so no external parameters are needed
    to re-evaluate), and the scalar evaluation metrics.  The per-node
    ``State`` cache is NOT stored (it is large and fully recomputable
    via ``Evaluator(network).evaluate(dag)``).

    Parameters
    ----------
    dag : ScheduleDAG
        The schedule DAG to persist.
    path : str or Path
        Destination file path.  Parent directories are created if needed.
    network : NetworkConfig
        The network this schedule was designed for.
    label : str
        Human-readable schedule identifier (e.g. from ``SearchResult.label``).
    score : float, optional
        Objective score as returned by ``ObjectiveConfig.score``.
    fidelity, rate, resource_cost, latency_s, success_prob : optional
        Scalar fields from ``EvaluationResult``.  If omitted, stored as
        ``null`` in the file.

    Returns
    -------
    Path
        Absolute path of the written file.
    """
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "_schema": _SCHEMA,
        "_version": SERDE_VERSION,
        "label": label,
        "score": score,
        "eval": {
            "fidelity": fidelity,
            "rate": rate,
            "resource_cost": resource_cost,
            "latency_s": latency_s,
            "success_prob": success_prob,
        },
        "network": network_to_dict(network),
        "dag": dag_to_dict(dag),
    }

    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out


def load_schedule(
    path: str | Path,
) -> tuple[ScheduleDAG, NetworkConfig, dict[str, Any]]:
    """Load a schedule artifact from a JSON file.

    Parameters
    ----------
    path : str or Path
        Path of a file previously written by :func:`save_schedule`.

    Returns
    -------
    dag : ScheduleDAG
        The reconstructed schedule DAG.  Call ``dag.validate()`` to
        verify structural integrity after loading if desired.
    network : NetworkConfig
        The network this schedule was designed for.
    meta : dict
        Metadata dict with keys:

        ``label``: the saved label string (empty string if not set).
        ``score``: the saved objective score (``None`` if not set).
        ``eval``: a dict with keys ``fidelity``, ``rate``,
                     ``resource_cost``, ``latency_s``, ``success_prob``
                     (each may be ``None`` if not stored).

        Note: ``meta["eval"]`` does NOT include per-node state caches.
        To get the full :class:`~hrgs_scheduler.schedule.evaluator.EvaluationResult`
        (including ``node_states``), call
        ``Evaluator(network).evaluate(dag)`` on the returned objects.

    Raises
    ------
    ValueError
        If the file's ``_schema`` or ``_version`` fields indicate an
        incompatible format.
    """
    raw = Path(path).read_text(encoding="utf-8")
    d = json.loads(raw)

    schema = d.get("_schema", "")
    version = d.get("_version", 0)
    if schema != _SCHEMA:
        raise ValueError(
            f"Unrecognised schema {schema!r}; expected {_SCHEMA!r}. "
            "Is this a valid hrgs_schedule file?"
        )
    if version != SERDE_VERSION:
        raise ValueError(
            f"Unsupported file version {version}; this build supports "
            f"version {SERDE_VERSION}. Re-export the schedule with the "
            "current version of the library."
        )

    dag = dict_to_dag(d["dag"])
    network = dict_to_network(d["network"])
    meta: dict[str, Any] = {
        "label": d.get("label", ""),
        "score": d.get("score"),
        "eval": d.get("eval", {}),
    }
    return dag, network, meta
