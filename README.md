# hrgs-purification-scheduler

Simulator and optimizer for purification scheduling on half-RGS-based
all-photonic quantum repeaters. See `docs/Validated Formal Model Def.md`
for the full formal spec (`Σ = (T, φ)`, backbone + scheduling layers,
cost functions) and `docs/WbW Plan.md` for the week-by-week project plan.

## Weeks 1-2: inner loop — **done**

**Files:**

| File | Role |
|---|---|
| models/error_vector.py | `ErrorVector(w,x,y,z)` — BSM composition rule, decoherence, `from_independent_z_flips` |
| models/stage.py | `RGSSStage`, `Span(a,b)`, `RGSS` singleton, `Span.join()` with legality checks |
| models/state.py | `State` — the full S=(e,s,t,t_gen,κ,r,h) tuple; immutable `with_*` mutators |
| models/network_config.py | `HopConfig` + `NetworkConfig` with `inner_error_per_hop`, `integrating_paper_config()` |
| models/resource_budget.py | `ResourceBudget(n_pur, e_max, m_max)` |
| operations/backbone.py | `gen`, `absa_bsm`, `join`, `idle`, `herald`, `pauli_correct` |
| operations/purification.py | `purify(circuit, s1, s2)`, `success_prob` — exact P_YY/ZX/XZ and Pur_YY/ZX/XZ formulas |
| schedule/node.py | All 7 frozen DAG node types |
| schedule/dag.py | `ScheduleDAG` — topo sort, stage-consistency validation (§4.1), `raw_chain`, `baseline_end_node_pumping`, `flexible_paper_schedule`, `single_hop_yy_purified` builders |
| schedule/evaluator.py | `Evaluator.evaluate()` — O(\|T\|) bottom-up pass → `EvaluationResult(F,R,C,L)` |
| schedule/visualize.py | `to_dot`/`save_dot`/`render` — Graphviz export of a `ScheduleDAG`, color/shape-coded by node type, optionally annotated with an `EvaluationResult` |
| cost_functions.py | `ObjectiveConfig`, `compare_schedules`, all §6.3 objective variants |
| timing.py | Closed-form canonical timing formulas (§2.6 table) — independent cross-check; `Evaluator.rate`/`.latency` (derived from actual DAG Herald/Purify structure) is the authoritative source |
| validation/fig5_fidelity_vs_noise.py | Reproduces [Integrating, Fig. 5]: fidelity vs. `e_d` for raw/baseline/flexible schedules |
| validation/fig6_rate_ratio.py | Reproduces [Integrating, Fig. 6]: rate ratios, derived from `Evaluator.evaluate(dag).rate` |

### Validation status against `docs/WbW Plan.md`'s Weeks 1-2 acceptance criteria

- **State object, operation catalog, bottom-up DAG evaluation (§7 inner loop):** done — see `models/`, `operations/`, `schedule/`. All models/operations manually audited term-by-term against both papers and `docs/Validated Formal Model Def.md`; two physics bugs found and fixed (spurious ZZ error at Gen time; wrong exponent variable — `arm_count` vs. `tree_depth` — in the inner-qubit error formula, [Bridging, eq. 10]).
- **Fig. 5 (fidelity vs. `e_d`) reproduction:** near-exact match. At `e_d=0.01`: raw/baseline/flexible = 0.8234/0.9168/0.9295 vs. paper's ~0.823/0.917/0.929.
- **Fig. 6 (rate ratio) reproduction:** only qualitative/order-of-magnitude match (~8.8x vs. paper's 45-65x for flexible/baseline). The DAG-structural mechanism (single deferred Herald vs. sequential heralded pumping rounds) is correctly modeled and *is* the authoritative source of `rate`/`latency` (not a standalone formula), but the paper doesn't state the numeric `tau_emit`/`tau_join`/`tau_pur_circ` values used for Fig. 6, so exact agreement isn't expected — do not force-fit magic numbers to hit 45-65x.
- **Canonical timing-table cross-check (§2.6):** `timing.py` implements the three closed-form formulas as an independent check; not yet wired into an automated test asserting agreement with `Evaluator`-derived latencies for the three canonical schedules.
- **Automated test suite:** implemented — `tests/` contains a 130-test `pytest` suite covering the models, operations, schedule layer, cost functions, and regression checks for the two validation scripts. Run it with `python3 -m pytest` (or `/usr/local/bin/python3.13 -m pytest` in this workspace).
- **Generated artifacts:** validation scripts now export DAG visualizations to `outputs/reproduction_figures/` as PNG files, using the schedule visualization helpers.

### Running the validation scripts

```bash
python3 validation/fig5_fidelity_vs_noise.py
python3 validation/fig6_rate_ratio.py
```

The scripts also populate `outputs/reproduction_figures/` with the corresponding DAG PNG exports.

### Visualizing a schedule

```bash
python3 -c "
from hrgs_scheduler.schedule import ScheduleDAG, render
from hrgs_scheduler.schedule.evaluator import Evaluator
from hrgs_scheduler.models.network_config import NetworkConfig

net = NetworkConfig.uniform(N=4, length=2.0, branching=(16,14,1), arm_count=18,
                             p_x_inner=0.001, p_z_inner=0.001, eta=1.0,
                             e_d=0.01, gamma=1e-6, c=2e8)
dag = ScheduleDAG.flexible_paper_schedule(N=4)
result = Evaluator(net).evaluate(dag)
render(dag, 'schedule.svg', result=result)  # requires Graphviz \`dot\` on PATH
"
```

**Next (Weeks 2-3):** outer-loop search over `Σ` — brute force on small `N` for
ground truth, then the DP-over-stages master algorithm, then a heuristic
fallback (greedy/beam search) for larger `N`.

