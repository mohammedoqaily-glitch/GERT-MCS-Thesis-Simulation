# Sensitivity and Robustness Analysis Methodology

## Analytical Purpose

The sensitivity framework evaluates the stability of the verified PERT-MCS and GERT-MCS model under controlled changes to routing probabilities, duration assumptions, loop caps, distribution family, random seed, and replication count. Sensitivity denotes an intervention on an input parameter; it is distinguished from correlation, variance association, convergence assessment, and robustness checks.

## Baseline Configuration

The authoritative baseline uses the verified Word inputs, 50,000 replications, root seed 42, Beta-PERT with lambda 4, and upward rounding once at the sampled activity or traversal level. GERT completion-time measures are conditional on Successful Closure unless explicitly labelled as mixed-outcome measures.

## One-Way Routing Sensitivity

Each eligible stochastic routing probability is varied independently to low and high levels. In the absence of expert intervals, the low and high values are defined by a relative change of 25%, subject to the unit interval and a non-collapse guard. When a target probability changes from p to v, every other outgoing probability q in the same XOR group is replaced by q(1-v)/(1-p). This preserves their relative proportions and ensures that each group sums to one.

## Duration Perturbation

Five transitions are screened using their expected rounded-duration contribution among successful runs and an auxiliary duration association. Screening does not itself constitute sensitivity. For each selected transition, the complete optimistic, most-likely, and pessimistic triplet is scaled coherently by plus or minus 10%, while preserving ordering and the distribution family.

## Loop-Cap Robustness

Each capped return transition is evaluated at cap 1, the authoritative cap, and one repetition above the authoritative cap. Once a loop reaches its cap, its probability mass is removed and the remaining eligible alternatives are proportionally renormalised, exactly as in the verified model.

## Distributional Robustness

Beta-PERT is compared with a triangular distribution using identical O, ML, and P values, network structure, routing probabilities, loop rules, seed, and replication count. Differences therefore quantify distribution-family robustness rather than a change in model topology.

## Seed and Replication Robustness

Ten fixed seeds quantify between-seed Monte Carlo variation. Replication convergence uses nested prefixes of the 50,000-run baseline stream at 1,000, 5,000, 10,000, 25,000, 50,000 replications, ensuring directly comparable random streams.

## Threshold and Bimodality Analysis

The early non-implementation probability is evaluated on the configured grid. A Gaussian KDE uses Silverman's robust bandwidth rule with a minimum bandwidth of 1.0 working day. Local modes must exceed a prominence of 5% of the maximum density and be separated by at least one bandwidth. One- and two-component univariate Gaussian mixtures are fitted by expectation-maximisation and compared using BIC. Classification combines the KDE mode count and a BIC improvement threshold of 10.

## Statistical Uncertainty

Outcome probabilities use 95% Wilson score intervals. Mean durations use standard errors and normal-theory 95% confidence intervals. P80, P90, and P95 use 1,000 nonparametric bootstrap resamples implemented through multinomial resampling of the empirical discrete duration distribution with a fixed bootstrap seed.

## Integrated Ranking

For each parameter and output, the maximum absolute low/high effect is divided by the largest effect observed for that output. The integrated influence score is the maximum of the six normalised effects for mean successful time, P90, P95, successful-closure probability, non-implementation probability, and dispute-diversion probability. This avoids combining incompatible units directly.

## Interpretation Boundaries

Baseline associations are not causal effects. Intervention scenarios quantify model sensitivity within the tested ranges, not empirical causal effects. The mixed-outcome GERT duration distribution must not be interpreted as a homogeneous successful-completion distribution. The analysis does not claim that GERT-MCS is universally more accurate than PERT-MCS.
