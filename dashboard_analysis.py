from __future__ import annotations

import csv
import io
import math
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np

from VO_GERT_MCS_Final_Appendix import GertResult, PertResult, LOOP_TAGS


PERCENTILES = (50, 80, 90, 95, 99)


def nearest_rank(values: np.ndarray, percentile: int) -> int:
    arr = np.sort(np.asarray(values))
    if arr.size == 0:
        return 0
    rank = max(1, math.ceil(percentile * arr.size / 100))
    return int(arr[rank - 1])


def summary_rows(pert: PertResult, gert: GertResult) -> list[dict[str, object]]:
    success = gert.outcome_codes == 1
    rows = []
    p = pert.totals
    g = gert.totals[success]
    for metric, pval, gval in [
        ("Mean", float(np.mean(p)), float(np.mean(g))),
        ("Standard deviation", float(np.std(p, ddof=1)), float(np.std(g, ddof=1))),
        ("P50", nearest_rank(p, 50), nearest_rank(g, 50)),
        ("P80", nearest_rank(p, 80), nearest_rank(g, 80)),
        ("P90", nearest_rank(p, 90), nearest_rank(g, 90)),
        ("P95", nearest_rank(p, 95), nearest_rank(g, 95)),
        ("P99", nearest_rank(p, 99), nearest_rank(g, 99)),
        ("Minimum", int(np.min(p)), int(np.min(g))),
        ("Maximum", int(np.max(p)), int(np.max(g))),
    ]:
        rows.append({"Metric": metric, "PERT–MCS": pval, "Successful GERT–MCS": gval, "Difference": gval - pval})
    return rows


def rows_to_csv(rows: list[dict[str, object]]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def histogram_with_refs(values: np.ndarray, title: str, refs: dict[str, float] | None = None):
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.hist(values, bins="auto")
    if refs:
        for label, x in refs.items():
            ax.axvline(x, linestyle="--", linewidth=1.4, label=f"{label}: {x:g}")
        ax.legend()
    ax.set_title(title)
    ax.set_xlabel("Lifecycle time (working days)")
    ax.set_ylabel("Frequency")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def ecdf_figure(series: list[tuple[str, np.ndarray]], title: str):
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    for label, values in series:
        ordered = np.sort(values)
        y = np.arange(1, len(ordered) + 1) / len(ordered)
        ax.plot(ordered, y, label=label)
    ax.set_title(title)
    ax.set_xlabel("Lifecycle time (working days)")
    ax.set_ylabel("Cumulative probability")
    ax.grid(alpha=0.2)
    ax.legend()
    fig.tight_layout()
    return fig


def overlay_histogram(pert: np.ndarray, gert_success: np.ndarray):
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bins = np.histogram_bin_edges(np.concatenate([pert, gert_success]), bins=40)
    ax.hist(pert, bins=bins, density=True, alpha=0.55, label="PERT–MCS")
    ax.hist(gert_success, bins=bins, density=True, alpha=0.45, label="Successful GERT–MCS")
    ax.set_title("PERT–MCS vs Successful GERT–MCS Lifecycle-Time Distributions")
    ax.set_xlabel("Lifecycle time (working days)")
    ax.set_ylabel("Density")
    ax.grid(alpha=0.2)
    ax.legend()
    fig.tight_layout()
    return fig


def quantile_difference_figure(pert: np.ndarray, gert_success: np.ndarray):
    ps = np.arange(1, 100)
    q_pert = np.array([nearest_rank(pert, int(p)) for p in ps])
    q_gert = np.array([nearest_rank(gert_success, int(p)) for p in ps])
    diff = q_gert - q_pert
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(ps, diff)
    ax.axhline(0, linewidth=1)
    ax.set_title("Quantile Difference: Successful GERT–MCS minus PERT–MCS")
    ax.set_xlabel("Percentile")
    ax.set_ylabel("Difference (working days)")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def percentile_comparison_figure(pert: np.ndarray, gert_success: np.ndarray):
    x = np.arange(len(PERCENTILES))
    width = 0.36
    pvals = [nearest_rank(pert, p) for p in PERCENTILES]
    gvals = [nearest_rank(gert_success, p) for p in PERCENTILES]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(x - width / 2, pvals, width, label="PERT–MCS")
    ax.bar(x + width / 2, gvals, width, label="Successful GERT–MCS")
    ax.set_xticks(x)
    ax.set_xticklabels([f"P{p}" for p in PERCENTILES])
    ax.set_ylabel("Working days")
    ax.set_title("Percentile Comparison")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    return fig


def convergence_data(values: np.ndarray, checkpoints: list[int] | None = None) -> dict[str, list[float]]:
    n = len(values)
    if checkpoints is None:
        checkpoints = [1000, 5000, 10000, 20000, 30000, 40000, n]
    checkpoints = sorted(set(min(n, c) for c in checkpoints if c <= n or c == n))
    if n not in checkpoints:
        checkpoints.append(n)
    return {
        "n": checkpoints,
        "mean": [float(np.mean(values[:c])) for c in checkpoints],
        "p90": [nearest_rank(values[:c], 90) for c in checkpoints],
        "p95": [nearest_rank(values[:c], 95) for c in checkpoints],
    }


def convergence_figure(values: np.ndarray, title: str):
    data = convergence_data(values)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(data["n"], data["mean"], marker="o", label="Mean")
    ax.plot(data["n"], data["p90"], marker="o", label="P90")
    ax.plot(data["n"], data["p95"], marker="o", label="P95")
    ax.set_title(title)
    ax.set_xlabel("Replications")
    ax.set_ylabel("Working days")
    ax.grid(alpha=0.2)
    ax.legend()
    fig.tight_layout()
    return fig


def outcome_probability_figure(gert: GertResult):
    success = int(np.sum(gert.outcome_codes == 1))
    terminated = int(np.sum(gert.outcome_codes == 0))
    labels = ["Successful Closeout", "Withdrawn/Rejected"]
    vals = np.array([success, terminated], dtype=float)
    probs = vals / vals.sum() * 100
    fig, ax = plt.subplots(figsize=(7.8, 4.5))
    bars = ax.bar(labels, probs)
    ax.set_ylabel("Probability (%)")
    ax.set_ylim(0, max(100, probs.max() * 1.18))
    ax.set_title("GERT–MCS Terminal-Outcome Probabilities")
    for bar, value in zip(bars, probs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{value:.2f}%", ha="center")
    fig.tight_layout()
    return fig


def overall_gert_outcome_histogram(gert: GertResult):
    success = gert.totals[gert.outcome_codes == 1]
    terminated = gert.totals[gert.outcome_codes == 0]
    bins = np.histogram_bin_edges(gert.totals, bins=50)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.hist(success, bins=bins, alpha=0.6, label="Successful Closeout")
    ax.hist(terminated, bins=bins, alpha=0.6, label="Withdrawn/Rejected")
    ax.set_title("GERT–MCS Lifecycle-Time Distributions by Outcome")
    ax.set_xlabel("Lifecycle time (working days)")
    ax.set_ylabel("Frequency")
    ax.legend()
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def outcome_variance_decomposition(gert: GertResult):
    groups = [gert.totals[gert.outcome_codes == code] for code in (1, 0)]
    counts = np.array([len(g) for g in groups], dtype=float)
    means = np.array([np.mean(g) for g in groups])
    grand = float(np.mean(gert.totals))
    within_ss = sum(np.sum((g - np.mean(g)) ** 2) for g in groups)
    between_ss = float(np.sum(counts * (means - grand) ** 2))
    total = within_ss + between_ss
    within = within_ss / total * 100 if total else 0
    between = between_ss / total * 100 if total else 0
    fig, ax = plt.subplots(figsize=(7.8, 4.5))
    bars = ax.bar(["Within outcomes", "Between outcomes"], [within, between])
    ax.set_ylabel("Share of total variance (%)")
    ax.set_title("GERT Lifecycle-Time Variance Decomposition")
    for bar, value in zip(bars, [within, between]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{value:.2f}%", ha="center")
    ax.set_ylim(0, 100)
    fig.tight_layout()
    return fig, within, between


def pert_activity_variance_figure(pert: PertResult, activity_labels: list[str]):
    variances = np.var(pert.rounded_durations, axis=0, ddof=1)
    shares = variances / variances.sum() * 100
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(activity_labels))
    ax.bar(x, shares)
    ax.set_xticks(x)
    ax.set_xticklabels(activity_labels, rotation=30, ha="right")
    ax.set_ylabel("Share of fixed-route variance (%)")
    ax.set_title("PERT–MCS Transition-Level Temporal Variance Contribution")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    return fig, shares


def loop_depth_figure(gert: GertResult):
    success = gert.outcome_codes == 1
    depth = gert.loop_counts.sum(axis=1)
    depths = sorted(np.unique(depth[success]))
    means = [float(np.mean(gert.totals[success & (depth == d)])) for d in depths]
    counts = [int(np.sum(success & (depth == d))) for d in depths]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bars = ax.bar([str(int(d)) for d in depths], means)
    ax.set_xlabel("Total designated loop traversals")
    ax.set_ylabel("Mean Successful Closeout time (days)")
    ax.set_title("Loop Depth and Successful-Closeout Lifecycle Time")
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f"n={count}", ha="center", fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    return fig


def loop_frequency_figure(gert: GertResult):
    activation = np.mean(gert.loop_counts > 0, axis=0) * 100
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(LOOP_TAGS))
    ax.bar(x, activation)
    ax.set_xticks(x)
    ax.set_xticklabels(LOOP_TAGS, rotation=45, ha="right")
    ax.set_ylabel("Activation probability (%)")
    ax.set_title("Arc-Level Feedback/Loop Activation Frequency")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    return fig


def route_pareto_figure(gert: GertResult, top_n: int = 25):
    counts = sorted(gert.route_counts.values(), reverse=True)
    shown = counts[:top_n]
    cumulative = np.cumsum(shown) / len(gert.totals) * 100
    x = np.arange(1, len(shown) + 1)
    fig, ax1 = plt.subplots(figsize=(9, 4.8))
    ax1.bar(x, np.array(shown) / len(gert.totals) * 100)
    ax1.set_xlabel("Exact route rank")
    ax1.set_ylabel("Route probability (%)")
    ax1.set_title(f"Pareto Distribution of Exact Realised GERT Routes (Top {len(shown)})")
    ax2 = ax1.twinx()
    ax2.plot(x, cumulative, marker="o")
    ax2.set_ylabel("Cumulative share (%)")
    ax2.set_ylim(0, 100)
    fig.tight_layout()
    return fig


def top_routes_rows(gert: GertResult, top_n: int = 10) -> list[dict[str, object]]:
    ordered = sorted(gert.route_counts.items(), key=lambda item: (-item[1], item[0]))[:top_n]
    rows = []
    for rank, (route, count) in enumerate(ordered, start=1):
        mask = np.array([r == route for r in gert.routes])
        rows.append({
            "Rank": rank,
            "Exact route": route,
            "Count": count,
            "Probability (%)": 100 * count / len(gert.totals),
            "Mean duration": float(np.mean(gert.totals[mask])),
            "P90": nearest_rank(gert.totals[mask], 90),
            "P95": nearest_rank(gert.totals[mask], 95),
        })
    return rows


def dispute_comparison_figure(gert: GertResult):
    success = gert.outcome_codes == 1
    with_d = gert.totals[success & gert.dispute_visited]
    without_d = gert.totals[success & ~gert.dispute_visited]
    bins = np.histogram_bin_edges(np.concatenate([with_d, without_d]), bins=40)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.hist(without_d, bins=bins, alpha=0.55, density=True, label="Successful without dispute")
    ax.hist(with_d, bins=bins, alpha=0.55, density=True, label="Successful with dispute")
    ax.set_title("Successful Lifecycle-Time Distributions With and Without Dispute Diversion")
    ax.set_xlabel("Lifecycle time (working days)")
    ax.set_ylabel("Density")
    ax.legend()
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def upper_tail_composition_figure(gert: GertResult):
    success = gert.outcome_codes == 1
    vals = gert.totals[success]
    loop_any = gert.loop_counts.sum(axis=1) > 0
    rows = []
    for p in (90, 95, 99):
        threshold = nearest_rank(vals, p)
        mask = success & (gert.totals >= threshold)
        rows.append((
            f"P{p}+",
            100 * np.mean(loop_any[mask]),
            100 * np.mean(gert.dispute_visited[mask]),
        ))
    labels = [r[0] for r in rows]
    loop = [r[1] for r in rows]
    dispute = [r[2] for r in rows]
    x = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(x - width/2, loop, width, label="Loop-bearing")
    ax.bar(x + width/2, dispute, width, label="Dispute-bearing")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Share of tail outcomes (%)")
    ax.set_title("Structural Composition of Successful Upper-Tail Outcomes")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    return fig


def outcome_probability_convergence_figure(gert: GertResult):
    n = len(gert.totals)
    checkpoints = [1000, 5000, 10000, 20000, 30000, 40000, n]
    checkpoints = sorted(set(c for c in checkpoints if c <= n))
    probs = [100 * np.mean(gert.outcome_codes[:c] == 1) for c in checkpoints]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(checkpoints, probs, marker="o")
    ax.set_title("GERT–MCS Convergence of Successful-Closeout Probability")
    ax.set_xlabel("Replications")
    ax.set_ylabel("Successful Closeout probability (%)")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig
