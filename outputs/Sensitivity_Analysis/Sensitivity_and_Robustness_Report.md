# Sensitivity and Robustness Report

## 1. Purpose of the Analysis

This analysis evaluates intervention sensitivity and Monte Carlo robustness for the verified VO PERT-MCS and GERT-MCS model. It responds directly to the requested one-way analyses, tornado charts, early-exit bimodality assessment, and integrated parameter ranking.

## 2. Baseline Model and Outputs

The baseline uses 50,000 replications, root seed 42, Beta-PERT lambda 4, and per-activity/per-traversal ceiling in working days. It reproduced 28,871 successful and 21,129 non-implementation closures. Mean successful-closure time was 112.491601 days, P90 was 125, P95 was 149, and P(Successful Closure) was 0.577420. The mixed-outcome mean was 66.805480 days and is not interpreted as homogeneous completion performance.

All 14 baseline reproduction checks passed.

## 3. Parameter-Selection Logic

Every eligible routing probability was varied by +/-25% because no expert ranges were present. Five duration transitions were selected using expected successful-duration contribution with an auxiliary Pearson association; the screening measure was not treated as sensitivity evidence.

## 4. Probability-Renormalisation Method

When one outgoing probability changed from p to v, each other probability q in its XOR group was replaced by q(1-v)/(1-p). Automated checks confirmed unit sums and unchanged non-target relative proportions.

## 5. One-Way Routing Sensitivity

The largest tested routing effect on successful-closure P90 was e56 at S5 -> S6, with a maximum absolute change of 53.000 working days. The largest tested routing effect on successful-closure probability was e12 at S1 -> S2, with a maximum absolute change of 0.152740.

## 6. Duration Sensitivity

The highest-ranked duration intervention was e45. Results are based on coherent triplet perturbations and not on squared correlation or VCI alone.

## 7. Loop-Cap Robustness

Across the tested cap values, the largest absolute change in successful-closure P90 was 0.000 working days. Loops with negligible activation are retained as explicit robustness findings.

## 8. Distributional Robustness

Switching from Beta-PERT to triangular sampling changed mean successful-closure time by +1.5037 days, P90 by +2.0 days, P95 by +2.0 days, and P(Successful Closure) by +0.000000.

## 9. Random-Seed Robustness

Across ten fixed seeds, P(Successful Closure) ranged from 0.577560 to 0.581700; successful-closure P90 ranged from 124 to 126 days.

## 10. Replication Convergence

Relative to the 50,000-run reference, the 1,000-run P(Success) deviation was -0.023420 and the 25,000-run deviation was -0.000300. Quantile deviations are reported in the convergence table.

## 11. Bimodality Threshold Analysis

Bimodality is already clear at the lowest tested probability (0.05).

Classification combines a Silverman-rule KDE, a 5% mode-prominence criterion, and one- versus two-component Gaussian-mixture BIC. No threshold is claimed solely from visual inspection.

## 12. Tornado-Chart Interpretation

Tornado bars show low and high scenario changes from the authoritative baseline. Bar length identifies sensitivity within the tested intervention range; it is not a causal effect size and cannot be generalised beyond that range.

## 13. Integrated Driver Ranking

The five highest integrated influence scores were: 1. e12 (Routing Probability, score 1.000); 2. e56 (Routing Probability, score 1.000); 3. e67 (Routing Probability, score 1.000); 4. e45 (Routing Probability, score 0.864); 5. e45 (Duration Triplet, score 0.750).

## 14. Main Findings

Routing and duration effects are output-specific. The leading P90 routing driver was e56, while the leading outcome-probability routing driver was e12. Distribution, cap, seed, and replication analyses quantify robustness rather than input correlation.

## 15. Limitations

No expert perturbation intervals or completion threshold Tc were present, so the documented fallback ranges were used and exceedance probability is reported as not defined. Fixed-seed stream starts were synchronised, but divergent routes consume different numbers of random draws; scenario differences therefore include residual Monte Carlo noise captured by confidence intervals. Gaussian mixtures are diagnostic approximations to a discrete mixed-outcome duration distribution. Baseline associations must not be interpreted causally.

## 16. Exact Reproduction Commands

```powershell
& 'C:\Users\moham\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' run_sensitivity.py --config sensitivity_config.yaml
& 'C:\Users\moham\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' run_sensitivity.py --config sensitivity_config.yaml --baseline-only
& 'C:\Users\moham\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p 'test_*.py' -v
```

Analysis version: 1.0.0. Python: 3.12.13. Generated UTC: 2026-07-30T21:31:26+00:00.
