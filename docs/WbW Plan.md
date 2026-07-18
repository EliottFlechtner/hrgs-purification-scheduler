## Week-by-week plan

**Weeks 1-2: Implementation, inner loop + validation.** Build the state object, operation catalog, and bottom-up DAG evaluation (§7 inner loop). Validate against the three canonical timing formulas (§2.6 table) and reproduce Fig. 5 (fidelity vs. depolarizing noise) and Fig. 6 (rate ratio, ~45-65x) from the Integrating paper. Don't move on until these match, since everything downstream depends on this being correct, and it also gives you your first "figure" for the report almost for free.

**Weeks 2-3: Outer loop.** Brute force on small $N$ (2-4) for ground truth, then the DP-over-stages master algorithm, then a heuristic fallback (greedy or beam search) for larger $N$. Cross-check DP against brute force on the small cases where both are tractable.

**Weeks 3-4: The headline experiment.** Run your optimizer at the paper's exact config ($N=10$, $(16,14,1)$, 18 arms) and compare against their Fig. 4 schedule. Important for the networking framing: match their own fairness constraint, both schemes consume the same number of half-RGS per hop (their Fig. 5/6 caption explicitly does this), so do a **resource-normalized comparison**: fix $C(\Sigma)$ equal to their baseline's resource cost and show your found schedule does better at that fixed cost, not just better in some absolute sense. That's the single most citable number in your report.

**Weeks 4-5: Sweeps and design principles.** Vary noise level, $N$, and budget $B$ to build Pareto-frontier plots ($F$ vs $R$, $F$ vs $C$) and extract at least one generalizable rule of thumb (e.g. "span-level purification dominates hop-level once $N$ exceeds X" or "the fidelity gain from RGSS-level purification saturates past $n_{\text{pur}}=$ Y"). Also do the optimizer-performance characterization here: runtime/memory vs. $N$ and $B$, where brute force stops being feasible, where DP takes over, where you need heuristics.

**Week 5-6: Writing.** Draft the report using the outline below, reusing your existing spec document almost directly for the formalism section.

**Week 6-7: Buffer, polish, and paper extraction.** Slack for experiments that take longer than expected, then extract the shorter paper from the finished report once you know which results are strongest.
