"""
hrgs_scheduler.models.stage
============================
Processing-stage / span index κ for entanglement resources.

Every State in the DAG carries a κ label that records *where* in the
network the resource currently lives [Validated Formal Model Def, §3.1]:

    κ ∈ { RGSS } ∪ { Span(a, b) : 0 ≤ a < b ≤ N }

RGSS: pre-transmission, RGSS-local (single-station) resource.
Span: an established edge covering hops a through b (inclusive).
        Span(i-1, i) is a single-hop link at hop i.
        Span(0, N)   is the full end-to-end pair.

Legality constraints
--------------------
* Gen nodes produce resources at κ = RGSS.
* Purify nodes require both inputs to share the same κ.
* Join/EntSwap of Span(a, b) and Span(b, d) produces Span(a, d)
  here d highlights the ability to represent non-adjacency of the two spans.
* PauliCorrect requires κ = Span(0, N).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class RGSSStage:
    """Pre-transmission RGSS-local (single-station) stage.

    Used for resources that have been generated locally but whose outer
    photon has not yet been sent to the ABSA.
    """

    def __repr__(self) -> str:
        return "RGSS"


@dataclass(frozen=True)
class Span:
    """Contiguous hop-interval stage, covering hops *a* through *b*.

    Parameters
    ----------
    a : int
        Left endpoint (station index).  0 ≤ a < b.
    b : int
        Right endpoint (station index). a < b ≤ N.
    """

    a: int
    b: int

    def __post_init__(self) -> None:
        if not (0 <= self.a < self.b):
            raise ValueError(f"Span requires 0 ≤ a < b, got Span({self.a}, {self.b})")

    @property
    def width(self) -> int:
        """Number of hops covered by this span."""
        return self.b - self.a

    def is_adjacent(self, other: Span) -> bool:
        """True when this span and *other* share exactly one endpoint."""
        return self.b == other.a or other.b == self.a

    def join(self, other: Span) -> Span:
        """Return the merged span after Join/EntSwap of two adjacent spans.

        Implements the span-consistency rule: Span(a,b) ⊕ Span(b,d) → Span(a,d).

        Raises
        ------
        ValueError
            If the two spans are not adjacent (do not share a boundary).
        """
        if self.b == other.a:
            return Span(self.a, other.b)
        if other.b == self.a:
            return Span(other.a, self.b)
        raise ValueError(f"Cannot join non-adjacent spans {self!r} and {other!r}")

    def __repr__(self) -> str:
        return f"Span({self.a}, {self.b})"


# Canonical singleton for the RGSS stage, used as a sentinel value
# throughout the codebase.
RGSS: RGSSStage = RGSSStage()

# Type alias for all valid stage values.
Stage = Union[RGSSStage, Span]
