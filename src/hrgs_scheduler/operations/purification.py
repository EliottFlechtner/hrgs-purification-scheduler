"""
hrgs_scheduler.operations.purification
========================================
Stabilizer-based 2-to-1 purification operators.

Each circuit maps two input States (sharing the same κ) to one output
State with an updated error vector, conditioned on measurement success.

Formal definitions [Integrating, eqs. (8)−(13)]
------------------------------------------------
Success probabilities:

    P_ZX(e₁, e₂) = (w₁+x₁)(w₂+x₂) + (z₁+y₁)(z₂+y₂)
    P_XZ(e₁, e₂) = (w₁+z₁)(w₂+z₂) + (x₁+y₁)(x₂+y₂)
    P_YY(e₁, e₂) = (w₁+y₁)(w₂+y₂) + (x₁+z₁)(x₂+z₂)

Post-purification error vectors (conditional on success):

    Pur_ZX = (1/P_ZX)  [w₁w₂+x₁x₂,  z₁z₂+y₁y₂,  z₁y₂+y₁z₂,  x₁w₂+w₁x₂]
    Pur_XZ = (1/P_XZ)  [w₁w₂+z₁z₂,  z₁w₂+w₁z₂,  x₁y₂+y₁x₂,  x₁x₂+y₁y₂]
    Pur_YY = (1/P_YY)  [w₁w₂+y₁y₂,  x₁z₂+z₁x₂,  y₁w₂+w₁y₂,  x₁x₂+z₁z₂]

Physical meaning of each circuit [Integrating, §V-B]
-----------------------------------------------------
ZX: detects Z errors on qubit B of the *second* copy.
XZ: detects Z errors on qubit A of the *second* copy.
YY: detects an odd number of Z errors across all four qubits (best at
       catching the ZI/IZ bias produced by inner-qubit measurements).

Legality
--------
Both input States must share the same κ (stage/span).

Result tuple
------------
Each operation returns (output_state, success_prob) so the caller can
track both the post-purification quality *and* the probability that the
measurement succeeded (used by the rate cost-function R).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import NamedTuple

from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.state import State

# ---------------------------------------------------------------------------
# Public API type
# ---------------------------------------------------------------------------


class PurificationResult(NamedTuple):
    """Return type of every purification call.

    Attributes
    ----------
    output_state : State
        Post-purification state, valid only on success.
    success_prob : float
        Probability that the stabilizer measurement returned the +1 (success)
        outcome, i.e.  P_ZX, P_XZ, or P_YY.
    """

    output_state: State
    success_prob: float


class PurificationCircuit(Enum):
    """Available purification circuit types."""

    YY = auto()
    ZX = auto()
    XZ = auto()


# ---------------------------------------------------------------------------
# Pure mathematical functions (operate on ErrorVector only)
# ---------------------------------------------------------------------------


def _success_prob_zx(e1: ErrorVector, e2: ErrorVector) -> float:
    """P_ZX(e₁, e₂) = (w₁+x₁)(w₂+x₂) + (z₁+y₁)(z₂+y₂)."""
    return (e1.w + e1.x) * (e2.w + e2.x) + (e1.z + e1.y) * (e2.z + e2.y)


def _success_prob_xz(e1: ErrorVector, e2: ErrorVector) -> float:
    """P_XZ(e₁, e₂) = (w₁+z₁)(w₂+z₂) + (x₁+y₁)(x₂+y₂)."""
    return (e1.w + e1.z) * (e2.w + e2.z) + (e1.x + e1.y) * (e2.x + e2.y)


def _success_prob_yy(e1: ErrorVector, e2: ErrorVector) -> float:
    """P_YY(e₁, e₂) = (w₁+y₁)(w₂+y₂) + (x₁+z₁)(x₂+z₂)."""
    return (e1.w + e1.y) * (e2.w + e2.y) + (e1.x + e1.z) * (e2.x + e2.z)


def _output_vector_zx(e1: ErrorVector, e2: ErrorVector, p: float) -> ErrorVector:
    """Pur_ZX output vector, normalised by 1/P_ZX."""
    return ErrorVector(
        w=(e1.w * e2.w + e1.x * e2.x) / p,
        x=(e1.z * e2.z + e1.y * e2.y) / p,
        y=(e1.z * e2.y + e1.y * e2.z) / p,
        z=(e1.x * e2.w + e1.w * e2.x) / p,
    )


def _output_vector_xz(e1: ErrorVector, e2: ErrorVector, p: float) -> ErrorVector:
    """Pur_XZ output vector, normalised by 1/P_XZ."""
    return ErrorVector(
        w=(e1.w * e2.w + e1.z * e2.z) / p,
        x=(e1.z * e2.w + e1.w * e2.z) / p,
        y=(e1.x * e2.y + e1.y * e2.x) / p,
        z=(e1.x * e2.x + e1.y * e2.y) / p,
    )


def _output_vector_yy(e1: ErrorVector, e2: ErrorVector, p: float) -> ErrorVector:
    """Pur_YY output vector, normalised by 1/P_YY."""
    return ErrorVector(
        w=(e1.w * e2.w + e1.y * e2.y) / p,
        x=(e1.x * e2.z + e1.z * e2.x) / p,
        y=(e1.y * e2.w + e1.w * e2.y) / p,
        z=(e1.x * e2.x + e1.z * e2.z) / p,
    )


# ---------------------------------------------------------------------------
# Public operation functions
# ---------------------------------------------------------------------------


def purify(
    circuit: PurificationCircuit,
    state1: State,
    state2: State,
) -> PurificationResult:
    """Apply a 2-to-1 purification circuit to two States.

    Both inputs must share the same κ (stage/span).  The output State
    inherits its κ from either input (they are identical), the earliest
    generation_time, the latest current_time, and a purification_rounds
    count incremented by 1.

    The side-effect parity of the output is the XOR of the two inputs
    (parities combine at every merge point [Validated Formal Model Def, §2.3]).

    Parameters
    ----------
    circuit : PurificationCircuit
        Which stabilizer measurement circuit to apply: YY, ZX, or XZ.
    state1 : State
        First input state (the one kept on success).
    state2 : State
        Second input state (consumed; provides the ancilla copy).

    Returns
    -------
    PurificationResult
        (output_state, success_prob): the post-purification state and
        the probability that the measurement succeeded.

    Raises
    ------
    ValueError
        If the two states have different stage labels κ.
    """
    if state1.stage != state2.stage:
        raise ValueError(
            f"Purification requires identical κ on both inputs, "
            f"got {state1.stage!r} and {state2.stage!r}"
        )

    e1, e2 = state1.error_vector, state2.error_vector

    if circuit is PurificationCircuit.ZX:
        p = _success_prob_zx(e1, e2)
        ev_out = _output_vector_zx(e1, e2, p)
    elif circuit is PurificationCircuit.XZ:
        p = _success_prob_xz(e1, e2)
        ev_out = _output_vector_xz(e1, e2, p)
    else:  # YY
        p = _success_prob_yy(e1, e2)
        ev_out = _output_vector_yy(e1, e2, p)

    output_state = State(
        error_vector=ev_out,
        side_effect_parity=(state1.side_effect_parity ^ state2.side_effect_parity) & 1,
        current_time=max(state1.current_time, state2.current_time),
        generation_time=min(state1.generation_time, state2.generation_time),
        stage=state1.stage,
        purification_rounds=max(state1.purification_rounds, state2.purification_rounds)
        + 1,
        herald_status=state1.herald_status,
    )
    return PurificationResult(output_state=output_state, success_prob=p)


def success_prob(
    circuit: PurificationCircuit,
    e1: ErrorVector,
    e2: ErrorVector,
) -> float:
    """Return the success probability for a purification circuit without building a State.

    Useful for cost-function estimation and search heuristics.

    Parameters
    ----------
    circuit : PurificationCircuit
        Which circuit: YY, ZX, or XZ.
    e1, e2 : ErrorVector
        Error vectors of the two input copies.
    """
    if circuit is PurificationCircuit.ZX:
        return _success_prob_zx(e1, e2)
    if circuit is PurificationCircuit.XZ:
        return _success_prob_xz(e1, e2)
    return _success_prob_yy(e1, e2)
