"""
hrgs_scheduler.operations.backbone
=====================================
Backbone-layer operation functions.

These implement the physical operations of the HRGS protocol that are
**not** search variables; they are fixed by the underlying architecture
[Bridging + Integrating].

Catalog [Validated Formal Model Def, §2.5]
------------------------------------------
Gen:          half-RGS generation.  Produces an RGSS-local State.
join:         Join/EntSwap.  Composes two States via BSM composition rule.
absa_bsm:     Outer-photon BSM at the ABSA.  Same math as join; creates a
              single-hop edge from two RGSS-local States.
idle:         Apply decoherence to a State over Δt.
herald:       Resolve the heralding status of a State.
pauli_correct: Terminal; verify legality and return the final edge.

Notes
-----
* Join/EntSwap and BSM both use the identical bilinear error-vector
  composition rule and are unified as ``join``.  The physical difference
  (ABSA vs. anchor CZ+XX) is captured by the stage labels, not the math.
* Side-effect parities XOR at every merge [Validated Formal Model Def, §2.3].
* ``pauli_correct`` does NOT apply a physical gate here; it is a legality
  check and marker that the classical Z^s correction has been tracked.
"""

from __future__ import annotations

import math

from hrgs_scheduler.models.error_vector import ErrorVector
from hrgs_scheduler.models.network_config import HopConfig, NetworkConfig
from hrgs_scheduler.models.stage import RGSS, RGSSStage, Span, Stage
from hrgs_scheduler.models.state import HeraldStatus, State

# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def gen(
    hop_config: HopConfig,
    t: float = 0.0,
    side_effect_parity: int = 0,
) -> State:
    """Generate an RGSS-local entanglement resource.

    Models the half-RGS generation operator Gen(𝓫) from
    [Validated Formal Model Def, §2.2].  The output is a State at κ = RGSS
    whose error vector captures the combined inner-qubit and outer-qubit
    (pre-transmission) error contributions for the given hop parameters.

    Error vector model
    ------------------
    The inner-qubit error per hop is [Bridging, eq. (10)]:

        p_in = ½ [1 − (1 − 2 p^X_in)(1 − 2 p^Z_in)^(m−1)]

    The outer photon has not yet been transmitted at Gen time, so the
    outer-qubit depolarizing (e_d) is NOT applied here; it is applied
    inside ``absa_bsm`` when the photon travels to the ABSA.

    The RGSS-local error vector therefore reflects only inner-qubit errors,
    applied as an independent Z-type channel on the ANCHOR only; the outer
    photon carries no error yet [Bridging, §VI.D]. Per [Validated Formal
    Model Def, §2.4]: "the inner-qubit term contributes no ZZ error", so
    the second marginal probability passed to ``from_independent_z_flips``
    must be 0, not p_in:

        e = ErrorVector.from_independent_z_flips(p_in, 0.0)

    i.e.  w = 1−p_in, x = p_in, y = 0, z = 0.

    Parameters
    ----------
    hop_config : HopConfig
        Physical parameters for the hop this resource belongs to.
    t : float
        Simulation clock value at generation time.
    side_effect_parity : int
        Initial side-effect parity s^gen ∈ {0, 1} (𝔽₂).
        In the HRGS protocol this is an unconditional XOR over every
        pushout-level Bernoulli indicator [Bridging, Fig. 8].  For
        deterministic simulation we allow it to be set explicitly; set
        to 0 to model the ideal (expected-value) case.

    Returns
    -------
    State
        Fresh RGSS-local resource at time *t*.
    """
    p_in = hop_config.inner_error_per_hop
    ev = ErrorVector.from_independent_z_flips(p_a=p_in, p_b=0.0)
    return State(
        error_vector=ev,
        side_effect_parity=side_effect_parity & 1,
        current_time=t,
        generation_time=t,
        stage=RGSS,
        purification_rounds=0,
        herald_status=HeraldStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# Join / EntSwap and ABSA BSM
# ---------------------------------------------------------------------------


def join(state_a: State, state_b: State) -> State:
    """Join two States via the BSM error-vector composition rule.

    Implements the unified Join/EntSwap operation from
    [Validated Formal Model Def, §2.5]:  CZ + XX-measurement on the anchor-
    role qubits, equivalent to an entanglement swap.

    Legal input combinations
    ------------------------
    * Two RGSS-local States → stays at RGSS  (pre-transmission pairing).
    * Span(a, b) + Span(b, d) → Span(a, d)   (post-transmission stitching).

    The output time is max(t₁, t₂); generation_time is min(t_gen₁, t_gen₂).
    Side-effect parities XOR [Validated Formal Model Def, §2.3].

    Parameters
    ----------
    state_a : State
        First input resource (left endpoint).
    state_b : State
        Second input resource (right endpoint).

    Returns
    -------
    State
        Composed resource covering the merged span.

    Raises
    ------
    ValueError
        If the stage combination is not a legal Join target.
    """
    out_stage = _join_stage(state_a.stage, state_b.stage)
    ev_out = state_a.error_vector.bsm_compose(state_b.error_vector)
    return State(
        error_vector=ev_out,
        side_effect_parity=(state_a.side_effect_parity ^ state_b.side_effect_parity)
        & 1,
        current_time=max(state_a.current_time, state_b.current_time),
        generation_time=min(state_a.generation_time, state_b.generation_time),
        stage=out_stage,
        purification_rounds=state_a.purification_rounds + state_b.purification_rounds,
        herald_status=_join_herald(state_a.herald_status, state_b.herald_status),
    )


def absa_bsm(
    state_a: State,
    state_b: State,
    hop_index: int,
    e_d: float,
) -> State:
    """Outer-photon Bell measurement at the ABSA for a single hop.

    Models the BSM at the ABSA between two RGSS-local resources from
    adjacent stations (half-RGS from the left and right sides of hop
    *hop_index*).  The BSM is capped at 50% success per arm; this
    function models a *successful* arm outcome.

    Outer-photon depolarizing noise model [Integrating, §V-B, §V-C, §V-D]
    -------------------------------------------------------------------
    Depolarizing noise (full single-qubit Pauli channel, uniform across
    all photons) is applied to *each side's* outer photon before the BSM.
    Because the anchor-outer pair forms a two-qubit graph state, a Pauli
    error on the outer qubit propagates to an equivalent Z-type error on
    the pair via the graph-state stabilizer equivalence [Integrating, §V-C]:

        I_a X_b  ≡  Z_a I_b   (contributes to the "x" = ZI component)
        I_a Y_b  ≡  Z_a Z_b   (contributes to the "y" = ZZ component)
        I_a Z_b  ≡  I_a Z_b   (contributes to the "z" = IZ component)

    For a standard depolarizing channel with total error probability e_d
    (each of X, Y, Z occurring with probability e_d/3), the equivalent
    two-qubit error vector for one photon is:

        e_photon = [1 - e_d, e_d/3, e_d/3, e_d/3]

    This is composed with any pre-existing (e.g. inner-qubit) error on
    that side using the *same* bilinear formula as BSM composition: both
    represent independent 𝔽₂×𝔽₂ Pauli-Z channels acting on the same pair,
    and sequential composition of two such channels is a group convolution
    with an identical closed form to eq. (14) [Integrating].

    The two (now outer-qubit-noisy) sides are then combined into the
    single-hop edge via the same BSM composition rule.

    Parameters
    ----------
    state_a : State
        RGSS-local resource from the left station (κ = RGSS).
    state_b : State
        RGSS-local resource from the right station (κ = RGSS).
    hop_index : int
        0-indexed hop number, used to set the output Span(hop_index, hop_index+1).
    e_d : float
        Outer-qubit depolarizing rate (total error probability per photon).

    Returns
    -------
    State
        Single-hop edge at κ = Span(hop_index, hop_index + 1).

    Raises
    ------
    ValueError
        If either input is not at κ = RGSS.
    """
    if not isinstance(state_a.stage, RGSSStage) or not isinstance(
        state_b.stage, RGSSStage
    ):
        raise ValueError(
            "absa_bsm requires both inputs at κ=RGSS, "
            f"got {state_a.stage!r} and {state_b.stage!r}"
        )

    # Single-photon depolarizing channel, mapped to the anchor-outer
    # two-qubit error vector via the graph-state Pauli equivalence.
    depol = ErrorVector(w=1.0 - e_d, x=e_d / 3.0, y=e_d / 3.0, z=e_d / 3.0)

    # Compose each side's pre-existing error (e.g. from inner qubits) with
    # the outer-photon depolarizing channel (sequential 𝔽₂×𝔽₂ convolution,
    # same closed form as bsm_compose).
    e_a_noisy = state_a.error_vector.bsm_compose(depol)
    e_b_noisy = state_b.error_vector.bsm_compose(depol)

    # Combine the two (now noisy) sides via the BSM composition rule.
    ev_out = e_a_noisy.bsm_compose(e_b_noisy)

    out_stage = Span(hop_index, hop_index + 1)
    return State(
        error_vector=ev_out,
        side_effect_parity=(state_a.side_effect_parity ^ state_b.side_effect_parity)
        & 1,
        current_time=max(state_a.current_time, state_b.current_time),
        generation_time=min(state_a.generation_time, state_b.generation_time),
        stage=out_stage,
        purification_rounds=state_a.purification_rounds + state_b.purification_rounds,
        herald_status=HeraldStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# Decoherence (Idle)
# ---------------------------------------------------------------------------


def idle(state: State, until: float, gamma: float) -> State:
    """Advance a State to time *until*, applying exponential decoherence.

    Implements [Validated Formal Model Def, §2.6]:

        e(t) = ¼𝟏 + exp(−γ Δt)  (e(t₀) − ¼𝟏)

    The decoherence is applied *locally*, not as a global correction,
    because the composition is nonlinear and order matters.

    Parameters
    ----------
    state : State
        State to decohere.
    until : float
        Target clock value; must be ≥ state.current_time.
    gamma : float
        Memory dephasing rate γ.

    Returns
    -------
    State
        Updated state with decohered error vector and current_time = *until*.

    Raises
    ------
    ValueError
        If *until* < state.current_time (cannot go backwards in time).
    """
    if until < state.current_time:
        raise ValueError(
            f"idle: target time {until} < current_time {state.current_time}"
        )
    delta_t = until - state.current_time
    ev_new = state.error_vector.decohere(gamma=gamma, delta_t=delta_t)
    return State(
        error_vector=ev_new,
        side_effect_parity=state.side_effect_parity,
        current_time=until,
        generation_time=state.generation_time,
        stage=state.stage,
        purification_rounds=state.purification_rounds,
        herald_status=state.herald_status,
    )


# ---------------------------------------------------------------------------
# Herald
# ---------------------------------------------------------------------------


def herald(state: State, propagation_time: float = 0.0) -> State:
    """Resolve the heralding status of a State.

    Marks the State's herald_status as RESOLVED, advancing current_time
    by *propagation_time* to model the classical communication round-trip
    (l/c for cross-node heralding).

    "Optimistic" vs. "heralded" purification is determined by where Herald
    nodes sit in the schedule DAG relative to Purify nodes, not by any
    separate operation type [Validated Formal Model Def, §3.3].

    Parameters
    ----------
    state : State
        State whose heralding is being confirmed.
    propagation_time : float
        Classical communication cost to resolve heralding (typically l/c).

    Returns
    -------
    State
        Same state with herald_status = RESOLVED and updated current_time.
    """
    return State(
        error_vector=state.error_vector,
        side_effect_parity=state.side_effect_parity,
        current_time=state.current_time + propagation_time,
        generation_time=state.generation_time,
        stage=state.stage,
        purification_rounds=state.purification_rounds,
        herald_status=HeraldStatus.RESOLVED,
    )


# ---------------------------------------------------------------------------
# PauliCorrect (terminal)
# ---------------------------------------------------------------------------


def pauli_correct(state: State, N: int) -> State:
    """Terminal Pauli-frame correction at the end of the schedule.

    Verifies that the State is at the full end-to-end span Span(0, N) and
    that heralding has been resolved, then marks it as corrected.

    The physical Z^s correction is tracked symbolically via side_effect_parity;
    this function verifies legality and returns the corrected state
    (parity reset to 0, representing the applied correction).

    Parameters
    ----------
    state : State
        Final entanglement resource; must be at κ = Span(0, N) and RESOLVED.
    N : int
        Number of hops in the network.

    Returns
    -------
    State
        The usable final Bell pair.

    Raises
    ------
    ValueError
        If the state is not at the correct stage or heralding is not resolved.
    """
    expected_stage = Span(0, N)
    if state.stage != expected_stage:
        raise ValueError(f"PauliCorrect requires κ = Span(0, {N}), got {state.stage!r}")
    if not state.is_herald_resolved:
        raise ValueError("PauliCorrect requires herald_status = RESOLVED")
    # Reset parity to 0: the Z^s correction has been applied.
    return State(
        error_vector=state.error_vector,
        side_effect_parity=0,
        current_time=state.current_time,
        generation_time=state.generation_time,
        stage=state.stage,
        purification_rounds=state.purification_rounds,
        herald_status=state.herald_status,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _join_stage(stage_a: Stage, stage_b: Stage) -> Stage:
    """Compute the output stage for a Join/EntSwap from the two input stages."""
    # RGSS + RGSS → RGSS  (pre-transmission RGSS-level join)
    if isinstance(stage_a, RGSSStage) and isinstance(stage_b, RGSSStage):
        return RGSS
    # Span(a,b) + Span(b,d) → Span(a,d)
    if isinstance(stage_a, Span) and isinstance(stage_b, Span):
        return stage_a.join(stage_b)
    raise ValueError(
        f"Illegal Join/EntSwap stage combination: {stage_a!r} and {stage_b!r}. "
        "Both must be RGSS, or both must be adjacent Span instances."
    )


def _join_herald(h_a: HeraldStatus, h_b: HeraldStatus) -> HeraldStatus:
    """Herald status of a joined state: RESOLVED only if both inputs are resolved."""
    if h_a is HeraldStatus.RESOLVED and h_b is HeraldStatus.RESOLVED:
        return HeraldStatus.RESOLVED
    return HeraldStatus.PENDING
