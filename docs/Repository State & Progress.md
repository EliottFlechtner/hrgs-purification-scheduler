# Repository State & Progress — Full Handoff Brief

**Purpose of this document:** a self-contained, detailed snapshot of what
has been built, verified, and found in `hrgs-purification-scheduler`, so
another AI (or the user's future self) can pick this project up with a
complete mental model, without needing to re-derive anything from the
papers or re-audit the physics from scratch. Written 19 July 2026, after
a full correctness recheck of every layer against the source papers and
this repo's own formal-model spec.

**Bottom line up front:** the physics core (error model, backbone
operations, purification, decoherence) is verified correct term-by-term
against both source papers and reproduces the paper's own published
numbers to within floating-point precision for fidelity. The outer-loop
optimizer (three search tiers: brute force, DP, beam-search
heuristic) is implemented, cross-validated for internal consistency, and
has already produced a genuine, reproducible result: **a discovered
schedule beats the paper's own hand-picked Fig. 4 schedule at the same
resource cost.** The one known, well-understood, and *documented* gap is
that the rate/latency model cannot reproduce the paper's exact Fig. 6
numeric ratio (45–65×) because the paper never publishes the timing
constants needed to do so — this is a data-availability limitation, not
a bug, and is explained in detail below and in its own doc.

---

## 1. Source material

- **Paper 1 ("Bridging")**: establishes the half-RGS (HRGS) repeater
  building block: generation via emitter pushout, the `[w,x,y,z]` Bell-
  diagonal error-vector formalism, the bilinear BSM composition rule, Z
  side-effect propagation with constant 2-bit/ABSA/trial classical cost,
  and the inner-qubit error formula (their eq. 10).
- **Paper 2 ("Integrating", arXiv:2504.18121, Benchasattabuse, Hajdušek,
  Van Meter)**: shows this HRGS building block is compatible with
  arbitrary purification scheduling (YY/ZX/XZ circuits, insertable at
  RGSS/link/end-node granularity) combined with *optimistic* (blind,
  non-heralded-until-the-end) purification. Publishes one fixed,
  hand-chosen schedule (Fig. 4) and explicitly states schedule
  optimization is future work — **this is the exact gap this project
  fills.** HTML source: `arxiv.org/html/2504.18121v1` (verify equations
  against this directly if in doubt — transcription errors happen).
  Their own code release
  (`Naphann/repeater-graph-state-protocol-based-on-half-RGS`) implements
  only the stabilizer/fidelity simulation, not the rate/timing model.
- **This repo's own formal model spec**:
  [docs/Validated Formal Model Def.md](Validated%20Formal%20Model%20Def.md) —
  the authoritative, validated translation of both papers into a single
  schedule-as-DAG formalism `Σ = (T, φ)`. Every source-code module below
  is checked against this document's section numbers.
- **Project plan**: [docs/WbW Plan.md](WbW%20Plan.md) (week-by-week) and
  [docs/Research Idea Description.md](Research%20Idea%20Description.md)
  (motivation/framing). Weeks 1-2 (inner loop) and Weeks 2-3 (outer loop
  search) are done; the Weeks 3-4 "headline experiment" has been run at
  least once with concrete results (§6 below).

## 2. The formal model, summarized

A **schedule** `Σ = (T, φ)` is a rooted DAG: leaves are `Gen` nodes
(half-RGS generation), internal nodes are backbone operations
(`Join`/`EntSwap`, `AbsaBsm`, `Idle`) or scheduling-layer operations
(`Purify`, `Herald`), and the root is a single `PauliCorrect` node at
`κ = Span(0, N)`. Every node produces a `State = (e, s, t, t_gen, κ, r,
h)`: a Bell-diagonal error vector `e = [w,x,y,z]`, an `𝔽₂` side-effect
parity `s`, timestamps, a stage/span label `κ`, purification-round count
`r`, and heralding status `h`. Evaluating `Σ` against a `NetworkConfig`
is a single bottom-up (`O(|T|)`) pass computing four cost functions at
the root:

- **Fidelity** `F(Σ) = w_root` (the `II`-component of the root error
  vector).
- **Rate** `R(Σ) = P[success] / E[wall-clock time]` (renewal-theory
  restart-on-failure).
- **Resource cost** `C(Σ) = |Gen nodes|`.
- **Latency** `L(Σ) = makespan of T`.

The optimization problem is `Σ* = argmax R(Σ)` subject to `F(Σ) ≥
F_min`, over all `Σ` legal w.r.t. `𝒩` and feasible w.r.t. budget `B`.
"Optimistic" vs. "heralded" purification is **not** a separate operation
— it's purely a function of where `Herald` nodes sit in the DAG relative
to `Purify` nodes (a branch is optimistic wherever purifications chain
without an intervening cross-node `Herald`). This is the single most
important structural idea in the whole model and is why the DAG
representation (rather than a fixed formula) is the right abstraction.

## 3. Code inventory, layer by layer, with verification status

### 3.1 `models/` — physical/mathematical primitives

| File | Contents | Verification status |
|---|---|---|
| `error_vector.py` | `ErrorVector(w,x,y,z)`: `bsm_compose` (bilinear composition rule), `decohere` (exponential relaxation to maximally-mixed), `from_independent_z_flips` | **Verified exact** against §2.4/§2.6 formulas. `bsm_compose` matches [Bridging eq. 5]/[Integrating eq. 14] term-for-term. |
| `stage.py` | `RGSSStage`, `Span(a,b)` with `.join()` legality (adjacency required), `.width` | **Verified**. Enforces `0 ≤ a < b ≤ N` and adjacency on join, matching §3.1/§4.1. |
| `state.py` | `State` tuple, `HeraldStatus` enum | **Verified** — direct 1:1 mapping to the formal `S = (e,s,t,t_gen,κ,r,h)` tuple. |
| `network_config.py` | `HopConfig` (per-hop physical params), `NetworkConfig` (full `𝒩` tuple), `integrating_paper_config()` (exact paper config: N=10, ℓ=2km, branching=(16,14,1), arm_count=18) | **Verified, with one fixed bug**: `inner_error_per_hop`'s eq.(10) exponent `(m-1)` must use `arm_count` (paper's `m` = number of arms), **not** `tree_depth` (`len(branching)`) — these are different numbers in the paper's own config (arm_count=18 vs. branching-vector length=3). This was found and fixed; confirmed via direct reference to the Bridging paper text ("m denotes the number of arms"). |
| `resource_budget.py` | `ResourceBudget(n_pur, e_max, m_max)` | Model exists and matches §5's tuple definition, but **`m_max` (max concurrent open branches) is not enforced anywhere** — see §5 (Known Gaps) below. |

### 3.2 `operations/` — backbone + purification physics

| File | Contents | Verification status |
|---|---|---|
| `backbone.py` | `gen`, `join`, `absa_bsm`, `idle`, `herald`, `pauli_correct` | **Verified, with two fixed bugs** (see below). Every function's docstring cites the exact paper equation/section it implements — read these docstrings first, they are detailed and accurate. |
| `purification.py` | `purify()` for `YY`/`ZX`/`XZ` circuits; `success_prob()` | **Verified, with one fixed bug** (`_output_vector_zx`/`_output_vector_xz` formula bodies were swapped — found via a unit test asserting output vectors sum to 1; fixed by swapping them back). All three circuits' success-probability and post-purification-vector formulas now match [Integrating eqs. 8–13] exactly. |

**Bugs found and fixed in this layer (all confirmed via direct equation
comparison + regression-tested against Fig. 5/6 validation scripts —
numbers were unaffected or improved, never regressed):**

1. `gen()` was calling `from_independent_z_flips(p_in, p_in)`, spuriously
   creating a nonzero `ZZ` (`y`) error component at generation time.
   Inner-qubit errors only ever contribute independent `ZI`/`IZ` (never
   `ZZ`), per [Bridging §VII-D]. Fixed to
   `from_independent_z_flips(p_in, 0.0)`.
2. `HopConfig.inner_error_per_hop`'s `m` exponent used `tree_depth`
   instead of `arm_count` (see table above).
3. `_output_vector_zx`/`_output_vector_xz` in `purification.py` had
   swapped formula bodies (self-inconsistent: outputs didn't sum to 1).

**Physically important design decisions worth knowing (not bugs, but
non-obvious interpretive choices):**

- `absa_bsm()`'s outer-photon depolarizing noise is modeled as a *full*
  single-qubit depolarizing channel (`[1-e_d, e_d/3, e_d/3, e_d/3]`)
  mapped via graph-state Pauli-equivalence to the two-qubit error-vector
  formalism, composed via the *same* bilinear `bsm_compose` rule used for
  joining different states (sequential composition of two `𝔽₂×𝔽₂`
  channels on the same state uses an identical closed form to composing
  channels across two states). This was a deliberate physics
  interpretation, not directly copy-pasted from a single equation in the
  paper — flagged here in case a future re-derivation disagrees.
- Since `absa_bsm` composes the depolarizing channel via `bsm_compose`
  (not `from_independent_z_flips`), it *does* introduce `ZZ` error from
  the outer photon (correctly — the inner-qubit-only exclusion is
  specific to inner-qubit measurements, not outer photons).

### 3.3 `schedule/` — the DAG representation and evaluator

| File | Contents | Verification status |
|---|---|---|
| `node.py` | 7 frozen dataclasses: `GenNode`, `AbsaBsmNode`, `JoinNode`, `PurifyNode`, `IdleNode`, `HeraldNode`, `PauliCorrectNode` | Matches §2.5/§3.2/§3.3's operation catalog 1:1. |
| `dag.py` | `ScheduleDAG`: topological sort, `validate()` (root check, reachability, **and** full structural stage-consistency checking — `_check_stage_consistency` walks the DAG bottom-up and cross-checks every node's *declared* output stage against what's structurally legal per §4.1), plus 5 canonical builders (`raw_chain`, `baseline_end_node_pumping`, `generic_end_node_pumping`, `link_level_pumped_chain`, `flexible_paper_schedule`, `single_hop_yy_purified`) | **Verified.** `flexible_paper_schedule(N=10)` is a hand-built exact reproduction of [Integrating, Fig. 4]'s structure (Pair A: 10 link-level YY-purified hops joined; Pair B: two N/2-hop segments, each from 2 raw sub-chains YY-purified then joined; Pair C: 1 raw N-hop chain; combined via `ZX`-purify(A,B) then `YY`-purify(result,C)). A deliberately-broken non-adjacent-span `Join` DAG is correctly rejected by `validate()` — confirms the stage-consistency check is load-bearing, not decorative. |
| `evaluator.py` | `Evaluator.evaluate(dag) -> EvaluationResult(fidelity, rate, resource_cost, latency, success_prob, node_states)` | **Verified for fidelity; latency/rate has a known, documented, unavoidable limitation** — see §4 below. |
| `serde.py` | JSON de/serialization for `ScheduleDAG` + `NetworkConfig` (`save_schedule`/`load_schedule`) | Round-trip tested. |
| `visualize.py` | `to_dot`/`save_dot`/`render` — pure-stdlib Graphviz DOT export, color/shape-coded per node type, optional `EvaluationResult` annotation; `render()` shells out to the `dot` CLI | Verified working end-to-end (rendered and visually inspected multiple DAGs this session, including the headline-experiment comparison in `outputs/headline_experiment_n10/`). |

### 3.4 `cost_functions.py` — objective layer

`ObjectiveConfig(primary, maximise, f_min, r_min, e_max)` with
`.is_feasible()`/`.score()` (returns `-inf` for infeasible — binary, no
partial credit) and presets
(`maximize_rate_with_fidelity_floor`, `maximize_fidelity_with_rate_floor`,
`minimize_cost_with_constraints`). **Verified** — direct implementation
of §6.1/§6.3's objective-substitution variants.

**Known gotcha for anyone querying results**: because infeasibility maps
to exactly `-inf` and Python's sort is stable, if *nothing* is feasible
at a given `e_max`/budget, the *first-generated* candidate (often the
unpurified "raw" one) will appear to "win" — always check
`len([r for r in results if r.score > float('-inf')])` before trusting
the top row of any results table.

### 3.5 `timing.py` — standalone closed-form cross-check (NOT authoritative)

Implements [Integrating §IV-B]'s three closed-form timing formulas
(raw/baseline/optimistic generation-time and memory-time expressions) as
an independent sanity check. **Superseded as the source of truth**:
`Evaluator.evaluate(dag).rate`/`.latency`, derived directly from the
DAG's own `Herald`/`Purify` node structure, is authoritative. This
module's docstring says so explicitly. See §4 for why this distinction
matters and why Fig. 6 still can't be reproduced exactly even with the
DAG-derived approach.

### 3.6 `search/` — the outer-loop optimizer (three tiers)

| Tier | File | Status |
|---|---|---|
| 1. Brute force | `brute_force.py` | Exhaustive enumeration over 3 fixed structural families (raw, end-node pumping heralded/optimistic, uniform link-level pumping) plus the paper's own `flexible_paper` schedule as a labeled candidate. Exact, tractable only for small `N`/`e_max`. |
| 2. DP (`dp_search`) | `dp.py` | `_SpanPartitionSearch.frontier(a,b)`: memoized recursive search over span-partition structures — tries every split point, keeps the full Pareto frontier (cost, fidelity, success_prob) per span, using multi-objective Pareto pruning (no single scalar composes correctly across a join, since joins multiply success probability and sum cost). Provably a superset of brute force. Combinatorially explodes past `N≈7` (empirically ~1,200+ candidates at width-7 spans for the paper's N=10 config). **Exact only for pumping-free schedules by default** — its "pumping" move (two independently-purified copies of the same span) is beam-limited for tractability, same tradeoff as beam search, unless `exact_pumping=True` (uncapped, only tractable at very small `N`; see `dp.py`'s "Exactness modes" docstring section). |
| 3. Beam search (heuristic) | `heuristic.py` (added this session) | Reuses the same `_SpanPartitionSearch` machinery as `dp_search` (100% shared node-construction/physics code — no separate "heuristic model" that could diverge), but caps each span's frontier at a fixed `beam_width` via `_beam_select` instead of keeping every non-dominated candidate. Makes search tractable at the paper's actual N=10 config (~10-14s vs. DP's intractability). Since `dp_search`'s own pumping is now also beam-limited by default, `dp_search` is no longer a guaranteed upper bound on `beam_search` once pumping is involved — use `dp_search(..., exact_pumping=True)` at small `N` for that comparison instead. |

**All three tiers build real `ScheduleDAG` nodes during search** (a
shared node pool + `_extract_reachable` DFS filter per finalist) rather
than an abstract "recipe" representation — this by construction
eliminates any risk of search-vs-evaluation physics divergence, at the
cost of some pool bookkeeping overhead.

**`_beam_select` had one real, found-and-fixed bug**: an earlier
single-ranking version discarded every purified single-hop candidate
(single-hop fidelity trivially exceeds any reasonable floor regardless
of purification, so ranking by "meets floor, then success_prob" always
preferred cheap/unpurified candidates locally) — which meant *zero*
beam-originated feasible candidates existed once N=10 hops were
composed and the composite fidelity actually needed purification. Fixed
by a two-way split: half the beam kept by raw fidelity (preserves
purification options for later wide-span composition), half by
efficiency/success_prob (preserves cheap options for spans that don't
need it). Regression-guarded by
`tests/test_heuristic.py::test_finds_own_span_partition_candidates_at_n10`.

`search/report.py`: `print_table`/`to_csv`/`to_json`/`save_result`/
`load_result`/`save_top` for displaying and exporting `SearchResult`
lists.

`validation/search_results.py`: CLI entry point,
`--algorithm {brute_force,dp,beam}`, with algorithm-specific flags
(`--beam-width`, `--max-link-copies`, `--max-enumerated-rounds`,
`--no-bf-families`).

## 4. Known limitation: Fig. 6 (rate ratio) cannot be exactly reproduced

**This is fully documented in its own file:**
[docs/Fig6 Rate Ratio Non-Reproducibility.md](Fig6%20Rate%20Ratio%20Non-Reproducibility.md)
— read that file for the complete derivation. Summary:

- Fig. 5 (fidelity vs. `e_d`) reproduces **near-exactly**: at `e_d=0.01`,
  raw/baseline/flexible = `0.8234`/`0.9168`/`0.9295` vs. the paper's
  `~0.823`/`~0.917`/`~0.929`.
- Fig. 6 (rate ratio) reproduces only the **correct mechanism and
  order of magnitude** (~8.8× for flexible/baseline vs. the paper's
  stated 45–65×), because:
  1. In the current DAG-evaluator model, only `HeraldNode`s contribute
     nonzero latency (`propagation_time × L_total/c`); `Gen`/`Join`/
     `AbsaBsm`/`Purify` all contribute zero added time. So the computed
     ratio is *exactly* the structural Herald-count ratio (9:1 for
     `n_pur=5` baseline: 4 sequential round-trip heralds + 1 final vs.
     flexible's single final herald).
  2. Wiring in real `τ_half`/`τ_join`/`τ_pur_circ` values (via
     `timing.py`'s formulas) does not fix this either — sweeping the
     absolute time scale `τ_emit` swings the ratio from `8.0` down to
     `0.59` (crossing below 1!), because the paper **never publishes**
     numeric values for these constants, and its own code release
     doesn't implement the rate/timing model either.
- **Conclusion**: this is a data-availability limitation of the source
  paper, not a bug in this codebase. Do not attempt to force-fit magic
  numbers to hit 45–65× — there is no principled way to recover the
  paper's specific timing constants from published information.

## 5. Known gaps (not bugs — explicitly flagged, not silently skipped)

- **`M_max` (max concurrent open branches, §5) is not enforced
  anywhere.** `cost_functions.satisfies_budget` only checks `E_max`
  (Gen-node count). `ResourceBudget` exists as a model but isn't wired
  into `ScheduleDAG`/`Evaluator`. The current DAG representation is
  static with no explicit time-slice/resource-holding semantics, so
  implementing this would require real design work (would need to model
  which branches are simultaneously "open" at any wall-clock instant),
  not a quick fix.
- **DP's recursive search doesn't explore purifying `n` independent
  copies of an already-partially-purified sub-span** (only `n`
  independent *raw* hops or `n` independent full raw chains are
  explored recursively). `dp_search()`/`beam_search()` sidestep this by
  merging in `brute_force_search()`'s existing end-node-pumping families
  as-is (`include_brute_force_families=True` default) rather than
  silently missing this class of schedule.
- **Adaptive scheduling** (branching on intermediate measurement
  outcomes) is explicitly out of scope for this model (§3, §8) — would
  require an MDP formulation, deferred to future work by design.
- `timing.py`'s `τ_cycle = τ_RGS + t_mem` renewal-theory convention is
  this project's own reasonable-but-*unverified* interpretation — no
  explicit closed-form "rate" equation combining the two appears
  verbatim in the paper text.

## 6. The headline experiment (Weeks 3-4 of the WbW plan) — result so far

Per the WbW plan: run the optimizer at the paper's exact `N=10` config
and do a **resource-normalized comparison** (fix `C(Σ)` equal to the
paper's own resource cost) against their Fig. 4 schedule. This has been
run once, with results and full artifacts saved in
[outputs/headline_experiment_n10/](../outputs/headline_experiment_n10/)
(see its own `README.md` for the full write-up, DOT/PNG diagrams of both
schedules, and a `results.csv`).

**Headline numbers** (`N=10`, `e_d=0.01`, `f_min=0.9` fidelity floor):

| Schedule | Cost `C(Σ)` | Fidelity | Success prob | Rate |
|---|---|---|---|---|
| Paper's `flexible_paper` (Fig. 4) | 100 | 0.9295 | 0.4056 | 4055.92 |
| Optimizer, same cost (100) | 100 | 0.9168 | 0.4158 | **4158.14** (+2.5%) |
| Optimizer, budget ≤ 100 (chooses 50) | 50 | 0.9047 | 0.6713 | **6713.18** (+65%) |

The optimizer's schedule structurally allocates purification
non-uniformly (per-hop, based on where composing many hops erodes
fidelity fastest) instead of applying one fixed circuit sequence
uniformly everywhere — this is *why* it wins, and is a direct,
reproducible demonstration of the gap the WbW plan set out to fill
("the paper explicitly names its own schedule as unoptimized ... this
is the gap this project targets," §4.2 of the formal model doc).

**This result has not yet been swept across the full `e_d ∈ [0, 0.01]`
range** (only run at the single paper-headline point `e_d=0.01`) — that
sweep, plus characterizing beam-width/quality tradeoffs, is the natural
next step for turning this into a full report-ready result set.

## 7. Test suite

`tests/` — **233 tests, all passing** (`python3 -m pytest -q` from repo
root with the venv activated; on this machine use
`PYTHONPATH=src` or `pip install -e .` if the package isn't found — the
`.venv` may not have it installed in editable mode, always check with
`pip show hrgs_scheduler` first). Files:

`test_error_vector.py`, `test_stage.py`, `test_state.py`,
`test_network_config.py`, `test_resource_budget.py`, `test_backbone.py`,
`test_purification.py`, `test_dag.py`, `test_evaluator.py`,
`test_serde.py`, `test_cost_functions.py`, `test_brute_force.py`,
`test_dp.py`, `test_heuristic.py`, `test_validation_regression.py`
(regression-checks the Fig. 5/6 validation scripts' output values).

A real bug (`purification.py`'s swapped ZX/XZ output formulas, §3.2 above)
was originally *found* by writing a unit test asserting error vectors
sum to 1 — a good template for future correctness auditing of any new
physics code added here.

## 8. File map (quick reference)

```
src/hrgs_scheduler/
  cost_functions.py        objective/score layer (§6)
  timing.py                 standalone closed-form timing cross-check (NOT authoritative)
  models/
    error_vector.py         ErrorVector: bsm_compose, decohere
    stage.py                 RGSSStage, Span(a,b)
    state.py                  State tuple, HeraldStatus
    network_config.py        HopConfig, NetworkConfig, integrating_paper_config()
    resource_budget.py       ResourceBudget(n_pur, e_max, m_max)  [m_max unenforced]
  operations/
    backbone.py               gen, join, absa_bsm, idle, herald, pauli_correct
    purification.py           purify(YY/ZX/XZ), success_prob
  schedule/
    node.py                    7 DAG node dataclasses
    dag.py                      ScheduleDAG + 6 canonical builders
    evaluator.py                Evaluator -> EvaluationResult(F,R,C,L,success_prob)
    serde.py                     JSON save/load
    visualize.py                 to_dot / save_dot / render (Graphviz)
  search/
    brute_force.py               Tier 1: exhaustive fixed families
    dp.py                         Tier 2: exact span-partition DP (+ shared beam-capping hooks)
    heuristic.py                  Tier 3: beam_search (reuses dp.py's machinery)
    report.py                     print_table/to_csv/to_json/save_result/load_result

validation/
  fig5_fidelity_vs_noise.py       reproduces Integrating Fig. 5 (near-exact)
  fig6_rate_ratio.py               reproduces Integrating Fig. 6 (order-of-magnitude only)
  search_results.py               CLI: --algorithm {brute_force,dp,beam}
  load_schedule.py                CLI to load/inspect saved schedule artifacts

outputs/
  reproduction_figures/            Fig 5/6 validation script artifacts (DOT/PNG)
  headline_experiment_n10/         Weeks 3-4 headline experiment: results.csv + 4 DAGs (paper baseline vs. 3 optimizer variants) + README.md write-up

tests/                              233 pytest tests, all passing

docs/
  Validated Formal Model Def.md    authoritative formal spec (Σ = (T,φ), §1-9)
  Research Idea Description.md     motivation/framing
  WbW Plan.md                       week-by-week plan
  Outer Loop Search Design.md       design rationale for the 3 search tiers
  Fig6 Rate Ratio Non-Reproducibility.md   full derivation of the §4 limitation above
  Glossary.md                       term reference
  Internship Progression Tracker.md
  Repository State & Progress.md    ← this file
```

## 9. Suggested next steps (not started, in rough priority order)

1. **Sweep the headline experiment across `e_d ∈ [0, 0.01]`** (not just
   the single `e_d=0.01` point) and characterize where the optimizer's
   advantage grows/shrinks — this is the natural next deliverable for a
   report figure.
2. **Sweep `beam_width`** to characterize the quality/runtime tradeoff
   of Tier 3 — itself a citable "generalizable rule of thumb" data point.
3. Decide whether to formally implement `M_max` enforcement (§5 gap) —
   requires real design work on concurrent-branch semantics, not a quick
   patch; flag to the user before attempting.
4. Consider whether DP/beam search should be extended to explore
   purifying copies of partially-purified sub-spans (currently only
   raw-hop or full-raw-chain copies are searched recursively; end-node
   pumping families are merged in as a stopgap instead, §5).
5. Optionally wire an automated test asserting `timing.py`'s closed-form
   formulas agree with `Evaluator`-derived latencies for the three
   canonical schedule types (README.md notes this cross-check exists but
   isn't yet automated).
