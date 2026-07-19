# Results Report: `docs/Roadmap_Derisk_and_Reframe.md` (§1-§4, all complete)

**Purpose of this document:** a handoff summary for another AI agent (or
future session) picking up this repo. All four items in
[docs/Roadmap_Derisk_and_Reframe.md](Roadmap_Derisk_and_Reframe.md) are
now **done, verified, and reproducible**. This file gives, for each
item: what was asked, what was found, and exactly which files to open
for the full data/writeup. No new findings are introduced here that
aren't already in the linked files — this is a navigation aid, not a
new source of truth.

Test suite: `PYTHONPATH=src python3 -m pytest -q` from repo root (with
`.venv` activated) — 233/233 passing as of this report.

---

## §1 — Excluded-move check at N=14 and N=18

**Ask:** determine whether the "excluded same-span-purification move"
(the move `dp_search`/`beam_search` provably cannot reach, per
[docs/Optimality Scope.md](Optimality%20Scope.md)) rescues feasibility
at the paper's own budget (`e_max = 10*N`) for N=14 and N=18, the two
points where `sweep_hop_count` reported no feasible schedule found.

**Result:** rescued at both, most importantly at N=18.

| N | Excluded-move result at `e_max=10*N` | Fidelity | Cost |
|---|---|---|---|
| 14 | Rescued (secondary confirmation — already feasible via `optimizer_matched_cost`) | 0.904348 | 116 |
| 18 | **Rescued** (headline result — nothing else found *anything* feasible here) | 0.928596 | 180 (exactly `10*N`) |

**Files:**
- [outputs/excluded_move_n14_n18/results.csv](../outputs/excluded_move_n14_n18/results.csv) — raw numbers.
- [outputs/excluded_move_n14_n18/README.md](../outputs/excluded_move_n14_n18/README.md) — full writeup, bounded-search caveat.
- Cross-referenced (permanent addendum, not a one-off edit) into [outputs/sweep_hop_count/README.md](../outputs/sweep_hop_count/README.md) and [docs/Optimality Scope.md](Optimality%20Scope.md).

**Key takeaway for downstream use:** any claim of "infeasible at N=18"
elsewhere in this repo (e.g. in `sweep_hop_count`'s Observation 3) must
be read as "infeasible for the schedule families `dp_search`/
`beam_search` search," not a true non-existence result — a real,
`ScheduleDAG.validate()`-passing schedule clearing the floor at N=18
exists at exactly the paper's own budget.

---

## §2 — Minimum required budget vs. N (scaling-law question)

**Ask:** for N in {10,12,14,16,18}, bisect the smallest `e_max` at which
`beam_search` (∪ brute-force families) clears `f_min=0.9`, rather than
assuming the paper's `10*N` formula is right.

**Result:**

| N | Paper's `10N` | Min. feasible `e_max` | Ratio |
|---|---|---|---|
| 10 | 100 | 50 | 0.50x |
| 12 | 120 | 67 | 0.56x |
| 14 | 140 | 82 | 0.59x |
| 16 | 160 | 128 | 0.80x |
| 18 | 180 | **not found** (gave up at 5760, 32x) | — |

Power-law fit: $e_{max}^{min} \approx 0.593 \cdot N^{1.909}$ — super-
linear, i.e. grows faster than the paper's linear `10N`. N=18 plateaus
at exactly F=0.8878 across the entire 180-5760 range tested (32x) — a
search-family wall, not a resource wall (see §1: a real schedule exists
at N=18 at 1x budget, just outside what `beam_search` can reach).

**Files:**
- [outputs/sweep_min_budget_vs_n/results.csv](../outputs/sweep_min_budget_vs_n/results.csv)
- [outputs/sweep_min_budget_vs_n/README.md](../outputs/sweep_min_budget_vs_n/README.md) — full writeup, power-law fit, N=18 scoping note.
- [outputs/sweep_min_budget_vs_n/min_budget_vs_n.png](../outputs/sweep_min_budget_vs_n/min_budget_vs_n.png) / `.svg` — plot vs. paper's linear reference line.
- Generating script: [validation/sweep_min_budget_vs_n.py](../validation/sweep_min_budget_vs_n.py).

**Operational note (relevant if re-running or extending):** this
script's naive upward bisection search once caused a real OOM crash of
the whole desktop session at N=18/e_max=11520 (`brute_force_search`'s
internal `cap = e_max // (2*N)` grows unbounded with `e_max` and is not
capped by `beam_search`). Fixed by capping the upward safety multiple at
32x (`_MAX_UPWARD_MULTIPLE` in the script) and, if relaunching any
similar large sweep in the background, wrapping with `ulimit -v
<bytes>` + `setsid ... &` (not just `nohup`) so a runaway allocation
raises a catchable `MemoryError` instead of an OS-level OOM kill. Full
details in repo memory (`/memories/repo/hrgs-scheduler-notes.md`,
section "brute_force_search / beam_search: unbounded-e_max memory
blowup").

---

## §3 — Reframe the e_d sweep as a resource-vs-quality curve

**Ask:** turn `sweep_ed`'s percent-improvement framing into "minimum
resource cost required to sustain `f_min=0.9`, as a function of `e_d`."

**Result:** at fixed N=10, minimum feasible `e_max` ranges from a flat
floor of **21** (for `e_d <= 0.005`, set by the raw chain's own Gen-node
count, not by noise) up to **50** at `e_d=0.010`. The paper's fixed
`e_max=100` therefore overspends by **2.0x-4.8x** across the entire
tested range — most severely at low noise where almost no purification
is actually needed.

**Files:**
- [outputs/sweep_min_budget_vs_ed/results.csv](../outputs/sweep_min_budget_vs_ed/results.csv)
- [outputs/sweep_min_budget_vs_ed/README.md](../outputs/sweep_min_budget_vs_ed/README.md) — full writeup.
- [outputs/sweep_min_budget_vs_ed/min_budget_vs_ed.png](../outputs/sweep_min_budget_vs_ed/min_budget_vs_ed.png) / `.svg` — plot vs. paper's fixed `e_max=100` reference line.
- Generating script (new): [validation/sweep_min_budget_vs_ed.py](../validation/sweep_min_budget_vs_ed.py).
- [outputs/sweep_ed_n10/README.md](../outputs/sweep_ed_n10/README.md) — Observations section updated to lead with this reframe; the original percent-improvement figures are now secondary/supporting.

---

## §4 — Uniform link-level baseline column

**Ask:** the uniform link-level family (same purification circuit at
every hop — "the reasonable default a practitioner would pick without
optimizing") is already searched by every `beam_search` call but was
never extracted/reported as its own comparison point. Add it.

**Result:** added a `link_level_baseline` variant to both existing
sweeps. Budget-relaxed optimizer's improvement *over link-level
specifically* (distinct from, and generally smaller than, its
improvement over the paper's hand-picked `flexible_paper`):

- `sweep_ed_n10` (N=10, across `e_d`): **+0.0% to +18.2%**.
- `sweep_hop_count` (across N, at `e_d=0.01`): **+0.0% to +14.2%** among
  the N where both are feasible (2,4,6,8,10,14); N=18's link-level
  baseline is itself infeasible there (F=0.8048).

**Gotcha worth knowing if extending this further:** the link-level
family's minimum `n_copies` is 2 (it always applies at least one
purification round), so its cost floor is 2x the raw chain's minimum
cost even when no purification is actually needed — do not assume "low
noise → link-level degenerates to the raw chain," that's false. Any
0%-improvement points are coincidental (both hit the same rate ceiling,
or the optimizer's own global best happens to itself be a `link.*`
candidate).

**Files:**
- [outputs/sweep_ed_n10/results.csv](../outputs/sweep_ed_n10/results.csv) / [improvement_summary.csv](../outputs/sweep_ed_n10/improvement_summary.csv) — new `link_level_baseline` rows/columns.
- [outputs/sweep_ed_n10/README.md](../outputs/sweep_ed_n10/README.md) — "Link-level baseline comparison" section.
- [outputs/sweep_hop_count/results.csv](../outputs/sweep_hop_count/results.csv) / [improvement_summary.csv](../outputs/sweep_hop_count/improvement_summary.csv) — same, per N.
- [outputs/sweep_hop_count/README.md](../outputs/sweep_hop_count/README.md) — "Link-level baseline comparison" section.
- Modified scripts: [validation/sweep_ed.py](../validation/sweep_ed.py), [validation/sweep_hop_count.py](../validation/sweep_hop_count.py).

---

## How everything connects (for writing the report's results section)

1. **§2's N=18 "not found"** must always be cited together with **§1's
   N=18 rescue** — the honest claim is "the paper's linear `10*N`
   budget formula is not the bottleneck at N=18; the specific schedule
   families `dp_search`/`beam_search` explore are." Never cite one
   without the other.
2. **§3's reframe is the strongest standalone "big claim"**: the
   paper's fixed `e_max` choice is demonstrably wrong-sized (over-
   spending 2x-4.8x) across an entire noise sweep at the paper's own
   N=10 — this doesn't need any of §1/§2's search-family caveats, since
   N=10 is far from where those caveats bite.
3. **§4's link-level numbers are a secondary, more conservative
   improvement claim** to report alongside (not instead of) the
   existing improvement-over-`flexible_paper` numbers — use both when
   describing "how much better is the optimizer," since link-level is
   the fairer baseline (a real practitioner default) while
   `flexible_paper` is explicitly the paper's own feasibility
   demonstration, not a claimed-optimal baseline.

## Reproducing everything in this report

```bash
cd /home/shark/Documents/hrgs-purification-scheduler
source .venv/bin/activate
PYTHONPATH=src python3 -m pytest -q                              # 233 tests
PYTHONPATH=src python3 -u validation/sweep_min_budget_vs_n.py     # §2 (slow, ~15-20 min; see operational note above)
PYTHONPATH=src python3 -u validation/sweep_min_budget_vs_ed.py    # §3 (~9 min)
PYTHONPATH=src python3 validation/sweep_ed.py                     # §4 (ed part, ~2.5 min)
PYTHONPATH=src python3 validation/sweep_hop_count.py              # §4 (N part, ~3.5 min)
```

(§1's `validation/excluded_move_at_scale.py` and its output already
exist from an earlier step and do not need rerunning unless the
underlying search code changes.)
