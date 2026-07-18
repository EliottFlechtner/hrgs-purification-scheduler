"""
hrgs_scheduler.models.network_config
======================================
Physical network configuration  N.

Formal definition [Validated Formal Model Def, §2.1]:

    𝓝 = (N, {l_i}, {𝓫⁽ⁱ⁾}, {kᵢ}, {(p^X_in,i, p^Z_in,i)}, {ηᵢ}, e_d, γ, c)

Each hop i (1-indexed in the paper, 0-indexed here) carries its own
HopConfig.  The NetworkConfig wraps the full collection of hops plus the
global physical constants.

Inner-qubit error model [Bridging, eq. (10)]
--------------------------------------------
For a single hop with branching vector 𝓫 = (b₀, …, b_m):
    m  = len(𝓫)  — tree depth / arm multiplicity
    p_ZI = p_IZ = ½ [1 − (1 − 2 p^X_in)(1 − 2 p^Z_in)^(m−1)]

End-to-end accumulated inner-qubit errors [Bridging, eqs. (6)−(9)]:
    p_ZI^e2e = ½ [1 − (1 − 2 p_ZI)^N]
    p_IZ^e2e = ½ [1 − (1 − 2 p_IZ)^N]

BSM success cap [Bridging, §VI.A]:
    Per arm, BSM success is capped at 50% independent of η or e_d.
    The arm count kᵢ provides redundancy against this ceiling.

Photon survival probability:
    ηᵢ = 10^(−α l_i / 10)  for attenuation α [dB/km].
    Can be provided directly or computed from l_i and α.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class HopConfig:
    """Physical parameters for a single hop (link between two adjacent stations).

    Parameters
    ----------
    length : float
        Hop length l_i in kilometres.
    branching : tuple[int, ...]
        Tree-encoding branching parameter sequence 𝓫⁽ⁱ⁾ = (b₀, …, b_{m−1}).
        len(branching) is the tree depth m.
    arm_count : int
        Biclique arm multiplicity kᵢ (number of arms per half-RGS at this hop).
    p_x_inner : float
        Logical X-measurement error probability on inner qubits, p^X_in,i.
    p_z_inner : float
        Logical Z-measurement error probability on inner qubits, p^Z_in,i.
    eta : float
        Photon survival probability ηᵢ ∈ (0, 1].
        Pass None to compute from *length* and *attenuation_db_per_km*.
    attenuation_db_per_km : float
        Fiber attenuation in dB/km.  Only used when *eta* is None.
        Default: 0.2 dB/km (standard SMF).
    """

    length: float
    branching: tuple[int, ...]
    arm_count: int
    p_x_inner: float
    p_z_inner: float
    eta: float | None = field(default=None)
    attenuation_db_per_km: float = field(default=0.2)

    def __post_init__(self) -> None:
        if self.eta is None:
            # Compute η from Beer–Lambert attenuation:  η = 10^(−α*l / 10)
            object.__setattr__(
                self,
                "eta",
                10.0 ** (-self.attenuation_db_per_km * self.length / 10.0),
            )
        if not (0.0 < self.eta <= 1.0):  # type: ignore[operator]
            raise ValueError(f"eta must be in (0, 1], got {self.eta!r}")
        if len(self.branching) == 0:
            raise ValueError("branching vector must be non-empty")

    # ------------------------------------------------------------------
    # Derived quantities
    # ------------------------------------------------------------------

    @property
    def tree_depth(self) -> int:
        """Tree depth m = len(branching)."""
        return len(self.branching)

    @property
    def inner_error_per_hop(self) -> float:
        """Per-hop inner-qubit error probability p_ZI = p_IZ [Bridging, eq. (10)].

        p = 0.5 * [1 − (1 − 2 p^X_in)(1 − 2 p^Z_in)^(m−1)]
        """
        m = self.tree_depth
        return 0.5 * (
            1.0 - (1.0 - 2.0 * self.p_x_inner) * (1.0 - 2.0 * self.p_z_inner) ** (m - 1)
        )

    @property
    def bsm_success_prob_per_arm(self) -> float:
        """Per-arm BSM success probability, capped at 50% [Bridging, §VI.A].

        p_BSM = min(η / 2, 0.5)
        """
        return min(self.eta / 2.0, 0.5)  # type: ignore[operator]


@dataclass(frozen=True)
class NetworkConfig:
    """Full network configuration tuple N.

    Parameters
    ----------
    hops : sequence of HopConfig
        One entry per hop, ordered from Alice (hop 0) to Bob (hop N−1).
        N = len(hops).
    e_d : float
        Outer-qubit depolarizing-channel parameter (per outer photon).
    gamma : float
        Quantum-memory decoherence rate constant γ (per unit time).
    c : float
        Signal propagation velocity (km per time unit).
    """

    hops: tuple[HopConfig, ...]
    e_d: float
    gamma: float
    c: float

    def __post_init__(self) -> None:
        if len(self.hops) == 0:
            raise ValueError("Network must have at least one hop.")
        # Coerce list input to tuple for hashability.
        object.__setattr__(self, "hops", tuple(self.hops))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def N(self) -> int:
        """Number of hops N between Alice and Bob."""
        return len(self.hops)

    def hop(self, i: int) -> HopConfig:
        """Return the HopConfig for hop *i* (0-indexed).

        Parameters
        ----------
        i : int
            Hop index, 0 ≤ i < N.
        """
        return self.hops[i]

    def inner_error_e2e(self) -> tuple[float, float]:
        """End-to-end accumulated inner-qubit error probabilities.

        Implements [Bridging, eqs. (6)−(9)] for a uniform network.
        In the heterogeneous case, chain the accumulation across hops.

        Returns
        -------
        (p_ZI_e2e, p_IZ_e2e)
            Both equal ½[1 − (1 − 2 p_per_hop)^N] for uniform networks.
        """
        # For a heterogeneous network, accumulate hop-by-hop.
        # p_ZI and p_IZ are symmetric by the inner-qubit model.
        p_zi = 0.0
        for hop in self.hops:
            p = hop.inner_error_per_hop
            p_zi = p_zi + p - 2.0 * p_zi * p  # XOR combination
        return p_zi, p_zi

    def total_length(self) -> float:
        """Total end-to-end fibre length L_total = Σ l_i in km."""
        return sum(h.length for h in self.hops)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def uniform(
        cls,
        N: int,
        length: float,
        branching: Sequence[int],
        arm_count: int,
        p_x_inner: float,
        p_z_inner: float,
        eta: float | None = None,
        attenuation_db_per_km: float = 0.2,
        e_d: float = 0.0,
        gamma: float = 0.0,
        c: float = 2e5,
    ) -> NetworkConfig:
        """Build a uniform network where every hop shares the same parameters.

        Parameters
        ----------
        N : int
            Number of hops.
        length : float
            Hop length in km (same for every hop).
        branching : Sequence[int]
            Tree-encoding branching vector (shared across hops).
        arm_count : int
            Biclique arm count per hop.
        p_x_inner, p_z_inner : float
            Inner-qubit error rates (shared across hops).
        eta : float or None
            Photon survival probability. Computed from *attenuation_db_per_km*
            and *length* when None.
        attenuation_db_per_km : float
            Fibre attenuation.  Used only when *eta* is None.
        e_d : float
            Outer-qubit depolarizing rate.
        gamma : float
            Memory dephasing rate.
        c : float
            Propagation speed (km / time unit).  Default: 2×10⁵ km/s ≈ 2/3 c.
        """
        hop = HopConfig(
            length=length,
            branching=tuple(branching),
            arm_count=arm_count,
            p_x_inner=p_x_inner,
            p_z_inner=p_z_inner,
            eta=eta,
            attenuation_db_per_km=attenuation_db_per_km,
        )
        return cls(hops=tuple(hop for _ in range(N)), e_d=e_d, gamma=gamma, c=c)

    # ------------------------------------------------------------------
    # Paper reference config [Integrating, §V.A]
    # ------------------------------------------------------------------

    @classmethod
    def integrating_paper_config(cls, e_d: float = 0.0) -> NetworkConfig:
        """Return the exact configuration used in [Integrating, §V.A] for reproducibility.

        N = (N=10, l_i=2 km, 𝓫=(16,14,1), kᵢ=18, e_d, γ=0, c=2×10⁵ km/s)
        with p^X_in = p^Z_in ≈ 0 (ideal inner qubits unless overridden).

        Parameters
        ----------
        e_d : float
            Outer-qubit depolarizing rate (swept in Fig. 5 validation).
        """
        return cls.uniform(
            N=10,
            length=2.0,
            branching=(16, 14, 1),
            arm_count=18,
            p_x_inner=0.0,
            p_z_inner=0.0,
            e_d=e_d,
            gamma=0.0,
            c=2e5,
        )
