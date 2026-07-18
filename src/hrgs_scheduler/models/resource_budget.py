"""
hrgs_scheduler.models.resource_budget
=======================================
Resource budget tuple B.

Formal definition [Validated Formal Model Def, §5]:

    B = (n_pur, E_max, M_max)

A schedule Σ is *feasible* with respect to B iff:
    |Gen leaves in T| ≤ E_max
and
    max concurrent open branches ≤ M_max.

n_pur corresponds directly to the extra-emitter count needed to generate
multiple half-RGSs per side for purification [Integrating, §IV.A].
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceBudget:
    """Resource-budget tuple B = (n_pur, E_max, M_max).

    Parameters
    ----------
    n_pur : int
        RGSS-level purification-round copy multiplicity: how many half-RGS
        copies are generated per side for RGSS-level purification.
        n_pur = 1 means no RGSS-level purification (one copy per side).
    e_max : int
        Maximum emitter count per trial.  Bounds the number of Gen leaves
        in the schedule DAG.
    m_max : int
        Maximum number of simultaneously held (open) entanglement states.
        Bounds the memory footprint of the schedule.
    """

    n_pur: int
    e_max: int
    m_max: int

    def __post_init__(self) -> None:
        if self.n_pur < 1:
            raise ValueError(f"n_pur must be ≥ 1, got {self.n_pur}")
        if self.e_max < 1:
            raise ValueError(f"e_max must be ≥ 1, got {self.e_max}")
        if self.m_max < 1:
            raise ValueError(f"m_max must be ≥ 1, got {self.m_max}")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def resource_cost(self) -> int:
        """Minimum number of Gen nodes implied by n_pur alone (2 × n_pur per hop)."""
        return self.n_pur

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def minimal(cls) -> ResourceBudget:
        """Minimal budget: no purification, 2 emitters, 1 held state."""
        return cls(n_pur=1, e_max=2, m_max=1)

    @classmethod
    def from_integrating_paper(cls) -> ResourceBudget:
        """Budget matching the worked example in [Validated Formal Model Def, §9].

        B = (n_pur=2, E_max=12, M_max=6).
        """
        return cls(n_pur=2, e_max=12, m_max=6)
