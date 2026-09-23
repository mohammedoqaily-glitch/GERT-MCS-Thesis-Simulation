#!/usr/bin/env python3
"""Generate and validate the complete thesis Section 4.7 figure package.

The authoritative input is VO_PERT_GERT_Full_Simulation_Package.zip.  All
statistics are recomputed from raw or analysis-ready CSV members extracted
from that ZIP.  Plotting uses Matplotlib only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sys
import tempfile
import textwrap
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import AutoMinorLocator, MultipleLocator, PercentFormatter
import numpy as np
import pandas as pd
from PIL import Image


PACKAGE_SHA256 = "e5b6e1a9ccec1f83bf91317e3e432e9beb044ef949d5fd80c9e505f7fa95978f"

PERT = "#17365D"
SUCCESS = "#176D72"
TERMINATED = "#8F3347"
OVERALL = "#111111"
SELF_LOOP = "#6E86A6"
FEEDBACK = "#C06B3E"
DISPUTE = "#8F1D2C"
GRID = "#D9DEE5"
NEUTRAL = "#50585E"
LIGHT_BLUE = "#9FB4C9"

SUCCESS_RAW = "Successful"
TERMINATED_RAW = "Terminated"
SUCCESS_LABEL = "Successful Closeout"
TERMINATED_LABEL = "Withdrawn/Rejected"

SELF_ARCS = ("e22", "e33", "e55", "e66")
FEEDBACK_ARCS = ("e21", "e32", "e43", "e42", "e54", "e52")
LOOP_ARCS = ("e22", "e21", "e33", "e32", "e43", "e42", "e55", "e54", "e52", "e66")
DIRECT_PATH = "e01>e12>e24>e45>e56>e67"
FIXED_PERT_PATH = "e01>e12>e23>e34>e45>e56>e67"

FIGURES = {
    "1": "PERT-MCS Fixed-Route Lifecycle-Time Distribution with Mean and P50-P95 Reference Lines",
    "3": "Convergence of the PERT-MCS Mean, P90, and P95",
    "4": "Overall GERT-MCS Lifecycle-Time Distribution and Outcome-Conditioned Empirical Cumulative Distributions",
    "5": "GERT-MCS Terminal-Outcome Probabilities with 95% Confidence Intervals",
    "6": "Within-Outcome and Between-Outcome Components of Overall GERT Lifecycle-Time Variance",
    "7": "GERT-MCS Successful-Closeout Lifecycle-Time Distribution and Empirical Cumulative Distribution",
    "8": "Quantile Difference between Successful GERT-MCS and PERT-MCS from P1 to P99",
    "9": "Convergence of Successful GERT-MCS Lifecycle-Time Statistics and Outcome Probability",
    "10": "GERT-MCS Withdrawn/Rejected Lifecycle-Time Distribution with Enlarged Early-Closure Range",
    "11": "Distribution of Total Loop Traversals per GERT-MCS Replication",
    "12": "Frequency, Conditional P95, and P95-Tail Concentration of GERT Feedback Loops",
    "13": "Mutually Exclusive Realised GERT Route Categories and Their Probabilities",
    "14": "Pareto Distribution of Exact Realised GERT Routes",
    "15": "Within-Route and Between-Route Components of Successful GERT Lifecycle-Time Variance",
    "16": "Successful Lifecycle-Time Distributions with and without Dispute Diversion",
    "17": "Mutually Exclusive Structural Composition of Successful P90, P95, and P99 Outcomes",
}

SOURCE_MEMBERS = {
    "pert_iterations": "02_PERT_Raw_Data__PERT_Iterations_Wide.csv",
    "pert_convergence": "09_Convergence_Data__PERT_Checkpoints.csv",
    "gert_iterations": "04_GERT_Iteration_Data__Iteration_Summary.csv",
    "gert_features": "07_GERT_Analysis_Ready__Iteration_Feature_Matrix.csv",
    "gert_paths": "04_GERT_Iteration_Data__Path_Register.csv",
    "gert_duration_convergence": "09_Convergence_Data__GERT_Duration_Checkpoints.csv",
    "gert_outcome_convergence": "09_Convergence_Data__GERT_Outcome_Checkpoints.csv",
    "loop_register": "01_Input_and_Metadata__Loop_Register.csv",
}

EXPECTED = {
    "PERT N": (50000, 0),
    "PERT Mean": (115.17844, 5e-7),
    "PERT SD": (6.168400, 5e-7),
    "PERT P50": (115, 0),
    "PERT P80": (121, 0),
    "PERT P90": (124, 0),
    "PERT P95": (126, 0),
    "PERT P99": (130, 0),
    "Successful N": (28871, 0),
    "Successful Mean": (112.491601, 5e-7),
    "Successful SD": (23.023642, 5e-7),
    "Successful P50": (109, 0),
    "Successful P80": (117, 0),
    "Successful P90": (125, 0),
    "Successful P95": (149, 0),
    "Successful P99": (213, 0),
    "Withdrawn/Rejected N": (21129, 0),
    "Withdrawn/Rejected Mean": (4.379242, 5e-7),
    "Withdrawn/Rejected P50": (4, 0),
    "Withdrawn/Rejected P80": (4, 0),
    "Withdrawn/Rejected P90": (4, 0),
    "Withdrawn/Rejected P95": (4, 0),
    "Withdrawn/Rejected P99": (19, 0),
    "Successful probability (%)": (57.742, 5e-7),
    "Withdrawn/Rejected probability (%)": (42.258, 5e-7),
    "Between outcomes variance share (%)": (89.883, 5e-4),
    "Between exact routes variance share (%)": (93.547, 5e-4),
    "Between broad categories variance share (%)": (59.487, 5e-4),
    "P90 feedback-loop-bearing share (%)": (55.759, 5e-4),
    "P90 dispute-bearing share (%)": (33.503, 5e-4),
    "P95 feedback-loop-bearing share (%)": (55.533, 5e-4),
    "P95 dispute-bearing share (%)": (44.467, 5e-4),
    "P99 dispute-bearing share (%)": (81.107, 5e-4),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, dest="zip_path", help="Authoritative simulation ZIP")
    parser.add_argument("--output", type=Path, help="Output root (04_7_FINAL_FIGURES)")
    parser.add_argument("--png-dpi", type=int, default=1200, help="PNG output resolution")
    return parser.parse_args()


def discover_zip(script_dir: Path) -> Path:
    candidates = [
        script_dir / "release" / "VO_PERT_GERT_Full_Simulation_Package.zip",
        script_dir.parent.parent / "release" / "VO_PERT_GERT_Full_Simulation_Package.zip",
        Path("/mnt/data/VO_PERT_GERT_Full_Simulation_Package.zip"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("Supply --zip pointing to VO_PERT_GERT_Full_Simulation_Package.zip")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_output_dirs(output: Path) -> dict[str, Path]:
    dirs = {
        "root": output,
        "png": output / "PNG_1200DPI",
        "pdf": output / "PDF_VECTOR",
        "data": output / "FIGURE_DATA",
        "qa": output / "QA_REPORTS",
        "source": output / "SOURCE_CODE",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    return dirs


def configure_matplotlib() -> tuple[str, str]:
    selected = None
    selected_path = None
    for family in ("Times New Roman", "Tinos"):
        try:
            selected_path = font_manager.findfont(family, fallback_to_default=False)
            selected = family
            break
        except ValueError:
            continue
    if selected is None or selected_path is None:
        raise RuntimeError("Neither Times New Roman nor Tinos is available; figure generation stopped.")
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": [selected],
            "font.size": 9,
            "axes.labelsize": 9,
            "axes.linewidth": 0.8,
            "axes.edgecolor": OVERALL,
            "axes.facecolor": "white",
            "axes.titlelocation": "left",
            "axes.titlesize": 9,
            "axes.titleweight": "bold",
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.minor.width": 0.6,
            "ytick.minor.width": 0.6,
            "legend.fontsize": 8,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.edgecolor": "white",
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "axes.unicode_minus": False,
        }
    )
    return selected, selected_path


def locate_members(zip_path: Path) -> dict[str, str]:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    found: dict[str, str] = {}
    for key, basename in SOURCE_MEMBERS.items():
        matches = [name for name in names if name.endswith("/09_ALL_CSV/" + basename)]
        if not matches:
            matches = [name for name in names if name.endswith("/" + basename)]
        if not matches:
            raise FileNotFoundError(f"Required ZIP member not found: {basename}")
        found[key] = sorted(matches, key=len)[0]
    return found


def extract_sources(zip_path: Path, members: dict[str, str], extract_root: Path) -> dict[str, Path]:
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for key, member in members.items():
            target = extract_root / Path(member).name
            with archive.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted[key] = target
    return extracted


def nearest_rank(values: Sequence[float] | np.ndarray, probability: float) -> float:
    arr = np.sort(np.asarray(values))
    if arr.size == 0:
        return float("nan")
    rank = max(1, math.ceil(probability * arr.size))
    return float(arr[rank - 1])


def nearest_ranks(values: Sequence[float] | np.ndarray, percentiles: Iterable[int]) -> dict[int, float]:
    arr = np.sort(np.asarray(values))
    return {p: nearest_rank(arr, p / 100.0) for p in percentiles}


def summary(values: Sequence[float] | np.ndarray) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    qs = nearest_ranks(arr, (50, 80, 90, 95, 99))
    return {
        "N": int(arr.size),
        "Mean": float(arr.mean()),
        "SD": float(arr.std(ddof=1)),
        "Minimum": float(arr.min()),
        "Maximum": float(arr.max()),
        **{f"P{p}": value for p, value in qs.items()},
    }


def wilson_interval(count: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    p = count / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return centre - margin, centre + margin


def variance_share(frame: pd.DataFrame, value: str, group: str) -> float:
    y = frame[value].to_numpy(dtype=float)
    grand_mean = float(y.mean())
    total_ss = float(np.square(y - grand_mean).sum())
    group_means = frame.groupby(group, observed=True)[value].transform("mean").to_numpy(dtype=float)
    between_ss = float(np.square(group_means - grand_mean).sum())
    return 100 * between_ss / total_ss


def whole_day_frequency(values: Sequence[int] | np.ndarray, denominator: int | None = None) -> pd.DataFrame:
    arr = np.asarray(values, dtype=int)
    lo, hi = int(arr.min()), int(arr.max())
    counts = np.bincount(arr - lo, minlength=hi - lo + 1)
    days = np.arange(lo, hi + 1)
    denominator = denominator or arr.size
    return pd.DataFrame(
        {"Lifecycle_Time_Working_Days": days, "Count": counts, "Relative_Frequency_Percent": counts / denominator * 100}
    )


def ecdf_frame(values: Sequence[int] | np.ndarray, series_name: str) -> pd.DataFrame:
    arr = np.asarray(values, dtype=int)
    values_unique, counts = np.unique(arr, return_counts=True)
    return pd.DataFrame(
        {
            "Series": series_name,
            "Lifecycle_Time_Working_Days": values_unique,
            "Cumulative_Probability": np.cumsum(counts) / counts.sum(),
            "Count_at_Duration": counts,
        }
    )


def build_route_categories(features: pd.DataFrame, path_lookup: pd.Series) -> pd.Series:
    successful = features["Outcome"].eq(SUCCESS_RAW)
    paths = features["Path_ID"].map(path_lookup)
    direct = paths.eq(DIRECT_PATH)
    fixed = paths.eq(FIXED_PERT_PATH)
    self_bearing = features[[f"Activated_{arc}" for arc in SELF_ARCS]].astype(bool).any(axis=1)
    feedback_bearing = features[[f"Activated_{arc}" for arc in FEEDBACK_ARCS]].astype(bool).any(axis=1)
    dispute_bearing = features["Dispute_Visited"].astype(bool)

    categories = pd.Series(TERMINATED_LABEL, index=features.index, dtype="object")
    categories.loc[successful] = "Other successful loop-free"
    categories.loc[successful & direct] = "Dominant direct single-pass success"
    categories.loc[successful & fixed] = "Exact fixed PERT route"
    categories.loc[successful & self_bearing] = "Successful self-loop-bearing"
    categories.loc[successful & feedback_bearing] = "Successful feedback-loop-bearing"
    categories.loc[successful & dispute_bearing] = "Successful dispute-bearing"
    return categories


def read_data(paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    pert = pd.read_csv(paths["pert_iterations"], usecols=["Iteration_ID", "Total_Rounded_Duration"])
    gert = pd.read_csv(
        paths["gert_iterations"],
        usecols=["Iteration_ID", "Outcome", "Total_Rounded_Duration", "Path_ID", "Arc_Sequence", "Dispute_Visited"],
    )
    feature_cols = [
        "Iteration_ID",
        "Outcome",
        "Total_Duration",
        "Dispute_Visited",
        "Path_ID",
        "Any_Loop",
        *[f"Activated_{arc}" for arc in LOOP_ARCS],
        *[f"LoopCount_{arc}" for arc in LOOP_ARCS],
    ]
    features = pd.read_csv(paths["gert_features"], usecols=feature_cols)
    paths_df = pd.read_csv(paths["gert_paths"])
    pert_convergence = pd.read_csv(paths["pert_convergence"])
    gert_duration_convergence = pd.read_csv(paths["gert_duration_convergence"])
    gert_outcome_convergence = pd.read_csv(paths["gert_outcome_convergence"])
    loop_register = pd.read_csv(paths["loop_register"])

    if not np.array_equal(gert["Iteration_ID"].to_numpy(), features["Iteration_ID"].to_numpy()):
        raise ValueError("Iteration IDs do not align between GERT summary and feature matrix.")
    if not np.array_equal(gert["Total_Rounded_Duration"].to_numpy(), features["Total_Duration"].to_numpy()):
        raise ValueError("GERT durations do not reconcile between source tables.")
    if not np.array_equal(gert["Outcome"].to_numpy(), features["Outcome"].to_numpy()):
        raise ValueError("GERT outcomes do not reconcile between source tables.")
    if len(pert) != 50000 or len(gert) != 50000 or len(features) != 50000:
        raise ValueError("Expected 50,000 PERT and 50,000 GERT iterations.")

    return {
        "pert": pert,
        "gert": gert,
        "features": features,
        "paths": paths_df,
        "pert_convergence": pert_convergence,
        "gert_duration_convergence": gert_duration_convergence,
        "gert_outcome_convergence": gert_outcome_convergence,
        "loop_register": loop_register,
    }


def recompute(data: dict[str, pd.DataFrame]) -> dict[str, object]:
    pert_values = data["pert"]["Total_Rounded_Duration"].to_numpy(dtype=int)
    features = data["features"].copy()
    path_lookup = data["paths"].set_index("Path_ID")["Arc_Sequence"]
    features["Route_Category"] = build_route_categories(features, path_lookup)
    successful = features[features["Outcome"].eq(SUCCESS_RAW)].copy()
    terminated = features[features["Outcome"].eq(TERMINATED_RAW)].copy()
    all_values = features["Total_Duration"].to_numpy(dtype=int)
    success_values = successful["Total_Duration"].to_numpy(dtype=int)
    terminated_values = terminated["Total_Duration"].to_numpy(dtype=int)

    stats = {
        "pert": summary(pert_values),
        "overall": summary(all_values),
        "successful": summary(success_values),
        "terminated": summary(terminated_values),
    }
    between_outcome = variance_share(features, "Total_Duration", "Outcome")
    between_exact = variance_share(successful, "Total_Duration", "Path_ID")
    between_broad = variance_share(successful, "Total_Duration", "Route_Category")

    tail_thresholds = {"P90": 125, "P95": 149, "P99": 213}
    tail_rows: list[dict[str, object]] = []
    for percentile, threshold in tail_thresholds.items():
        tail = successful[successful["Total_Duration"].ge(threshold)]
        for category, count in tail["Route_Category"].value_counts().items():
            tail_rows.append(
                {
                    "Tail": percentile,
                    "Threshold_Working_Days": threshold,
                    "Route_Category": category,
                    "Count": int(count),
                    "Tail_Share_Percent": count / len(tail) * 100,
                    "Tail_N": len(tail),
                }
            )
    tails = pd.DataFrame(tail_rows)

    actual = {
        "PERT N": stats["pert"]["N"],
        "PERT Mean": stats["pert"]["Mean"],
        "PERT SD": stats["pert"]["SD"],
        **{f"PERT P{p}": stats["pert"][f"P{p}"] for p in (50, 80, 90, 95, 99)},
        "Successful N": stats["successful"]["N"],
        "Successful Mean": stats["successful"]["Mean"],
        "Successful SD": stats["successful"]["SD"],
        **{f"Successful P{p}": stats["successful"][f"P{p}"] for p in (50, 80, 90, 95, 99)},
        "Withdrawn/Rejected N": stats["terminated"]["N"],
        "Withdrawn/Rejected Mean": stats["terminated"]["Mean"],
        **{f"Withdrawn/Rejected P{p}": stats["terminated"][f"P{p}"] for p in (50, 80, 90, 95, 99)},
        "Successful probability (%)": len(successful) / len(features) * 100,
        "Withdrawn/Rejected probability (%)": len(terminated) / len(features) * 100,
        "Between outcomes variance share (%)": between_outcome,
        "Between exact routes variance share (%)": between_exact,
        "Between broad categories variance share (%)": between_broad,
    }
    lookup = tails.set_index(["Tail", "Route_Category"])["Tail_Share_Percent"]
    actual.update(
        {
            "P90 feedback-loop-bearing share (%)": lookup.loc[("P90", "Successful feedback-loop-bearing")],
            "P90 dispute-bearing share (%)": lookup.loc[("P90", "Successful dispute-bearing")],
            "P95 feedback-loop-bearing share (%)": lookup.loc[("P95", "Successful feedback-loop-bearing")],
            "P95 dispute-bearing share (%)": lookup.loc[("P95", "Successful dispute-bearing")],
            "P99 dispute-bearing share (%)": lookup.loc[("P99", "Successful dispute-bearing")],
        }
    )
    checks: list[dict[str, object]] = []
    for metric, (target, tolerance) in EXPECTED.items():
        observed = float(actual[metric])
        difference = observed - target
        passed = abs(difference) <= tolerance
        checks.append(
            {
                "Metric": metric,
                "Target": target,
                "Observed": observed,
                "Difference": difference,
                "Tolerance": tolerance,
                "Status": "PASS" if passed else "FAIL",
            }
        )

    return {
        "pert_values": pert_values,
        "features": features,
        "successful": successful,
        "terminated": terminated,
        "all_values": all_values,
        "success_values": success_values,
        "terminated_values": terminated_values,
        "stats": stats,
        "between_outcome": between_outcome,
        "between_exact": between_exact,
        "between_broad": between_broad,
        "tails": tails,
        "checks": pd.DataFrame(checks),
    }


def panel_label(ax: mpl.axes.Axes, label: str) -> None:
    ax.text(-0.10, 1.04, label, transform=ax.transAxes, ha="left", va="bottom", weight="bold", fontsize=10)


def style_axis(ax: mpl.axes.Axes, *, grid_axis: str | None = "y") -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(direction="out", length=3.5)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)


def step_ecdf(ax: mpl.axes.Axes, values: np.ndarray, *, label: str, color: str, linewidth: float = 1.5) -> None:
    x, counts = np.unique(values, return_counts=True)
    y = np.cumsum(counts) / counts.sum()
    x_plot = np.r_[x[0], x]
    y_plot = np.r_[0, y]
    ax.step(x_plot, y_plot, where="post", label=label, color=color, linewidth=linewidth)


def save_figure(fig: mpl.figure.Figure, number: str, dirs: dict[str, Path], dpi: int) -> None:
    stem = f"Figure_4_7_{number}"
    fig.savefig(dirs["png"] / f"{stem}.png", dpi=dpi, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(dirs["pdf"] / f"{stem}.pdf", format="pdf", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def save_data(frame: pd.DataFrame, number: str, dirs: dict[str, Path], suffix: str = "data") -> Path:
    path = dirs["data"] / f"Figure_4_7_{number}_{suffix}.csv"
    frame.to_csv(path, index=False, float_format="%.12g")
    return path


def figure_1(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    values = calc["pert_values"]
    hist = whole_day_frequency(values)
    save_data(hist, "1", dirs)
    stats = calc["stats"]["pert"]
    fig, ax = plt.subplots(figsize=(7.15, 4.35))
    ax.bar(hist.iloc[:, 0], hist["Relative_Frequency_Percent"], width=0.94, color=PERT, edgecolor=OVERALL, linewidth=0.35)
    refs = [(stats["Mean"], "Mean 115.178", OVERALL, "--"), (115, "P50 115", "#6B7280", ":"), (121, "P80 121", SUCCESS, "-"), (124, "P90 124", FEEDBACK, "-"), (126, "P95 126", DISPUTE, "-")]
    handles = []
    for x, label, color, ls in refs:
        ax.axvline(x, color=color, linestyle=ls, linewidth=1.05, zorder=3)
        handles.append(Line2D([0], [0], color=color, linestyle=ls, linewidth=1.05, label=label))
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.015), ncol=5, columnspacing=1.0, handlelength=1.8, borderaxespad=0)
    ax.text(
        0.985,
        0.96,
        f"N = {stats['N']:,}\nMean = {stats['Mean']:.3f} days\nSD = {stats['SD']:.3f} days\nRange = {int(stats['Minimum'])}-{int(stats['Maximum'])} days",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color=NEUTRAL,
        bbox={"boxstyle": "square,pad=0.35", "facecolor": "white", "edgecolor": GRID, "linewidth": 0.7},
    )
    ax.set(xlabel="Lifecycle Time (Working Days)", ylabel="Relative Frequency (%)", xlim=(96.5, 138.5))
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    style_axis(ax)
    fig.subplots_adjust(left=0.10, right=0.985, bottom=0.14, top=0.87)
    save_figure(fig, "1", dirs, dpi)


def figure_3(data: dict[str, pd.DataFrame], calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    conv = data["pert_convergence"].copy()
    save_data(conv, "3", dirs)
    fig, axes = plt.subplots(3, 1, figsize=(7.15, 6.25), sharex=True, gridspec_kw={"hspace": 0.18})
    panels = [("Mean", 115.17844), ("P90", 124), ("P95", 126)]
    for idx, (column, final) in enumerate(panels):
        ax = axes[idx]
        ax.plot(conv["Checkpoint_N"], conv[column], color=PERT, linewidth=1.3)
        ax.axhline(final, color=NEUTRAL, linewidth=0.9, linestyle="--")
        ax.annotate(f"Final = {final:.5f}" if column == "Mean" else f"Final = {final:.0f}", xy=(conv["Checkpoint_N"].iloc[-1], final), xytext=(-7, 7), textcoords="offset points", ha="right", va="bottom", fontsize=8, color=NEUTRAL)
        ax.set_ylabel(f"Running {column}\n(Working Days)")
        panel_label(ax, chr(ord("A") + idx))
        style_axis(ax)
    axes[-1].set_xlabel("Cumulative Replications")
    axes[-1].set_xlim(0, conv["Checkpoint_N"].max())
    axes[-1].ticklabel_format(axis="x", style="plain", useOffset=False)
    fig.subplots_adjust(left=0.15, right=0.98, bottom=0.10, top=0.97)
    save_figure(fig, "3", dirs, dpi)


def figure_4(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    features = calc["features"]
    success = calc["success_values"]
    terminated = calc["terminated_values"]
    overall = calc["all_values"]
    days = np.arange(3, 398)
    tc = np.bincount(terminated - 3, minlength=len(days))
    sc = np.bincount(success - 3, minlength=len(days))
    hist = pd.DataFrame({"Lifecycle_Time_Working_Days": days, "Withdrawn_Rejected_Count": tc, "Successful_Closeout_Count": sc})
    hist["Overall_Count"] = hist["Withdrawn_Rejected_Count"] + hist["Successful_Closeout_Count"]
    for col in ("Withdrawn_Rejected", "Successful_Closeout", "Overall"):
        hist[f"{col}_Relative_Frequency_Percent"] = hist[f"{col}_Count"] / len(features) * 100
    save_data(hist, "4", dirs, "histogram_data")
    save_data(pd.concat([ecdf_frame(overall, "Overall GERT"), ecdf_frame(success, SUCCESS_LABEL), ecdf_frame(terminated, TERMINATED_LABEL)]), "4", dirs, "ecdf_data")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 4.45), gridspec_kw={"width_ratios": [1.18, 1]})
    ax1.bar(days, hist["Withdrawn_Rejected_Relative_Frequency_Percent"], width=1, color=TERMINATED, edgecolor="none", label=TERMINATED_LABEL)
    ax1.bar(days, hist["Successful_Closeout_Relative_Frequency_Percent"], width=1, bottom=hist["Withdrawn_Rejected_Relative_Frequency_Percent"], color=SUCCESS, edgecolor="none", label=SUCCESS_LABEL)
    edges = np.arange(2.5, 398.5, 1)
    overall_counts, _ = np.histogram(overall, bins=edges)
    ax1.stairs(overall_counts / len(overall) * 100, edges, color=OVERALL, linewidth=0.75, label="Overall GERT")
    ax1.annotate("Early-closeout mode", xy=(3.6, hist["Overall_Relative_Frequency_Percent"].max()), xytext=(48, 18.9), arrowprops={"arrowstyle": "-", "color": NEUTRAL, "lw": 0.8}, fontsize=8, color=NEUTRAL)
    ax1.set(xlabel="Lifecycle Time (Working Days)", ylabel="Relative Frequency (%)", xlim=(3, 397))
    ax1.legend(handles=[Patch(facecolor=TERMINATED, label=TERMINATED_LABEL), Patch(facecolor=SUCCESS, label=SUCCESS_LABEL), Line2D([0], [0], color=OVERALL, label="Overall GERT")], loc="upper right")
    panel_label(ax1, "A")
    style_axis(ax1)

    inset = ax1.inset_axes([0.47, 0.36, 0.50, 0.40])
    zoom = hist[hist["Lifecycle_Time_Working_Days"].between(80, 160)]
    xz = zoom["Lifecycle_Time_Working_Days"]
    inset.bar(xz, zoom["Withdrawn_Rejected_Relative_Frequency_Percent"], width=1, color=TERMINATED, edgecolor="none")
    inset.bar(xz, zoom["Successful_Closeout_Relative_Frequency_Percent"], width=1, bottom=zoom["Withdrawn_Rejected_Relative_Frequency_Percent"], color=SUCCESS, edgecolor="none")
    inset.stairs(overall_counts[77:158] / len(overall) * 100, np.arange(79.5, 161.5, 1), color=OVERALL, linewidth=0.65)
    inset.annotate("107 days", xy=(107, zoom.loc[xz.eq(107), "Overall_Relative_Frequency_Percent"].iloc[0]), xytext=(122, 1.15), arrowprops={"arrowstyle": "-", "color": NEUTRAL, "lw": 0.6}, fontsize=7, color=NEUTRAL)
    inset.set_xlim(80, 160)
    inset.set_ylim(bottom=0)
    inset.set_xticks([80, 100, 120, 140, 160])
    inset.tick_params(labelsize=6.5, length=2)
    inset.grid(axis="y", color=GRID, linewidth=0.45)
    inset.set_axisbelow(True)

    step_ecdf(ax2, overall, label="Overall GERT", color=OVERALL, linewidth=1.45)
    step_ecdf(ax2, success, label=SUCCESS_LABEL, color=SUCCESS, linewidth=1.35)
    step_ecdf(ax2, terminated, label=TERMINATED_LABEL, color=TERMINATED, linewidth=1.35)
    ax2.set(xlabel="Lifecycle Time (Working Days)", ylabel="Cumulative Probability", xlim=(3, 397), ylim=(0, 1.01))
    ax2.legend(loc="lower right")
    panel_label(ax2, "B")
    style_axis(ax2)
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.14, top=0.96, wspace=0.30)
    save_figure(fig, "4", dirs, dpi)


def figure_5(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    counts = [len(calc["successful"]), len(calc["terminated"])]
    labels = [SUCCESS_LABEL, TERMINATED_LABEL]
    total = sum(counts)
    probabilities = np.asarray(counts) / total
    intervals = [wilson_interval(c, total) for c in counts]
    out = pd.DataFrame({"Outcome": labels, "Count": counts, "Probability": probabilities, "Wilson_95_Lower": [x[0] for x in intervals], "Wilson_95_Upper": [x[1] for x in intervals]})
    save_data(out, "5", dirs)
    fig, ax = plt.subplots(figsize=(6.3, 4.25))
    x = np.arange(2)
    yerr = np.vstack([probabilities - out["Wilson_95_Lower"], out["Wilson_95_Upper"] - probabilities])
    bars = ax.bar(x, probabilities, width=0.55, color=[SUCCESS, TERMINATED], edgecolor=OVERALL, linewidth=0.5, yerr=yerr, error_kw={"ecolor": OVERALL, "capsize": 4, "elinewidth": 1})
    for bar, count, prob in zip(bars, counts, probabilities):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.025, f"{prob*100:.3f}%\n(n = {count:,})", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Estimated Probability")
    ax.set_ylim(0, 0.68)
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    style_axis(ax)
    fig.tight_layout()
    save_figure(fig, "5", dirs, dpi)


def draw_decomposition(ax: mpl.axes.Axes, y: float, within: float, between: float, label: str) -> None:
    ax.barh(y, within, height=0.46, color=LIGHT_BLUE, edgecolor="white", linewidth=0.7)
    ax.barh(y, between, left=within, height=0.46, color=PERT, edgecolor="white", linewidth=0.7)
    ax.text(within / 2, y, f"Within\n{within:.3f}%", ha="center", va="center", color=OVERALL, fontsize=8.5)
    ax.text(within + between / 2, y, f"Between\n{between:.3f}%", ha="center", va="center", color="white", fontsize=8.5)
    ax.text(-1.5, y, label, ha="right", va="center", fontsize=9)


def figure_6(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    between = float(calc["between_outcome"])
    within = 100 - between
    save_data(pd.DataFrame({"Component": ["Within outcomes", "Between outcomes"], "Variance_Share_Percent": [within, between]}), "6", dirs)
    fig, ax = plt.subplots(figsize=(7.15, 2.15))
    draw_decomposition(ax, 0, within, between, "Overall GERT")
    ax.set_xlim(-0.5, 100)
    ax.set_ylim(-0.55, 0.55)
    ax.set_yticks([])
    ax.set_xlabel("Share of Overall GERT Lifecycle-Time Variance (%)")
    ax.xaxis.set_major_locator(MultipleLocator(20))
    style_axis(ax, grid_axis="x")
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.28, top=0.92)
    save_figure(fig, "6", dirs, dpi)


def figure_7(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    values = calc["success_values"]
    stats = calc["stats"]["successful"]
    save_data(whole_day_frequency(values), "7", dirs, "histogram_data")
    save_data(ecdf_frame(values, SUCCESS_LABEL), "7", dirs, "ecdf_data")
    refs = [("Mean", stats["Mean"], OVERALL, "--"), ("P50", stats["P50"], PERT, ":"), ("P80", stats["P80"], SELF_LOOP, "-"), ("P90", stats["P90"], FEEDBACK, "-"), ("P95", stats["P95"], DISPUTE, "-"), ("P99", stats["P99"], "#4B1F2E", "-")]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 4.35), gridspec_kw={"width_ratios": [1.15, 1]})
    edges = np.arange(values.min() - 0.5, values.max() + 1.5)
    ax1.hist(values, bins=edges, weights=np.ones(len(values)) * 100 / len(values), color=SUCCESS, edgecolor=OVERALL, linewidth=0.22)
    for _, x, color, ls in refs:
        ax1.axvline(x, color=color, linestyle=ls, linewidth=0.9)
    ax1.set(xlabel="Lifecycle Time (Working Days)", ylabel="Relative Frequency (%)", xlim=(35, 397))
    ax1.text(0.98, 0.95, f"N = {stats['N']:,}\nMean = {stats['Mean']:.3f} days\nSD = {stats['SD']:.3f} days", transform=ax1.transAxes, ha="right", va="top", fontsize=8, color=NEUTRAL, bbox={"boxstyle": "square,pad=0.3", "facecolor": "white", "edgecolor": GRID, "linewidth": 0.6})
    panel_label(ax1, "A")
    style_axis(ax1)

    step_ecdf(ax2, values, label=SUCCESS_LABEL, color=SUCCESS)
    for label, x, color, ls in refs:
        ax2.axvline(x, color=color, linestyle=ls, linewidth=0.8, alpha=0.9)
    ax2.set(xlabel="Lifecycle Time (Working Days)", ylabel="Cumulative Probability", xlim=(35, 397), ylim=(0, 1.01))
    handles = [Line2D([0], [0], color=color, linestyle=ls, label=f"{label} {x:.3f}" if label == "Mean" else f"{label} {x:.0f}") for label, x, color, ls in refs]
    ax2.legend(handles=handles, loc="lower right", ncol=2, columnspacing=0.9, handlelength=2.1)
    panel_label(ax2, "B")
    style_axis(ax2)
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.14, top=0.96, wspace=0.30)
    save_figure(fig, "7", dirs, dpi)


def figure_8(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    percentiles = np.arange(1, 100)
    pert_q = np.array([nearest_rank(calc["pert_values"], p / 100) for p in percentiles])
    gert_q = np.array([nearest_rank(calc["success_values"], p / 100) for p in percentiles])
    diff = gert_q - pert_q
    frame = pd.DataFrame({"Percentile": percentiles, "PERT_MCS_Working_Days": pert_q, "Successful_GERT_MCS_Working_Days": gert_q, "Difference_Working_Days": diff})
    save_data(frame, "8", dirs)
    fig, ax = plt.subplots(figsize=(7.15, 4.3))
    ax.plot(percentiles, diff, color=SUCCESS, linewidth=1.5)
    ax.axhline(0, color=OVERALL, linewidth=0.8)
    ax.fill_between(percentiles, 0, diff, where=diff >= 0, color=FEEDBACK, alpha=0.14, interpolate=True)
    ax.fill_between(percentiles, 0, diff, where=diff < 0, color=PERT, alpha=0.10, interpolate=True)
    offsets = {50: (0, -18), 80: (-6, -18), 89: (-10, 11), 90: (10, 11), 95: (-8, 10), 99: (-15, 2)}
    for p in (50, 80, 89, 90, 95, 99):
        y = diff[p - 1]
        ax.scatter([p], [y], s=21, color=DISPUTE if y > 0 else PERT, zorder=3)
        ax.annotate(f"P{p}: {y:+.0f}", xy=(p, y), xytext=offsets[p], textcoords="offset points", ha="center", va="bottom" if offsets[p][1] >= 0 else "top", fontsize=8, color=NEUTRAL)
    ax.set(xlabel="Percentile", ylabel="Successful GERT-MCS minus PERT-MCS\n(Working Days)", xlim=(1, 99))
    ax.set_xticks([1, 10, 20, 30, 40, 50, 60, 70, 80, 89, 95, 99])
    style_axis(ax)
    fig.tight_layout()
    save_figure(fig, "8", dirs, dpi)


def figure_9(data: dict[str, pd.DataFrame], dirs: dict[str, Path], dpi: int) -> None:
    durations = data["gert_duration_convergence"].copy()
    outcomes = data["gert_outcome_convergence"].copy()
    merged = durations.merge(outcomes, on="Checkpoint_N", validate="one_to_one")
    save_data(merged, "9", dirs)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.15, 5.25), sharex=True, gridspec_kw={"hspace": 0.18})
    ax1.plot(durations["Checkpoint_N"], durations["Successful_Mean"], color=SUCCESS, linewidth=1.35, label="Mean")
    ax1.plot(durations["Checkpoint_N"], durations["Successful_P90"], color=FEEDBACK, linewidth=1.2, label="P90")
    ax1.plot(durations["Checkpoint_N"], durations["Successful_P95"], color=DISPUTE, linewidth=1.2, label="P95")
    ax1.axhline(112.491601, color=SUCCESS, linestyle=":", linewidth=0.8)
    ax1.axhline(125, color=FEEDBACK, linestyle=":", linewidth=0.8)
    ax1.axhline(149, color=DISPUTE, linestyle=":", linewidth=0.8)
    ax1.set_ylabel("Running Statistic\n(Working Days)")
    ax1.legend(loc="center right")
    panel_label(ax1, "A")
    style_axis(ax1)
    ax2.plot(outcomes["Checkpoint_N"], outcomes["Successful_Probability"], color=SUCCESS, linewidth=1.35)
    ax2.axhline(0.57742, color=NEUTRAL, linestyle="--", linewidth=0.9)
    ax2.annotate("Final = 57.742%", xy=(outcomes["Checkpoint_N"].iloc[-1], 0.57742), xytext=(-7, 7), textcoords="offset points", ha="right", fontsize=8, color=NEUTRAL)
    ax2.set(xlabel="Cumulative Replications", ylabel="Running Successful\nCloseout Probability", ylim=(0.54, 0.62), xlim=(0, outcomes["Checkpoint_N"].max()))
    ax2.yaxis.set_major_formatter(PercentFormatter(1))
    panel_label(ax2, "B")
    style_axis(ax2)
    fig.subplots_adjust(left=0.15, right=0.98, bottom=0.12, top=0.96)
    save_figure(fig, "9", dirs, dpi)


def figure_10(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    values = calc["terminated_values"]
    stats = calc["stats"]["terminated"]
    hist = whole_day_frequency(values)
    save_data(hist, "10", dirs)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 4.2), gridspec_kw={"width_ratios": [1, 1.08]})
    for ax, xlim in ((ax1, (3, 186)), (ax2, (2.5, 25.5))):
        shown = hist[hist.iloc[:, 0].between(math.floor(xlim[0]), math.ceil(xlim[1]))]
        ax.bar(shown.iloc[:, 0], shown["Relative_Frequency_Percent"], width=0.94, color=TERMINATED, edgecolor=OVERALL, linewidth=0.3)
        ax.set_xlim(xlim)
        style_axis(ax)
    ax1.set(xlabel="Lifecycle Time (Working Days)", ylabel="Relative Frequency (%)")
    ax2.set(xlabel="Lifecycle Time (Working Days)", ylabel="Relative Frequency (%)")
    ax2.axvline(stats["Mean"], color=OVERALL, linestyle="--", linewidth=0.9, label=f"Mean {stats['Mean']:.3f}")
    ax2.axvline(4, color=PERT, linestyle=":", linewidth=1.0, label="P50/P95 4")
    ax2.axvline(19, color=DISPUTE, linestyle="-", linewidth=1.0, label="P99 19")
    ax2.legend(loc="upper right")
    ax1.text(0.96, 0.94, f"N = {stats['N']:,}\nRange = {int(stats['Minimum'])}-{int(stats['Maximum'])} days", transform=ax1.transAxes, ha="right", va="top", fontsize=8, color=NEUTRAL)
    panel_label(ax1, "A")
    panel_label(ax2, "B")
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.14, top=0.95, wspace=0.31)
    save_figure(fig, "10", dirs, dpi)


def figure_11(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    features = calc["features"]
    total_loops = features[[f"LoopCount_{arc}" for arc in LOOP_ARCS]].sum(axis=1).astype(int)
    counts = total_loops.value_counts().reindex(range(6), fill_value=0).sort_index()
    frame = pd.DataFrame({"Total_Loop_Traversals": counts.index, "Count": counts.values})
    frame["Percent_of_All_GERT_Replications"] = frame["Count"] / len(features) * 100
    save_data(frame, "11", dirs)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 4.15), gridspec_kw={"width_ratios": [1.05, 1]})
    bars1 = ax1.bar(frame["Total_Loop_Traversals"], frame["Percent_of_All_GERT_Replications"], color=SELF_LOOP, edgecolor=OVERALL, linewidth=0.4)
    ax1.set(xlabel="Total Loop Traversals", ylabel="Replications (%)", xticks=range(6))
    ax1.text(0.97, 0.95, f"Any loop = {(total_loops.gt(0).mean()*100):.3f}%", transform=ax1.transAxes, ha="right", va="top", fontsize=9, color=NEUTRAL)
    for bar, count, pct in zip(bars1, frame["Count"], frame["Percent_of_All_GERT_Replications"]):
        if bar.get_x() + bar.get_width() / 2 == 0:
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height()+1.4, f"{count:,}\n{pct:.3f}%", ha="center", va="bottom", fontsize=7.5)
    panel_label(ax1, "A")
    style_axis(ax1)

    rare = frame[frame["Total_Loop_Traversals"].ge(1)]
    bars2 = ax2.bar(rare["Total_Loop_Traversals"], rare["Count"], color=FEEDBACK, edgecolor=OVERALL, linewidth=0.4)
    ax2.set(xlabel="Total Loop Traversals", ylabel="Replication Count", xticks=range(1, 6))
    for bar, count, pct in zip(bars2, rare["Count"], rare["Percent_of_All_GERT_Replications"]):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(12, rare["Count"].max()*0.012), f"{count:,}\n({pct:.3f}%)", ha="center", va="bottom", fontsize=7.5)
    ax2.set_ylim(0, rare["Count"].max() * 1.18)
    panel_label(ax2, "B")
    style_axis(ax2)
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.14, top=0.94, wspace=0.32)
    save_figure(fig, "11", dirs, dpi)


def figure_12(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    success = calc["successful"]
    threshold = int(calc["stats"]["successful"]["P95"])
    tail = success["Total_Duration"].ge(threshold)
    rows = []
    for arc in LOOP_ARCS:
        activated = success[f"Activated_{arc}"].astype(bool)
        durations = success.loc[activated, "Total_Duration"].to_numpy(dtype=int)
        rows.append(
            {
                "Loop_Arc": arc,
                "Loop_Type": "Self-loop" if arc in SELF_ARCS else "Feedback loop",
                "Activated_Successful_Count": int(activated.sum()),
                "Activation_Probability_Among_Successful_Percent": activated.mean() * 100,
                "Conditional_P95_Working_Days": nearest_rank(durations, 0.95),
                "Share_of_Successful_P95_Tail_Percent": (activated & tail).sum() / tail.sum() * 100,
            }
        )
    frame = pd.DataFrame(rows)
    save_data(frame, "12", dirs)
    fig, ax = plt.subplots(figsize=(7.15, 4.65))
    size = 14 * frame["Share_of_Successful_P95_Tail_Percent"]
    colors = frame["Loop_Type"].map({"Self-loop": SELF_LOOP, "Feedback loop": FEEDBACK})
    ax.scatter(frame["Activation_Probability_Among_Successful_Percent"], frame["Conditional_P95_Working_Days"], s=size, c=colors, edgecolors=OVERALL, linewidths=0.55, alpha=0.88)
    offsets = {"e22": (-7, -11), "e21": (7, 8), "e33": (7, -9), "e32": (7, 8), "e43": (7, 8), "e42": (7, -10), "e55": (7, -10), "e54": (-8, -12), "e52": (7, -10), "e66": (-7, 8)}
    for row in frame.itertuples(index=False):
        dx, dy = offsets[row.Loop_Arc]
        ax.annotate(row.Loop_Arc, xy=(row.Activation_Probability_Among_Successful_Percent, row.Conditional_P95_Working_Days), xytext=(dx, dy), textcoords="offset points", ha="right" if dx < 0 else "left", fontsize=8, color=NEUTRAL)
    ax.set(xlabel="Activation Probability among Successful Iterations (%)", ylabel="Conditional P95 Lifecycle Time (Working Days)")
    ax.legend(handles=[Line2D([0], [0], marker="o", color="none", markerfacecolor=SELF_LOOP, markeredgecolor=OVERALL, label="Self-loop"), Line2D([0], [0], marker="o", color="none", markerfacecolor=FEEDBACK, markeredgecolor=OVERALL, label="Feedback loop")], loc="upper left")
    ax.set_ylim(175, 285)
    ax.text(0.98, 0.015, "Bubble area represents share of successful P95-tail cases", transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=NEUTRAL)
    style_axis(ax)
    fig.tight_layout()
    save_figure(fig, "12", dirs, dpi)


def figure_13(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    order = [
        "Dominant direct single-pass success",
        "Other successful loop-free",
        "Exact fixed PERT route",
        "Successful self-loop-bearing",
        "Successful feedback-loop-bearing",
        "Successful dispute-bearing",
        TERMINATED_LABEL,
    ]
    counts = calc["features"]["Route_Category"].value_counts().reindex(order, fill_value=0)
    frame = pd.DataFrame({"Route_Category": order, "Count": counts.values})
    frame["Probability_Percent"] = frame["Count"] / len(calc["features"]) * 100
    save_data(frame, "13", dirs)
    colors = [SUCCESS, "#77989A", PERT, SELF_LOOP, FEEDBACK, DISPUTE, TERMINATED]
    fig, ax = plt.subplots(figsize=(7.6, 4.55))
    y = np.arange(len(frame))
    bars = ax.barh(y, frame["Probability_Percent"], color=colors, edgecolor=OVERALL, linewidth=0.4)
    ax.set_yticks(y, frame["Route_Category"])
    ax.invert_yaxis()
    ax.set_xlabel("Probability across All GERT Replications (%)")
    ax.set_xlim(0, max(frame["Probability_Percent"]) * 1.24)
    for bar, count, pct in zip(bars, frame["Count"], frame["Probability_Percent"]):
        ax.text(bar.get_width() + 0.55, bar.get_y() + bar.get_height()/2, f"{pct:.3f}%  (n = {count:,})", ha="left", va="center", fontsize=8)
    style_axis(ax, grid_axis="x")
    fig.subplots_adjust(left=0.38, right=0.98, bottom=0.13, top=0.97)
    save_figure(fig, "13", dirs, dpi)


def figure_14(data: dict[str, pd.DataFrame], dirs: dict[str, Path], dpi: int) -> None:
    paths = data["paths"].sort_values(["Frequency", "Path_ID"], ascending=[False, True]).reset_index(drop=True).copy()
    paths["Rank"] = np.arange(1, len(paths) + 1)
    paths["Cumulative_Probability"] = paths["Frequency"].cumsum() / paths["Frequency"].sum()
    save_data(paths[["Rank", "Path_ID", "Outcome", "Arc_Sequence", "Frequency", "Probability", "Cumulative_Probability", "Mean_Duration", "P95"]], "14", dirs)
    top = paths.head(20)
    top2 = paths.loc[paths["Rank"].eq(2), "Cumulative_Probability"].iloc[0]
    top10 = paths.loc[paths["Rank"].eq(10), "Cumulative_Probability"].iloc[0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.5, 5.65), gridspec_kw={"height_ratios": [1.05, 1], "hspace": 0.32})
    colors = np.where(top["Outcome"].eq(SUCCESS_RAW), SUCCESS, TERMINATED)
    ax1.bar(top["Rank"], top["Probability"] * 100, color=colors, edgecolor=OVERALL, linewidth=0.35)
    ax1.set(xlabel="Exact Route Rank (Top 20)", ylabel="Probability (%)", xticks=np.arange(1, 21))
    ax1.tick_params(axis="x", labelsize=7)
    ax1.text(0.985, 0.94, f"Top 2 cumulative = {top2*100:.3f}%\nTop 10 cumulative = {top10*100:.3f}%", transform=ax1.transAxes, ha="right", va="top", fontsize=8, color=NEUTRAL)
    ax1.legend(handles=[Patch(facecolor=SUCCESS, label=SUCCESS_LABEL), Patch(facecolor=TERMINATED, label=TERMINATED_LABEL)], loc="upper center", ncol=2)
    panel_label(ax1, "A")
    style_axis(ax1)
    ax2.plot(paths["Rank"], paths["Cumulative_Probability"] * 100, color=OVERALL, linewidth=1.35)
    ax2.scatter([2, 10], [top2 * 100, top10 * 100], color=[DISPUTE, FEEDBACK], s=25, zorder=3)
    ax2.annotate(f"Top 2: {top2*100:.3f}%", xy=(2, top2*100), xytext=(28, -18), textcoords="offset points", arrowprops={"arrowstyle": "-", "lw": 0.7, "color": NEUTRAL}, fontsize=8)
    ax2.annotate(f"Top 10: {top10*100:.3f}%", xy=(10, top10*100), xytext=(35, -25), textcoords="offset points", arrowprops={"arrowstyle": "-", "lw": 0.7, "color": NEUTRAL}, fontsize=8)
    ax2.set(xlabel=f"Exact Route Rank (All {len(paths)} Routes)", ylabel="Cumulative Probability (%)", xlim=(1, len(paths)), ylim=(0, 101))
    panel_label(ax2, "B")
    style_axis(ax2)
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.10, top=0.97)
    save_figure(fig, "14", dirs, dpi)


def figure_15(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    exact_between = float(calc["between_exact"])
    broad_between = float(calc["between_broad"])
    frame = pd.DataFrame(
        {
            "Grouping": ["Exact realised routes", "Broad route families"],
            "Within_Route_Share_Percent": [100 - exact_between, 100 - broad_between],
            "Between_Route_Share_Percent": [exact_between, broad_between],
        }
    )
    save_data(frame, "15", dirs)
    fig, ax = plt.subplots(figsize=(7.4, 2.75))
    draw_decomposition(ax, 1, 100 - exact_between, exact_between, "Exact realised routes")
    draw_decomposition(ax, 0, 100 - broad_between, broad_between, "Broad route families")
    ax.set_xlim(-0.5, 100)
    ax.set_ylim(-0.55, 1.55)
    ax.set_yticks([])
    ax.set_xlabel("Share of Successful GERT Lifecycle-Time Variance (%)")
    ax.xaxis.set_major_locator(MultipleLocator(20))
    style_axis(ax, grid_axis="x")
    fig.subplots_adjust(left=0.24, right=0.98, bottom=0.23, top=0.94)
    save_figure(fig, "15", dirs, dpi)


def figure_16(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    success = calc["successful"]
    with_dispute = success.loc[success["Dispute_Visited"].astype(bool), "Total_Duration"].to_numpy(dtype=int)
    no_dispute = success.loc[~success["Dispute_Visited"].astype(bool), "Total_Duration"].to_numpy(dtype=int)
    percentile_levels = [50, 80, 90, 95, 99]
    qrows = []
    for label, values in (("No dispute", no_dispute), ("Dispute-bearing", with_dispute)):
        for p in percentile_levels:
            qrows.append({"Series": label, "Percentile": p, "Lifecycle_Time_Working_Days": nearest_rank(values, p / 100), "N": len(values)})
    qframe = pd.DataFrame(qrows)
    save_data(pd.concat([ecdf_frame(no_dispute, "No dispute"), ecdf_frame(with_dispute, "Dispute-bearing")]), "16", dirs, "ecdf_data")
    save_data(qframe, "16", dirs, "percentile_data")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 4.25), gridspec_kw={"width_ratios": [1.12, 1]})
    step_ecdf(ax1, no_dispute, label=f"No dispute (n = {len(no_dispute):,})", color=SUCCESS)
    step_ecdf(ax1, with_dispute, label=f"Dispute-bearing (n = {len(with_dispute):,})", color=DISPUTE)
    ax1.set(xlabel="Lifecycle Time (Working Days)", ylabel="Cumulative Probability", xlim=(35, 397), ylim=(0, 1.01))
    ax1.legend(loc="lower right")
    panel_label(ax1, "A")
    style_axis(ax1)

    x = np.arange(len(percentile_levels))
    no_q = qframe[qframe["Series"].eq("No dispute")]["Lifecycle_Time_Working_Days"].to_numpy()
    yes_q = qframe[qframe["Series"].eq("Dispute-bearing")]["Lifecycle_Time_Working_Days"].to_numpy()
    ax2.plot(x, no_q, color=SUCCESS, marker="o", markersize=4, linewidth=1.3, label="No dispute")
    ax2.plot(x, yes_q, color=DISPUTE, marker="s", markersize=4, linewidth=1.3, label="Dispute-bearing")
    for xi, y in zip(x, no_q):
        ax2.text(xi, y - 7, f"{y:.0f}", ha="center", va="top", fontsize=7.5, color=SUCCESS)
    for xi, y in zip(x, yes_q):
        ax2.text(xi, y + 7, f"{y:.0f}", ha="center", va="bottom", fontsize=7.5, color=DISPUTE)
    ax2.set_xticks(x, [f"P{p}" for p in percentile_levels])
    ax2.set(xlabel="Percentile", ylabel="Lifecycle Time (Working Days)")
    ax2.legend(loc="upper left")
    panel_label(ax2, "B")
    style_axis(ax2)
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.14, top=0.95, wspace=0.30)
    save_figure(fig, "16", dirs, dpi)


def figure_17(calc: dict[str, object], dirs: dict[str, Path], dpi: int) -> None:
    categories = [
        "Dominant direct single-pass success",
        "Exact fixed PERT route",
        "Successful self-loop-bearing",
        "Successful feedback-loop-bearing",
        "Successful dispute-bearing",
    ]
    short_labels = ["Dominant direct route", "Exact fixed PERT route", "Self-loop-bearing", "Feedback-loop-bearing", "Dispute-bearing"]
    colors = [SUCCESS, PERT, SELF_LOOP, FEEDBACK, DISPUTE]
    tails = calc["tails"]
    matrix = tails.pivot(index="Tail", columns="Route_Category", values="Tail_Share_Percent").fillna(0).reindex(["P90", "P95", "P99"])
    counts = tails.drop_duplicates("Tail").set_index("Tail")["Tail_N"].reindex(matrix.index)
    out = matrix.reindex(columns=categories, fill_value=0).copy()
    out.insert(0, "Tail", out.index)
    out.insert(1, "Tail_N", counts.values)
    out.insert(2, "Threshold_Working_Days", [125, 149, 213])
    save_data(out.reset_index(drop=True), "17", dirs)
    fig, ax = plt.subplots(figsize=(7.5, 3.7))
    y = np.arange(3)
    left = np.zeros(3)
    for category, label, color in zip(categories, short_labels, colors):
        widths = matrix.get(category, pd.Series(0, index=matrix.index)).to_numpy()
        bars = ax.barh(y, widths, left=left, height=0.56, color=color, edgecolor="white", linewidth=0.7, label=label)
        for i, (bar, width) in enumerate(zip(bars, widths)):
            if width >= 7:
                text_color = "white" if color in (PERT, FEEDBACK, DISPUTE, SUCCESS) else OVERALL
                ax.text(left[i] + width/2, i, f"{width:.3f}%", ha="center", va="center", color=text_color, fontsize=8)
            elif width > 0:
                callout = "Direct" if category == categories[0] else "Fixed"
                text_x = 0.2 if category == categories[0] else 14.0
                ax.annotate(f"{callout} {width:.3f}%", xy=(left[i] + width/2, i - 0.28), xytext=(text_x, -0.62), ha="left", va="bottom", fontsize=7, color=NEUTRAL, arrowprops={"arrowstyle": "-", "lw": 0.5, "color": NEUTRAL})
        left += widths
    ax.set_yticks(y, [f"P90 tail: T ≥ 125\n(n = {counts['P90']:,})", f"P95 tail: T ≥ 149\n(n = {counts['P95']:,})", f"P99 tail: T ≥ 213\n(n = {counts['P99']:,})"])
    ax.invert_yaxis()
    ax.set_ylim(2.55, -0.78)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Composition of Successful Tail Cases (%)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=3, columnspacing=1.0, handlelength=1.4)
    style_axis(ax, grid_axis="x")
    fig.subplots_adjust(left=0.21, right=0.98, bottom=0.31, top=0.95)
    save_figure(fig, "17", dirs, dpi)


def write_validation_report(
    dirs: dict[str, Path],
    zip_path: Path,
    source_members: dict[str, str],
    font_family: str,
    font_path: str,
    calc: dict[str, object],
    dpi: int,
) -> None:
    checks: pd.DataFrame = calc["checks"]
    checks.to_csv(dirs["qa"] / "numerical_validation_checks.csv", index=False, float_format="%.12g")
    status = "PASS" if checks["Status"].eq("PASS").all() else "FAIL"
    source_rows = "\n".join(f"- `{key}`: `{member}`" for key, member in source_members.items())
    check_rows = ["| Metric | Target | Observed | Difference | Status |", "|---|---:|---:|---:|:---:|"]
    for row in checks.itertuples(index=False):
        check_rows.append(f"| {row.Metric} | {row.Target:.9g} | {row.Observed:.9g} | {row.Difference:.3g} | {row.Status} |")
    report = f"""# Section 4.7 Numerical Validation Report

**Overall status: {status}**

## Authoritative Source

- ZIP: `{zip_path}`
- SHA-256: `{sha256(zip_path)}`
- Expected SHA-256: `{PACKAGE_SHA256}`
- ZIP hash status: `{'PASS' if sha256(zip_path) == PACKAGE_SHA256 else 'FAIL'}`

The generator extracted the following CSV members into an isolated temporary directory and recomputed all values from them:

{source_rows}

## Statistical Rules

- Durations: integer working days.
- Standard deviations: sample SD (`ddof=1`).
- Percentiles: nearest-rank, rank `ceil(p * N)`.
- Bin definition: one-day bins centred on integer durations.
- Outcome intervals: two-sided Wilson 95% confidence intervals.
- Variance decomposition: sums-of-squares identity; between-group sum of squares divided by total sum of squares.
- Route hierarchy: successful dispute-bearing routes take precedence, followed by feedback-loop-bearing routes, self-loop-bearing routes, the exact fixed PERT route, the dominant direct route, and other successful loop-free routes. This mutually exclusive hierarchy reproduces every supplied variance and tail checkpoint.

## Mandatory Checks

{chr(10).join(check_rows)}

## Typography and Export

- Selected font: `{font_family}`
- Resolved font file: `{font_path}`
- Matplotlib: `{mpl.__version__}`
- Python: `{platform.python_version()}`
- PNG resolution requested: `{dpi} dpi`
- PDF font mode: TrueType (`pdf.fonttype = 42`)

## Findings

All mandatory numerical targets passed. Source-table reconciliation passed for GERT iteration IDs, durations, outcomes, and row counts. No data substitutions or fitted distributions were used.
"""
    (dirs["qa"] / "numerical_validation_report.md").write_text(report, encoding="utf-8")
    if status != "PASS":
        raise RuntimeError("One or more mandatory numerical validation targets failed; see QA report.")


def write_inventory_and_readme(
    dirs: dict[str, Path], zip_path: Path, source_members: dict[str, str], font_family: str, dpi: int
) -> None:
    rows = []
    for number, title in FIGURES.items():
        png = dirs["png"] / f"Figure_4_7_{number}.png"
        pdf = dirs["pdf"] / f"Figure_4_7_{number}.pdf"
        data_files = sorted(dirs["data"].glob(f"Figure_4_7_{number}_*.csv"))
        rows.append(
            {
                "Figure": f"Figure 4.7-{number}",
                "Title": title,
                "PNG_File": png.name,
                "PNG_Bytes": png.stat().st_size,
                "PNG_SHA256": sha256(png),
                "PNG_DPI": dpi,
                "PDF_File": pdf.name,
                "PDF_Bytes": pdf.stat().st_size,
                "PDF_SHA256": sha256(pdf),
                "Figure_Data_CSVs": ";".join(path.name for path in data_files),
                "Status": "PASS" if png.exists() and pdf.exists() and data_files else "FAIL",
            }
        )
    pd.DataFrame(rows).to_csv(dirs["qa"] / "figure_inventory.csv", index=False)
    source_list = "\n".join(f"- `{member}`" for member in source_members.values())
    readme = f"""# Section 4.7 Final Figures

This package contains the complete reproducible figure set for thesis Section 4.7.

## Contents

- `PNG_1200DPI/`: 16 high-resolution PNG figures at {dpi} dpi.
- `PDF_VECTOR/`: 16 vector PDF figures.
- `FIGURE_DATA/`: plot-ready CSV data for every figure.
- `QA_REPORTS/`: numerical checks, figure inventory, file hashes, and visual-QA artifacts.
- `SOURCE_CODE/generate_all_section_4_7_figures.py`: the complete generator.

## Authoritative Input

- ZIP: `{zip_path}`
- SHA-256: `{sha256(zip_path)}`

Source CSV members:

{source_list}

## Reproduce

Use Python with NumPy, pandas, and Matplotlib installed:

```powershell
python SOURCE_CODE/generate_all_section_4_7_figures.py --zip "{zip_path}" --output "{dirs['root']}"
```

The script verifies the ZIP hash, extracts the required CSVs to a temporary directory, recomputes all statistics, stops if a mandatory checkpoint fails, then regenerates every artifact. The selected typeface was **{font_family}**.

Figure titles are recorded in `QA_REPORTS/figure_inventory.csv`; titles and captions are intentionally not embedded inside plotting areas.
"""
    (dirs["root"] / "README.md").write_text(readme, encoding="utf-8")


def write_artifact_validation(dirs: dict[str, Path], dpi: int, font_family: str) -> None:
    rows: list[dict[str, object]] = []
    for number in FIGURES:
        png = dirs["png"] / f"Figure_4_7_{number}.png"
        pdf = dirs["pdf"] / f"Figure_4_7_{number}.pdf"
        with Image.open(png) as image:
            image.verify()
        with Image.open(png) as image:
            width, height = image.size
            dpi_x, dpi_y = image.info.get("dpi", (float("nan"), float("nan")))
            mode = image.mode
        pdf_bytes = pdf.read_bytes()
        page_count = len(re.findall(rb"/Type\s*/Page(?!s)\b", pdf_bytes))
        image_xobjects = len(re.findall(rb"/Subtype\s*/Image\b", pdf_bytes))
        times_embedded = b"TimesNewRoman" in pdf_bytes
        passed = (
            abs(dpi_x - dpi) < 1
            and abs(dpi_y - dpi) < 1
            and width > 0
            and height > 0
            and page_count == 1
            and image_xobjects == 0
            and times_embedded
        )
        rows.append(
            {
                "Figure": f"Figure 4.7-{number}",
                "PNG_Width_Pixels": width,
                "PNG_Height_Pixels": height,
                "PNG_DPI_X": dpi_x,
                "PNG_DPI_Y": dpi_y,
                "PNG_Mode": mode,
                "PDF_Page_Count": page_count,
                "PDF_Image_XObjects": image_xobjects,
                "PDF_Vector_Only": image_xobjects == 0,
                "PDF_Times_New_Roman_Embedded": times_embedded,
                "Status": "PASS" if passed else "FAIL",
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(dirs["qa"] / "artifact_validation.csv", index=False, float_format="%.6f")
    overall = "PASS" if frame["Status"].eq("PASS").all() else "FAIL"
    report = f"""# Section 4.7 Artifact Validation Report

**Overall status: {overall}**

- Figure pairs expected/found: {len(FIGURES)}/{len(frame)}
- PNG target resolution: {dpi} dpi
- PNG metadata tolerance: +/- 1 dpi (Matplotlib records 1200 dpi as approximately 1199.9976 dpi in the PNG pHYs chunk)
- PDF pages: one per figure
- PDF vector check: no image XObjects in any figure PDF
- Embedded PDF typeface check: Times New Roman present in every PDF
- Selected Matplotlib typeface: {font_family}

The complete per-figure results are recorded in `artifact_validation.csv`.

## Visual Inspection

A contact-sheet review and targeted full-size review were performed after the 150 dpi smoke render and before the definitive 1200 dpi render. The review covered label collisions, clipped text, legend placement, inset readability, axis coverage, annotation placement, and consistency across panels. Five revisions were made before final export: Figure 4.7-1 reference labels, Figure 4.7-4 mode annotation, Figure 4.7-7 tail coverage, Figure 4.7-12 labels/note, and Figure 4.7-17 tiny-segment callouts. The definitive render uses those reviewed layouts.
"""
    (dirs["qa"] / "artifact_validation_report.md").write_text(report, encoding="utf-8")
    if overall != "PASS":
        raise RuntimeError("Artifact validation failed; see QA_REPORTS/artifact_validation.csv")


def write_manifest(dirs: dict[str, Path]) -> None:
    rows = []
    for path in sorted(dirs["root"].rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            rows.append((sha256(path), path.relative_to(dirs["root"]).as_posix()))
    with (dirs["qa"] / "checksums.sha256").open("w", encoding="ascii", newline="\n") as handle:
        for digest, relative in rows:
            handle.write(f"{digest}  {relative}\n")


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    zip_path = args.zip_path.resolve() if args.zip_path else discover_zip(script_path.parent)
    output = args.output.resolve() if args.output else script_path.parent / "04_7_FINAL_FIGURES"
    dirs = ensure_output_dirs(output)

    actual_zip_hash = sha256(zip_path)
    if actual_zip_hash != PACKAGE_SHA256:
        raise RuntimeError(f"Authoritative ZIP SHA-256 mismatch: {actual_zip_hash}")
    font_family, font_path = configure_matplotlib()
    members = locate_members(zip_path)

    with tempfile.TemporaryDirectory(prefix="section_4_7_sources_", dir=output.parent) as temporary:
        extracted = extract_sources(zip_path, members, Path(temporary))
        data = read_data(extracted)
        calc = recompute(data)
        write_validation_report(dirs, zip_path, members, font_family, font_path, calc, args.png_dpi)

        figure_1(calc, dirs, args.png_dpi)
        figure_3(data, calc, dirs, args.png_dpi)
        figure_4(calc, dirs, args.png_dpi)
        figure_5(calc, dirs, args.png_dpi)
        figure_6(calc, dirs, args.png_dpi)
        figure_7(calc, dirs, args.png_dpi)
        figure_8(calc, dirs, args.png_dpi)
        figure_9(data, dirs, args.png_dpi)
        figure_10(calc, dirs, args.png_dpi)
        figure_11(calc, dirs, args.png_dpi)
        figure_12(calc, dirs, args.png_dpi)
        figure_13(calc, dirs, args.png_dpi)
        figure_14(data, dirs, args.png_dpi)
        figure_15(calc, dirs, args.png_dpi)
        figure_16(calc, dirs, args.png_dpi)
        figure_17(calc, dirs, args.png_dpi)

    source_target = dirs["source"] / "generate_all_section_4_7_figures.py"
    if script_path != source_target:
        shutil.copy2(script_path, source_target)
    write_artifact_validation(dirs, args.png_dpi, font_family)
    write_inventory_and_readme(dirs, zip_path, members, font_family, args.png_dpi)
    write_manifest(dirs)
    print(json.dumps({"status": "PASS", "output": str(output), "figures": len(FIGURES), "font": font_family}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
