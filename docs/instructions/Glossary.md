## Half-RGS Purification Scheduling Model

Companion reference to [[v2 current]]. Each entry now includes both a short working name and a more formal mathematical name, in case one register suits a given audience/context better than the other.

### Network configuration $\mathcal N$

|Symbol|Short name|Formal name|
|---|---|---|
|$\mathcal N$|network config|network configuration tuple|
|$N$|number of hops|hop cardinality|
|$\ell_i$|hop $i$ length|inter-station separation, hop $i$|
|$\vec b^{(i)}$|branching vector, hop $i$|tree-encoding branching parameter sequence, hop $i$|
|$k_i$|arm count, hop $i$|biclique arm multiplicity, hop $i$|
|$p^X_{\text{in},i}$|inner X error rate, hop $i$|logical X-measurement error probability, inner qubit, hop $i$|
|$p^Z_{\text{in},i}$|inner Z error rate, hop $i$|logical Z-measurement error probability, inner qubit, hop $i$|
|$\eta_i$|photon loss, hop $i$|photon transmissivity / survival probability, hop $i$|
|$e_d$|depolarizing rate|outer-qubit depolarizing-channel parameter|
|$\gamma$|dephasing rate|quantum-memory decoherence rate constant|
|$c$|propagation speed|signal propagation velocity|

### Generation process

|Symbol|Short name|Formal name|
|---|---|---|
|$\mathrm{Gen}(\vec b)$|generation op|half-RGS generation operator|
|$m$|arm/depth count|arm multiplicity (equiv. tree depth)|
|$g_{i,j}$|side-effect bit|pushout-induced Bernoulli side-effect indicator, arm $i$, level $j$|
|$s^{\text{gen}}$|gen. parity|accumulated generation-phase side-effect parity|
|$\tau_{\text{gen}}$|gen. time|half-RGS generation latency|

### Z-side-effect algebra

|Symbol|Short name|Formal name|
|---|---|---|
|$s$|parity bit|Clifford side-effect parity, $\mathbb F_2$-valued|
|$s^{\text{total}}_A$|total parity|accumulated end-node correction parity, party $A$|
|$Z^{s}$|correction op|conditional Pauli-$Z$ correction operator|

### Edge error vector

|Symbol|Short name|Formal name|
|---|---|---|
|$\mathbf e=[w,x,y,z]^T$|error vector|Bell-diagonal error-probability vector|
|$w,x,y,z$|vector components|probabilities of $II, ZI, ZZ, IZ$ error syndromes ($w$ = fidelity)|
|$\mathrm{BSM}(\mathbf e_1,\mathbf e_2)$|BSM composition|bilinear error-vector composition map|
|$p_{ZI}, p_{IZ}$|per-hop inner error|single-hop inner-qubit error probabilities|
|$p^{e2e}_{ZI}, p^{e2e}_{IZ}$|e2e inner error|end-to-end accumulated inner-qubit error probabilities|

### Purification

|Symbol|Short name|Formal name|
|---|---|---|
|$P_{YY}, P_{ZX}, P_{XZ}$|success probabilities|stabilizer-measurement success probabilities|
|$\mathrm{Pur}_{YY}, \mathrm{Pur}_{ZX}, \mathrm{Pur}_{XZ}$|purified outputs|conditional post-purification error-vector maps|

### State object $S$

| Symbol           | Short name    | Formal name                                    |
| ---------------- | ------------- | ---------------------------------------------- |
| $S$              | state object  | entanglement-resource state tuple ("edge")     |
| $\mathbf e$      | error vector  | (field) Bell-diagonal error-probability vector |
| $s$              | parity        | (field) accumulated side-effect parity         |
| $t$              | current time  | (field) instantaneous simulation timestamp     |
| $t_{\text{gen}}$ | gen. time     | (field) resource-generation timestamp          |
| $\kappa$         | stage/span    | (field) processing-stage / span index          |
| $r$              | round count   | (field) purification-round multiplicity        |
| $h$              | herald status | (field) heralding-resolution status            |

### $\kappa$ (stage/span)

|Symbol|Short name|Formal name|
|---|---|---|
|$\mathrm{RGSS}$|pre-transmission stage|RGS-source-local (pre-transmission) processing stage|
|$\mathrm{Span}(a,b)$|hop span|contiguous hop-interval index, $a$ to $b$|

### Backbone / scheduling operations

|Symbol/Name|Short name|Formal name|
|---|---|---|
|$\mathrm{Gen}$|generation|half-RGS generation operator|
|$\mathrm{Join}/\mathrm{EntSwap}$|join/swap|anchor-joining entanglement-swap operator|
|$\mathrm{BSM}$|Bell measurement|outer-qubit Bell-state-measurement operator|
|$\mathrm{Z}\text{-meas} / \mathrm{XX}\text{-meas}$|inner measurements|inner-qubit Pauli-basis measurement operators|
|$\mathrm{PauliCorrect}$|correction|terminal Pauli-frame correction operator|
|$\mathrm{Idle}$|wait|idle/decoherence-accumulation operator|
|$\mathrm{Discard}$|discard|scheduling-layer resource-release operator|
|$\mathrm{Herald}$|herald|classical-heralding resolution operator|
|$\mathrm{Purify}\text{-}YY/ZX/XZ$|purification circuits|stabilizer-based 2-to-1 purification operators|

### Decoherence

|Symbol|Short name|Formal name|
|---|---|---|
|$T_{\text{idle}}(\Sigma)$|total idle time|cumulative idle-time functional of a schedule|
|$\Delta t$|wait interval|single-node idle-duration increment|

### Schedule object

| Symbol   | Short name       | Formal name                                                 |
| -------- | ---------------- | ----------------------------------------------------------- |
| $\Sigma$ | schedule         | purification-schedule object                                |
| $T$      | schedule DAG     | rooted directed-acyclic-graph structure underlying $\Sigma$ |
| $\phi$   | stage assignment | stage-assignment (labeling) function, $T\to\kappa$          |

### Resource budget $B$

|Symbol|Short name|Formal name|
|---|---|---|
|$B$|resource budget|resource-budget tuple|
|$n_{\text{pur}}$|copies per round|RGSS-level purification-round copy multiplicity|
|$E_{\max}$|max emitters|emitter-count feasibility bound|
|$M_{\max}$|max held states|concurrent-memory-occupancy feasibility bound|

### Cost functions

|Symbol|Short name|Formal name|
|---|---|---|
|$F(\Sigma;\mathcal N)$|fidelity|end-to-end Bell-state fidelity functional|
|$R(\Sigma;\mathcal N)$|rate|expected entanglement-distribution rate functional|
|$C(\Sigma)$|resource cost|resource-consumption functional|
|$L(\Sigma;\mathcal N)$|latency|schedule-makespan (latency) functional|
|$F_{\min}$|fidelity threshold|minimum-acceptable-fidelity constraint bound|