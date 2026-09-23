from __future__ import annotations

import math

import numpy as np


def silverman_bandwidth(values: np.ndarray, minimum: float = 1.0) -> float:
    array = np.asarray(values, dtype=np.float64)
    if array.size < 2:
        return minimum
    sd = float(array.std(ddof=1))
    q25, q75 = np.quantile(array, [0.25, 0.75])
    robust = min(sd, float((q75 - q25) / 1.34)) if q75 > q25 else sd
    if robust <= 0:
        robust = max(sd, minimum)
    return max(minimum, 0.9 * robust * array.size ** (-0.2))


def gaussian_kde(values: np.ndarray, grid_points: int = 512, minimum_bandwidth: float = 1.0) -> tuple[np.ndarray, np.ndarray, float]:
    array = np.asarray(values, dtype=np.float64)
    bandwidth = silverman_bandwidth(array, minimum_bandwidth)
    grid = np.linspace(float(array.min() - 3 * bandwidth), float(array.max() + 3 * bandwidth), grid_points)
    density = np.zeros_like(grid)
    chunk = 5000
    factor = 1.0 / (array.size * bandwidth * math.sqrt(2 * math.pi))
    for start in range(0, array.size, chunk):
        sample = array[start:start + chunk]
        z = (grid[:, None] - sample[None, :]) / bandwidth
        density += np.exp(-0.5 * z * z).sum(axis=1)
    density *= factor
    return grid, density, bandwidth


def meaningful_modes(grid: np.ndarray, density: np.ndarray, bandwidth: float, prominence_fraction: float = 0.05) -> list[dict]:
    candidates = np.where((density[1:-1] > density[:-2]) & (density[1:-1] >= density[2:]))[0] + 1
    peak_max = float(density.max())
    window = max(3, int(round(3 * bandwidth / max(grid[1] - grid[0], 1e-12))))
    modes = []
    for index in candidates:
        left = density[max(0, index - window):index + 1]
        right = density[index:min(len(density), index + window + 1)]
        prominence = float(density[index] - max(float(left.min()), float(right.min())))
        if density[index] >= prominence_fraction * peak_max and prominence >= prominence_fraction * peak_max:
            modes.append({"x": float(grid[index]), "density": float(density[index]), "prominence": prominence})
    separated = []
    for mode in sorted(modes, key=lambda item: item["density"], reverse=True):
        if all(abs(mode["x"] - accepted["x"]) >= bandwidth for accepted in separated):
            separated.append(mode)
    return sorted(separated, key=lambda item: item["x"])


def _normal_pdf(values: np.ndarray, mean: float, variance: float) -> np.ndarray:
    variance = max(variance, 1e-6)
    return np.exp(-0.5 * (values - mean) ** 2 / variance) / math.sqrt(2 * math.pi * variance)


def gaussian_mixture_bic(values: np.ndarray) -> dict:
    x = np.asarray(values, dtype=np.float64)
    n = x.size
    mean = float(x.mean())
    variance = max(float(x.var()), 1e-6)
    log_likelihood_1 = float(np.log(_normal_pdf(x, mean, variance) + 1e-300).sum())
    bic1 = 2 * math.log(n) - 2 * log_likelihood_1
    best = None
    for low_q, high_q in ((0.2, 0.8), (0.1, 0.9), (0.3, 0.7)):
        means = np.asarray(np.quantile(x, [low_q, high_q]), dtype=np.float64)
        variances = np.asarray([variance, variance], dtype=np.float64)
        weights = np.asarray([0.5, 0.5], dtype=np.float64)
        previous = -math.inf
        for _ in range(250):
            weighted = np.column_stack([weights[k] * _normal_pdf(x, means[k], variances[k]) for k in range(2)])
            denominator = weighted.sum(axis=1) + 1e-300
            responsibilities = weighted / denominator[:, None]
            nk = responsibilities.sum(axis=0) + 1e-12
            weights = nk / n
            means = (responsibilities * x[:, None]).sum(axis=0) / nk
            variances = (responsibilities * (x[:, None] - means) ** 2).sum(axis=0) / nk
            variances = np.maximum(variances, 1e-4)
            likelihood = float(np.log(denominator).sum())
            if abs(likelihood - previous) < 1e-7:
                break
            previous = likelihood
        candidate = {"log_likelihood": likelihood, "weights": weights, "means": means, "variances": variances}
        if best is None or candidate["log_likelihood"] > best["log_likelihood"]:
            best = candidate
    bic2 = 5 * math.log(n) - 2 * best["log_likelihood"]
    order = np.argsort(best["means"])
    return {
        "BIC_1_Component": bic1,
        "BIC_2_Component": bic2,
        "Delta_BIC_1_minus_2": bic1 - bic2,
        "GMM2_Mean_1": float(best["means"][order[0]]),
        "GMM2_Mean_2": float(best["means"][order[1]]),
        "GMM2_Weight_1": float(best["weights"][order[0]]),
        "GMM2_Weight_2": float(best["weights"][order[1]]),
    }


def classify_distribution(values: np.ndarray, config: dict) -> tuple[dict, dict]:
    grid, density, bandwidth = gaussian_kde(values, config["kde_grid_points"], config["kde_min_bandwidth_days"])
    modes = meaningful_modes(grid, density, bandwidth, config["mode_prominence_fraction"])
    mixture = gaussian_mixture_bic(values)
    delta = mixture["Delta_BIC_1_minus_2"]
    if len(modes) >= 2 and delta >= config["gmm_bic_clear_threshold"]:
        classification = "clearly bimodal"
    elif len(modes) == 1 and delta <= 0:
        classification = "unimodal"
    elif len(modes) >= 2 or delta > 0:
        classification = "weakly bimodal"
    else:
        classification = "indeterminate"
    row = {
        "KDE_Bandwidth_Days": bandwidth,
        "Meaningful_Mode_Count": len(modes),
        "Mode_Locations_Days": ";".join(f"{mode['x']:.3f}" for mode in modes),
        **mixture,
        "Classification": classification,
    }
    curve = {"grid": grid, "density": density, "modes": modes}
    return row, curve


def threshold_interval(rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: row["Early_Exit_Probability"])
    unimodal = [row["Early_Exit_Probability"] for row in ordered if row["Classification"] == "unimodal"]
    clear = [row["Early_Exit_Probability"] for row in ordered if row["Classification"] == "clearly bimodal"]
    if clear and not unimodal:
        return {"Threshold_Result": f"Bimodality is already clear at the lowest tested probability ({min(clear):.2f}).", "Threshold_Low": None, "Threshold_High": min(clear)}
    if unimodal and not clear:
        return {"Threshold_Result": f"No clear bimodality through the highest tested probability ({max(unimodal):.2f}).", "Threshold_Low": max(unimodal), "Threshold_High": None}
    if unimodal and clear:
        low = max(value for value in unimodal if value < max(clear)) if any(value < max(clear) for value in unimodal) else max(unimodal)
        highs = [value for value in clear if value > low]
        if highs:
            high = min(highs)
            intervening = [row for row in ordered if low < row["Early_Exit_Probability"] < high]
            stable = all(row["Classification"] in {"weakly bimodal", "indeterminate"} for row in intervening)
            wording = "transition interval" if stable else "unstable classification interval"
            return {"Threshold_Result": f"{wording}: {low:.2f} to {high:.2f}.", "Threshold_Low": low, "Threshold_High": high}
    return {"Threshold_Result": "No defensible threshold could be identified from the tested grid.", "Threshold_Low": None, "Threshold_High": None}
