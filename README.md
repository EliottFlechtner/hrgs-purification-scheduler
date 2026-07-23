# hrgs-purification-scheduler

Simulator and optimizer for purification scheduling on half-RGS-based
all-photonic quantum repeaters.

## Repository layout

```
hrgs-purification-scheduler/
├── src/hrgs_scheduler/   ← Python package: the scheduler/optimizer
├── tests/                ← pytest suite (227 tests)
├── pyproject.toml        ← package config & tool settings
│
├── experiments/          ← research experiment scripts (run against the package)
├── outputs/              ← generated results from experiments (CSV, PNG, DOT)
├── docs/                 ← research notes, formal model spec, roadmaps
│
└── thesis/               ← LaTeX internship report (build with `cd thesis && make`)
```

See `docs/Validated Formal Model Def.md` for the full formal spec
(`Σ = (T, φ)`, backbone + scheduling layers, cost functions) and
`docs/WbW Plan.md` for the week-by-week project plan.

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
| schedule/serde.py | Stable JSON de/serializer for `ScheduleDAG` + `NetworkConfig` artifacts (`save_schedule`, `load_schedule`) |
| schedule/visualize.py | `to_dot`/`save_dot`/`render` — Graphviz export of a `ScheduleDAG`, color/shape-coded by node type, optionally annotated with an `EvaluationResult` |
| cost_functions.py | `ObjectiveConfig`, `compare_schedules`, all §6.3 objective variants |
| timing.py | Closed-form canonical timing formulas (§2.6 table) — independent cross-check; `Evaluator.rate`/`.latency` (derived from actual DAG Herald/Purify structure) is the authoritative source |
| experiments/fig5_fidelity_vs_noise.py | Reproduces [Integrating, Fig. 5]: fidelity vs. `e_d` for raw/baseline/flexible schedules |
| experiments/fig6_rate_ratio.py | Reproduces [Integrating, Fig. 6]: rate ratios, derived from `Evaluator.evaluate(dag).rate` |
| experiments/load_schedule.py | CLI to load saved schedule artifacts, verify metrics, print node counts, and export DOT/rendered images |

### Status against `docs/WbW Plan.md`'s Weeks 1-2 acceptance criteria

- **State object, operation catalog, bottom-up DAG evaluation (§7 inner loop):** done — see `models/`, `operations/`, `schedule/`. All models/operations manually audited term-by-term against both papers and `docs/Validated Formal Model Def.md`; two physics bugs found and fixed (spurious ZZ error at Gen time; wrong exponent variable — `arm_count` vs. `tree_depth` — in the inner-qubit error formula, [Bridging, eq. 10]).
- **Fig. 5 (fidelity vs. `e_d`) reproduction:** near-exact match. At `e_d=0.01`: raw/baseline/flexible = 0.8234/0.9168/0.9295 vs. paper's ~0.823/0.917/0.929.
- **Fig. 6 (rate ratio) reproduction:** only qualitative/order-of-magnitude match (~8.8x vs. paper's 45-65x for flexible/baseline). The DAG-structural mechanism (single deferred Herald vs. sequential heralded pumping rounds) is correctly modeled and *is* the authoritative source of `rate`/`latency` (not a standalone formula), but the paper doesn't state the numeric `tau_emit`/`tau_join`/`tau_pur_circ` values used for Fig. 6, so exact agreement isn't expected — do not force-fit magic numbers to hit 45-65x.
- **Canonical timing-table cross-check (§2.6):** `timing.py` implements the three closed-form formulas as an independent check; not yet wired into an automated test asserting agreement with `Evaluator`-derived latencies for the three canonical schedules.
- **Automated test suite:** implemented — `tests/` contains a 227-test `pytest` suite covering the models, operations, schedule layer, cost functions, outer-loop search (brute force + DP), serialization round-trips, and regression checks for the validation scripts. Run it with `python3 -m pytest` (or `/usr/local/bin/python3.13 -m pytest` in this workspace).
- **Generated artifacts:** experiment scripts now export DAG visualizations to `outputs/reproduction_figures/` as PNG files, using the schedule visualization helpers.

### Running the experiment scripts

```bash
python3 experiments/fig5_fidelity_vs_noise.py
python3 experiments/fig6_rate_ratio.py
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

## Weeks 2-3: outer loop — **done (brute force + DP)**

Search over the schedule space `Σ` to find the best schedule for a given
network, objective, and resource budget `e_max`. Two algorithms are
implemented, both returning the same `SearchResult` type so they can be
displayed/exported with the same tooling. See
`docs/Outer Loop Search Design.md` for the full design rationale.

**Files:**

| File | Role |
|---|---|
| search/brute_force.py | `brute_force_search()` — exhaustive enumeration of three fixed structural families (raw, end-node pumping heralded/optimistic, uniform link-level pumping). Exact ground truth on small `N`. |
| search/dp.py | `dp_search()` — memoized recursive search over span-partition structures (Bellman-style optimal-cost-to-go over the span partial order), with variable per-hop copy-count, arbitrary split points, and pumped (independently-purified) span pairs. Always a superset of `brute_force_search` on the same inputs. **Exact only for pumping-free schedules by default** — pumping's frontier is beam-limited for tractability, same tradeoff as `beam_search`, unless `exact_pumping=True` (uncapped, only tractable at very small `N`). See `search/dp.py`'s module docstring, "Exactness modes" section. |
| search/report.py | `print_table`, `to_csv`, `to_json`, `save_result`, `load_result`, `save_top` — display/export utilities plus structural save/load helpers for `SearchResult` artifacts |
| experiments/search_results.py | CLI script: run either search algorithm and print/export the results |
| experiments/load_schedule.py | CLI script: load a saved schedule artifact, verify it, and visualize/export it |

### Running the search CLI

```bash
# Brute force (default), paper config
python3 experiments/search_results.py

# DP-over-stages, small uniform network
python3 experiments/search_results.py --algorithm dp --N 4 --uniform --e_max 24 --top 10

# Export results
python3 experiments/search_results.py --algorithm dp --N 4 --uniform --e_max 24 \
    --csv outputs/search/dp_run.csv --json outputs/search/dp_run.json

# Save the top 3 schedules as full, loadable artifacts
python3 experiments/search_results.py --algorithm dp --N 4 --uniform --e_max 24 \
    --save-top 3 --save-dir outputs/schedules/dp_n4
```

Run `python3 experiments/search_results.py --help` for the full flag list
(both algorithms share `--N`, `--uniform`, `--e_d`, `--e_max`, `--f_min`,
`--objective`, `--top`, `--csv`, `--json`; `--algorithm dp` adds
`--max-link-copies`, `--max-enumerated-rounds`, `--no-bf-families`).

### Persisting, reloading, and visualizing found schedules

`--csv` / `--json` exports are summary tables only (rank/label/metrics).
To keep a schedule as a reusable object, save structural artifacts with
`--save-top` (or programmatically via `search.save_result`).

```bash
# 1) Save top-k structural artifacts from a search run
python3 experiments/search_results.py --algorithm dp --N 4 --uniform --e_max 24 \
    --save-top 5 --save-dir outputs/schedules/dp_n4

# 2) Inspect one saved artifact (summary)
python3 experiments/load_schedule.py \
    outputs/schedules/dp_n4/rank_001_*.json

# 3) Re-evaluate and verify stored metrics vs fresh evaluator output
python3 experiments/load_schedule.py \
    outputs/schedules/dp_n4/rank_001_*.json --verify --print-nodes

# 4) Export DOT and render SVG/PNG from the loaded schedule
python3 experiments/load_schedule.py \
    outputs/schedules/dp_n4/rank_001_*.json \
    --dot outputs/schedules/dp_n4/rank_001.dot

python3 experiments/load_schedule.py \
    outputs/schedules/dp_n4/rank_001_*.json \
    --render outputs/schedules/dp_n4/rank_001.svg --annotate
```

Programmatic API for the same workflow:

```python
from hrgs_scheduler.search import dp_search, save_result, load_result
from hrgs_scheduler.schedule import load_schedule, save_schedule

# save one result
result = dp_search(network, objective, e_max=24)[0]
save_result(result, "outputs/schedules/best.json", network=network)

# load it later
loaded_result, loaded_network = load_result("outputs/schedules/best.json")
```

### Cross-check

`dp_search(...)` always returns a superset of `brute_force_search(...)`
on identical inputs (by construction — DP merges in the brute-force
families), which is the "cross-check DP against brute force on small
cases" validation called for by the WbW plan. This is asserted directly
in `tests/test_dp.py::TestDpSearch::test_superset_of_brute_force_labels`.

**Next (Weeks 3+):** heuristic search (greedy/beam/simulated annealing)
for `N`/`e_max` beyond exact DP tractability.

