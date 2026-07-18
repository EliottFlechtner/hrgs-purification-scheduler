# CLI Command Reference

A practical list of commands for running searches, saving/loading schedule artifacts,
validating figures, and exporting visualizations.

All commands assume you are in the repository root:

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
```

## 1) Environment and sanity checks

Use the interpreter that is known to work for this repo:

```bash
/usr/local/bin/python3.13 --version
```

Check test discovery only (fast):

```bash
/usr/local/bin/python3.13 -m pytest --collect-only -q
```

Run full tests:

```bash
/usr/local/bin/python3.13 -m pytest -q
```

Run only DP + serializer tests:

```bash
/usr/local/bin/python3.13 -m pytest tests/test_dp.py tests/test_serde.py -q
```

## 2) Validation scripts (paper reproductions)

Fig. 5 fidelity-vs-noise:

```bash
python3 validation/fig5_fidelity_vs_noise.py
```

Fig. 6 rate-ratio:

```bash
python3 validation/fig6_rate_ratio.py
```

## 3) Search CLI basics

Default run (brute force, paper config):

```bash
python3 validation/search_results.py
```

Brute force with custom budget/fidelity floor:

```bash
python3 validation/search_results.py \
  --algorithm brute_force \
  --e_max 30 \
  --f_min 0.92
```

DP run on small uniform network:

```bash
python3 validation/search_results.py \
  --algorithm dp \
  --N 4 \
  --uniform \
  --e_max 24 \
  --top 20
```

Show only feasible rows:

```bash
python3 validation/search_results.py --top 20 --no-infeasible
```

See all CLI flags:

```bash
python3 validation/search_results.py --help
```

## 4) Exporting summary tables

Export CSV and JSON summary metrics (rank/label/F/R/C/L/P/score):

```bash
python3 validation/search_results.py \
  --algorithm dp \
  --N 4 \
  --uniform \
  --e_max 24 \
  --csv outputs/search/dp_run.csv \
  --json outputs/search/dp_run.json
```

Important: these summary exports are not full DAG objects.
Use section 5 to save loadable schedule artifacts.

## 5) Saving loadable schedule artifacts

Save top-k results as full structural artifacts (DAG + network + eval scalars):

```bash
python3 validation/search_results.py \
  --algorithm dp \
  --N 4 \
  --uniform \
  --e_max 24 \
  --save-top 5 \
  --save-dir outputs/schedules/dp_n4
```

Example output files:

```text
outputs/schedules/dp_n4/rank_001_<label>.json
outputs/schedules/dp_n4/rank_002_<label>.json
...
```

## 6) Loading, verifying, and inspecting saved artifacts

Print summary of one saved schedule artifact:

```bash
python3 validation/load_schedule.py outputs/schedules/dp_n4/rank_001_*.json
```

Re-evaluate and verify stored metrics vs fresh evaluator output:

```bash
python3 validation/load_schedule.py \
  outputs/schedules/dp_n4/rank_001_*.json \
  --verify
```

Also print node-type counts:

```bash
python3 validation/load_schedule.py \
  outputs/schedules/dp_n4/rank_001_*.json \
  --verify --print-nodes
```

## 7) Visualization and DOT export

Export DOT source only:

```bash
python3 validation/load_schedule.py \
  outputs/schedules/dp_n4/rank_001_*.json \
  --dot outputs/schedules/dp_n4/rank_001.dot
```

Render SVG:

```bash
python3 validation/load_schedule.py \
  outputs/schedules/dp_n4/rank_001_*.json \
  --render outputs/schedules/dp_n4/rank_001.svg
```

Render annotated SVG (includes per-node fidelity/time):

```bash
python3 validation/load_schedule.py \
  outputs/schedules/dp_n4/rank_001_*.json \
  --render outputs/schedules/dp_n4/rank_001_annotated.svg \
  --annotate
```

Render PNG instead of SVG:

```bash
python3 validation/load_schedule.py \
  outputs/schedules/dp_n4/rank_001_*.json \
  --render outputs/schedules/dp_n4/rank_001.png
```

## 8) DP-specific tuning knobs

Limit DP recursion to only span-partition candidates (exclude merged brute-force families):

```bash
python3 validation/search_results.py \
  --algorithm dp \
  --N 4 \
  --uniform \
  --e_max 24 \
  --no-bf-families
```

Control per-span copy-count and circuit enumeration budget:

```bash
python3 validation/search_results.py \
  --algorithm dp \
  --N 4 \
  --uniform \
  --e_max 24 \
  --max-link-copies 4 \
  --max-enumerated-rounds 4
```

## 9) Brute-force family toggles

Disable specific brute-force families:

```bash
python3 validation/search_results.py \
  --algorithm brute_force \
  --no-heralded \
  --no-optimistic \
  --no-link
```

Cap purification copy-count in brute force:

```bash
python3 validation/search_results.py \
  --algorithm brute_force \
  --max-n-pur 5
```

## 10) Typical end-to-end workflow

```bash
# 1) Run DP search and save top 3 artifacts
python3 validation/search_results.py \
  --algorithm dp --N 4 --uniform --e_max 24 \
  --save-top 3 --save-dir outputs/schedules/run1

# 2) Verify top artifact
python3 validation/load_schedule.py outputs/schedules/run1/rank_001_*.json --verify --print-nodes

# 3) Export visualization
python3 validation/load_schedule.py outputs/schedules/run1/rank_001_*.json \
  --render outputs/schedules/run1/rank_001.svg --annotate
```
