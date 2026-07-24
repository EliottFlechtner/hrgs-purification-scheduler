# Non-Adaptive Purification Scheduling for Half-RGS Quantum Repeaters

**Scope:** arbitrary, fixed-in-advance (non-adaptive) purification schedules.
**Future extension:** adaptive/closed-loop scheduling.

## 1. Purpose

Given a physical network configuration and a resource budget, this model represents *any fixed purification schedule* (any combination of purification circuit YY/ZX/XZ, applied at any stage: generation, link, arbitrary multi-hop segment, or end-node, in any order, mixed arbitrarily across parallel branches) as a **single well-defined mathematical object $\Sigma$**. Given $\Sigma$, the model computes fidelity, rate, resource cost, and latency.

**Goal:** search the space of valid $\Sigma$ to find the one(s) optimizing a chosen cost function, for a given network config and budget.

The model splits into two layers:
- **Backbone layer** ([[#2. Backbone layer|§2]]): the physical process of establishing entanglement (generation, joining/swapping, Pauli frame correction), fixed by the underlying protocol \[[[Bencha2026Bridging|Bridging]] + [[Bencha2025Integrating|Integrating]]]. Not a search variable.
- **Scheduling layer** ([[#3. Scheduling layer|§3]]): the decisions being searched over, i.e. where to insert purification, which circuit to use, and how to sequence optimistic vs. heralded steps.

A schedule $\Sigma$ ([[#4. Schedule as a formal object|§4]]) is a program built from operations of both layers. Only the scheduling-layer choices are what optimization varies.

## 2. Backbone layer

### 2.1 Network configuration

$$\mathcal{N} = \Big(N,\ \{{\ell_i}\}_{i=1}^{N},\ \{{\vec{b}^{(i)}}\}_{i=1}^{N},\ \{{k_i}\}_{i=1}^N,\ \{({p^{X}_{\mathrm{in},i} ,\;p^{Z}_{\mathrm{in},i}})\}_{i=1}^{N},\ \{{\eta_i}\}_{i=1}^{N},\ e_d,\ \gamma,\ c\Big)$$

- $N$: hops between Alice and Bob (one hop = one RGSS $\leftrightarrow$ ABSA link between adjacent stations).
- $\ell_i$: hop $i$ length.
- $\vec b^{(i)}$: tree-code branching for hop $i$'s inner qubits.
- $k_i$: biclique arm count at hop $i$.
- $p^X_{\mathrm{in},i}, p^Z_{\mathrm{in},i}$: error rates of the X/Z logical measurements on tree-encoded inner qubits (feeds [[#2.4 Edge error vector and composition|§2.4]]).
- $\eta_i$: photon survival probability, $\eta = 10^{-\alpha\ell/10}$ for attenuation $\alpha$.
- $e_d$: outer-qubit depolarizing rate.
- $\gamma$: memory dephasing rate ([[#2.6 Decoherence|§2.6]]).
- $c$: propagation speed.

Example config, from \[[[Bencha2025Integrating|Integrating]], §V.A\]: $$\mathcal{N} = \Big(N=10,\ \ell_i=2\text{ km},\ \vec{b}^{(i)}=(16,14,1),\ k_i=18,\ e_d\in[0,0.01],\ \dots\Big), \quad \forall i$$
BSM success is structurally **capped at 50% per arm**, independent of $\eta_i$ or $e_d$, due to the inherent limits of linear-optics Bell measurement \[[[Bencha2026Bridging|Bridging]], §VI.A]. $k_i$ exists to provide redundancy against this ceiling.

### 2.2 Generation process

A half-RGS with branching $\vec b = (b_0,\dots,b_m)$ and $m$ arms is built by a sequence of emitter pushout operations, repeated once per arm \[[[Bencha2026Bridging|Bridging]], Fig. 6, eq. (4)]:

$$ \mathrm{Gen}(\vec b) \to \big(\mathbf e,\ s^{\text{gen}},\ \tau_{\text{gen}}(\vec b)\big) $$

- $\mathbf e$: error vector. Generation of a [[Half-RGS (HRGS)]] produces a resource carrying the same $[w,x,y,z]^T$ formalism as an established edge, as a pre-transmission, same-station instance rather than a cross-station one (see [[#2.4 Edge error vector and composition|§2.4]]).
- $s^{\text{gen}}$: accumulated Z-side-effect parity from the pushout-plus-Z-measurement sequence, tracked at the anchor qubit:

$$s^{\text{gen}}= \bigoplus_{i=1}^{m}\bigoplus_{j=1}^{\text{depth}(\vec b)} g_{i,j}, \quad g_{i,j}\sim\mathrm{Bernoulli}(1/2)$$

Every level's potential flip within one arm's generation always propagates to the anchor \[[[Bencha2026Bridging|Bridging]], Fig. 8], so this is an **unconditional XOR over every level of every arm**, with no conditional witness-chain tracking needed.

- $\tau_{\text{gen}}(\vec b) \propto \sum_j \log_2 b_j$ \[[[Bencha2026Bridging|Bridging]], [[Varnava2006Loss|Varnava 2006]]].

### 2.3 Z side-effect algebra

Side effects live in $\mathbb F_2$. Composition is XOR whenever paths merge (BSM, XX-measurement propagation, anchor joining), since Z side effects need only one bit of information per vertex \[[[Bencha2026Bridging|Bridging]], §II-B]. Final correction:

$$ s^{\text{total}}_A = \bigoplus_{\text{all sources}} s_{\text{source}} \implies \text{apply } Z^{s^{\text{total}}_A}\text{ at PauliCorrect}$$

Per-trial communication cost is 2 bits per ABSA \[[[Bencha2026Bridging|Bridging]], §VI-B]: local parity & success/fail flag. Constant regardless of tree depth, because the pushout-level process ([[#2.2 Generation process|§2.2]]) pre-collapses the tree's side effects into one bit ($s^{\text{gen}}$).

This side-effect algebra is a separate linear ($\mathbb F_2$) layer from the nonlinear, real-valued fidelity layer below. A schedule must be legal with respect to both independently.

### 2.4 Edge error vector and composition

Once a resource participates in a BSM (outer-qubit), it becomes a two-party edge carrying $\mathbf e=[w,x,y,z]^T$, the probabilities of $II, ZI, ZZ, IZ$ errors on a Bell pair \[[[Bencha2025Integrating|Integrating]], eq. (7)]:

$$[w,x,y,z]^T := w|\phi_{II}\rangle\langle\phi_{II}| + x|\phi_{ZI}\rangle\langle\phi_{ZI}| + y|\phi_{ZZ}\rangle\langle\phi_{ZZ}| + z|\phi_{IZ}\rangle\langle\phi_{IZ}|$$

This formalism applies at every stage, including RGSS-local pre-transmission resources: the anchor together with its outer photon forms a two-qubit graph state carrying the same $\mathbf e$ formalism even before transmission \[[[Bencha2026Bridging|Bridging]], §VII-B]. RGSS-level purification uses the same circuits as end-node purification \[[[Bencha2025Integrating|Integrating]], §IV-A, Fig. 3], purifying two independently-generated copies of the same side's half-RGS anchor against each other.

Two contributions combine into an edge's $\mathbf e$ once BSM/composition occurs:
- **Outer-qubit term**: from $e_d$ applied to the outer photon during transmission.
- **Inner-qubit term**: independent, per-hop \[[[Bencha2026Bridging|Bridging]], eq. (10)]:
$$p_{ZI}=p_{IZ}=\tfrac12\big[1-(1-2p^X_{\text{in}})(1-2p^Z_{\text{in}})^{m-1}\big]$$
accumulating over $N$ hops \[[[Bencha2026Bridging|Bridging]], eqs. (6)-(9)]:
$$p^{e2e}_{ZI} = \tfrac12\big[1-(1-2p_{ZI})^N\big], \qquad p^{e2e}_{IZ} = \tfrac12\big[1-(1-2p_{IZ})^N\big]$$

The inner-qubit term contributes no ZZ error: outer-qubit operations contribute to all error terms (ZI, IZ, ZZ), while inner-qubit measurements contribute only to the independent ZI and IZ terms \[[[Bencha2026Bridging|Bridging]], §VII-D]. Under isotropic noise, the scheme is therefore biased toward ZI and IZ over ZZ.

Both contributions combine via the bilinear BSM-composition rule \[[[Bencha2025Integrating|Integrating]], eq. (14) / [[Bencha2026Bridging|Bridging]], eq. (5)]:
$$\mathrm{BSM}(\mathbf e_1,\mathbf e_2) = \begin{bmatrix} w_1w_2+x_1x_2+y_1y_2+z_1z_2 \\ w_1x_2+x_1w_2+z_1y_2+y_1z_2 \\ w_1y_2+y_1w_2+x_1z_2+z_1x_2 \\ w_1z_2+z_1w_2+x_1y_2+y_1x_2 \end{bmatrix}$$

### 2.5 Backbone operations catalog

Joining two half-RGSs into an RGS effectively realizes the entanglement swapping operation, even though the physical joining may occur before all qubits arrive at the ABSA \[[[Bencha2026Bridging|Bridging]], §III/§IV-C]. This functional equivalence is what allows purification techniques from memory-based architectures to be adapted here. Consequently, `Join` and `EntSwap` are treated as a single unified operation: joining two freshly-generated half-RGS anchors at an RGSS, and stitching two previously-established edges, are both the identical CZ-then-XX-measurement on a pair of anchor-role qubits.

| Op                             | Inputs                                                                                        | Output                                                                                                                                                                                        |
| ------------------------------ | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Gen**                        | $\vec b$, branching vector                                                                    | $(\mathbf e, s^{\text{gen}}, \tau_{\text{gen}})$                                                                                                                                              |
| **Join/EntSwap**               | 2 edges/anchors, $\kappa=(a,b)$, $\kappa=(b,d)$, or two RGSS-local pre-transmission resources | 1 edge, $\kappa=(a,d)$, via §2.4's BSM composition rule. CZ+XX on the anchor-role qubits, contributes to $s$ bookkeeping (§2.3)                                                               |
| **BSM**                        | 2 outer photons at an ABSA                                                                    | fresh edge at $\kappa=(i{-}1,i)$, success capped at 50% per arm (§2.1)                                                                                                                        |
| **Z-meas / XX-meas**           | inner tree qubits, or non-selected arms at ABSA                                               | side-effect propagation (§2.3). Each ABSA keeps exactly one successful-BSM arm and Z-measures all other arms: a forced backbone mechanism, distinct from the scheduling-layer `Discard` below |
| **PauliCorrect**               | 1 edge, $\kappa=(0,N)$, heralded                                                              | usable Bell pair, apply $Z^{s^{\text{total}}}$                                                                                                                                                |
| **Idle**                       | 1 state, wait duration $\Delta t$                                                             | same state, $\mathbf e$ relaxed per §2.6                                                                                                                                                      |
| **Discard** (scheduling-layer) | 1 state                                                                                       | frees the resource for $M_{\max}$ accounting, a scheduling choice                                                                                                                             |

### 2.6 Decoherence

While idle, an edge's error vector relaxes toward the maximally mixed state:
$$\mathbf e(t) = \tfrac14\mathbf 1 + e^{-\gamma t}\big(\mathbf e(t_0)-\tfrac14\mathbf 1\big)$$

\[[[Bencha2025Integrating|Integrating]], §IV-B] gives closed-form generation and memory-time expressions for three canonical schedule types, which serve as a validation target for the cost functions ([[#6. Cost functions and the optimization problem|§6]]):

|Scenario|Generation time|Memory coherence time|
|---|---|---|
|Raw (no purification)|$\tau^{(\text{raw})}_{\text{RGS}} = \tau_{\text{half-RGS}}+\tau_{\text{join}}$|$t^{(\text{raw})}_{\text{mem}}\approx \tau_{\text{half-RGS}}+L_{\text{total}}/c$|
|Baseline (end-node purification)|$\tau_{\text{RGS}}$ same as raw|$t^{(\text{p-base})}_{\text{mem}}\approx n_{\text{pur}}\tau_{\text{half-RGS}}+\tau_{\text{pur circ}}+2L_{\text{total}}/c$|
|Optimistic (this framework)|$\tau^{(\text{p-opt})}_{\text{RGS}} = n_{\text{pur}}\tau_{\text{half-RGS}}+\max{\tau_{\text{pur circ}}+\tau_{\text{join}},\ n_{\text{pur}}\tau_{\text{join}}}$|$t^{(\text{p-opt})}_{\text{mem}}\approx n_{\text{pur}}\tau_{\text{half-RGS}}+\tau_{\text{pur circ}}+L_{\text{total}}/c$|

The baseline pays $2L_{\text{total}}/c$; the optimistic scheme pays only $L_{\text{total}}/c$. This is the mechanism the Herald-placement formalism ([[#3.3 Herald and optimism|§3.3]]) captures. Any schedule $\Sigma$ that reduces to one of these three canonical forms should reproduce these exact formulas when evaluated by the inner-loop DAG pass ([[#7. Search algorithm|§7]]).

Total idle time:
$$T_{\text{idle}}(\Sigma) = \sum_{v\in T}\big(t_{\text{consumed}}(v)-t_{\text{gen}}(v)\big)$$
Applied **locally at every node**, not as a single lump correction, since the relaxation is nonlinear and composition order matters.

## 3. Scheduling layer

### 3.1 State object (edge)

$$ S = \big(\mathbf e,\ s,\ t,\ t_{\text{gen}},\ \kappa,\ r,\ h\big) $$
One vector type is used throughout, at every $\kappa$ (§2.4).
- $\mathbf e$: error state, meaningful at every stage (RGSS-local pre-transmission pairing at generation time, or post-join/composition edge).
- $s$: side-effect parity accumulated by this object ([[#2.3 Z side-effect algebra|§2.3]]).
- $t, t_{\text{gen}}$: current time and generation time, giving $\Delta t_{\text{idle}}=t-t_{\text{gen}}$ for [[#2.6 Decoherence|§2.6]].
- $\kappa \in {{\mathrm{RGSS}}}\cup{{\mathrm{Span}(a,b): 0\le a<b\le N}}$: RGSS for pre-transmission same-side resources, or a span $(a,b)$ for an established edge covering hops $a$ through $b$.
- $r$: purification rounds applied, reserved for future search-heuristic use.
- $h$: heralding status, load-bearing (`PauliCorrect` requires $h=$resolved).

### 3.2 Purification operations

Success probabilities and purified output vectors \[[[Bencha2025Integrating|Integrating]], eqs. (8)-(13)]:
$$ P_{ZX}(e_1,e_2) = (w_1+x_1)(w_2+x_2)+(z_1+y_1)(z_2+y_2) $$$$ P_{XZ}(e_1,e_2) = (w_1+z_1)(w_2+z_2)+(x_1+y_1)(x_2+y_2) $$$$ P_{YY}(e_1,e_2) = (w_1+y_1)(w_2+y_2)+(x_1+z_1)(x_2+z_2) $$
$$ \mathrm{Pur}_{ZX} = \frac{1}{P_{ZX}}\begin{bmatrix}w_1w_2+z_1z_2\\ z_1w_2+w_1z_2\\ x_1y_2+y_1x_2\\ x_1x_2+y_1y_2\end{bmatrix} \quad \mathrm{Pur}_{XZ} = \frac{1}{P_{XZ}}\begin{bmatrix}w_1w_2+x_1x_2\\ z_1z_2+y_1y_2\\ z_1y_2+y_1z_2\\ x_1w_2+w_1x_2\end{bmatrix} \quad \mathrm{Pur}_{YY} = \frac{1}{P_{YY}}\begin{bmatrix}w_1w_2+y_1y_2\\ x_1z_2+z_1x_2\\ y_1w_2+w_1y_2\\ x_1x_2+z_1z_2\end{bmatrix} $$

Each circuit detects a specific error type and keeps one of the two input copies: ZX detects Z errors on qubit $b$, XZ detects Z errors on qubit $a$, YY detects an odd number of Z errors across all four qubits \[[[Bencha2025Integrating|Integrating]], §V-B].

Since inner-qubit errors bias toward independent ZI and IZ over ZZ (§2.4), entanglement pumping sequences typically start with YY, which is best suited to catching that bias early, before switching to ZX/XZ.

**Legality**: $S_1,S_2$ *must share identical* $\kappa$, regardless of differing history.

### 3.3 Herald and optimism

Distribution and purification are performed **immediately in sequence**, without waiting for heralding confirmation. Classical outcomes are compared only once at the end, combining the heralding of Bell pair generation and the purification results in a single round of communication \[[[Bencha2025Integrating|Integrating]], §III-B, Fig. 2].

|Op|Inputs|Output|
|---|---|---|
|**Herald**|1 state, $h=$pending|same state, $h=$resolved, classical communication cost $\ell/c$ if cross-node|

"Optimistic" vs. "heralded" purification **is not a separate operation type**. It is determined by where `Herald` sits in the schedule DAG relative to `Purify` nodes.

=> A branch is optimistic wherever `Purify` nodes chain without an intervening cross-node `Herald`.

## 4. Schedule as a formal object

### 4.1 Definition

$$ \Sigma = (T,\phi) $$
- $T$: rooted DAG. Leaves are `Gen`; internal nodes are backbone or scheduling-layer operations ([[#2.5 Backbone operations catalog|§2.5]], [[#3.2 Purification operations|§3.2]], [[#3.3 Herald and optimism|§3.3]]); root is `PauliCorrect` at $\kappa=(0,N)$.
- $\phi:T\to\kappa$, legal iff:
    - `Gen` only at RGSS
    - `Purify` requires identical $\kappa$ on both children
    - `Join/EntSwap` requires adjacent spans, or two RGSS-local resources
    - `PauliCorrect` requires $\kappa=(0,N)$.
- **Span consistency**: `Join/EntSwap` with children $(a,b),(b,d)$ produces $(a,d)$.

### 4.2 Why this represents arbitrary fixed schedules

Validated directly against \[[[Bencha2025Integrating|Integrating]], Fig. 4]'s flexible-scheduling example: one pair is built by purifying each link-level connection and stitching the purified links across the full path; a second pair is formed by stitching link-level pairs into two 5-hop segments, purifying within each segment, then connecting them; a third pair is built by directly stitching raw link-level pairs with no intermediate purification. All three are then combined at the end nodes via a pumping-like purification sequence.

This is precisely the mixed-granularity, mixed-provenance, end-node-combination structure this model represents: span-generalized $\kappa$ allows arbitrary stitching granularity, and `Purify` requiring only matching $\kappa$, not matching history, **allows combining differently-purified branches.**

The paper explicitly names this schedule as unoptimized, noting that further improvements should be achievable through optimized scheduling strategies, and that selecting optimal purification schedules remains an open problem \[[[Bencha2025Integrating|Integrating]], §VI-VII]. This is the gap this project targets.

Fully adaptive schedules, branching on intermediate outcomes, are out of scope.

## 5. Resource budget

$$ B = (n_{\text{pur}},\ E_{\max},\ M_{\max}) $$
$n_{\text{pur}}$ corresponds directly to the extra-emitter count needed to generate multiple half-RGSs per side for purification \[[[Bencha2025Integrating|Integrating]], §IV-A].

- $n_{\text{pur}}$: copies per RGSS-level purification round.
- $E_{\max}$: max emitters per trial, bounds `Gen` leaf count in $T$.
- $M_{\max}$: max simultaneously held states.

$\Sigma$ is feasible iff $|\text{Gen leaves}|\le E_{\max}$ and max concurrent open branches $\le M_{\max}$.

## 6. Cost functions and the optimization problem

### 6.1 Cost functions

- $F(\Sigma;\mathcal N) = w_{\text{root}}$
    Fidelity is the $w$ component of $\mathbf e$ at the root: the final probability of the ideal Bell state component \[[[Bencha2026Bridging|Bridging]], §VII-D].

- $R(\Sigma;\mathcal N) = \frac{\Pr[\Sigma\text{ succeeds}]}{\mathbb E[\text{total wall-clock time}(\Sigma)]}$
    Rate, under a renewal-theory assumption of full restart on failure. \[[[Bencha2025Integrating|Integrating]], Fig. 6] reports the optimistic scheme beating baseline by a factor of roughly 45 to 65 depending on noise level, a concrete number this model's $R$ formula should reproduce when specialized to their exact schedule.

- $C(\Sigma) = |\text{Gen nodes in }T|$: resource cost.
- $L(\Sigma;\mathcal N) = \text{makespan of }T$: latency, grounded by the timing table in [[#2.6 Decoherence|§2.6]].

### 6.2 Optimization problem

$$\boxed{ \Sigma^{*}(\mathcal N,B) = \arg\max_{\Sigma\ \text{feasible w.r.t. }B,\ \text{legal w.r.t. }\mathcal N} R(\Sigma;\mathcal N) \quad\text{s.t.}\quad F(\Sigma;\mathcal N)\ge F_{\min} }$$
Over all feasible and legal $\Sigma$: maximize rate subject to a fidelity floor.

### 6.3 Objective substitution

The same $\Sigma$/cost-function machinery supports different research questions by swapping which cost function is optimized and which is constrained:
- Maximize $F$ s.t. $R\ge R_{\min}$: best achievable quality given a throughput floor.
- Minimize $C$ s.t. $F\ge F_{\min}$ and $R\ge R_{\min}$: cheapest hardware meeting both bars.
- Minimize $L$ s.t. $F\ge F_{\min}$: fastest schedule meeting a quality bar, relevant for latency-sensitive protocols such as QKD session setup.

## 7. Search algorithm

**Inner loop, fixed-schedule evaluation:** given a concrete $\Sigma$, computing $F,R,C,L$ is a bottom-up pass over the DAG $T$. Each node's output depends only on its children's, giving $O(|T|)$ dynamic programming / sum-product evaluation.

**Outer loop, search over $\Sigma$**, three tractable tiers:
1. Brute force over bounded-depth schedules: exact results, for validating structural intuitions on small $N$.
2. [[Dynamic Programming (DP)]] over stages: since $\kappa$ has a natural partial order (RGSS, then increasing spans, then $(0,N)$), a Bellman-style optimal-cost-to-go computation $V(\kappa,\mathbf e,B_{\text{remaining}})$ scales far better than brute force and is the natural master algorithm.
3. Heuristic search (greedy, beam search, simulated annealing) once $N,B$ exceed exact-DP tractability.

**Two-level decomposition, structure vs. allocation:**
1. Outer combinatorial/DP search over schedule structure: which spans, which stitching pattern, which purification circuits, where.
2. For a fixed structure, an inner (I)LP/convex program allocating how many purification rounds to each stage under the budget.

The inner sub-problem is linear, since success probabilities are log-additive and resource cost is linear, unlike the outer structure search, where fidelity composition is bilinear and non-convex. This two-level decomposition is the most tractable path to a working optimizer.

## 8. Open design decisions
- **Decoherence channel**: current model uses exponential dephasing toward the maximally mixed state. Hardware-specific asymmetric noise would change the relative performance of ZX/XZ/YY circuits.
- **Objective pairing**: which cost function to optimize and which to constrain ([[#6.3 Objective substitution|§6.3]]).
- **Adaptive scheduling**: fully adaptive schedules, branching on intermediate outcomes, require an MDP formulation, deferred to future work.

## 9. Worked example

$N=2$, budget $B=(n_{\text{pur}}{=}2,\ E_{\max}{=}12,\ M_{\max}{=}6)$. Chosen to exercise every mechanism, not optimized for fidelity.

```
Hop 1 (RGSS purification, mixed provenance):
  Gen(b) → e^(1)  ┐
  Gen(b) → e^(2)  ┴→ Purify-YY [κ=RGSS, two independent same-side copies] → e^purified
  Gen(b) → e^(3)  (unpurified, other half)
  Join/EntSwap(e^purified, e^(3)) [κ=RGSS] → anchor pair
  BSM → edge_1 [κ=(0,1)]

Hop 2 (raw, no purification):
  Gen(b)×2 → Join/EntSwap [κ=RGSS] → BSM → edge_2 [κ=(1,2)]

Join/EntSwap(edge_1[κ=(0,1)], edge_2[κ=(1,2)]) → trial_A [κ=(0,2)]

(Repeat the whole above block independently) → trial_B [κ=(0,2)]

Purify-XZ(trial_A, trial_B) [κ=(0,2), end-node since N=2] → merged
  ── Idle (waiting, optimistic, no Herald yet) ──
Herald(merged) → h: resolved
PauliCorrect(merged) → final usable pair, apply Z^{s_total}
```

![[purification_schedule_dag.png|697]]![[physical_topology_dag.png|697]]

The RGSS-level `Purify-YY` step purifies two independently-generated copies of hop 1's same-side half-RGS anchor (§2.4). `Join/EntSwap` is the single unified operation throughout. Span-based $\kappa$, mixed provenance at end-node purification, and the single deferred `Herald` are all validated against \[[[Bencha2025Integrating|Integrating]], Fig. 4]'s structure ([[#4.2 Why this represents arbitrary fixed schedules|§4.2]]).

**Resource cost**: $C(\Sigma)=10$ `Gen` nodes.