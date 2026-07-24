"""
hrgs_scheduler.models.state
============================
The entanglement-resource state object S.

Each node in the schedule DAG consumes and/or produces States.
A State is a snapshot of one entanglement resource (Bell pair or
RGSS-local anchor-photon pair) at a specific moment in time.

Formal definition [Validated Formal Model Def, §3.1]:

    S = (e, s, t, t_gen, κ, r, h)

Fields
------
error_vector       : e, Bell-diagonal error-probability vector.
    side_effect_parity : s, accumulated Clifford side-effect parity (𝔽₂).
    current_time       : t, instantaneous simulation timestamp.
    generation_time    : t_gen, timestamp at which this resource was created.
    stage              : κ, processing stage / span index.
    purification_rounds: r, number of purification rounds already applied.
    herald_status      : h, whether classical heralding has been resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.stage import Stage, RGSS


class HeraldStatus(Enum):
    """Heralding-resolution status of an entanglement resource.

    PENDING:  classical heralding outcome not yet received (optimistic mode).
    RESOLVED: classical heralding outcome confirmed; PauliCorrect is legal.
    """

    PENDING = auto()
    RESOLVED = auto()


@dataclass
class State:
    """Entanglement-resource state tuple S = (e, s, t, t_gen, κ, r, h).

    Parameters
    ----------
    error_vector : ErrorVector
        Current Bell-diagonal error state of this resource.
    side_effect_parity : int
        Accumulated Pauli-Z side-effect parity (0 or 1, in 𝔽₂) that must
        be corrected at PauliCorrect time.
    current_time : float
        Simulation clock value at the moment this state is observed/produced.
    generation_time : float
        Clock value when the resource was first generated (Gen node).
    stage : Stage
        Processing stage κ: either RGSS or a Span(a, b).
    purification_rounds : int
        Number of purification operations already applied to this resource.
        Informational; used by search heuristics.
    herald_status : HeraldStatus
        Whether the classical heralding outcome for this resource has been
        communicated and confirmed.
    """

    error_vector: ErrorVector
    side_effect_parity: int
    current_time: float
    generation_time: float
    stage: Stage
    purification_rounds: int = field(default=0)
    herald_status: HeraldStatus = field(default=HeraldStatus.PENDING)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def idle_duration(self) -> float:
        """Δt_idle = t - t_gen: time this resource has been waiting."""
        return self.current_time - self.generation_time

    @property
    def fidelity(self) -> float:
        """Shortcut: F = w component of the error vector."""
        return self.error_vector.fidelity

    @property
    def is_herald_resolved(self) -> bool:
        """True when heralding has been confirmed (PauliCorrect is legal)."""
        return self.herald_status is HeraldStatus.RESOLVED

    # ------------------------------------------------------------------
    # State transitions (return new, mutated copies)
    # ------------------------------------------------------------------

    def with_error_vector(self, ev: ErrorVector) -> State:
        """Return a copy of this State with an updated error vector."""
        return State(
            error_vector=ev,
            side_effect_parity=self.side_effect_parity,
            current_time=self.current_time,
            generation_time=self.generation_time,
            stage=self.stage,
            purification_rounds=self.purification_rounds,
            herald_status=self.herald_status,
        )

    def with_stage(self, stage: Stage) -> State:
        """Return a copy of this State with an updated stage κ."""
        return State(
            error_vector=self.error_vector,
            side_effect_parity=self.side_effect_parity,
            current_time=self.current_time,
            generation_time=self.generation_time,
            stage=stage,
            purification_rounds=self.purification_rounds,
            herald_status=self.herald_status,
        )

    def with_time(self, t: float) -> State:
        """Return a copy of this State with an updated current_time."""
        return State(
            error_vector=self.error_vector,
            side_effect_parity=self.side_effect_parity,
            current_time=t,
            generation_time=self.generation_time,
            stage=self.stage,
            purification_rounds=self.purification_rounds,
            herald_status=self.herald_status,
        )

    def with_herald_resolved(self) -> State:
        """Return a copy of this State with herald_status = RESOLVED."""
        return State(
            error_vector=self.error_vector,
            side_effect_parity=self.side_effect_parity,
            current_time=self.current_time,
            generation_time=self.generation_time,
            stage=self.stage,
            purification_rounds=self.purification_rounds,
            herald_status=HeraldStatus.RESOLVED,
        )

    def with_parity_xor(self, other_parity: int) -> State:
        """Return a copy with side_effect_parity XOR'd with *other_parity*.

        Side effects live in 𝔽₂; composition is XOR at every merge point
        [Validated Formal Model Def, §2.3].
        """
        return State(
            error_vector=self.error_vector,
            side_effect_parity=(self.side_effect_parity ^ other_parity) & 1,
            current_time=self.current_time,
            generation_time=self.generation_time,
            stage=self.stage,
            purification_rounds=self.purification_rounds,
            herald_status=self.herald_status,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def fresh_rgss(cls, error_vector: ErrorVector, t: float = 0.0) -> State:
        """Create a freshly-generated RGSS-local resource at time *t*."""
        return cls(
            error_vector=error_vector,
            side_effect_parity=0,
            current_time=t,
            generation_time=t,
            stage=RGSS,
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"State(κ={self.stage!r}, F={self.fidelity:.4f},"
            f" s={self.side_effect_parity}, t={self.current_time:.3f},"
            f" h={self.herald_status.name}, r={self.purification_rounds})"
        )
