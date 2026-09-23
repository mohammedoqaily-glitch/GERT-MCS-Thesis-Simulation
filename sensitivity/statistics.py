from __future__ import annotations

import hashlib
import math

import numpy as np

from .model import LOOP_TAGS, SimulationResult


def nearest_quantile(values: np.ndarray, probability: float) -> float | None:
    array = np.sort(np.asarray(values))
    if array.size == 0:
        return None
    index = max(0, min(array.size - 1, math.ceil(probability * array.size) - 1))
    return float(array[index])


def mean_ci(values: np.ndarray, confidence: float = 0.95) -> tuple[float | None, float | None, float | None]:
    array = np.asarray(values, dtype=np.float64)
    if array.size < 2:
        return None, None, None
    mean = float(array.mean())
    se = float(array.std(ddof=1) / math.sqrt(array.size))
    z = 1.959963984540054 if math.isclose(confidence, 0.95) else 1.959963984540054
    return se, mean - z * se, mean + z * se


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    z = 1.959963984540054 if math.isclose(confidence, 0.95) else 1.959963984540054
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def bootstrap_quantile_intervals(
    values: np.ndarray,
    probabilities: tuple[float, ...] = (0.8, 0.9, 0.95),
    resamples: int = 1000,
    seed: int = 20260731,
    confidence: float = 0.95,
) -> dict[str, tuple[float | None, float | None]]:
    array = np.asarray(values)
    if array.size == 0:
        return {f"p{int(p * 100)}": (None, None) for p in probabilities}
    support, counts = np.unique(array, return_counts=True)
    rng = np.random.default_rng(seed)
    bootstrap_counts = rng.multinomial(array.size, counts / counts.sum(), size=resamples)
    cumulative = np.cumsum(bootstrap_counts, axis=1)
    output = {}
    alpha = (1.0 - confidence) / 2.0
    for probability in probabilities:
        target = math.ceil(probability * array.size)
        indices = np.argmax(cumulative >= target, axis=1)
        estimates = support[indices]
        output[f"p{int(probability * 100)}"] = (
            float(np.quantile(estimates, alpha, method="nearest")),
            float(np.quantile(estimates, 1 - alpha, method="nearest")),
        )
    return output


def scenario_bootstrap_seed(base_seed: int, scenario_id: str) -> int:
    token = hashlib.sha256(scenario_id.encode("utf-8")).digest()
    return (base_seed + int.from_bytes(token[:4], "little")) % (2**32 - 1)


def metrics_from_result(result: SimulationResult, config: dict) -> dict:
    valid = result.outcomes >= 0
    success = result.outcomes == 1
    nonimplementation = result.outcomes == 0
    computational = result.outcomes < 0
    successful_times = result.totals[success]
    all_times = result.totals[valid]
    n = int(valid.sum())
    success_n = int(success.sum())
    nonimplementation_n = int(nonimplementation.sum())
    dispute_n = int(np.sum(result.dispute_visited & valid))
    any_loop = np.any(result.loop_counts > 0, axis=1) & valid
    se, mean_low, mean_high = mean_ci(successful_times, config["confidence_level"])
    quantile_cis = bootstrap_quantile_intervals(
        successful_times,
        resamples=config["bootstrap_resamples"],
        seed=scenario_bootstrap_seed(config["bootstrap_seed"], result.scenario_id),
        confidence=config["confidence_level"],
    )
    success_ci = wilson_interval(success_n, n, config["confidence_level"])
    nonimplementation_ci = wilson_interval(nonimplementation_n, n, config["confidence_level"])
    dispute_ci = wilson_interval(dispute_n, n, config["confidence_level"])
    threshold = config.get("completion_threshold_days")
    row = {
        "Scenario_ID": result.scenario_id,
        "Replications": result.replications,
        "Seed": result.seed,
        "Distribution": result.distribution,
        "Valid_Runs": n,
        "Successful_Count": success_n,
        "NonImplementation_Count": nonimplementation_n,
        "ComputationalTermination_Count": int(computational.sum()),
        "Mean_Successful_Time": float(successful_times.mean()) if success_n else None,
        "Successful_Mean_SE": se,
        "Successful_Mean_CI_Low": mean_low,
        "Successful_Mean_CI_High": mean_high,
        "Median_Successful_Time": nearest_quantile(successful_times, 0.5),
        "Successful_P80": nearest_quantile(successful_times, 0.8),
        "Successful_P80_CI_Low": quantile_cis["p80"][0],
        "Successful_P80_CI_High": quantile_cis["p80"][1],
        "Successful_P90": nearest_quantile(successful_times, 0.9),
        "Successful_P90_CI_Low": quantile_cis["p90"][0],
        "Successful_P90_CI_High": quantile_cis["p90"][1],
        "Successful_P95": nearest_quantile(successful_times, 0.95),
        "Successful_P95_CI_Low": quantile_cis["p95"][0],
        "Successful_P95_CI_High": quantile_cis["p95"][1],
        "Successful_Time_SD": float(successful_times.std(ddof=1)) if success_n > 1 else None,
        "P_Exceed_Tc_Given_Success": float(np.mean(successful_times > threshold)) if threshold is not None and success_n else None,
        "Tc_Working_Days": threshold,
        "P_Success": success_n / n if n else None,
        "P_Success_CI_Low": success_ci[0],
        "P_Success_CI_High": success_ci[1],
        "P_NonImplementation": nonimplementation_n / n if n else None,
        "P_NonImplementation_CI_Low": nonimplementation_ci[0],
        "P_NonImplementation_CI_High": nonimplementation_ci[1],
        "P_Dispute_Diversion": dispute_n / n if n else None,
        "P_Dispute_CI_Low": dispute_ci[0],
        "P_Dispute_CI_High": dispute_ci[1],
        "P_Any_Loop": float(np.mean(any_loop[valid])) if n else None,
        "Expected_Total_Loop_Repetitions": float(result.loop_counts[valid].sum(axis=1).mean()) if n else None,
        "Computational_Termination_Rate": float(computational.mean()),
        "Unconditional_Mean_Time_Mixed_Outcomes": float(all_times.mean()) if n else None,
        "Mean_Transition_Count": float(result.transition_counts[valid].mean()) if n else None,
        "Renormalisation_Frequency": float(result.renormalisation_counts[valid].mean()) if n else None,
    }
    for index, tag in enumerate(LOOP_TAGS):
        counts = result.loop_counts[:, index]
        row[f"{tag}_Activation_Probability"] = float(np.mean(counts[valid] > 0)) if n else None
        row[f"{tag}_Mean_Repetitions"] = float(np.mean(counts[valid])) if n else None
        row[f"{tag}_Cap_Probability"] = float(np.mean(result.cap_hits[valid, index])) if n else None
    return row


def add_changes(row: dict, baseline: dict, fields: list[str]) -> dict:
    output = dict(row)
    for field in fields:
        value = row.get(field)
        base = baseline.get(field)
        output[f"Abs_Change_{field}"] = None if value is None or base is None else value - base
        output[f"Pct_Change_{field}"] = None if value is None or base in (None, 0) else 100.0 * (value - base) / abs(base)
    return output


def driver_screen(result: SimulationResult, arc_tags: list[str]) -> list[dict]:
    if result.arc_durations is None or result.arc_counts is None:
        raise ValueError("Driver capture was not enabled")
    success = result.outcomes == 1
    totals = result.totals[success].astype(np.float64)
    rows = []
    for index, tag in enumerate(arc_tags):
        durations = result.arc_durations[success, index].astype(np.float64)
        activation = float(np.mean(result.arc_counts[success, index] > 0))
        expected_contribution = float(durations.mean())
        correlation = float(np.corrcoef(durations, totals)[0, 1]) if np.std(durations) > 0 and np.std(totals) > 0 else 0.0
        score = expected_contribution * (1.0 + abs(correlation))
        rows.append({
            "Arc_Tag": tag,
            "Successful_Activation_Probability": activation,
            "Mean_Successful_Duration_Contribution": expected_contribution,
            "Pearson_Duration_Association": correlation,
            "Screening_Score": score,
        })
    return sorted(rows, key=lambda row: (-row["Screening_Score"], row["Arc_Tag"]))
