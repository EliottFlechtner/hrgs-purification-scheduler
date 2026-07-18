"""
hrgs_scheduler.models.error_vector
===================================
Bell-diagonal error-probability vector  e = [w, x, y, z]^T.

Physical meaning
----------------
A two-qubit entangled resource is described by the four probabilities
of the Pauli-Z error syndromes on the Bell pair [Integrating, eq. (7)]:

    e = w|φ_II⟩⟨φ_II| + x|φ_ZI⟩⟨φ_ZI| + y|φ_ZZ⟩⟨φ_ZZ| + z|φ_IZ⟩⟨φ_IZ|

where

    w  = P(II) = no error  (fidelity component, i.e. F = w)
    x  = P(ZI) = Z error on qubit A only
    y  = P(ZZ) = Z error on both qubits
    z  = P(IZ) = Z error on qubit B only

and  w + x + y + z = 1.

Notes
-----
* Only Z-type errors are tracked, consistent with the HRGS architecture
  where inner-qubit measurements propagate solely ZI and IZ errors to the
  anchor pair [Bridging, §VII-D].
* BSM composition uses the bilinear rule from [Bridging, eq. (5)] /
  [Integrating, eq. (14)].
* Decoherence applies an exponential relaxation toward the maximally-mixed
  state [Validated Formal Model Def, §2.6].
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorVector:
    """Immutable Bell-diagonal error-probability vector e = (w, x, y, z).

    Parameters
    ----------
    w : float
        P(II) = fidelity component (probability of no error).
    x : float
        P(ZI) = Z error on qubit A.
    y : float
        P(ZZ) = Z error on both qubits.
    z : float
        P(IZ) = Z error on qubit B.
    """

    w: float
    x: float
    y: float
    z: float

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def ideal(cls) -> ErrorVector:
        """Return the ideal (perfect Bell state) error vector e = [1,0,0,0]."""
        return cls(1.0, 0.0, 0.0, 0.0)

    @classmethod
    def maximally_mixed(cls) -> ErrorVector:
        """Return the maximally-mixed state error vector e = 0.25[1,1,1,1]."""
        return cls(0.25, 0.25, 0.25, 0.25)

    @classmethod
    def from_independent_z_flips(cls, p_a: float, p_b: float) -> ErrorVector:
        """Build an error vector from independent Z-flip probabilities on each qubit.

        This is the standard model when qubit-A and qubit-B errors are
        statistically independent:

            w = (1 - p_a)(1 - p_b)
            x = p_a (1 - p_b)
            y = p_a  p_b
            z = (1 - p_a) p_b

        Parameters
        ----------
        p_a : float
            Marginal probability of a Z flip on qubit A (ZI or ZZ events).
        p_b : float
            Marginal probability of a Z flip on qubit B (IZ or ZZ events).
        """
        return cls(
            w=(1.0 - p_a) * (1.0 - p_b),
            x=p_a * (1.0 - p_b),
            y=p_a * p_b,
            z=(1.0 - p_a) * p_b,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def fidelity(self) -> float:
        """End-to-end Bell-state fidelity F = w (the II component)."""
        return self.w

    @property
    def p_za(self) -> float:
        """Marginal Z-flip probability on qubit A: P(ZI) + P(ZZ) = x + y."""
        return self.x + self.y

    @property
    def p_zb(self) -> float:
        """Marginal Z-flip probability on qubit B: P(IZ) + P(ZZ) = z + y."""
        return self.z + self.y

    @property
    def is_normalised(self) -> bool:
        """True when the four probabilities sum to 1 within floating-point tolerance."""
        return math.isclose(self.w + self.x + self.y + self.z, 1.0, abs_tol=1e-9)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def bsm_compose(self, other: ErrorVector) -> ErrorVector:
        """Compose two error vectors via the bilinear BSM composition rule.

        Implements [Bridging, eq. (5)] / [Integrating, eq. (14)]:

            BSM(e1, e2) = [
                w1*w2 + x1*x2 + y1*y2 + z1*z2,
                w1*x2 + x1*w2 + z1*y2 + y1*z2,
                w1*y2 + y1*w2 + x1*z2 + z1*x2,
                w1*z2 + z1*w2 + x1*y2 + y1*x2
            ]

        This rule applies to every Join/EntSwap and ABSA-BSM in the DAG.

        Parameters
        ----------
        other : ErrorVector
            The second operand error vector e2.

        Returns
        -------
        ErrorVector
            The composed error vector for the output state.
        """
        w1, x1, y1, z1 = self.w, self.x, self.y, self.z
        w2, x2, y2, z2 = other.w, other.x, other.y, other.z
        return ErrorVector(
            w=w1 * w2 + x1 * x2 + y1 * y2 + z1 * z2,
            x=w1 * x2 + x1 * w2 + z1 * y2 + y1 * z2,
            y=w1 * y2 + y1 * w2 + x1 * z2 + z1 * x2,
            z=w1 * z2 + z1 * w2 + x1 * y2 + y1 * x2,
        )

    def decohere(self, gamma: float, delta_t: float) -> ErrorVector:
        """Apply exponential dephasing toward the maximally-mixed state.

        Implements [Validated Formal Model Def, §2.6]:

            e(t) = ¼1 + exp(-γ*Δt)  (e(t₀) - ¼1)

        The relaxation is applied **per node** in the DAG, not as a
        single global correction, because the composition is nonlinear.

        Parameters
        ----------
        gamma : float
            Memory dephasing rate constant γ.
        delta_t : float
            Idle duration Δt = t_consumed - t_gen for this node.

        Returns
        -------
        ErrorVector
            The decohered error vector.
        """
        decay = math.exp(-gamma * delta_t)
        mixed = 0.25
        return ErrorVector(
            w=mixed + decay * (self.w - mixed),
            x=mixed + decay * (self.x - mixed),
            y=mixed + decay * (self.y - mixed),
            z=mixed + decay * (self.z - mixed),
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ErrorVector(w={self.w:.6f}, x={self.x:.6f},"
            f" y={self.y:.6f}, z={self.z:.6f})"
        )
