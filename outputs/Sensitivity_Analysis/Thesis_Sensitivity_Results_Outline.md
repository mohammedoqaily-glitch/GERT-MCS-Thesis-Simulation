# Thesis Sensitivity Results Outline

## Table 4.X: Sensitivity Parameters and Perturbation Ranges

**Purpose:** Defines every tested intervention.

**Variables shown:** Parameter IDs, baseline, low, high, and selection rule.

**Correct interpretation:** The table defines scenario scope.

**Incorrect interpretation to avoid:** Do not interpret ranges as confidence intervals.

**Exact source:** Sensitivity_Parameters worksheet; Thesis_Tables/Table_4X_Sensitivity_Parameters.csv

## Table 4.Y: One-Way Routing-Probability Sensitivity Results

**Purpose:** Quantifies routing interventions.

**Variables shown:** Conditional time, outcomes, loops, and mixed-outcome mean.

**Correct interpretation:** Differences are relative to the verified baseline with valid XOR groups.

**Incorrect interpretation to avoid:** Do not treat mixed-outcome time as successful completion time.

**Exact source:** Routing_OAT worksheet; Thesis_Tables/Table_4Y_Routing_OAT.csv

## Table 4.Z: Duration-Parameter Sensitivity Results

**Purpose:** Quantifies coherent duration-triplet interventions.

**Variables shown:** Conditional time and outcome measures.

**Correct interpretation:** Time effects result from one transition's O/ML/P scaling.

**Incorrect interpretation to avoid:** Do not describe the screening score as one-way sensitivity.

**Exact source:** Duration_OAT worksheet; Thesis_Tables/Table_4Z_Duration_OAT.csv

## Table 4.W: Loop-Cap and Distributional Robustness

**Purpose:** Tests structural and distribution assumptions.

**Variables shown:** Loop, cap, renormalisation, time, and distribution-family metrics.

**Correct interpretation:** Small effects support robustness only within tested alternatives.

**Incorrect interpretation to avoid:** Do not claim a zero effect outside the tested cap and family choices.

**Exact source:** LoopCap_Robustness and Distribution_Robustness worksheets; Thesis_Tables/Table_4W_LoopCap_Distribution.csv

## Table 4.V: Early-Exit Threshold Analysis

**Purpose:** Evaluates mixed-outcome multimodality.

**Variables shown:** Early-exit probability, outcomes, P90, KDE modes, GMM BIC, classification.

**Correct interpretation:** The threshold or interval follows the numerical classification rule.

**Incorrect interpretation to avoid:** Do not infer a threshold from visual inspection alone.

**Exact source:** Threshold_Analysis worksheet; Thesis_Tables/Table_4V_Threshold_Analysis.csv

## Table 4.U: Random-Seed and Replication-Count Robustness

**Purpose:** Quantifies Monte Carlo stability.

**Variables shown:** Seed summaries and nested-stream convergence.

**Correct interpretation:** Variation represents simulation uncertainty, not input sensitivity.

**Incorrect interpretation to avoid:** Do not rank model inputs from seed variation.

**Exact source:** Seed_Robustness and Replication_Convergence worksheets; Thesis_Tables/Table_4U_Seed_Convergence.csv

## Table 4.T: Integrated Sensitivity Ranking

**Purpose:** Ranks tested parameters across normalised outputs.

**Variables shown:** Maximum effects, normalised effects, score, and rank.

**Correct interpretation:** Rank identifies influence within the specified ranges and outputs.

**Incorrect interpretation to avoid:** Do not interpret rank as causality or universal importance.

**Exact source:** Integrated_Ranking worksheet; Thesis_Tables/Table_4T_Integrated_Ranking.csv

## Figure 4.1: Routing Probability Tornado - P90

**Purpose:** Ranks routing effects on conditional P90.

**Variables shown:** Low/high P90 changes.

**Correct interpretation:** Longer bars indicate greater tested P90 sensitivity.

**Incorrect interpretation to avoid:** Do not compare bar length as a probability.

**Exact source:** Figures/01_Routing_Probability_Tornado_P90.png; Tornado_P90_Data worksheet

## Figure 4.2: Routing Probability Tornado - P(Success)

**Purpose:** Ranks routing effects on successful closure.

**Variables shown:** Low/high probability changes.

**Correct interpretation:** Direction and magnitude show routing intervention effects.

**Incorrect interpretation to avoid:** Do not read associations as causal evidence.

**Exact source:** Figures/02_Routing_Probability_Tornado_PSuccess.png; Tornado_Outcome_Data worksheet

## Figure 4.3: Duration Sensitivity Tornado - P90

**Purpose:** Ranks selected duration drivers.

**Variables shown:** Low/high P90 changes.

**Correct interpretation:** Bars are actual OAT interventions.

**Incorrect interpretation to avoid:** Do not substitute correlation for the displayed interventions.

**Exact source:** Figures/03_Duration_Sensitivity_Tornado_P90.png; Duration_OAT worksheet

## Figure 4.4: Loop-Cap Robustness Comparison

**Purpose:** Compares cap alternatives.

**Variables shown:** P90 by loop and cap.

**Correct interpretation:** Flat profiles indicate robustness at tested caps.

**Incorrect interpretation to avoid:** Do not infer that loops are structurally irrelevant.

**Exact source:** Figures/04_Loop_Cap_Robustness_Comparison.png; LoopCap_Robustness worksheet

## Figure 4.5: Distribution-Family Robustness

**Purpose:** Compares Beta-PERT and triangular durations.

**Variables shown:** Conditional mean, P90, and P95.

**Correct interpretation:** Differences isolate distribution-family choice.

**Incorrect interpretation to avoid:** Do not attribute differences to routing.

**Exact source:** Figures/05_Distribution_Family_Robustness_Comparison.png; Distribution_Robustness worksheet

## Figure 4.6: Seed Robustness

**Purpose:** Shows fixed-seed variation.

**Variables shown:** P90 and P95 by seed.

**Correct interpretation:** Narrow variation supports Monte Carlo stability.

**Incorrect interpretation to avoid:** Do not interpret seed as a substantive model input.

**Exact source:** Figures/06_Seed_Robustness_Plot.png; Seed_Robustness worksheet

## Figure 4.7: Replication Convergence

**Purpose:** Shows nested-stream convergence.

**Variables shown:** P90 and P95 by N.

**Correct interpretation:** Stabilisation supports the selected N.

**Incorrect interpretation to avoid:** Do not equate visual smoothness with zero uncertainty.

**Exact source:** Figures/07_Replication_Convergence_Plot.png; Replication_Convergence worksheet

## Figure 4.8: Early-Exit Probability versus Outcomes

**Purpose:** Shows outcome response to early exit.

**Variables shown:** Success, non-implementation, and dispute probabilities.

**Correct interpretation:** Outcome changes follow a controlled routing intervention.

**Incorrect interpretation to avoid:** Dispute incidence is not a terminal outcome share.

**Exact source:** Figures/08_Early_Exit_Probability_vs_Outcome_Probabilities.png; Threshold_Analysis worksheet

## Figure 4.9: Early-Exit Probability versus Successful P90

**Purpose:** Separates conditional time from outcome mixing.

**Variables shown:** Conditional P90 across grid.

**Correct interpretation:** Changes apply only to successful closures.

**Incorrect interpretation to avoid:** Do not use the mixed-outcome mean in its place.

**Exact source:** Figures/09_Early_Exit_Probability_vs_Successful_P90.png; Threshold_Analysis worksheet

## Figure 4.10: Bimodality Classification

**Purpose:** Shows numerical modal classification.

**Variables shown:** Classification across grid.

**Correct interpretation:** Threshold claims follow KDE and BIC criteria.

**Incorrect interpretation to avoid:** Do not infer modes from histogram bars alone.

**Exact source:** Figures/10_Bimodality_Classification_vs_Early_Exit_Probability.png; Threshold_Analysis worksheet

## Figure 4.11: Selected Histograms and KDEs

**Purpose:** Illustrates classified mixed distributions.

**Variables shown:** Histogram and KDE panels.

**Correct interpretation:** Panels visually support, but do not define, classification.

**Incorrect interpretation to avoid:** Do not treat early exits as successful early completion.

**Exact source:** Figures/11_Selected_Combined_Histograms_KDEs.png; Threshold_Analysis worksheet

## Figure 4.12: Integrated Driver Ranking

**Purpose:** Summarises multi-output influence.

**Variables shown:** Normalised influence scores.

**Correct interpretation:** Rank is conditional on tested ranges and normalisation.

**Incorrect interpretation to avoid:** Do not compare raw effects with incompatible units.

**Exact source:** Figures/12_Integrated_Driver_Ranking.png; Integrated_Ranking worksheet
