"""
hrgs_scheduler.timing
======================
Canonical timing-formula model from [Integrating, §IV-B].

NOTE: as of the Fig. 6 validation fix, the *authoritative* source of
rate/latency numbers is no longer this standalone closed-form module but
``Evaluator.evaluate(dag).rate`` / ``.latency``, computed directly from
the schedule DAG's own Herald/Purify structure (see
``validation/fig6_rate_ratio.py`` and the ``herald()`` docstring in
``operations/backbone.py``). This module remains useful as an independent
analytical cross-check and for quick what-if calculations without
building a full DAG, but should agree with the DAG-derived values for the
canonical raw/baseline/flexible schedules.

This module implements the three closed-form timing expressions that
appear in [Validated Formal Model Def, §2.6] timing table.  They serve as:

  1. A direct cross-check target: any schedule Σ that reduces to one of
     the three canonical forms must reproduce these formulas when evaluated
     by the inner-loop DAG evaluator (with correct gen_time / propagation_time
     fields wired in).

  2. A lightweight way to compute rate without full DAG evaluation, useful
     for the rate-ratio Fig. 6 validation.

Canonical timing table [Integrating, §IV-B]
-------------------------------------------

  Raw (no purification):
    τ_RGS^(raw)    = τ_half + τ_join
    t_mem^(raw)    ≈ τ_half + L/c

  Baseline (heralded end-node purification via entanglement pumping):
    τ_RGS^(base)   = τ_half + τ_join   (same generation rate as raw)
    t_mem^(base)   ≈ n_pur·τ_half + τ_pur + n_rounds·(2·L/c)

  Optimistic (blind / optimistic RGSS-level purification, single herald):
    τ_RGS^(opt)    = n_pur·τ_half + max(τ_pur + τ_join, n_pur·τ_join)
    t_mem^(opt)    ≈ n_pur·τ_half + τ_pur + L/c

Key insight [Integrating, §III-B, §VI]: baseline uses *heralded* two-way
purification via entanglement pumping [Gidney 2023], which is inherently
sequential — each of the n_rounds = n_pur − 1 pumping rounds must wait for
a full round-trip (2L/c) classical confirmation of the previous round's
success before proceeding ("the avoidance of classical communication
multiple rounds of end node communications ... required in the baseline
scheme for coordinating entanglement pumping across long distances"
[Integrating, §VI]). The optimistic/flexible scheme instead defers *all*
heralding — regardless of how many nested purification stages (link-level,
segment-level, end-node combination) are used — to a single round of
classical communication at the very end, paying only L/c once. This is
the dominant source of the reported 45–65× rate advantage, not merely the
factor-of-2 floor from a single deferred herald.

Physical time-scale parameters
-------------------------------
  τ_half   — half-RGS generation latency.
             For tree branching b⃗ = (b₀, …, b_{m-1}):
               τ_half = τ_emit × Σ_j log₂(b_j)
             where τ_emit is the per-qubit emission / gate cycle time.
  τ_join   — anchor CZ + XX measurement latency (≈ τ_emit in practice).
  τ_pur    — purification circuit latency (≈ τ_emit; small).
  L/c      — one-way propagation time: L_total / c.

Rate definition (renewal-theory)
---------------------------------
  R(scenario) = P_success / τ_cycle

  where τ_cycle is the wall-clock time per attempt, i.e.
    Raw:      τ_RGS^(raw)  + t_mem^(raw)
    Baseline: τ_RGS^(base) + t_mem^(base)
    Optimistic: τ_RGS^(opt) + t_mem^(opt)

  (The cycle time includes both the generation phase and the memory-wait
  phase, since the emitter is occupied during both.)

Rate ratio (Fig. 6 target)
----------------------------
  ρ = R_opt / R_base = (P_opt / τ_cycle^(opt)) / (P_base / τ_cycle^(base))

  If P_opt ≈ P_base (same purification circuit, same noise):
    ρ ≈ τ_cycle^(base) / τ_cycle^(opt)

  In the regime τ_half, τ_pur, τ_join ≪ L/c (which holds for N=10, 2 km
  hops, τ_emit ~ ns, L/c ~ 100 µs):
    τ_cycle^(base) ≈ 2L/c
    τ_cycle^(opt)  ≈ L/c
    ρ → 2   (fundamental floor from the single vs. double herald)

  The actual 45–65× factor reported in [Integrating, Fig. 6] is measured
  against the *raw* (no-purification) baseline, not the heralded baseline.
  That is:
    ρ_fig6 = R_opt / R_raw = (P_opt × τ_cycle^(raw)) / (1 × τ_cycle^(opt))

  This ratio is dominated by the fidelity gain: P_opt (the purification
  success probability compounded over all rounds) is << 1, but the
  purified state has F > 0.9 while the raw state does not, so a fair
  comparison requires normalising by resource cost (C(Σ)) as described
  in the week-3/4 plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hrgs_scheduler.models.network_config import NetworkConfig


@dataclass(frozen=True)
class TimingParameters:
    """Physical time-scale parameters for the timing model.

    All times should be in consistent units (e.g. microseconds).

    Parameters
    ----------
    tau_emit : float
        Per-qubit emission / gate cycle time.  Sets the absolute time scale.
    tau_join : float
        Latency of one Join/EntSwap (CZ + XX-meas) operation.
        Typically ≈ tau_emit.
    tau_pur : float
        Latency of one 2-qubit purification circuit.
        Typically ≈ tau_emit (local gate).
    """

    tau_emit: float
    tau_join: float
    tau_pur: float

    @classmethod
    def default(cls, tau_emit: float = 1.0) -> TimingParameters:
        """Construct default parameters with tau_join = tau_pur = tau_emit."""
        return cls(tau_emit=tau_emit, tau_join=tau_emit, tau_pur=tau_emit)


@dataclass(frozen=True)
class CanonicalLatencies:
    """Latency values for the three canonical schedule types.

    Attributes
    ----------
    tau_half : float
        Half-RGS generation latency τ_half.
    tau_rgs_raw : float
        RGS generation time for the raw scenario.
    tau_rgs_opt : float
        RGS generation time for the optimistic scenario.
    t_mem_raw : float
        Memory coherence time for the raw scenario.
    t_mem_base : float
        Memory coherence time for the baseline (heralded) scenario.
    t_mem_opt : float
        Memory coherence time for the optimistic scenario.
    tau_cycle_raw : float
        Full cycle time (generation + memory) for the raw scenario.
    tau_cycle_base : float
        Full cycle time for the baseline scenario.
    tau_cycle_opt : float
        Full cycle time for the optimistic scenario.
    """

    tau_half: float
    tau_rgs_raw: float
    tau_rgs_opt: float
    t_mem_raw: float
    t_mem_base: float
    t_mem_opt: float
    tau_cycle_raw: float
    tau_cycle_base: float
    tau_cycle_opt: float


def half_rgs_generation_time(
    network: NetworkConfig, timing: TimingParameters, hop_index: int = 0
) -> float:
    """Compute τ_half for hop *hop_index*.

    τ_half = τ_emit × Σ_j log₂(b_j)

    where b⃗ = branching vector and the sum runs over all tree levels j.
    [Validated Formal Model Def, §2.2; Bridging, Varnava 2006]

    Parameters
    ----------
    network : NetworkConfig
    timing : TimingParameters
    hop_index : int
        Which hop's branching vector to use.  For a uniform network all
        hops give the same result.
    """
    branching = network.hop(hop_index).branching
    return timing.tau_emit * sum(math.log2(b) for b in branching if b > 1)


def canonical_latencies(
    network: NetworkConfig,
    timing: TimingParameters,
    n_pur: int,
    n_rounds: int | None = None,
) -> CanonicalLatencies:
    """Compute the three canonical timing values from [Integrating, §IV-B].

    Parameters
    ----------
    network : NetworkConfig
        Physical configuration; used for L_total and c.
    timing : TimingParameters
        Time-scale parameters.
    n_pur : int
        Number of half-RGS copies per side (n_pur = 1 → raw/no purification).
    n_rounds : int or None
        Number of *sequential* heralded pumping rounds required by the
        baseline scheme (each costs a full 2L/c round trip).  Defaults to
        ``n_pur - 1`` (one round per sacrificial copy consumed, matching
        the paper's entanglement-pumping baseline).

    Returns
    -------
    CanonicalLatencies
    """
    tau_half = half_rgs_generation_time(network, timing)
    tau_join = timing.tau_join
    tau_pur = timing.tau_pur
    L_over_c = network.total_length() / network.c  # one-way propagation
    if n_rounds is None:
        n_rounds = max(n_pur - 1, 0)

    # --- Generation times ---
    tau_rgs_raw = tau_half + tau_join
    tau_rgs_opt = n_pur * tau_half + max(tau_pur + tau_join, n_pur * tau_join)

    # --- Memory coherence times ---
    t_mem_raw = tau_half + L_over_c
    t_mem_base = n_pur * tau_half + tau_pur + n_rounds * 2.0 * L_over_c
    t_mem_opt = n_pur * tau_half + tau_pur + L_over_c

    # --- Full cycle times ---
    tau_cycle_raw = tau_rgs_raw + t_mem_raw
    tau_cycle_base = tau_rgs_raw + t_mem_base  # generation rate unchanged for baseline
    tau_cycle_opt = tau_rgs_opt + t_mem_opt

    return CanonicalLatencies(
        tau_half=tau_half,
        tau_rgs_raw=tau_rgs_raw,
        tau_rgs_opt=tau_rgs_opt,
        t_mem_raw=t_mem_raw,
        t_mem_base=t_mem_base,
        t_mem_opt=t_mem_opt,
        tau_cycle_raw=tau_cycle_raw,
        tau_cycle_base=tau_cycle_base,
        tau_cycle_opt=tau_cycle_opt,
    )


def rate_ratio_opt_vs_raw(
    network: NetworkConfig,
    timing: TimingParameters,
    n_pur: int,
    p_success_opt: float,
    n_rounds: int | None = None,
) -> float:
    """Compute R_opt / R_raw — the rate ratio targeted by [Integrating, Fig. 6].

    R_opt / R_raw = (P_opt / τ_cycle^(opt)) / (1 / τ_cycle^(raw))
                 = P_opt × τ_cycle^(raw) / τ_cycle^(opt)

    Parameters
    ----------
    network : NetworkConfig
    timing : TimingParameters
    n_pur : int
        Number of purification copies.
    p_success_opt : float
        Product of all purification success probabilities P[Σ_opt succeeds].
        Obtained from ``EvaluationResult.success_prob``.
    n_rounds : int or None
        Number of sequential heralded pumping rounds; see ``canonical_latencies``.

    Returns
    -------
    float
        The rate ratio ρ = R_opt / R_raw.
    """
    lat = canonical_latencies(network, timing, n_pur, n_rounds=n_rounds)
    return p_success_opt * lat.tau_cycle_raw / lat.tau_cycle_opt


def rate_ratio_opt_vs_base(
    network: NetworkConfig,
    timing: TimingParameters,
    n_pur: int,
    p_success_opt: float,
    p_success_base: float,
    n_rounds: int | None = None,
) -> float:
    """Compute R_opt / R_base — the "optimistic vs. heralded baseline" ratio.

    In the L/c-dominated regime, this ratio approaches ``n_rounds`` (the
    number of sequential heralded round trips avoided by the optimistic
    scheme), rather than a fixed floor of 2 — see module docstring.

    Parameters
    ----------
    network : NetworkConfig
    timing : TimingParameters
    n_pur : int
    p_success_opt : float
        P[optimistic schedule succeeds].
    p_success_base : float
        P[baseline heralded schedule succeeds].
    n_rounds : int or None
        Number of sequential heralded pumping rounds; see ``canonical_latencies``.
    """
    lat = canonical_latencies(network, timing, n_pur, n_rounds=n_rounds)
    r_opt = p_success_opt / lat.tau_cycle_opt
    r_base = p_success_base / lat.tau_cycle_base
    return r_opt / r_base


def timing_summary(
    network: NetworkConfig,
    timing: TimingParameters,
    n_pur: int,
    n_rounds: int | None = None,
) -> str:
    """Return a formatted summary of canonical timing values.

    Parameters
    ----------
    network : NetworkConfig
    timing : TimingParameters
    n_pur : int
    n_rounds : int or None
        Number of sequential heralded pumping rounds; see ``canonical_latencies``.
    """
    lat = canonical_latencies(network, timing, n_pur, n_rounds=n_rounds)
    L_over_c = network.total_length() / network.c
    lines = [
        f"=== Canonical timing (N={network.N}, n_pur={n_pur}) ===",
        f"  τ_half       = {lat.tau_half:.4g}",
        f"  L/c          = {L_over_c:.4g}  (ratio τ_half/L_over_c = {lat.tau_half/L_over_c:.3g})",
        f"",
        f"  Raw:      τ_RGS = {lat.tau_rgs_raw:.4g}  t_mem = {lat.t_mem_raw:.4g}"
        f"  → cycle = {lat.tau_cycle_raw:.4g}",
        f"  Baseline: τ_RGS = {lat.tau_rgs_raw:.4g}  t_mem = {lat.t_mem_base:.4g}"
        f"  → cycle = {lat.tau_cycle_base:.4g}",
        f"  Optimistic: τ_RGS = {lat.tau_rgs_opt:.4g}  t_mem = {lat.t_mem_opt:.4g}"
        f"  → cycle = {lat.tau_cycle_opt:.4g}",
        f"",
        f"  t_mem_base / t_mem_opt = {lat.t_mem_base / lat.t_mem_opt:.3f}  "
        f"(savings from deferred herald)",
    ]
    return "\n".join(lines)
