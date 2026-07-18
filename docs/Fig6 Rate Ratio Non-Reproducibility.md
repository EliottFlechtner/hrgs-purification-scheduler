# Why Fig. 6 (rate ratio) cannot be exactly reproduced

**Status:** confirmed limitation, not a bug. Fig. 5 (fidelity) reproduces
near-exactly; Fig. 6 (rate ratio) only reproduces the correct *mechanism*
and *order of magnitude*. This document records why, so the discrepancy
isn't mistaken for a defect in `validation/fig6_rate_ratio.py`,
`schedule/evaluator.py`, or the timing model in a future session.

## 1. What we do reproduce exactly

[Integrating, §VI] states the flexible/optimistic scheme "outperforms the
baseline strategy by a factor ranging from approximately 45 to 65,
depending on the noise level" and Fig. 6's caption states the raw/flexible
ratio is "scaled by a factor of 10 for easier comparison" — i.e. the true
raw/flexible ratio is ~5.0–8.6×. Screenshotting the actual figure
(`x5.png` / `rate-plot.png` at `arxiv.org/html/2504.18121v1`) confirms:

| Curve | Paper's range (e_d: 0 → 0.01) |
|---|---|
| flexible / baseline | ~46.5× → 65× |
| raw / flexible (true scale) | ~5.0× → 8.6× |

Our `validation/fig6_rate_ratio.py` reproduces the **structural mechanism**
correctly: baseline's entanglement-pumping purification is *heralded*
(sequential, two-way, `2·L_total/c` per round for each of the `n_pur - 1`
pumping rounds), while the flexible/optimistic scheme defers *all*
heralding to a single one-way `L_total/c` confirmation at the very end
— exactly [Integrating, §III-B]'s distinction, encoded structurally via
`HeraldNode` placement relative to `PurifyNode`s in the schedule DAG
(see [`Validated Formal Model Def.md`](Validated%20Formal%20Model%20Def.md#33-herald-and-optimism)
§3.3). Fig. 5's fidelity numbers, which depend on the *same* underlying
error-vector/purification model, match the paper to within `±0.0005`
absolute fidelity — confirming the physics (BSM composition, purification
success probabilities, decoherence) is correct. Fig. 6's ratio is wrong
in *magnitude* only, not in *direction* or *mechanism*.

## 2. Root cause: the model currently only assigns nonzero duration to `HeraldNode`s

Tracing `Evaluator.evaluate()`'s bottom-up pass
([`schedule/evaluator.py`](../src/hrgs_scheduler/schedule/evaluator.py)):

| Node type | Contribution to `current_time` |
|---|---|
| `GenNode` | fixed `gen_time` (defaults to `0.0`, identical for every leaf — **not** scaled by `τ_half` or `n_pur`) |
| `AbsaBsmNode`, `JoinNode` | `max(t_left, t_right)` — **zero added latency** |
| `PurifyNode` | `max(t_primary, t_ancilla)` — **zero added latency** (no `τ_pur_circ` term) |
| `IdleNode` | advances to `until` (decoheres `e`, but is unused by any of the three canonical builders) |
| `HeraldNode` | **the only node that adds physical time**: `propagation_time × L_total/c` |
| `PauliCorrectNode` | inherits child's time |

Consequently, `EvaluationResult.latency` for *any* of the three canonical
schedules (`raw_chain`, `baseline_end_node_pumping`,
`flexible_paper_schedule`) is **entirely determined by how many
`HeraldNode`s are on the path to the root, and their `propagation_time`
multipliers** — not by [Integrating]'s actual eqs. (1)–(6), which also
include `n_pur·τ_half` (half-RGS generation time, scaled by the number of
purification copies) and `τ_pur_circ`/`τ_join` (local operation times).

For `baseline_end_node_pumping(N, n_pur=5)`: 4 sequential `PurifyNode`s,
each followed by an intermediate round-trip `HeraldNode`
(`propagation_time=2.0`), plus one final one-way `HeraldNode`
(`propagation_time=1.0`) → total Herald weight = `4×2 + 1 = 9`.
For `flexible_paper_schedule(N)`: only the single final one-way
`HeraldNode` → total Herald weight = `1`.

**This `9:1` structural ratio is exactly what `fig6_rate_ratio.py` measures**
(confirmed numerically: `flex_over_base` ranges `8.78×`–`9.00×` across
`e_d ∈ [0, 0.01]`, essentially flat since it's dominated by a fixed
node-count ratio, only lightly perturbed by the noise-dependent
`success_prob` term in `R = success_prob / latency`).

## 3. Why wiring in real `τ_half`/`τ_join`/`τ_pur_circ` values would not by itself fix this

`timing.py` independently implements [Integrating]'s closed-form eqs.
(1)–(6) and was used to sanity-check the order of magnitude. Sweeping its
`tau_emit` parameter (which sets `τ_half`, `τ_join`, `τ_pur_circ` via
`TimingParameters.default`) against the paper's own
`N=10, ℓ=2 km, c=2×10⁵ km/s` config (`L_total/c = 1×10⁻⁴`, same time
units) gives:

| `τ_emit` | `τ_half` | ratio (opt/base, `P_success=1`) |
|---|---|---|
| `0` | `0` | `8.00` |
| `1e-8` | `7.81e-8` | `7.94` |
| `1e-7` | `7.81e-7` | `7.43` |
| `1e-6` | `7.81e-6` | `4.61` |
| `1e-5` | `7.81e-5` | `1.37` |
| `1e-4` | `7.81e-4` | `0.67` |
| `1e-3` | `7.81e-3` | `0.59` |

The ratio swings by more than an order of magnitude — even **crossing
below 1** (i.e. the "optimistic" scheme becoming *slower* than baseline)
— purely as a function of the never-stated absolute time scale `τ_emit`
relative to `L_total/c`. This is because the optimistic scheme's
generation-time term (`n_pur·τ_half`, appearing in **both** eq. (5)'s
`τ_RGS` and eq. (6)'s `t_mem`) grows faster with `τ_emit` than baseline's
does, since baseline's generation rate is unaffected by purification
(`τ_RGS` stays equal to the raw case, eq. (1)/(3)) and only its *memory*
term picks up the `n_pur·τ_half` cost once.

**[Integrating] never states numeric values for `τ_emit` (photon
emission/gate-cycle time), `τ_join`, or `τ_pur_circ`** — only the
*network* configuration (`N=10`, `ℓ=2 km`, branching `(16,14,1)`, arm
count `18`, `e_d ∈ [0, 0.01]`) is given numerically in §V-A. The paper's
own public repository
([`Naphann/repeater-graph-state-protocol-based-on-half-RGS`](https://github.com/Naphann/repeater-graph-state-protocol-based-on-half-RGS))
implements only the stabilizer/fidelity simulation (confirmed by manual
inspection in an earlier session — see repo memory), not the rate/timing
model used to generate Fig. 6's y-axis. There is also no explicit
closed-form "rate" equation given in the paper text combining `τ_RGS` and
`t_mem` into a single renewal-theory cycle time — `timing.py`'s
`τ_cycle = τ_RGS + t_mem` convention is our own reasonable-but-unverified
interpretation, not something drawn verbatim from the paper.

## 4. Conclusion

Reproducing Fig. 6's exact `45×`–`65×` number requires the authors'
specific, unpublished `τ_emit`/`τ_join`/`τ_pur_circ` constants (or
equivalently, their exact renewal-theory cycle-time formula), neither of
which is recoverable from the paper text or its associated code release.
**Do not force-fit magic timing constants to hit `45–65×`** — this would
create a false sense of validation. The correct scope for this project's
Fig. 6 validation is:

- ✅ Confirm the *mechanism* (Herald placement determines
  optimistic-vs-heralded rate advantage) — done, structurally correct.
- ✅ Confirm the *direction* (flexible/optimistic always beats baseline,
  baseline always beats raw once resource-normalized) — done.
- ✅ Confirm *order of magnitude* is plausible (single-digit-to-low-tens ×,
  not e.g. 1000× or 1.001×) — done (~9×, within the same order as the
  paper's ~45–65×).
- ❌ Exact numeric agreement — not achievable without unpublished
  constants; not a goal for this project's validation, and no further
  time should be spent trying to force it.

If wiring real generation-time modeling into `gen_time`/`Join`/`Purify`
node latencies becomes useful for later parts of the project (e.g. the
outer-loop search's latency cost function `L(Σ)`), that is a legitimate
and separate piece of future work — see the README's "Next (Weeks 2-3)"
note — but it should be pursued for its own sake (a more physically
complete latency model), not as an attempt to hit this specific
unreproducible number.
