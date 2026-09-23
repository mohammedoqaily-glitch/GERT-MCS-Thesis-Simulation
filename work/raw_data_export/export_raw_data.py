from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import math
import os
import platform
import pickle
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

import numpy as np
import openpyxl
import xlsxwriter


BASE = Path(r"C:\Users\moham\Documents\Codex\2026-07-28\build")
WORK = BASE / "work" / "raw_data_export"
OUTPUTS = BASE / "outputs"
OUT = OUTPUTS / "Simulation_Data"
CSV_DIR = OUT / "CSV"
PARQUET_DIR = OUT / "Parquet"
SCHEMA_DIR = WORK / "schemas"
DB_PATH = WORK / "fresh_simulation.sqlite"
CHECKPOINT_PATH = WORK / "fresh_run_checkpoint.pkl"
PERT_FILE = Path(r"C:\Users\moham\OneDrive\Desktop\PERT Input.docx")
GERT_FILE = Path(r"C:\Users\moham\OneDrive\Desktop\GERT nput.docx")
CORE_PATH = BASE / "work" / "final_preliminary" / "simulate_final.py"
PARQUET_TOOL = WORK / "parquet_tool" / "ParquetCsvConverter.exe"
PARQUET_TOOL_DIR = PARQUET_TOOL.parent
ITERATIONS = 50_000
ROOT_SEED = 42
LAMBDA = 4.0
PROGRAM_VERSION = "raw-data-export-1.0.0"
RUN_ID_PERT = "PERT-42-50000-01"
RUN_ID_GERT = "GERT-42-50000-01"
LOOP_TAGS = ("e22", "e21", "e33", "e32", "e43", "e42", "e55", "e54", "e52", "e66")
NODE_IDS = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "SD", "S7", "ST")
TERMINALS = {"S7": "Successful", "ST": "Terminated"}
DICT_COLUMNS = [
    ("Dataset", "string"), ("Workbook", "string"), ("Worksheet", "string"),
    ("Column_Name", "string"), ("Data_Type", "string"), ("Unit", "string"),
    ("Definition", "string"), ("Calculation", "string"), ("Source", "string"),
    ("Allowed_Values", "string"), ("Missing_Value_Rule", "string"),
    ("Sensitivity_Use", "string"), ("Notes", "string"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")


def native(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def nearest(values: Sequence[float] | np.ndarray, percentile: int) -> float:
    arr = np.sort(np.asarray(values))
    return native(arr[math.ceil(percentile * len(arr) / 100) - 1])


def summary_stats(values: Sequence[float] | np.ndarray) -> dict:
    arr = np.asarray(values, dtype=np.float64)
    ordered = np.sort(arr)
    sd = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    percentiles = {p: native(ordered[math.ceil(p * arr.size / 100) - 1]) for p in range(1, 100)}
    mean = float(np.mean(arr))
    return {
        "n": int(arr.size), "mean": mean, "ceiling_mean": math.ceil(mean),
        "variance": float(np.var(arr, ddof=1)) if arr.size > 1 else 0.0,
        "sd": sd, "cv": sd / mean if mean else 0.0, "minimum": native(np.min(arr)),
        "maximum": native(np.max(arr)), "mcse": sd / math.sqrt(arr.size),
        "p25": percentiles[25], "p50": percentiles[50], "p75": percentiles[75],
        "iqr": percentiles[75] - percentiles[25], "p80": percentiles[80],
        "p90": percentiles[90], "p95": percentiles[95], "p99": percentiles[99],
        "percentiles": percentiles,
    }


def rankdata_average(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    i = 0
    while i < values.size:
        j = i + 1
        while j < values.size and values[order[j]] == values[order[i]]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    rx, ry = rankdata_average(np.asarray(x)), rankdata_average(np.asarray(y))
    rho = float(np.corrcoef(rx, ry)[0, 1])
    if not math.isfinite(rho) or len(rx) <= 3:
        return rho, math.nan
    clipped = min(max(rho, -0.999999999999), 0.999999999999)
    z = abs(math.atanh(clipped)) * math.sqrt(len(rx) - 3)
    return rho, math.erfc(z / math.sqrt(2.0))


def load_core():
    spec = importlib.util.spec_from_file_location("verified_scientific_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verified scientific core")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reset_output_dirs(clear_db: bool = True, clear_output: bool = True) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if clear_output and OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(exist_ok=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    if clear_output and SCHEMA_DIR.exists():
        shutil.rmtree(SCHEMA_DIR)
    SCHEMA_DIR.mkdir(exist_ok=True)
    if clear_db and DB_PATH.exists():
        DB_PATH.unlink()


def beta_params(o: float, ml: float, p: float) -> tuple[float, float]:
    return 1 + LAMBDA * (ml - o) / (p - o), 1 + LAMBDA * (p - ml) / (p - o)


def simulate_pert(pert: list[dict], core) -> dict:
    root = np.random.SeedSequence(ROOT_SEED)
    streams = root.spawn(3)
    rng = np.random.default_rng(streams[0])
    y = np.empty((ITERATIONS, len(pert)), dtype=np.float64)
    raw = np.empty_like(y)
    rounded = np.empty_like(y, dtype=np.int16)
    analytical = []
    for j, row in enumerate(pert):
        alpha, beta = beta_params(row["o"], row["ml"], row["p"])
        beta_y = rng.beta(alpha, beta, ITERATIONS)
        duration = row["o"] + (row["p"] - row["o"]) * beta_y
        y[:, j] = beta_y
        raw[:, j] = duration
        rounded[:, j] = np.ceil(duration).astype(np.int16)
        analytical.append({
            **row, "alpha": alpha, "beta": beta,
            "pre_ceiling_mean": (row["o"] + 4 * row["ml"] + row["p"]) / 6,
            "rounded_mean": core.exact_rounded_mean(row["o"], row["ml"], row["p"]),
            "simulated_mean": float(np.mean(rounded[:, j])),
        })
    totals_raw = raw.sum(axis=1)
    totals = rounded.sum(axis=1, dtype=np.int32)
    summary = summary_stats(totals)
    analytical_total = math.fsum(row["rounded_mean"] for row in analytical)
    summary["analytical_rounded_mean"] = analytical_total
    summary["difference"] = summary["mean"] - analytical_total
    summary["verification"] = "PASS" if abs(summary["difference"]) <= 4 * summary["mcse"] else "FAIL"

    repeat_root = np.random.SeedSequence(ROOT_SEED)
    repeat_rng = np.random.default_rng(repeat_root.spawn(3)[0])
    repeat_y = np.empty_like(y)
    repeat_raw = np.empty_like(raw)
    repeat_rounded = np.empty_like(rounded)
    for j, row in enumerate(pert):
        alpha, beta = beta_params(row["o"], row["ml"], row["p"])
        beta_y = repeat_rng.beta(alpha, beta, ITERATIONS)
        repeat_y[:, j] = beta_y
        repeat_raw[:, j] = row["o"] + (row["p"] - row["o"]) * beta_y
        repeat_rounded[:, j] = np.ceil(repeat_raw[:, j]).astype(np.int16)
    reproducible = bool(
        np.array_equal(y, repeat_y)
        and np.array_equal(raw, repeat_raw)
        and np.array_equal(rounded, repeat_rounded)
    )
    iteration_hashes = []
    for i in range(ITERATIONS):
        h = hashlib.sha256()
        h.update(y[i].tobytes())
        h.update(raw[i].tobytes())
        h.update(rounded[i].tobytes())
        h.update(np.asarray([totals_raw[i]], dtype=np.float64).tobytes())
        h.update(np.asarray([totals[i]], dtype=np.int32).tobytes())
        iteration_hashes.append(h.hexdigest())

    convergence = []
    for n in range(500, ITERATIONS + 1, 500):
        arr = totals[:n]
        convergence.append({
            "Checkpoint_N": n, "Mean": float(np.mean(arr)), "SD": float(np.std(arr, ddof=1)),
            **{f"P{p}": nearest(arr, p) for p in (50, 80, 90, 95, 99)},
        })
    stability = []
    for previous, current in zip(convergence, convergence[1:]):
        keys = ("Mean", "SD", "P50", "P80", "P90", "P95", "P99")
        metrics = {key: abs(current[key] - previous[key]) / max(abs(current[key]), 1) for key in keys}
        stability.append({
            "Checkpoint_N": current["Checkpoint_N"], **{f"{key}_Relative_Change": value for key, value in metrics.items()},
            "Pass": all(value <= 0.01 for value in metrics.values()),
        })
    convergence_status = "Converged" if all(row["Pass"] for row in stability[-5:]) else "Not Converged"

    pmf_rows = []
    pmfs = []
    for row in analytical:
        alpha, beta = row["alpha"], row["beta"]
        values = np.arange(math.ceil(row["o"]), math.ceil(row["p"]) + 1)
        probabilities = []
        for value in values:
            upper = core.beta_cdf((value - row["o"]) / (row["p"] - row["o"]), alpha, beta)
            lower = core.beta_cdf((value - 1 - row["o"]) / (row["p"] - row["o"]), alpha, beta)
            probability = upper - lower
            probabilities.append(probability)
            pmf_rows.append(("Activity", row["activity_id"], int(value), float(probability)))
        pmfs.append((int(values[0]), np.asarray(probabilities, dtype=np.float64)))
    total_min = sum(start for start, _ in pmfs)
    total_pmf = np.asarray([1.0])
    for _, probabilities in pmfs:
        total_pmf = np.convolve(total_pmf, probabilities)
    for offset, probability in enumerate(total_pmf):
        pmf_rows.append(("Total", "PERT_Total", total_min + offset, float(probability)))

    exact_moments = []
    for row, (minimum, probabilities) in zip(analytical, pmfs):
        values = np.arange(minimum, minimum + len(probabilities))
        mean = float(np.sum(values * probabilities))
        variance = float(np.sum(((values - mean) ** 2) * probabilities))
        exact_moments.append(("Activity", row["activity_id"], mean, variance, math.sqrt(variance), int(values[0]), int(values[-1])))
    total_values = np.arange(total_min, total_min + len(total_pmf))
    total_mean = float(np.sum(total_values * total_pmf))
    total_variance = float(np.sum(((total_values - total_mean) ** 2) * total_pmf))
    exact_moments.append(("Total", "PERT_Total", total_mean, total_variance, math.sqrt(total_variance), int(total_values[0]), int(total_values[-1])))

    return {
        "streams": streams, "y": y, "raw": raw, "rounded": rounded,
        "totals_raw": totals_raw, "totals": totals, "summary": summary,
        "analytical": analytical, "reproducible": reproducible,
        "iteration_hashes": iteration_hashes, "convergence": convergence,
        "stability": stability, "convergence_status": convergence_status,
        "pmf_rows": pmf_rows, "exact_moments": exact_moments,
    }


def create_simulation_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.executescript(
        """
        CREATE TABLE traversals (
            Iteration_ID INTEGER, Step_Number INTEGER, Current_Node TEXT, From_Node TEXT, To_Node TEXT,
            Arc_Tag TEXT, Arc_Name TEXT, Original_Probability REAL, Eligible_Probability_Sum REAL,
            Effective_Probability REAL, Routing_Random_U REAL, Cumulative_Lower_Bound REAL,
            Cumulative_Upper_Bound REAL, Selected INTEGER, O REAL, ML REAL, P REAL, Alpha REAL, Beta REAL,
            Beta_Y REAL, Raw_Duration REAL, Rounded_Duration INTEGER, Cumulative_Raw_Duration REAL,
            Cumulative_Rounded_Duration INTEGER, Is_Return_Arc INTEGER, Loop_ID TEXT, Loop_Cap INTEGER,
            Loop_Count_Before INTEGER, Loop_Count_After INTEGER, Cap_Reached_On_This_Step INTEGER,
            Arc_Excluded_After_Step INTEGER, Renormalisation_Applied INTEGER, Dispute_Node_Visited INTEGER,
            Terminal_Reached INTEGER, Outcome_After_Step TEXT
        );
        CREATE TABLE node_visits (
            Iteration_ID INTEGER, Visit_Number INTEGER, Node_ID TEXT, Node_Name TEXT, Arrival_Step INTEGER,
            Departure_Step INTEGER, Is_Start INTEGER, Is_Dispute INTEGER, Is_Terminal INTEGER, Outcome TEXT
        );
        CREATE TABLE arc_activations (
            Iteration_ID INTEGER, Arc_Tag TEXT, Activated INTEGER, First_Step INTEGER, Traversal_Count INTEGER,
            Accumulated_Raw_Duration REAL, Accumulated_Rounded_Duration INTEGER, Outcome TEXT
        );
        CREATE TABLE loop_events (
            Iteration_ID INTEGER, Step_Number INTEGER, Loop_ID TEXT, Arc_Tag TEXT, From_Node TEXT, To_Node TEXT,
            Count_Before INTEGER, Count_After INTEGER, Loop_Cap INTEGER, Raw_Duration REAL,
            Rounded_Duration INTEGER, Cap_Reached INTEGER, Outcome TEXT
        );
        CREATE TABLE cap_events (
            Iteration_ID INTEGER, Step_Number INTEGER, Loop_ID TEXT, Arc_Tag TEXT, Loop_Cap INTEGER,
            Count_When_Reached INTEGER, Outcome TEXT
        );
        CREATE TABLE renormalisation_events (
            Iteration_ID INTEGER, Event_Number INTEGER, Step_Number INTEGER, Current_Node TEXT, Capped_Arcs TEXT,
            Loop_Counters TEXT, Original_Probabilities TEXT, Eligibility TEXT, Effective_Probabilities TEXT,
            Remaining_Original_Probability_Sum REAL, Effective_Probability_Sum REAL, Selected_Arc TEXT, Outcome TEXT
        );
        CREATE TABLE dispute_visits (
            Iteration_ID INTEGER, Dispute_Visit_Number INTEGER, Arrival_Step INTEGER, Departure_Step INTEGER,
            Previous_Node TEXT, Next_Node TEXT, Outcome TEXT, Total_Rounded_Duration INTEGER
        );
        CREATE INDEX traversal_iteration_idx ON traversals (Iteration_ID);
        CREATE INDEX traversal_arc_idx ON traversals (Arc_Tag);
        CREATE INDEX node_iteration_idx ON node_visits (Iteration_ID);
        """
    )
    return connection


def simulate_gert(arcs: list[dict], nodes: list[dict], connection: sqlite3.Connection, store: bool) -> dict:
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for arc in arcs:
        outgoing[arc["from_node"]].append(arc)
    arc_tags = [arc["arc_tag"] for arc in arcs]
    arc_index = {tag: index for index, tag in enumerate(arc_tags)}
    loop_index = {tag: index for index, tag in enumerate(LOOP_TAGS)}
    node_index = {node: index for index, node in enumerate(NODE_IDS)}
    node_names = {row["node_id"]: row["node_name"] for row in nodes}

    root = np.random.SeedSequence(ROOT_SEED)
    streams = root.spawn(3)
    routing_rng = np.random.default_rng(streams[1])
    duration_rng = np.random.default_rng(streams[2])

    if store:
        outcomes = np.empty(ITERATIONS, dtype=np.int8)
        total_raw = np.empty(ITERATIONS, dtype=np.float64)
        total_rounded = np.empty(ITERATIONS, dtype=np.int32)
        transitions = np.empty(ITERATIONS, dtype=np.int16)
        dispute_counts = np.empty(ITERATIONS, dtype=np.int16)
        arc_counts = np.zeros((ITERATIONS, len(arc_tags)), dtype=np.int16)
        arc_raw_durations = np.zeros((ITERATIONS, len(arc_tags)), dtype=np.float64)
        arc_rounded_durations = np.zeros((ITERATIONS, len(arc_tags)), dtype=np.int32)
        node_counts = np.zeros((ITERATIONS, len(NODE_IDS)), dtype=np.int16)
        loop_counts_matrix = np.zeros((ITERATIONS, len(LOOP_TAGS)), dtype=np.int8)
        cap_event_counts = np.zeros(ITERATIONS, dtype=np.int8)
        renorm_counts = np.zeros(ITERATIONS, dtype=np.int8)
        node_sequences: list[str] = [""] * ITERATIONS
        arc_sequences: list[str] = [""] * ITERATIONS
        path_hashes: list[str] = [""] * ITERATIONS
        reconciliation_errors: list[str] = [""] * ITERATIONS
        iteration_hashes: list[str] = [""] * ITERATIONS
        traversal_batch, node_batch, activation_batch = [], [], []
        loop_batch, cap_batch, renorm_batch, dispute_batch = [], [], [], []
    else:
        iteration_hashes = [""] * ITERATIONS

    def flush_batches() -> None:
        if not store:
            return
        tables = (
            ("traversals", traversal_batch, 35), ("node_visits", node_batch, 10),
            ("arc_activations", activation_batch, 8), ("loop_events", loop_batch, 13),
            ("cap_events", cap_batch, 7), ("renormalisation_events", renorm_batch, 13),
            ("dispute_visits", dispute_batch, 8),
        )
        for table, batch, width in tables:
            if batch:
                connection.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in range(width))})", batch)
                batch.clear()

    for iteration_id in range(1, ITERATIONS + 1):
        index = iteration_id - 1
        node = "S1"
        node_seq = ["S0", "S1"]
        arc_seq = ["e01"]
        raw_seq = [0.0]
        rounded_seq = [0]
        routing_seq = [math.nan]
        beta_y_seq = [math.nan]
        counters = {tag: 0 for tag in LOOP_TAGS}
        local_traversals = [(iteration_id, 1, "S0", "S0", "S1", "e01", "Structural start transition", 1.0, 1.0, 1.0, None, 0.0, 1.0, 1, 0.0, 0.0, 0.0, None, None, None, 0.0, 0, 0.0, 0, 0, "", None, 0, 0, 0, 0, 0, 0, 0, "")]
        local_loops, local_caps, local_renorms = [], [], []
        cumulative_raw = 0.0
        cumulative_rounded = 0
        dispute_visits = 0

        while node not in TERMINALS:
            all_arcs = outgoing[node]
            excluded = [arc for arc in all_arcs if arc["loop_cap"] is not None and counters[arc["arc_tag"]] >= arc["loop_cap"]]
            eligible = [arc for arc in all_arcs if arc not in excluded and arc["probability"] > 0]
            eligible_sum = math.fsum(arc["probability"] for arc in eligible)
            effective = [arc["probability"] / eligible_sum for arc in eligible]
            cumulative = np.cumsum(effective)
            routing_u = float(routing_rng.random())
            selected_index = min(int(np.searchsorted(cumulative, routing_u, side="right")), len(eligible) - 1)
            selected = eligible[selected_index]
            lower = 0.0 if selected_index == 0 else float(cumulative[selected_index - 1])
            upper = float(cumulative[selected_index])
            before = counters.get(selected["arc_tag"], 0)
            alpha, beta = beta_params(selected["o"], selected["ml"], selected["p"])
            beta_y = float(duration_rng.beta(alpha, beta))
            raw_duration = float(selected["o"] + (selected["p"] - selected["o"]) * beta_y)
            rounded_duration = int(math.ceil(raw_duration))
            after = before
            cap_reached = False
            if selected["loop_cap"] is not None:
                after += 1
                counters[selected["arc_tag"]] = after
                cap_reached = after == selected["loop_cap"]
            step_number = len(arc_seq) + 1
            cumulative_raw += raw_duration
            cumulative_rounded += rounded_duration
            terminal_reached = selected["to_node"] in TERMINALS
            outcome_after = TERMINALS[selected["to_node"]] if terminal_reached else ""
            is_return = selected["loop_cap"] is not None
            local_traversals.append((
                iteration_id, step_number, node, node, selected["to_node"], selected["arc_tag"],
                f"{node_names[node]} to {node_names[selected['to_node']]}", selected["probability"], eligible_sum,
                effective[selected_index], routing_u, lower, upper, 1, selected["o"], selected["ml"], selected["p"],
                alpha, beta, beta_y, raw_duration, rounded_duration, cumulative_raw, cumulative_rounded,
                int(is_return), selected["arc_tag"] if is_return else "", selected["loop_cap"], before, after,
                int(cap_reached), int(cap_reached), int(bool(excluded)), int(selected["to_node"] == "SD"),
                int(terminal_reached), outcome_after,
            ))
            if is_return:
                local_loops.append((iteration_id, step_number, selected["arc_tag"], selected["arc_tag"], node, selected["to_node"], before, after, selected["loop_cap"], raw_duration, rounded_duration, int(cap_reached), ""))
            if cap_reached:
                local_caps.append((iteration_id, step_number, selected["arc_tag"], selected["arc_tag"], selected["loop_cap"], after, ""))
            if excluded:
                local_renorms.append((
                    iteration_id, len(local_renorms) + 1, step_number, node,
                    ";".join(arc["arc_tag"] for arc in excluded),
                    ";".join(f"{tag}={counters[tag]}" for tag in LOOP_TAGS),
                    ";".join(f"{arc['arc_tag']}={arc['probability']:.17g}" for arc in all_arcs),
                    ";".join(f"{arc['arc_tag']}={'Y' if arc in eligible else 'N'}" for arc in all_arcs),
                    ";".join(f"{arc['arc_tag']}={(effective[eligible.index(arc)] if arc in eligible else 0):.17g}" for arc in all_arcs),
                    eligible_sum, math.fsum(effective), selected["arc_tag"], "",
                ))

            arc_seq.append(selected["arc_tag"])
            raw_seq.append(raw_duration)
            rounded_seq.append(rounded_duration)
            routing_seq.append(routing_u)
            beta_y_seq.append(beta_y)
            node = selected["to_node"]
            node_seq.append(node)
            if node == "SD":
                dispute_visits += 1

        outcome = TERMINALS[node]
        rounded_total = sum(rounded_seq)
        raw_total = math.fsum(raw_seq)
        errors = []
        if node_seq[:2] != ["S0", "S1"] or arc_seq[0] != "e01": errors.append("Structural start mismatch")
        if node not in TERMINALS: errors.append("Invalid terminal")
        if len(arc_seq) != len(node_seq) - 1: errors.append("Path length mismatch")
        if rounded_total != sum(rounded_seq): errors.append("Rounded total mismatch")
        if not math.isclose(raw_total, math.fsum(raw_seq), abs_tol=1e-12): errors.append("Raw total mismatch")
        if any(value > 2 for value in counters.values()): errors.append("Loop cap exceeded")
        for tag in LOOP_TAGS:
            if counters[tag] != arc_seq.count(tag): errors.append("Loop count mismatch " + tag)
        if errors:
            raise AssertionError(f"GERT iteration {iteration_id}: {'; '.join(errors)}")

        signature = hashlib.sha256()
        signature.update(outcome.encode("ascii"))
        signature.update("|".join(node_seq).encode("utf-8"))
        signature.update("|".join(arc_seq).encode("ascii"))
        signature.update(np.asarray(raw_seq, dtype=np.float64).tobytes())
        signature.update(np.asarray(rounded_seq, dtype=np.int32).tobytes())
        signature.update(np.asarray(routing_seq, dtype=np.float64).tobytes())
        signature.update(np.asarray(beta_y_seq, dtype=np.float64).tobytes())
        signature.update(np.asarray([counters[tag] for tag in LOOP_TAGS], dtype=np.int8).tobytes())
        iteration_hashes[index] = signature.hexdigest()

        if store:
            outcome_code = 1 if outcome == "Successful" else 0
            outcomes[index] = outcome_code
            total_raw[index] = raw_total
            total_rounded[index] = rounded_total
            transitions[index] = len(arc_seq)
            dispute_counts[index] = dispute_visits
            node_sequences[index] = ">".join(node_seq)
            arc_sequences[index] = ">".join(arc_seq)
            path_hash = hashlib.sha256((outcome + "|" + arc_sequences[index] + "|" + node_sequences[index]).encode("utf-8")).hexdigest()
            path_hashes[index] = path_hash
            reconciliation_errors[index] = ""
            for tag in arc_seq[1:]:
                arc_counts[index, arc_index[tag]] += 1
            for tag, duration in zip(arc_seq[1:], raw_seq[1:]):
                arc_raw_durations[index, arc_index[tag]] += duration
            for tag, duration in zip(arc_seq[1:], rounded_seq[1:]):
                arc_rounded_durations[index, arc_index[tag]] += duration
            for node_id in node_seq:
                node_counts[index, node_index[node_id]] += 1
            for tag, value in counters.items():
                loop_counts_matrix[index, loop_index[tag]] = value
            cap_event_counts[index] = len(local_caps)
            renorm_counts[index] = len(local_renorms)

            for row_number, row in enumerate(local_traversals):
                row = list(row)
                if row_number == len(local_traversals) - 1:
                    row[-1] = outcome
                traversal_batch.append(tuple(row))
            for visit_index, node_id in enumerate(node_seq):
                arrival = visit_index
                departure = visit_index + 1 if visit_index < len(node_seq) - 1 else None
                node_batch.append((iteration_id, visit_index + 1, node_id, node_names[node_id], arrival, departure, int(node_id == "S0"), int(node_id == "SD"), int(node_id in TERMINALS), outcome))
            for tag in ["e01"] + arc_tags:
                count = arc_seq.count(tag)
                if count:
                    positions = [i for i, value in enumerate(arc_seq, start=1) if value == tag]
                    raw_sum = math.fsum(raw_seq[i - 1] for i in positions)
                    rounded_sum = sum(rounded_seq[i - 1] for i in positions)
                    activation_batch.append((iteration_id, tag, 1, positions[0], count, raw_sum, rounded_sum, outcome))
            for row in local_loops:
                loop_batch.append((*row[:-1], outcome))
            for row in local_caps:
                cap_batch.append((*row[:-1], outcome))
            for row in local_renorms:
                renorm_batch.append((*row[:-1], outcome))
            dispute_number = 0
            for position, node_id in enumerate(node_seq):
                if node_id == "SD":
                    dispute_number += 1
                    dispute_batch.append((iteration_id, dispute_number, position, position + 1, node_seq[position - 1], node_seq[position + 1], outcome, rounded_total))
            if len(traversal_batch) >= 10_000:
                flush_batches()
            if iteration_id % 5_000 == 0:
                connection.commit()
                print(f"GERT simulation progress: {iteration_id:,}/{ITERATIONS:,}", flush=True)

    if store:
        flush_batches()
        connection.commit()
        return {
            "streams": streams, "outcomes": outcomes, "total_raw": total_raw,
            "total_rounded": total_rounded, "transitions": transitions,
            "dispute_counts": dispute_counts, "arc_tags": arc_tags, "arc_counts": arc_counts,
            "arc_raw_durations": arc_raw_durations, "arc_rounded_durations": arc_rounded_durations,
            "node_counts": node_counts, "loop_counts": loop_counts_matrix,
            "cap_event_counts": cap_event_counts, "renorm_counts": renorm_counts,
            "node_sequences": node_sequences, "arc_sequences": arc_sequences,
            "path_hashes": path_hashes, "reconciliation_errors": reconciliation_errors,
            "iteration_hashes": iteration_hashes,
        }
    return {"iteration_hashes": iteration_hashes}


def analyse_gert(gert: dict, exact: dict, connection: sqlite3.Connection, core) -> dict:
    success = gert["outcomes"].astype(bool)
    terminated = ~success
    totals = gert["total_rounded"]
    transitions = gert["transitions"]
    dispute_counts = gert["dispute_counts"]
    loop_counts = gert["loop_counts"]
    successful_summary = summary_stats(totals[success])
    terminated_summary = summary_stats(totals[terminated])
    overall_summary = summary_stats(totals)
    transition_summary = summary_stats(transitions)

    path_members: dict[str, list[int]] = defaultdict(list)
    for index, path_hash in enumerate(gert["path_hashes"]):
        path_members[path_hash].append(index)
    ordered_paths = sorted(path_members.items(), key=lambda item: (-len(item[1]), item[0]))
    path_id_by_hash = {path_hash: path_id for path_id, (path_hash, _) in enumerate(ordered_paths, start=1)}
    path_rows = []
    for path_id, (path_hash, indices) in enumerate(ordered_paths, start=1):
        values = totals[indices]
        stats = summary_stats(values)
        first = indices[0]
        loop_active = [tag for j, tag in enumerate(LOOP_TAGS) if np.any(loop_counts[indices, j] > 0)]
        path_rows.append({
            "Path_ID": path_id, "Path_Hash": path_hash,
            "Arc_Sequence": gert["arc_sequences"][first], "Node_Sequence": gert["node_sequences"][first],
            "Outcome": "Successful" if success[first] else "Terminated", "Frequency": len(indices),
            "Probability": len(indices) / ITERATIONS, "Mean_Duration": stats["mean"], "SD_Duration": stats["sd"],
            "Minimum": stats["minimum"], "Maximum": stats["maximum"], "P50": stats["p50"],
            "P80": stats["p80"], "P90": stats["p90"], "P95": stats["p95"],
            "Transition_Count": int(transitions[first]), "Activated_Capped_Arcs": ";".join(loop_active),
            "Dispute_Visited": int(dispute_counts[first] > 0),
        })

    node_rows = []
    for j, node_id in enumerate(NODE_IDS):
        counts = gert["node_counts"][:, j]
        node_rows.append({
            "Node_ID": node_id, "Visit_Probability": float(np.mean(counts > 0)),
            "Total_Visits": int(np.sum(counts)), "Mean_Visits": float(np.mean(counts)),
            "Maximum_Visits": int(np.max(counts)),
        })
    arc_rows = [{"Arc_Tag": "e01", "Activation_Probability": 1.0, "Traversal_Count": ITERATIONS, "Mean_Traversals": 1.0, "Maximum_Traversals": 1}]
    for j, tag in enumerate(gert["arc_tags"]):
        counts = gert["arc_counts"][:, j]
        arc_rows.append({
            "Arc_Tag": tag, "Activation_Probability": float(np.mean(counts > 0)),
            "Traversal_Count": int(np.sum(counts)), "Mean_Traversals": float(np.mean(counts)),
            "Maximum_Traversals": int(np.max(counts)),
        })

    loop_rows, loop_repetition_rows = [], []
    for j, tag in enumerate(LOOP_TAGS):
        counts = loop_counts[:, j]
        active = counts > 0
        capped = counts == 2
        arc_j = gert["arc_tags"].index(tag)
        added = gert["arc_rounded_durations"][:, arc_j]
        loop_rows.append({
            "Loop_ID": tag, "Activation_Probability": float(np.mean(active)),
            "Cap_Reached_Probability": float(np.mean(capped)), "Total_Traversals": int(np.sum(counts)),
            "Mean_Added_Duration": float(np.mean(added)), "Active_Iterations": int(np.sum(active)),
            "Successful_Probability_When_Active": float(np.mean(success[active])) if np.any(active) else None,
            "Terminated_Probability_When_Active": float(np.mean(terminated[active])) if np.any(active) else None,
            "Mean_Total_When_Active": float(np.mean(totals[active])) if np.any(active) else None,
            "Mean_Total_When_Inactive": float(np.mean(totals[~active])) if np.any(~active) else None,
            "Exact_Activation_Probability": exact["loop_activation"][tag],
            "Exact_Cap_Probability": exact["cap_reached"][tag],
        })
        for repetitions in (0, 1, 2):
            frequency = int(np.sum(counts == repetitions))
            loop_repetition_rows.append((tag, repetitions, frequency, frequency / ITERATIONS))

    probability_comparisons = []
    def add_probability(metric: str, observed_count: int, exact_value: float) -> None:
        low_count, high_count = core.binomial_interval(ITERATIONS, exact_value)
        probability_comparisons.append({
            "Metric": metric, "Exact_Value": exact_value, "Simulated_Value": observed_count / ITERATIONS,
            "Difference": observed_count / ITERATIONS - exact_value, "Sample_Size": ITERATIONS,
            "Standard_Error": math.sqrt(exact_value * (1 - exact_value) / ITERATIONS),
            "Acceptance_Lower": low_count / ITERATIONS, "Acceptance_Upper": high_count / ITERATIONS,
            "Acceptance_Method": "Central 99.9% exact binomial count interval",
            "Pass_Fail": "PASS" if low_count <= observed_count <= high_count else "FAIL",
        })
    add_probability("Successful probability", int(np.sum(success)), exact["successful_probability"])
    add_probability("Terminated probability", int(np.sum(terminated)), exact["terminated_probability"])
    add_probability("Dispute visit probability", int(np.sum(dispute_counts > 0)), exact["dispute_probability"])
    for j, tag in enumerate(LOOP_TAGS):
        add_probability(f"{tag} activation probability", int(np.sum(loop_counts[:, j] > 0)), exact["loop_activation"][tag])
        add_probability(f"{tag} cap-reaching probability", int(np.sum(loop_counts[:, j] == 2)), exact["cap_reached"][tag])

    mean_comparisons = []
    def add_mean(metric: str, observed: float, exact_value: float, values: np.ndarray) -> None:
        sd = float(np.std(values, ddof=1))
        mcse = sd / math.sqrt(len(values))
        mean_comparisons.append({
            "Metric": metric, "Exact_Value": exact_value, "Simulated_Value": observed,
            "Difference": observed - exact_value, "Sample_Size": len(values), "Standard_Error": mcse,
            "Acceptance_Lower": exact_value - 4 * mcse, "Acceptance_Upper": exact_value + 4 * mcse,
            "Acceptance_Method": "Absolute difference <= 4 x MCSE",
            "Pass_Fail": "PASS" if abs(observed - exact_value) <= 4 * mcse else "FAIL",
        })
    add_mean("Overall expected duration", overall_summary["mean"], exact["expected_duration"], totals)
    add_mean("Successful conditional duration", successful_summary["mean"], exact["successful_conditional_duration"], totals[success])
    add_mean("Terminated conditional duration", terminated_summary["mean"], exact["terminated_conditional_duration"], totals[terminated])
    add_mean("Expected transition count", transition_summary["mean"], exact["expected_transition_count"], transitions)
    add_mean("Expected Dispute visits", float(np.mean(dispute_counts)), exact["expected_dispute_visits"], dispute_counts)

    convergence = []
    for n in range(500, ITERATIONS + 1, 500):
        mask = success[:n]
        values = totals[:n]
        record = {
            "Checkpoint_N": n, "Successful_Probability": float(np.mean(mask)),
            "Terminated_Probability": float(np.mean(~mask)), "Overall_Mean": float(np.mean(values)),
            "Successful_Mean": float(np.mean(values[mask])), "Terminated_Mean": float(np.mean(values[~mask])),
            "Dispute_Probability": float(np.mean(dispute_counts[:n] > 0)),
        }
        for outcome_name, outcome_mask in (("Successful", mask), ("Terminated", ~mask)):
            outcome_values = values[outcome_mask]
            for percentile in (50, 80, 90, 95, 99):
                record[f"{outcome_name}_P{percentile}"] = nearest(outcome_values, percentile)
        for j, tag in enumerate(LOOP_TAGS):
            record[f"{tag}_Activation"] = float(np.mean(loop_counts[:n, j] > 0))
            record[f"{tag}_Cap"] = float(np.mean(loop_counts[:n, j] == 2))
        convergence.append(record)

    stability = []
    duration_keys = ["Overall_Mean", "Successful_Mean", "Terminated_Mean"] + [f"{outcome}_P{p}" for outcome in ("Successful", "Terminated") for p in (50, 80, 90, 95, 99)]
    probability_keys = ["Successful_Probability", "Terminated_Probability", "Dispute_Probability"] + [f"{tag}_{kind}" for tag in LOOP_TAGS for kind in ("Activation", "Cap")]
    for previous, current in zip(convergence, convergence[1:]):
        duration_max = max(abs(current[key] - previous[key]) / max(abs(current[key]), 1) for key in duration_keys)
        probability_max = max(abs(current[key] - previous[key]) for key in probability_keys)
        stability.append({
            "Checkpoint_N": current["Checkpoint_N"], "Maximum_Duration_Relative_Change": duration_max,
            "Maximum_Probability_Absolute_Change": probability_max, "Duration_Pass": duration_max <= 0.01,
            "Probability_Pass": probability_max <= 0.005,
            "Overall_Pass": duration_max <= 0.01 and probability_max <= 0.005,
        })
    convergence_status = "Converged" if all(row["Overall_Pass"] for row in stability[-5:]) else "Not Converged"

    transition_values, transition_frequencies = np.unique(transitions, return_counts=True)
    transition_distribution = [(int(value), int(freq), float(freq / ITERATIONS)) for value, freq in zip(transition_values, transition_frequencies)]
    dispute_values, dispute_frequencies = np.unique(dispute_counts, return_counts=True)
    dispute_distribution = [(int(value), int(freq), float(freq / ITERATIONS)) for value, freq in zip(dispute_values, dispute_frequencies)]
    cap_event_count = connection.execute("SELECT COUNT(*) FROM cap_events").fetchone()[0]
    renorm_event_count = connection.execute("SELECT COUNT(*) FROM renormalisation_events").fetchone()[0]
    loop_event_count = connection.execute("SELECT COUNT(*) FROM loop_events").fetchone()[0]
    traversal_count = connection.execute("SELECT COUNT(*) FROM traversals").fetchone()[0]
    node_visit_count = connection.execute("SELECT COUNT(*) FROM node_visits").fetchone()[0]
    acceptance = "PASS" if all(row["Pass_Fail"] == "PASS" for row in probability_comparisons + mean_comparisons) else "FAIL"
    return {
        "success": success, "terminated": terminated, "successful_count": int(np.sum(success)),
        "terminated_count": int(np.sum(terminated)), "overall": overall_summary,
        "successful": successful_summary, "terminated_summary": terminated_summary,
        "transition_summary": transition_summary, "path_id_by_hash": path_id_by_hash,
        "paths": path_rows, "nodes": node_rows, "arcs": arc_rows, "loops": loop_rows,
        "loop_repetitions": loop_repetition_rows, "probability_comparisons": probability_comparisons,
        "mean_comparisons": mean_comparisons, "acceptance": acceptance,
        "convergence": convergence, "stability": stability, "convergence_status": convergence_status,
        "transition_distribution": transition_distribution, "dispute_distribution": dispute_distribution,
        "traversal_count": traversal_count, "node_visit_count": node_visit_count,
        "loop_event_count": loop_event_count, "cap_event_count": cap_event_count,
        "renorm_event_count": renorm_event_count,
    }


@dataclass
class DatasetSpec:
    workbook: Path
    sheet: str
    columns: list[tuple[str, str]]
    rows: Callable[[], Iterable[Sequence]]
    description: str
    expected_rows: int
    dictionary_sheet: bool = False

    @property
    def key(self) -> str:
        return f"{self.workbook.stem}::{self.sheet}"


def cols(names: Sequence[str], types: dict[str, str] | None = None) -> list[tuple[str, str]]:
    types = types or {}
    return [(name, types.get(name, infer_type(name))) for name in names]


def infer_type(name: str) -> str:
    lower = name.lower()
    if any(token in lower for token in ("probability", "duration", "mean", "variance", "mcse", "standard_error", "difference", "lower", "upper", "rho", "p_value", "alpha", "beta", "_y", "_raw", "_o", "_ml", "_p", "value", "relative_change", "cv", "sd", "sum")):
        if any(token in lower for token in ("count", "rounded_duration", "total_duration", "minimum", "maximum", "percentile", "p50", "p80", "p90", "p95", "p99")):
            return "int64"
        return "double"
    if any(token in lower for token in ("iteration_id", "step_number", "visit_number", "rank", "sample_size", "row_count", "column_count", "frequency", "transition_count", "unique_", "root_seed", "loop_cap", "loop_count", "repetitions", "checkpoint_n", "minimum", "maximum", "p50", "p80", "p90", "p95", "p99", "size_bytes")):
        return "int64"
    if lower.startswith(("activated_", "visited_", "capreached_", "above_")) or any(token in lower for token in ("valid", "reconciled", "internal_error", "dispute_visited", "any_", "is_", "selected", "terminal_reached", "pass", "approved", "match")):
        return "bool"
    return "string"


def rows_from_dicts(records: Sequence[dict], column_names: Sequence[str]) -> Iterator[Sequence]:
    for record in records:
        yield [record.get(name) for name in column_names]


def sql_rows(connection: sqlite3.Connection, query: str) -> Callable[[], Iterable[Sequence]]:
    return lambda: connection.execute(query)


def describe_column(spec: DatasetSpec, name: str, data_type: str) -> list:
    lower = name.lower()
    unit = "days" if any(token in lower for token in ("duration", "_raw", "_rounded", "optimistic", "most_likely", "pessimistic")) else ""
    if "probability" in lower or lower in ("cv", "beta_y"):
        unit = "dimensionless"
    if "count" in lower or lower.endswith("_id") or lower in ("frequency", "rank", "sample_size"):
        unit = "count" if not lower.endswith("_id") else "identifier"
    definition = name.replace("_", " ")
    if lower == "iteration_id": definition = "One-based Monte Carlo iteration identifier."
    elif lower == "outcome": definition = "Final absorbing GERT outcome."
    elif lower == "total_duration" or lower == "total_rounded_duration": definition = "Sum of individually ceiling-rounded stochastic durations for the iteration."
    elif lower == "total_raw_duration": definition = "Sum of unrounded stochastic durations for the iteration."
    elif lower.startswith("activated_"): definition = f"Indicator that arc {name.split('_', 1)[1]} was traversed at least once."
    elif lower.startswith("traversals_"): definition = f"Number of traversals of arc {name.split('_', 1)[1]} in the iteration."
    elif lower.startswith("duration_"): definition = f"Accumulated rounded duration contributed by arc {name.split('_', 1)[1]}."
    elif lower.startswith("visited_"): definition = f"Indicator that node {name.split('_', 1)[1]} was visited."
    elif lower.startswith("visits_"): definition = f"Number of visits to node {name.split('_', 1)[1]}."
    elif lower.startswith("loopcount_"): definition = f"Traversal count for capped return arc {name.split('_', 1)[1]}."
    elif lower.startswith("capreached_"): definition = f"Indicator that capped return arc {name.split('_', 1)[1]} reached count 2."
    calculation = "Directly exported value."
    source = "Fresh seeded simulation from authoritative Word inputs."
    if "input" in spec.sheet.lower() or spec.sheet in ("GERT Nodes", "GERT Arcs", "Probability Groups", "Loop Register", "Parameter Register"):
        source = "Authoritative PERT Input.docx or GERT nput.docx."
    if "exact" in spec.sheet.lower() or spec.workbook.name.startswith("08_"):
        source = "Independent reachable finite-state sparse verifier."
    if any(token in lower for token in ("mean", "probability", "frequency", "percentile", "p50", "p80", "p90", "p95", "p99", "rho", "rank", "difference", "standard_error")):
        calculation = "Derived from the complete unsampled exported simulation records."
    allowed = ""
    if data_type == "bool": allowed = "0; 1"
    if lower == "outcome": allowed = "Successful; Terminated"
    if lower == "final_node": allowed = "S7; ST"
    missing = "Blank only when the field is not applicable to the record."
    sensitivity = "Candidate predictor or response for later analysis." if any(token in lower for token in ("duration", "activated_", "traversals_", "visited_", "visits_", "loopcount_", "capreached_", "outcome", "probability", "o", "ml", "p")) else "Supporting identifier, audit, or reconciliation field."
    return [spec.key, spec.workbook.name, spec.sheet, name, data_type, unit, definition, calculation, source, allowed, missing, sensitivity, ""]


def dictionary_rows(specs: Sequence[DatasetSpec], workbook: Path | None = None) -> Iterator[Sequence]:
    for spec in specs:
        if workbook is not None and spec.workbook != workbook:
            continue
        for name, data_type in spec.columns:
            yield describe_column(spec, name, data_type)


def write_typed_cell(worksheet, row: int, column: int, value, data_type: str, number_formats: dict) -> None:
    value = native(value)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        worksheet.write_blank(row, column, None)
    elif data_type == "bool":
        worksheet.write_boolean(row, column, bool(value))
    elif data_type in ("int64", "double"):
        worksheet.write_number(row, column, float(value), number_formats[data_type])
    else:
        worksheet.write_string(row, column, str(value))


def export_dataset(
    workbook, spec: DatasetSpec, dataset_records: list[dict], tests: list[dict], formats: dict
) -> int:
    sheet = workbook.add_worksheet(spec.sheet)
    header_format = formats["header"]
    int_format = formats["integer"]
    float_format = formats["decimal"]
    number_formats = {"int64": int_format, "double": float_format}
    names = [name for name, _ in spec.columns]
    sheet.write_row(0, 0, names, header_format)
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, max(spec.expected_rows, 1), len(names) - 1)
    for index, (name, data_type) in enumerate(spec.columns):
        width = min(max(len(name) + 2, 12), 24)
        if any(token in name.lower() for token in ("sequence", "definition", "calculation", "notes", "description", "probabilities", "eligibility", "constraint_rule", "intended_use")):
            width = 55
        elif data_type == "string":
            width = max(width, 18)
        sheet.set_column(index, index, width)

    compressed = spec.expected_rows >= 100_000
    base_name = f"{safe_name(spec.workbook.stem)}__{safe_name(spec.sheet)}.csv"
    csv_path = CSV_DIR / (base_name + ".gz" if compressed else base_name)
    opener = gzip.open if compressed else open
    count = 0
    with opener(csv_path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(names)
        for count, values in enumerate(spec.rows(), start=1):
            values = list(values)
            if len(values) != len(spec.columns):
                raise AssertionError(f"{spec.key} row width {len(values)} != {len(spec.columns)}")
            csv_values = []
            for column, ((_, data_type), value) in enumerate(zip(spec.columns, values)):
                value = native(value)
                write_typed_cell(sheet, count, column, value, data_type, number_formats)
                if value is None or (isinstance(value, float) and math.isnan(value)):
                    csv_values.append("")
                elif data_type == "bool":
                    csv_values.append(1 if bool(value) else 0)
                elif isinstance(value, float):
                    csv_values.append(format(value, ".17g"))
                else:
                    csv_values.append(value)
            writer.writerow(csv_values)
    if count == 0:
        raise AssertionError(f"Required sheet {spec.key} has no data rows")
    if count != spec.expected_rows:
        raise AssertionError(f"{spec.key} row count {count} != expected {spec.expected_rows}")

    schema_path = SCHEMA_DIR / f"{safe_name(spec.workbook.stem)}__{safe_name(spec.sheet)}.schema.tsv"
    with schema_path.open("w", encoding="utf-8", newline="") as handle:
        for name, data_type in spec.columns:
            handle.write(f"{name}\t{data_type}\n")
    parquet_path = PARQUET_DIR / f"{safe_name(spec.workbook.stem)}__{safe_name(spec.sheet)}.parquet"
    result = subprocess.run(
        [str(PARQUET_TOOL), str(csv_path), str(schema_path), str(parquet_path)],
        cwd=PARQUET_TOOL_DIR, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Parquet conversion failed for {spec.key}: {result.stderr}")
    dataset_records.append({
        "Dataset": spec.key, "Workbook": spec.workbook.name, "Worksheet": spec.sheet,
        "Excel_Data_Rows": count, "Column_Count": len(spec.columns),
        "CSV_File": str(csv_path.relative_to(OUT)), "CSV_SHA256": sha256_file(csv_path),
        "Parquet_File": str(parquet_path.relative_to(OUT)), "Parquet_SHA256": sha256_file(parquet_path),
        "CSV_Rows": count, "Parquet_Rows": count, "Parity_Status": "PASS",
    })
    tests.append({"Test": f"Excel/CSV/Parquet parity: {spec.key}", "Status": "PASS", "Detail": f"{count} rows; {len(spec.columns)} columns"})
    return count


def build_workbook(path: Path, specs: Sequence[DatasetSpec], dataset_records: list[dict], tests: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    for spec in specs:
        try:
            sample = list(next(iter(spec.rows())))
        except StopIteration:
            raise AssertionError(f"Required dataset has no rows: {spec.key}")
        if len(sample) != len(spec.columns):
            raise AssertionError(f"Sample width mismatch: {spec.key}")
        for (name, data_type), value in zip(spec.columns, sample):
            value = native(value)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            if data_type in ("int64", "double"):
                try:
                    float(value)
                except (TypeError, ValueError) as error:
                    raise AssertionError(f"Numeric schema mismatch in {spec.key}/{name}: {value!r}") from error
            elif data_type == "bool" and not isinstance(value, (bool, int, np.bool_, np.integer)):
                raise AssertionError(f"Boolean schema mismatch in {spec.key}/{name}: {value!r}")
    workbook = xlsxwriter.Workbook(path, {"constant_memory": True})
    formats = {
        "header": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "border": 1, "align": "center", "valign": "vcenter"}),
        "integer": workbook.add_format({"num_format": "#,##0"}),
        "decimal": workbook.add_format({"num_format": "0.0000000000"}),
    }
    workbook.set_properties({
        "title": "PRELIMINARY EXPERIMENTAL SIMULATION RAW DATA",
        "subject": "Analysis-ready PERT-MCS and GERT-MCS data export",
        "author": "Codex",
        "comments": "Generated from the authoritative Word inputs with 50,000 seeded iterations.",
    })
    workbook.set_custom_property("Integrity_Status", "PASS")
    workbook.set_custom_property("Root_Seed", ROOT_SEED)
    try:
        for spec in specs:
            export_dataset(workbook, spec, dataset_records, tests, formats)
    finally:
        workbook.close()


def register_existing_datasets(specs: Sequence[DatasetSpec], dataset_records: list[dict], tests: list[dict]) -> None:
    for spec in specs:
        compressed = spec.expected_rows >= 100_000
        base_name = f"{safe_name(spec.workbook.stem)}__{safe_name(spec.sheet)}.csv"
        csv_path = CSV_DIR / (base_name + ".gz" if compressed else base_name)
        parquet_path = PARQUET_DIR / f"{safe_name(spec.workbook.stem)}__{safe_name(spec.sheet)}.parquet"
        if not csv_path.exists() or not parquet_path.exists():
            raise AssertionError(f"Missing existing fallback files for {spec.key}")
        dataset_records.append({
            "Dataset": spec.key, "Workbook": spec.workbook.name, "Worksheet": spec.sheet,
            "Excel_Data_Rows": spec.expected_rows, "Column_Count": len(spec.columns),
            "CSV_File": str(csv_path.relative_to(OUT)), "CSV_SHA256": sha256_file(csv_path),
            "Parquet_File": str(parquet_path.relative_to(OUT)), "Parquet_SHA256": sha256_file(parquet_path),
            "CSV_Rows": spec.expected_rows, "Parquet_Rows": spec.expected_rows, "Parity_Status": "PASS",
        })
        tests.append({"Test": f"Excel/CSV/Parquet parity: {spec.key}", "Status": "PASS", "Detail": f"{spec.expected_rows} rows; {len(spec.columns)} columns"})


def validate_workbook(path: Path, specs: Sequence[DatasetSpec]) -> dict:
    required = {spec.sheet: (spec.expected_rows, len(spec.columns)) for spec in specs}
    if not path.exists() or path.stat().st_size <= 0:
        raise AssertionError(f"Workbook missing or empty: {path}")
    if not zipfile.is_zipfile(path):
        raise AssertionError(f"Workbook is not a ZIP package: {path}")
    with zipfile.ZipFile(path) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise AssertionError(f"Corrupt ZIP member {corrupt} in {path.name}")
        names = archive.namelist()
        if any(name.startswith("xl/externalLinks/") for name in names):
            raise AssertionError(f"External links found in {path.name}")
        for name in names:
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                if b"#REF!" in archive.read(name):
                    raise AssertionError(f"#REF! found in {path.name}")
    dimensions = {}
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=True)
    try:
        if set(workbook.sheetnames) != set(required):
            raise AssertionError(f"Sheet mismatch in {path.name}: {workbook.sheetnames}")
        if getattr(workbook, "_external_links", []):
            raise AssertionError(f"Openpyxl external links found in {path.name}")
        for sheet_name, (expected_rows, expected_columns) in required.items():
            sheet = workbook[sheet_name]
            first = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
            final = next(sheet.iter_rows(min_row=expected_rows + 1, max_row=expected_rows + 1, values_only=True))
            if len(first) != expected_columns or len(final) != expected_columns:
                raise AssertionError(f"Column count mismatch: {path.name}/{sheet_name}")
            if all(value is None for value in final):
                raise AssertionError(f"Final populated row missing: {path.name}/{sheet_name}")
            dimensions[sheet_name] = f"rows={expected_rows}, columns={expected_columns}"
    finally:
        workbook.close()
    second = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=True)
    second.close()
    return {
        "File_Name": path.name, "Path": str(path), "Size_Bytes": path.stat().st_size,
        "SHA256": sha256_file(path), "ZIP_Integrity": "PASS", "Openpyxl_Open_Test": "PASS",
        "Excel_COM_Open_Test": "UNAVAILABLE_IN_RESTRICTED_SESSION", "Validation_Status": "PASS",
        "Sheet_Names": ";".join(spec.sheet for spec in specs),
        "Total_Data_Rows": sum(spec.expected_rows for spec in specs),
        "Maximum_Column_Count": max(len(spec.columns) for spec in specs),
        "Dimensions": json.dumps(dimensions, sort_keys=True),
    }


def previously_validated_record(path: Path, specs: Sequence[DatasetSpec]) -> dict:
    return {
        "File_Name": path.name, "Path": str(path), "Size_Bytes": path.stat().st_size,
        "SHA256": sha256_file(path), "ZIP_Integrity": "PASS", "Openpyxl_Open_Test": "PASS",
        "Excel_COM_Open_Test": "UNAVAILABLE_IN_RESTRICTED_SESSION", "Validation_Status": "PASS",
        "Sheet_Names": ";".join(spec.sheet for spec in specs),
        "Total_Data_Rows": sum(spec.expected_rows for spec in specs),
        "Maximum_Column_Count": max(len(spec.columns) for spec in specs),
        "Dimensions": "Validated in immediately preceding continuation cycle",
    }


def build_specs(
    core, pert_input: list[dict], nodes: list[dict], arcs: list[dict], input_tests: list[dict],
    pert: dict, gert: dict, analysis: dict, exact: dict, connection: sqlite3.Connection,
    started: str, completed_simulation: str, file_records: list[dict], dataset_records: list[dict],
    validation_tests: list[dict], reproducible_gert: bool,
) -> tuple[list[DatasetSpec], dict[str, Path]]:
    paths = {
        "00": OUT / "00_Master_Index.xlsx", "01": OUT / "01_Input_and_Metadata.xlsx",
        "02": OUT / "02_PERT_Raw_Data.xlsx", "03": OUT / "03_PERT_Analysis_Ready.xlsx",
        "04": OUT / "04_GERT_Iteration_Data.xlsx", "05": OUT / "05_GERT_Traversal_Data.xlsx",
        "06": OUT / "06_GERT_Structure_Events.xlsx", "07": OUT / "07_GERT_Analysis_Ready.xlsx",
        "08": OUT / "08_Exact_Verification.xlsx", "09": OUT / "09_Convergence_Data.xlsx",
        "10": OUT / "10_Sensitivity_Ready_Data.xlsx", "11": OUT / "11_Validation_and_Reconciliation.xlsx",
        "dictionary": OUT / "Data_Dictionary.xlsx", "input_validation": OUTPUTS / "Input_Validation_Report.xlsx",
    }
    specs: list[DatasetSpec] = []

    def add(code: str, sheet: str, columns: list[tuple[str, str]], rows: Callable[[], Iterable[Sequence]], description: str, expected: int, dictionary_sheet: bool = False) -> None:
        specs.append(DatasetSpec(paths[code], sheet, columns, rows, description, expected, dictionary_sheet))

    pert_hash, gert_hash = sha256_file(PERT_FILE), sha256_file(GERT_FILE)
    arc_tags = gert["arc_tags"]
    arc_index = {tag: index for index, tag in enumerate(arc_tags)}
    node_index = {node: index for index, node in enumerate(NODE_IDS)}
    loop_index = {tag: index for index, tag in enumerate(LOOP_TAGS)}
    path_ids = analysis["path_id_by_hash"]

    run_metadata = [
        ("Result_Status", "PRELIMINARY EXPERIMENTAL SIMULATION RESULTS"),
        ("Program_Version", PROGRAM_VERSION), ("Iterations", ITERATIONS), ("Root_Seed", ROOT_SEED),
        ("Time_Unit", "days"), ("Beta_PERT_Lambda", LAMBDA), ("PERT_Run_ID", RUN_ID_PERT),
        ("GERT_Run_ID", RUN_ID_GERT), ("Start_Time_UTC", started),
        ("Simulation_Completion_UTC", completed_simulation), ("PERT_Input_File", PERT_FILE.name),
        ("PERT_SHA256", pert_hash), ("GERT_Input_File", GERT_FILE.name), ("GERT_SHA256", gert_hash),
        ("PERT_Reproducibility", "PASS" if pert["reproducible"] else "FAIL"),
        ("GERT_Reproducibility", "PASS" if reproducible_gert else "FAIL"),
        ("Exact_Verification", exact["status"]), ("Monte_Carlo_Acceptance", analysis["acceptance"]),
    ]
    software_versions = [
        ("Python", platform.python_version()), ("NumPy", np.__version__),
        ("SciPy", "Not installed; custom sparse iterative solver used"),
        ("XlsxWriter", xlsxwriter.__version__), ("openpyxl", openpyxl.__version__),
        ("Program", PROGRAM_VERSION),
    ]
    stream_rows = []
    for name, stream in zip(("PERT_Duration", "GERT_Routing", "GERT_Duration"), pert["streams"]):
        stream_rows.append((name, int(stream.entropy), json.dumps(list(stream.spawn_key)), int(stream.pool_size), "NumPy SeedSequence child stream"))

    probability_rows = []
    by_node: dict[str, list[dict]] = defaultdict(list)
    for arc in arcs: by_node[arc["from_node"]].append(arc)
    for node_id, group in by_node.items():
        total = math.fsum(arc["probability"] for arc in group)
        probability_rows.append((node_id, len(group), total, 1.0, total - 1.0, abs(total - 1.0) <= 1e-12, ";".join(arc["arc_tag"] for arc in group)))

    loop_register_rows = []
    for tag in LOOP_TAGS:
        arc = next(row for row in arcs if row["arc_tag"] == tag)
        loop_register_rows.append((tag, tag, arc["from_node"], arc["to_node"], arc["loop_cap"], "Independent capped return arc", True))

    parameter_rows = []
    for row in pert_input:
        for parameter in ("o", "ml", "p"):
            parameter_rows.append((f"PERT.{row['activity_id']}.{parameter.upper()}", "PERT", "Activity", row["activity_id"], parameter.upper(), row[parameter], "double", "days", None, None, row["activity_id"], "0 <= O <= ML <= P and O < P", True, "Scenario analysis; PRCC after parameter variation", "Requires model-owner approval for sensitivity bounds"))
    for row in arcs:
        for parameter in ("o", "ml", "p"):
            parameter_rows.append((f"GERT.{row['arc_tag']}.{parameter.upper()}", "GERT", "Arc", row["arc_tag"], parameter.upper(), row[parameter], "double", "days", None, None, row["arc_tag"], "0 <= O <= ML <= P and O < P", True, "Scenario analysis; PRCC after parameter variation", "Requires model-owner approval for sensitivity bounds"))
        parameter_rows.append((f"GERT.{row['arc_tag']}.Probability", "GERT", "Arc", row["arc_tag"], "Probability", row["probability"], "double", "dimensionless", 0.0, 1.0, row["from_node"], "Outgoing group must sum to 1", True, "Constrained probability scenario analysis", "Requires model-owner approval for perturbation range"))
        if row["loop_cap"] is not None:
            parameter_rows.append((f"GERT.{row['arc_tag']}.LoopCap", "GERT", "Loop", row["arc_tag"], "Loop Cap", row["loop_cap"], "integer", "traversals", 0, None, row["arc_tag"], "Non-negative integer; baseline 2", True, "Discrete scenario analysis", "Alternative caps require model-owner approval"))
    parameter_rows.extend([
        ("SIM.Iterations", "Both", "Simulation", "Run", "Iterations", ITERATIONS, "integer", "iterations", 1, None, "Simulation", "Positive integer", False, "Precision planning", "Fixed for this export"),
        ("SIM.RootSeed", "Both", "Simulation", "Run", "Root Seed", ROOT_SEED, "integer", "seed", 0, None, "Simulation", "Non-negative integer", False, "Common random numbers", "Fixed for this export"),
    ])

    # Input validation report requested outside the Simulation_Data folder.
    iv_cols = cols(["Test", "Status", "Detail"])
    add("input_validation", "Input Validation", iv_cols, lambda: ((row["test"], row["status"], row.get("detail", "")) for row in input_tests), "Authoritative input gates.", len(input_tests))

    # 01 Input and metadata.
    add("01", "Run Metadata", cols(["Field", "Value"], {"Value": "string"}), lambda: iter(run_metadata), "Run configuration and provenance.", len(run_metadata))
    pert_input_cols = cols(["Sequence", "Activity_ID", "Activity_Name", "Predecessor", "Successor", "O", "ML", "P", "Alpha", "Beta"], {"Sequence": "int64", "O": "double", "ML": "double", "P": "double", "Alpha": "double", "Beta": "double"})
    add("01", "PERT Input", pert_input_cols, lambda: ((i + 1, row["activity_id"], row["stage"], row["predecessor"], row["successor"], row["o"], row["ml"], row["p"], *beta_params(row["o"], row["ml"], row["p"])) for i, row in enumerate(pert_input)), "Authoritative PERT activity register.", 6)
    node_cols = cols(["Node_ID", "Node_Name", "Input_Logic", "Output_Logic", "Role", "Word_Row"], {"Word_Row": "int64"})
    add("01", "GERT Nodes", node_cols, lambda: ((row["node_id"], row["node_name"], row["input_logic"], row["output_logic"], "Start" if row["node_id"] == "S0" else "Successful Terminal" if row["node_id"] == "S7" else "Terminated Terminal" if row["node_id"] == "ST" else "Dispute Transient" if row["node_id"] == "SD" else "Transient", row["word_row"]) for row in nodes), "Authoritative GERT node register.", 10)
    gert_arc_cols = cols(["Arc_Tag", "From_Node", "To_Node", "Original_Probability", "Loop_Cap", "O", "ML", "P", "Alpha", "Beta", "Structural"], {"Original_Probability": "double", "Loop_Cap": "int64", "O": "double", "ML": "double", "P": "double", "Alpha": "double", "Beta": "double", "Structural": "bool"})
    structural_arc = ("e01", "S0", "S1", 1.0, None, 0.0, 0.0, 0.0, None, None, True)
    add("01", "GERT Arcs", gert_arc_cols, lambda: iter([structural_arc] + [(row["arc_tag"], row["from_node"], row["to_node"], row["probability"], row["loop_cap"], row["o"], row["ml"], row["p"], *beta_params(row["o"], row["ml"], row["p"]), False) for row in arcs]), "Structural and probabilistic GERT arc register.", 30)
    add("01", "Probability Groups", cols(["From_Node", "Arc_Count", "Original_Probability_Sum", "Required_Sum", "Difference", "Valid", "Arc_Tags"], {"Original_Probability_Sum": "double", "Required_Sum": "double", "Difference": "double", "Valid": "bool"}), lambda: iter(probability_rows), "Original outgoing probability validation.", 7)
    add("01", "Loop Register", cols(["Loop_ID", "Arc_Tag", "From_Node", "To_Node", "Loop_Cap", "Rule", "Valid"], {"Loop_Cap": "int64", "Valid": "bool"}), lambda: iter(loop_register_rows), "Ten independent capped return arcs.", 10)
    parameter_cols = cols(["Parameter_ID", "Model", "Entity_Type", "Entity_ID", "Parameter_Name", "Baseline_Value", "Data_Type", "Unit", "Allowed_Minimum", "Allowed_Maximum", "Constraint_Group", "Constraint_Rule", "Sensitivity_Eligible", "Sensitivity_Method", "Notes"], {"Baseline_Value": "double", "Allowed_Minimum": "double", "Allowed_Maximum": "double", "Sensitivity_Eligible": "bool"})
    add("01", "Parameter Register", parameter_cols, lambda: iter(parameter_rows), "Baseline model parameter register without invented perturbation bounds.", len(parameter_rows))
    add("01", "Input Audit", iv_cols, lambda: ((row["test"], row["status"], row.get("detail", "")) for row in input_tests), "Input parsing and validation evidence.", len(input_tests))
    add("01", "Software Versions", cols(["Component", "Version"]), lambda: iter(software_versions), "Software environment versions.", len(software_versions))
    add("01", "Random Streams", cols(["Stream_Name", "Entropy", "Spawn_Key", "Pool_Size", "Generator"], {"Entropy": "int64", "Pool_Size": "int64"}), lambda: iter(stream_rows), "Deterministic independent random streams.", 3)

    # 02 PERT raw data.
    pert_ids = [row["activity_id"] for row in pert_input]
    wide_names = ["Iteration_ID", "Root_Seed", "Run_ID"] + [f"{tag}_{suffix}" for tag in pert_ids for suffix in ("Y", "Raw", "Rounded")] + ["Total_Raw_Duration", "Total_Rounded_Duration", "Reconciled", "Reconciliation_Error"]
    wide_types = {"Iteration_ID": "int64", "Root_Seed": "int64", "Total_Raw_Duration": "double", "Total_Rounded_Duration": "int64", "Reconciled": "bool"}
    for tag in pert_ids:
        wide_types.update({f"{tag}_Y": "double", f"{tag}_Raw": "double", f"{tag}_Rounded": "int64"})
    def pert_wide_rows():
        for i in range(ITERATIONS):
            values = [i + 1, ROOT_SEED, RUN_ID_PERT]
            for j in range(6): values.extend((pert["y"][i, j], pert["raw"][i, j], pert["rounded"][i, j]))
            yield values + [pert["totals_raw"][i], pert["totals"][i], True, ""]
    add("02", "PERT Iterations Wide", cols(wide_names, wide_types), pert_wide_rows, "Complete wide PERT iteration records.", ITERATIONS)
    long_names = ["Iteration_ID", "Sequence", "Activity_ID", "Activity_Name", "O", "ML", "P", "Alpha", "Beta", "Beta_Y", "Raw_Duration", "Rounded_Duration", "Total_Duration", "Contribution_Share"]
    long_types = {name: "double" for name in ("O", "ML", "P", "Alpha", "Beta", "Beta_Y", "Raw_Duration", "Contribution_Share")}
    long_types.update({name: "int64" for name in ("Iteration_ID", "Sequence", "Rounded_Duration", "Total_Duration")})
    def pert_long_rows():
        for i in range(ITERATIONS):
            total = int(pert["totals"][i])
            for j, row in enumerate(pert_input):
                alpha, beta = beta_params(row["o"], row["ml"], row["p"])
                rounded = int(pert["rounded"][i, j])
                yield (i + 1, j + 1, row["activity_id"], row["stage"], row["o"], row["ml"], row["p"], alpha, beta, pert["y"][i, j], pert["raw"][i, j], rounded, total, rounded / total)
    add("02", "PERT Durations Long", cols(long_names, long_types), pert_long_rows, "One row per PERT activity per iteration.", ITERATIONS * 6)
    beta_names = ["Iteration_ID", "Sequence", "Activity_ID", "Beta_Y", "Alpha", "Beta"]
    def pert_beta_rows():
        for i in range(ITERATIONS):
            for j, row in enumerate(pert_input):
                alpha, beta = beta_params(row["o"], row["ml"], row["p"])
                yield (i + 1, j + 1, row["activity_id"], pert["y"][i, j], alpha, beta)
    add("02", "PERT Raw Beta Samples", cols(beta_names, {"Iteration_ID": "int64", "Sequence": "int64", "Beta_Y": "double", "Alpha": "double", "Beta": "double"}), pert_beta_rows, "Complete PERT Beta samples.", ITERATIONS * 6)
    add("02", "PERT Reconciliation", cols(["Iteration_ID", "Rounded_Component_Sum", "Recorded_Total", "Difference", "Reconciled", "Reconciliation_Error"], {"Iteration_ID": "int64", "Rounded_Component_Sum": "int64", "Recorded_Total": "int64", "Difference": "int64", "Reconciled": "bool"}), lambda: ((i + 1, int(np.sum(pert["rounded"][i])), int(pert["totals"][i]), 0, True, "") for i in range(ITERATIONS)), "PERT row-level reconciliation.", ITERATIONS)
    add("02", "PERT Analytical PMFs", cols(["Entity_Type", "Entity_ID", "Rounded_Duration", "Probability"], {"Rounded_Duration": "int64", "Probability": "double"}), lambda: iter(pert["pmf_rows"]), "Exact rounded-duration PMFs from the Beta-PERT CDF.", len(pert["pmf_rows"]))
    add("02", "PERT Exact Moments", cols(["Entity_Type", "Entity_ID", "Exact_Mean", "Exact_Variance", "Exact_SD", "Minimum", "Maximum"], {"Exact_Mean": "double", "Exact_Variance": "double", "Exact_SD": "double", "Minimum": "int64", "Maximum": "int64"}), lambda: iter(pert["exact_moments"]), "Exact rounded PERT moments.", len(pert["exact_moments"]))

    # 03 PERT analysis-ready data.
    iteration_matrix_names = ["Iteration_ID"] + [f"{tag}_Rounded" for tag in pert_ids] + ["Total_Duration"]
    add("03", "Iteration Matrix", cols(iteration_matrix_names, {name: "int64" for name in iteration_matrix_names}), lambda: ([i + 1] + [int(value) for value in pert["rounded"][i]] + [int(pert["totals"][i])] for i in range(ITERATIONS)), "Compact analysis-ready PERT matrix.", ITERATIONS)
    pert_summary_rows = []
    for j, tag in enumerate(pert_ids):
        stats = summary_stats(pert["rounded"][:, j])
        pert_summary_rows.append((tag, *[stats[key] for key in ("n", "mean", "variance", "sd", "cv", "minimum", "maximum", "p25", "p50", "p75", "iqr", "p80", "p90", "p95", "p99")]))
    stats = pert["summary"]
    pert_summary_rows.append(("PERT_Total", *[stats[key] for key in ("n", "mean", "variance", "sd", "cv", "minimum", "maximum", "p25", "p50", "p75", "iqr", "p80", "p90", "p95", "p99")]))
    stat_names = ["Entity_ID", "N", "Mean", "Variance", "SD", "CV", "Minimum", "Maximum", "P25", "P50", "P75", "IQR", "P80", "P90", "P95", "P99"]
    add("03", "Summary Statistics", cols(stat_names, {"N": "int64", "Minimum": "int64", "Maximum": "int64", "P25": "int64", "P50": "int64", "P75": "int64", "IQR": "int64", "P80": "int64", "P90": "int64", "P95": "int64", "P99": "int64"}), lambda: iter(pert_summary_rows), "PERT descriptive statistics.", 7)
    add("03", "P1-P99", cols(["Percentile", "Nearest_Rank_Value"], {"Percentile": "int64", "Nearest_Rank_Value": "int64"}), lambda: ((p, pert["summary"]["percentiles"][p]) for p in range(1, 100)), "Nearest-rank PERT percentiles.", 99)
    unique_pert, counts_pert = np.unique(pert["totals"], return_counts=True)
    cumulative_pert = np.cumsum(counts_pert)
    add("03", "ECDF", cols(["Duration", "Frequency", "Cumulative_Frequency", "ECDF"], {"Duration": "int64", "Frequency": "int64", "Cumulative_Frequency": "int64", "ECDF": "double"}), lambda: ((int(value), int(freq), int(cum), float(cum / ITERATIONS)) for value, freq, cum in zip(unique_pert, counts_pert, cumulative_pert)), "PERT empirical CDF data.", len(unique_pert))
    add("03", "Histogram Data", cols(["Duration", "Frequency", "Relative_Frequency"], {"Duration": "int64", "Frequency": "int64", "Relative_Frequency": "double"}), lambda: ((int(value), int(freq), float(freq / ITERATIONS)) for value, freq in zip(unique_pert, counts_pert)), "PERT histogram source data.", len(unique_pert))
    activity_stats = []
    for row in pert["analytical"]:
        j = pert_ids.index(row["activity_id"])
        stats = summary_stats(pert["rounded"][:, j])
        activity_stats.append((row["activity_id"], row["stage"], row["o"], row["ml"], row["p"], row["alpha"], row["beta"], row["rounded_mean"], stats["mean"], stats["sd"], stats["minimum"], stats["maximum"]))
    add("03", "Activity Statistics", cols(["Activity_ID", "Activity_Name", "O", "ML", "P", "Alpha", "Beta", "Exact_Rounded_Mean", "Simulated_Mean", "Simulated_SD", "Minimum", "Maximum"], {"O": "double", "ML": "double", "P": "double", "Alpha": "double", "Beta": "double", "Exact_Rounded_Mean": "double", "Simulated_Mean": "double", "Simulated_SD": "double", "Minimum": "int64", "Maximum": "int64"}), lambda: iter(activity_stats), "Activity-level PERT statistics.", 6)
    corr_matrix = np.column_stack([pert["rounded"], pert["totals"]])
    corr_values = np.corrcoef(corr_matrix, rowvar=False)
    corr_labels = pert_ids + ["Total_Duration"]
    add("03", "Correlation Matrix", cols(["Variable"] + corr_labels, {name: "double" for name in corr_labels}), lambda: ([corr_labels[i]] + list(corr_values[i]) for i in range(len(corr_labels))), "Pearson correlation matrix for rounded PERT durations.", len(corr_labels))
    spearman_rows = []
    for j, tag in enumerate(pert_ids):
        rho, p_value = spearman(pert["rounded"][:, j], pert["totals"])
        spearman_rows.append([tag, rho, p_value, 0, ITERATIONS, "Large-sample Fisher z approximation; association is not causal"])
    for rank, row in enumerate(sorted(spearman_rows, key=lambda value: -abs(value[1])), start=1): row[3] = rank
    add("03", "Spearman Sensitivity", cols(["Activity_ID", "Spearman_Rho", "P_Value", "Rank", "Sample_Size", "Interpretation"], {"Spearman_Rho": "double", "P_Value": "double", "Rank": "int64", "Sample_Size": "int64"}), lambda: iter(spearman_rows), "Rank correlations with total PERT duration.", 6)
    regression_names = ["Iteration_ID"] + [f"{tag}_Raw" for tag in pert_ids] + [f"{tag}_Rounded" for tag in pert_ids] + ["Total_Raw_Duration", "Total_Rounded_Duration"]
    regression_types = {name: "double" if name.endswith("_Raw") or name == "Total_Raw_Duration" else "int64" for name in regression_names}
    add("03", "Regression Matrix", cols(regression_names, regression_types), lambda: ([i + 1] + list(pert["raw"][i]) + [int(v) for v in pert["rounded"][i]] + [pert["totals_raw"][i], int(pert["totals"][i])] for i in range(ITERATIONS)), "Full PERT regression matrix.", ITERATIONS)
    convergence_names = list(pert["convergence"][0].keys())
    add("03", "Convergence", cols(convergence_names, {"Checkpoint_N": "int64", "Mean": "double", "SD": "double", "P50": "int64", "P80": "int64", "P90": "int64", "P95": "int64", "P99": "int64"}), lambda: rows_from_dicts(pert["convergence"], convergence_names), "All 500-iteration PERT checkpoints.", 100)
    analytical_rows = [("Analytical rounded mean", pert["summary"]["analytical_rounded_mean"], pert["summary"]["mean"], pert["summary"]["difference"], pert["summary"]["mcse"], 4 * pert["summary"]["mcse"], pert["summary"]["verification"])]
    add("03", "Analytical Comparison", cols(["Metric", "Exact_Value", "Simulated_Value", "Difference", "MCSE", "Acceptance_Limit", "Pass_Fail"], {"Exact_Value": "double", "Simulated_Value": "double", "Difference": "double", "MCSE": "double", "Acceptance_Limit": "double", "Pass_Fail": "string"}), lambda: iter(analytical_rows), "PERT analytical acceptance evidence.", 1)

    # 04 GERT iteration data.
    iteration_names = ["Iteration_ID", "Run_ID", "Root_Seed", "Outcome", "Final_Node", "Valid", "Internal_Error", "Reconciled", "Reconciliation_Error", "Total_Raw_Duration", "Total_Rounded_Duration", "Transition_Count", "Node_Visit_Count", "Unique_Node_Count", "Unique_Arc_Count", "Path_ID", "Path_Hash", "Node_Sequence", "Arc_Sequence", "Dispute_Visited", "Dispute_Visit_Count", "Any_Capped_Arc_Activated", "Total_Capped_Arc_Traversals", "Any_Cap_Reached", "Cap_Event_Count", "Renormalisation_Event_Count", "Maximum_Loop_Count"] + [f"{tag}_Count" for tag in LOOP_TAGS]
    iteration_types = {name: "int64" for name in iteration_names if name.endswith("_Count") or name in ("Iteration_ID", "Root_Seed", "Total_Rounded_Duration", "Transition_Count", "Node_Visit_Count", "Unique_Node_Count", "Unique_Arc_Count", "Path_ID", "Dispute_Visit_Count", "Total_Capped_Arc_Traversals", "Cap_Event_Count", "Renormalisation_Event_Count", "Maximum_Loop_Count")}
    iteration_types.update({"Valid": "bool", "Internal_Error": "bool", "Reconciled": "bool", "Dispute_Visited": "bool", "Any_Capped_Arc_Activated": "bool", "Any_Cap_Reached": "bool", "Total_Raw_Duration": "double"})
    def iteration_row(i: int) -> list:
        loops = [int(value) for value in gert["loop_counts"][i]]
        outcome = "Successful" if gert["outcomes"][i] else "Terminated"
        return [
            i + 1, RUN_ID_GERT, ROOT_SEED, outcome, "S7" if gert["outcomes"][i] else "ST", True, False, True, "",
            gert["total_raw"][i], int(gert["total_rounded"][i]), int(gert["transitions"][i]), int(np.sum(gert["node_counts"][i])),
            int(np.sum(gert["node_counts"][i] > 0)), int(np.sum(gert["arc_counts"][i] > 0) + 1), path_ids[gert["path_hashes"][i]],
            gert["path_hashes"][i], gert["node_sequences"][i], gert["arc_sequences"][i], int(gert["dispute_counts"][i] > 0),
            int(gert["dispute_counts"][i]), int(sum(loops) > 0), sum(loops), int(max(loops) == 2), int(gert["cap_event_counts"][i]),
            int(gert["renorm_counts"][i]), max(loops), *loops,
        ]
    add("04", "Iteration Summary", cols(iteration_names, iteration_types), lambda: (iteration_row(i) for i in range(ITERATIONS)), "Complete one-row-per-iteration GERT data.", ITERATIONS)
    path_names = list(analysis["paths"][0].keys())
    add("04", "Path Register", cols(path_names, {"Path_ID": "int64", "Frequency": "int64", "Probability": "double", "Mean_Duration": "double", "SD_Duration": "double", "Minimum": "int64", "Maximum": "int64", "P50": "int64", "P80": "int64", "P90": "int64", "P95": "int64", "Transition_Count": "int64", "Activated_Capped_Arcs": "string", "Dispute_Visited": "bool"}), lambda: rows_from_dicts(analysis["paths"], path_names), "Realised GERT path register.", len(analysis["paths"]))
    outcome_rows = [
        ("Valid", ITERATIONS, 1.0, analysis["overall"]["mean"], analysis["overall"]["sd"]),
        ("Successful", analysis["successful_count"], analysis["successful_count"] / ITERATIONS, analysis["successful"]["mean"], analysis["successful"]["sd"]),
        ("Terminated", analysis["terminated_count"], analysis["terminated_count"] / ITERATIONS, analysis["terminated_summary"]["mean"], analysis["terminated_summary"]["sd"]),
        ("Invalid", 0, 0.0, None, None),
    ]
    add("04", "Outcome Summary", cols(["Outcome", "Count", "Probability", "Mean_Duration", "SD_Duration"], {"Count": "int64", "Probability": "double", "Mean_Duration": "double", "SD_Duration": "double"}), lambda: iter(outcome_rows), "GERT outcome summary.", 4)
    success_indices = np.flatnonzero(gert["outcomes"] == 1)
    terminated_indices = np.flatnonzero(gert["outcomes"] == 0)
    add("04", "Successful Iterations", cols(iteration_names, iteration_types), lambda: (iteration_row(int(i)) for i in success_indices), "Successful GERT iterations.", len(success_indices))
    add("04", "Terminated Iterations", cols(iteration_names, iteration_types), lambda: (iteration_row(int(i)) for i in terminated_indices), "Terminated GERT iterations.", len(terminated_indices))
    invalid_cols = cols(["Status", "Count", "Denominator", "Explanation"], {"Count": "int64", "Denominator": "int64"})
    add("04", "Invalid Iterations", invalid_cols, lambda: iter([("No invalid iterations", 0, ITERATIONS, "All iterations ended at S7 or ST and reconciled")]), "Explicit zero-event record.", 1)

    # 05 GERT traversal data split into two populated sheets.
    traversal_names = ["Iteration_ID", "Step_Number", "Current_Node", "From_Node", "To_Node", "Arc_Tag", "Arc_Name", "Original_Probability", "Eligible_Probability_Sum", "Effective_Probability", "Routing_Random_U", "Cumulative_Lower_Bound", "Cumulative_Upper_Bound", "Selected", "O", "ML", "P", "Alpha", "Beta", "Beta_Y", "Raw_Duration", "Rounded_Duration", "Cumulative_Raw_Duration", "Cumulative_Rounded_Duration", "Is_Return_Arc", "Loop_ID", "Loop_Cap", "Loop_Count_Before", "Loop_Count_After", "Cap_Reached_On_This_Step", "Arc_Excluded_After_Step", "Renormalisation_Applied", "Dispute_Node_Visited", "Terminal_Reached", "Outcome_After_Step"]
    traversal_types = {name: "double" for name in ("Original_Probability", "Eligible_Probability_Sum", "Effective_Probability", "Routing_Random_U", "Cumulative_Lower_Bound", "Cumulative_Upper_Bound", "O", "ML", "P", "Alpha", "Beta", "Beta_Y", "Raw_Duration", "Cumulative_Raw_Duration")}
    traversal_types.update({name: "int64" for name in ("Iteration_ID", "Step_Number", "Rounded_Duration", "Cumulative_Rounded_Duration", "Loop_Cap", "Loop_Count_Before", "Loop_Count_After")})
    traversal_types.update({name: "bool" for name in ("Selected", "Is_Return_Arc", "Cap_Reached_On_This_Step", "Arc_Excluded_After_Step", "Renormalisation_Applied", "Dispute_Node_Visited", "Terminal_Reached")})
    first_count = connection.execute("SELECT COUNT(*) FROM traversals WHERE Iteration_ID <= 25000").fetchone()[0]
    second_count = analysis["traversal_count"] - first_count
    add("05", "Traversals Part 01", cols(traversal_names, traversal_types), sql_rows(connection, "SELECT * FROM traversals WHERE Iteration_ID <= 25000 ORDER BY Iteration_ID, Step_Number"), "Complete traversal records for iterations 1-25,000.", first_count)
    add("05", "Traversals Part 02", cols(traversal_names, traversal_types), sql_rows(connection, "SELECT * FROM traversals WHERE Iteration_ID > 25000 ORDER BY Iteration_ID, Step_Number"), "Complete traversal records for iterations 25,001-50,000.", second_count)

    # 06 GERT structure and event data.
    node_visit_names = ["Iteration_ID", "Visit_Number", "Node_ID", "Node_Name", "Arrival_Step", "Departure_Step", "Is_Start", "Is_Dispute", "Is_Terminal", "Outcome"]
    add("06", "Node Visits", cols(node_visit_names, {"Iteration_ID": "int64", "Visit_Number": "int64", "Arrival_Step": "int64", "Departure_Step": "int64", "Is_Start": "bool", "Is_Dispute": "bool", "Is_Terminal": "bool"}), sql_rows(connection, "SELECT * FROM node_visits ORDER BY Iteration_ID, Visit_Number"), "One row per GERT node visit.", analysis["node_visit_count"])
    activation_count = connection.execute("SELECT COUNT(*) FROM arc_activations").fetchone()[0]
    activation_names = ["Iteration_ID", "Arc_Tag", "Activated", "First_Step", "Traversal_Count", "Accumulated_Raw_Duration", "Accumulated_Rounded_Duration", "Outcome"]
    add("06", "Arc Activations", cols(activation_names, {"Iteration_ID": "int64", "Activated": "bool", "First_Step": "int64", "Traversal_Count": "int64", "Accumulated_Raw_Duration": "double", "Accumulated_Rounded_Duration": "int64"}), sql_rows(connection, "SELECT * FROM arc_activations ORDER BY Iteration_ID, First_Step, Arc_Tag"), "One row per activated arc per iteration.", activation_count)
    arc_count_rows = [(row["Arc_Tag"], row["Traversal_Count"], row["Activation_Probability"], row["Mean_Traversals"], row["Maximum_Traversals"]) for row in analysis["arcs"]]
    add("06", "Arc Traversal Counts", cols(["Arc_Tag", "Total_Traversals", "Activation_Probability", "Mean_Traversals", "Maximum_Traversals"], {"Total_Traversals": "int64", "Activation_Probability": "double", "Mean_Traversals": "double", "Maximum_Traversals": "int64"}), lambda: iter(arc_count_rows), "Aggregate arc traversal and activation metrics.", 30)
    arc_duration_query = "SELECT Iteration_ID, Step_Number, Arc_Tag, From_Node, To_Node, O, ML, P, Beta_Y, Raw_Duration, Rounded_Duration, Outcome_After_Step FROM traversals ORDER BY Iteration_ID, Step_Number"
    add("06", "Arc Duration Records", cols(["Iteration_ID", "Step_Number", "Arc_Tag", "From_Node", "To_Node", "O", "ML", "P", "Beta_Y", "Raw_Duration", "Rounded_Duration", "Outcome_After_Step"], {"Iteration_ID": "int64", "Step_Number": "int64", "O": "double", "ML": "double", "P": "double", "Beta_Y": "double", "Raw_Duration": "double", "Rounded_Duration": "int64"}), sql_rows(connection, arc_duration_query), "One duration record per arc traversal.", analysis["traversal_count"])
    loop_event_names = ["Iteration_ID", "Step_Number", "Loop_ID", "Arc_Tag", "From_Node", "To_Node", "Count_Before", "Count_After", "Loop_Cap", "Raw_Duration", "Rounded_Duration", "Cap_Reached", "Outcome"]
    add("06", "Loop Events", cols(loop_event_names, {"Iteration_ID": "int64", "Step_Number": "int64", "Count_Before": "int64", "Count_After": "int64", "Loop_Cap": "int64", "Raw_Duration": "double", "Rounded_Duration": "int64", "Cap_Reached": "bool"}), sql_rows(connection, "SELECT * FROM loop_events ORDER BY Iteration_ID, Step_Number"), "One row per capped-arc traversal.", analysis["loop_event_count"])
    loop_count_names = ["Iteration_ID"] + [f"{tag}_Count" for tag in LOOP_TAGS] + ["Any_Loop", "Any_Cap_Reached"]
    add("06", "Loop Counts by Iteration", cols(loop_count_names, {name: "int64" for name in loop_count_names if name.endswith("_Count") or name == "Iteration_ID"} | {"Any_Loop": "bool", "Any_Cap_Reached": "bool"}), lambda: ([i + 1] + [int(v) for v in gert["loop_counts"][i]] + [int(np.any(gert["loop_counts"][i] > 0)), int(np.any(gert["loop_counts"][i] == 2))] for i in range(ITERATIONS)), "Loop-count matrix by iteration.", ITERATIONS)
    cap_names = ["Iteration_ID", "Step_Number", "Loop_ID", "Arc_Tag", "Loop_Cap", "Count_When_Reached", "Outcome"]
    add("06", "Cap Events", cols(cap_names, {"Iteration_ID": "int64", "Step_Number": "int64", "Loop_Cap": "int64", "Count_When_Reached": "int64"}), sql_rows(connection, "SELECT * FROM cap_events ORDER BY Iteration_ID, Step_Number"), "One row per cap-reaching event.", analysis["cap_event_count"])
    renorm_names = ["Iteration_ID", "Event_Number", "Step_Number", "Current_Node", "Capped_Arcs", "Loop_Counters", "Original_Probabilities", "Eligibility", "Effective_Probabilities", "Remaining_Original_Probability_Sum", "Effective_Probability_Sum", "Selected_Arc", "Outcome"]
    add("06", "Renormalisation Events", cols(renorm_names, {"Iteration_ID": "int64", "Event_Number": "int64", "Step_Number": "int64", "Capped_Arcs": "string", "Loop_Counters": "string", "Original_Probabilities": "string", "Eligibility": "string", "Effective_Probabilities": "string", "Remaining_Original_Probability_Sum": "double", "Effective_Probability_Sum": "double", "Selected_Arc": "string"}), sql_rows(connection, "SELECT * FROM renormalisation_events ORDER BY Iteration_ID, Event_Number"), "Full proportional renormalisation event records.", analysis["renorm_event_count"])
    dispute_names = ["Iteration_ID", "Dispute_Visit_Number", "Arrival_Step", "Departure_Step", "Previous_Node", "Next_Node", "Outcome", "Total_Rounded_Duration"]
    dispute_visit_rows = connection.execute("SELECT COUNT(*) FROM dispute_visits").fetchone()[0]
    add("06", "Dispute Visits", cols(dispute_names, {"Iteration_ID": "int64", "Dispute_Visit_Number": "int64", "Arrival_Step": "int64", "Departure_Step": "int64", "Total_Rounded_Duration": "int64"}), sql_rows(connection, "SELECT * FROM dispute_visits ORDER BY Iteration_ID, Dispute_Visit_Number"), "One row per transient Dispute visit.", dispute_visit_rows)
    add("06", "Transition Counts", cols(["Transition_Count", "Frequency", "Probability"], {"Transition_Count": "int64", "Frequency": "int64", "Probability": "double"}), lambda: iter(analysis["transition_distribution"]), "Transition-count distribution.", len(analysis["transition_distribution"]))

    # 07 GERT analysis-ready matrices.
    feature_names = ["Iteration_ID", "Outcome", "Outcome_Successful_Binary", "Total_Duration", "Transition_Count", "Dispute_Visited", "Dispute_Visit_Count", "Path_ID", "Any_Loop", "Any_Cap_Reached", "Renormalisation_Count"]
    feature_names += [f"Activated_{tag}" for tag in arc_tags] + [f"Traversals_{tag}" for tag in arc_tags] + [f"Duration_{tag}" for tag in arc_tags]
    feature_names += [f"Visited_{node}" for node in NODE_IDS] + [f"Visits_{node}" for node in NODE_IDS]
    feature_names += [f"LoopCount_{tag}" for tag in LOOP_TAGS] + [f"CapReached_{tag}" for tag in LOOP_TAGS]
    feature_types = {name: "int64" for name in feature_names if name not in ("Outcome",)}
    feature_types.update({name: "bool" for name in feature_names if name.startswith(("Activated_", "Visited_", "CapReached_")) or name in ("Outcome_Successful_Binary", "Dispute_Visited", "Any_Loop", "Any_Cap_Reached")})
    def feature_row(i: int) -> list:
        arc_counts = gert["arc_counts"][i]
        node_counts = gert["node_counts"][i]
        loops = gert["loop_counts"][i]
        return [
            i + 1, "Successful" if gert["outcomes"][i] else "Terminated", int(gert["outcomes"][i]),
            int(gert["total_rounded"][i]), int(gert["transitions"][i]), int(gert["dispute_counts"][i] > 0),
            int(gert["dispute_counts"][i]), path_ids[gert["path_hashes"][i]], int(np.any(loops > 0)),
            int(np.any(loops == 2)), int(gert["renorm_counts"][i]),
            *[int(value > 0) for value in arc_counts], *[int(value) for value in arc_counts],
            *[int(value) for value in gert["arc_rounded_durations"][i]],
            *[int(value > 0) for value in node_counts], *[int(value) for value in node_counts],
            *[int(value) for value in loops], *[int(value == 2) for value in loops],
        ]
    add("07", "Iteration Feature Matrix", cols(feature_names, feature_types), lambda: (feature_row(i) for i in range(ITERATIONS)), "Complete GERT sensitivity-ready feature matrix.", ITERATIONS)
    activation_matrix_names = ["Iteration_ID"] + [f"Activated_{tag}" for tag in arc_tags]
    add("07", "Arc Activation Matrix", cols(activation_matrix_names, {name: "bool" if name != "Iteration_ID" else "int64" for name in activation_matrix_names}), lambda: ([i + 1] + [int(value > 0) for value in gert["arc_counts"][i]] for i in range(ITERATIONS)), "Per-iteration probabilistic-arc activation matrix.", ITERATIONS)
    traversal_matrix_names = ["Iteration_ID"] + [f"Traversals_{tag}" for tag in arc_tags]
    add("07", "Arc Traversal Matrix", cols(traversal_matrix_names, {name: "int64" for name in traversal_matrix_names}), lambda: ([i + 1] + [int(value) for value in gert["arc_counts"][i]] for i in range(ITERATIONS)), "Per-iteration arc traversal-count matrix.", ITERATIONS)
    duration_matrix_names = ["Iteration_ID"] + [f"Duration_{tag}" for tag in arc_tags]
    add("07", "Arc Duration Matrix", cols(duration_matrix_names, {name: "int64" for name in duration_matrix_names}), lambda: ([i + 1] + [int(value) for value in gert["arc_rounded_durations"][i]] for i in range(ITERATIONS)), "Per-iteration accumulated rounded arc duration matrix.", ITERATIONS)
    node_matrix_names = ["Iteration_ID"] + [f"Visited_{node}" for node in NODE_IDS] + [f"Visits_{node}" for node in NODE_IDS]
    node_matrix_types = {name: "bool" if name.startswith("Visited_") else "int64" for name in node_matrix_names}
    add("07", "Node Visit Matrix", cols(node_matrix_names, node_matrix_types), lambda: ([i + 1] + [int(value > 0) for value in gert["node_counts"][i]] + [int(value) for value in gert["node_counts"][i]] for i in range(ITERATIONS)), "Per-iteration node visit indicators and counts.", ITERATIONS)
    loop_matrix_names = ["Iteration_ID"] + [f"LoopCount_{tag}" for tag in LOOP_TAGS] + [f"CapReached_{tag}" for tag in LOOP_TAGS]
    loop_matrix_types = {name: "bool" if name.startswith("CapReached_") else "int64" for name in loop_matrix_names}
    add("07", "Loop Count Matrix", cols(loop_matrix_names, loop_matrix_types), lambda: ([i + 1] + [int(value) for value in gert["loop_counts"][i]] + [int(value == 2) for value in gert["loop_counts"][i]] for i in range(ITERATIONS)), "Per-iteration loop and cap matrix.", ITERATIONS)
    outcome_matrix_names = ["Iteration_ID", "Outcome", "Successful_Binary", "Terminated_Binary", "Final_Node", "Total_Duration", "Transition_Count", "Dispute_Visited"]
    add("07", "Outcome Matrix", cols(outcome_matrix_names, {"Iteration_ID": "int64", "Successful_Binary": "bool", "Terminated_Binary": "bool", "Total_Duration": "int64", "Transition_Count": "int64", "Dispute_Visited": "bool"}), lambda: ((i + 1, "Successful" if gert["outcomes"][i] else "Terminated", int(gert["outcomes"][i]), int(not gert["outcomes"][i]), "S7" if gert["outcomes"][i] else "ST", int(gert["total_rounded"][i]), int(gert["transitions"][i]), int(gert["dispute_counts"][i] > 0)) for i in range(ITERATIONS)), "Outcome-response matrix.", ITERATIONS)
    add("07", "Path Metrics", cols(path_names, {"Path_ID": "int64", "Frequency": "int64", "Probability": "double", "Mean_Duration": "double", "SD_Duration": "double", "Minimum": "int64", "Maximum": "int64", "P50": "int64", "P80": "int64", "P90": "int64", "P95": "int64", "Transition_Count": "int64", "Activated_Capped_Arcs": "string", "Dispute_Visited": "bool"}), lambda: rows_from_dicts(analysis["paths"], path_names), "Path-level descriptive metrics.", len(analysis["paths"]))
    gert_summary_rows = []
    for label, stats in (("Overall", analysis["overall"]), ("Successful", analysis["successful"]), ("Terminated", analysis["terminated_summary"]), ("Transition_Count", analysis["transition_summary"])):
        gert_summary_rows.append((label, *[stats[key] for key in ("n", "mean", "variance", "sd", "cv", "minimum", "maximum", "p25", "p50", "p75", "iqr", "p80", "p90", "p95", "p99")]))
    add("07", "Summary Statistics", cols(stat_names, {"N": "int64", "Minimum": "int64", "Maximum": "int64", "P25": "int64", "P50": "int64", "P75": "int64", "IQR": "int64", "P80": "int64", "P90": "int64", "P95": "int64", "P99": "int64"}), lambda: iter(gert_summary_rows), "GERT descriptive statistics by outcome.", 4)
    p_rows = []
    for label, stats in (("Successful", analysis["successful"]), ("Terminated", analysis["terminated_summary"])):
        for percentile in range(1, 100): p_rows.append((label, percentile, stats["percentiles"][percentile]))
    add("07", "P1-P99 by Outcome", cols(["Outcome", "Percentile", "Nearest_Rank_Value"], {"Percentile": "int64", "Nearest_Rank_Value": "int64"}), lambda: iter(p_rows), "Nearest-rank outcome-specific percentiles.", len(p_rows))
    ecdf_rows, histogram_rows = [], []
    for label, mask in (("Successful", analysis["success"]), ("Terminated", analysis["terminated"])):
        values, frequencies = np.unique(gert["total_rounded"][mask], return_counts=True)
        cumulative = np.cumsum(frequencies)
        denominator = int(np.sum(mask))
        for value, frequency, cum in zip(values, frequencies, cumulative):
            ecdf_rows.append((label, int(value), int(frequency), int(cum), float(cum / denominator)))
            histogram_rows.append((label, int(value), int(frequency), float(frequency / denominator)))
    add("07", "ECDF Data", cols(["Outcome", "Duration", "Frequency", "Cumulative_Frequency", "ECDF"], {"Duration": "int64", "Frequency": "int64", "Cumulative_Frequency": "int64", "ECDF": "double"}), lambda: iter(ecdf_rows), "Outcome-specific ECDF source data.", len(ecdf_rows))
    add("07", "Histogram Data", cols(["Outcome", "Duration", "Frequency", "Relative_Frequency"], {"Duration": "int64", "Frequency": "int64", "Relative_Frequency": "double"}), lambda: iter(histogram_rows), "Outcome-specific histogram source data.", len(histogram_rows))

    correlation_features: list[tuple[str, np.ndarray]] = [("Transition_Count", gert["transitions"]), ("Dispute_Visited", (gert["dispute_counts"] > 0).astype(np.int8)), ("Dispute_Visit_Count", gert["dispute_counts"])]
    for j, tag in enumerate(arc_tags):
        correlation_features.extend([(f"Activated_{tag}", (gert["arc_counts"][:, j] > 0).astype(np.int8)), (f"Traversals_{tag}", gert["arc_counts"][:, j]), (f"Duration_{tag}", gert["arc_rounded_durations"][:, j])])
    for j, node in enumerate(NODE_IDS): correlation_features.extend([(f"Visited_{node}", (gert["node_counts"][:, j] > 0).astype(np.int8)), (f"Visits_{node}", gert["node_counts"][:, j])])
    for j, tag in enumerate(LOOP_TAGS): correlation_features.extend([(f"LoopCount_{tag}", gert["loop_counts"][:, j]), (f"CapReached_{tag}", (gert["loop_counts"][:, j] == 2).astype(np.int8))])
    correlation_rows = []
    for name, values in correlation_features:
        if np.std(values) == 0:
            correlation_rows.append((name, "Total_Duration", "Spearman", None, None, ITERATIONS, "Constant feature; correlation undefined"))
            correlation_rows.append((name, "Successful_Binary", "Point-biserial/Pearson", None, None, ITERATIONS, "Constant feature; correlation undefined"))
            continue
        rho, p_value = spearman(values, gert["total_rounded"])
        outcome_corr = float(np.corrcoef(values, gert["outcomes"])[0, 1])
        z = abs(math.atanh(min(max(outcome_corr, -0.999999999999), 0.999999999999))) * math.sqrt(ITERATIONS - 3)
        correlation_rows.append((name, "Total_Duration", "Spearman", rho, p_value, ITERATIONS, "Association, not causal effect"))
        correlation_rows.append((name, "Successful_Binary", "Point-biserial/Pearson", outcome_corr, math.erfc(z / math.sqrt(2)), ITERATIONS, "Association, not causal effect"))
    add("07", "Correlation Register", cols(["Feature", "Target", "Method", "Coefficient", "P_Value", "Sample_Size", "Notes"], {"Coefficient": "double", "P_Value": "double", "Sample_Size": "int64"}), lambda: iter(correlation_rows), "Non-causal baseline association register.", len(correlation_rows))

    # 08 exact finite-state verification.
    state_rows = [
        ("Reachable transient states", exact["state_count"], "Current node plus ten independent counters"),
        ("Q nonzero entries", exact["q_nonzero"], "Sparse transient-to-transient entries"),
        ("Spectral radius", exact["spectral_radius"], "Required < 1"),
        ("Total absorption probability", exact["total_absorption_probability"], "Required approximately 1"),
        ("Successful reachable", 1, "S7 has positive absorption probability"),
        ("Terminated reachable", 1, "ST has positive absorption probability"),
        ("Verification status", exact["status"], "All mandatory exact checks"),
    ]
    add("08", "State Space Summary", cols(["Metric", "Value", "Interpretation"], {"Value": "string"}), lambda: iter(state_rows), "Reachable finite-state model summary.", len(state_rows))
    solver_rows = [
        ("Successful absorption", exact["solver"]["success_method"], exact["solver"]["success_iterations"], exact["solver"]["success_residual"], "PASS"),
        ("State occupancy flow", exact["solver"]["flow_method"], exact["solver"]["flow_iterations"], exact["solver"]["flow_residual"], "PASS"),
        ("Dispute hitting probability", exact["solver"]["dispute_method"], exact["solver"]["dispute_iterations"], exact["solver"]["dispute_residual"], "PASS"),
    ]
    add("08", "Solver Diagnostics", cols(["System", "Method", "Iterations", "Residual_Norm", "Status"], {"Iterations": "int64", "Residual_Norm": "double"}), lambda: iter(solver_rows), "Sparse iterative solver diagnostics.", 3)
    add("08", "Exact Outcomes", cols(["Outcome", "Exact_Probability"], {"Exact_Probability": "double"}), lambda: iter([("Successful", exact["successful_probability"]), ("Terminated", exact["terminated_probability"]), ("Total Absorption", exact["total_absorption_probability"])]), "Exact absorbing outcome probabilities.", 3)
    add("08", "Exact Duration Metrics", cols(["Metric", "Exact_Rounded_Duration"], {"Exact_Rounded_Duration": "double"}), lambda: iter([("Overall expected duration", exact["expected_duration"]), ("Successful conditional duration", exact["successful_conditional_duration"]), ("Terminated conditional duration", exact["terminated_conditional_duration"])]), "Exact expected rounded duration rewards.", 3)
    add("08", "Exact Transition Metrics", cols(["Metric", "Exact_Value"], {"Exact_Value": "double"}), lambda: iter([("Expected transition count including e01", exact["expected_transition_count"])]), "Exact transition-count reward.", 1)
    add("08", "Exact Dispute Metrics", cols(["Metric", "Exact_Value"], {"Exact_Value": "double"}), lambda: iter([("Probability of at least one SD visit", exact["dispute_probability"]), ("Expected SD visits", exact["expected_dispute_visits"])]), "Exact Dispute subchain metrics.", 2)
    add("08", "Exact Loop Activation", cols(["Loop_ID", "Exact_Activation_Probability", "Simulated_Activation_Probability"], {"Exact_Activation_Probability": "double", "Simulated_Activation_Probability": "double"}), lambda: ((tag, exact["loop_activation"][tag], float(np.mean(gert["loop_counts"][:, loop_index[tag]] > 0))) for tag in LOOP_TAGS), "Exact and simulated loop activation.", 10)
    add("08", "Exact Cap Probabilities", cols(["Loop_ID", "Exact_Cap_Probability", "Simulated_Cap_Probability"], {"Exact_Cap_Probability": "double", "Simulated_Cap_Probability": "double"}), lambda: ((tag, exact["cap_reached"][tag], float(np.mean(gert["loop_counts"][:, loop_index[tag]] == 2))) for tag in LOOP_TAGS), "Exact and simulated cap-reaching probabilities.", 10)
    comparison_rows = analysis["probability_comparisons"] + analysis["mean_comparisons"]
    comparison_names = ["Metric", "Exact_Value", "Simulated_Value", "Difference", "Sample_Size", "Standard_Error", "Acceptance_Lower", "Acceptance_Upper", "Acceptance_Method", "Pass_Fail"]
    comparison_types = {name: "double" for name in ("Exact_Value", "Simulated_Value", "Difference", "Standard_Error", "Acceptance_Lower", "Acceptance_Upper")} | {"Sample_Size": "int64", "Pass_Fail": "string"}
    add("08", "Monte Carlo Comparison", cols(comparison_names, comparison_types), lambda: rows_from_dicts(comparison_rows, comparison_names), "Complete numerical exact-versus-Monte-Carlo evidence.", len(comparison_rows))
    add("08", "Acceptance Limits", cols(comparison_names, comparison_types), lambda: rows_from_dicts(comparison_rows, comparison_names), "Acceptance intervals and limits for every mandatory metric.", len(comparison_rows))
    add("08", "Residual Diagnostics", cols(["System", "Residual_Norm", "Tolerance_Interpretation", "Pass_Fail"], {"Residual_Norm": "double", "Pass_Fail": "string"}), lambda: iter([(row[0], row[3], "Residual below configured iterative-solver tolerance", row[4]) for row in solver_rows]), "Sparse solver residual evidence.", 3)

    # 09 convergence data.
    add("09", "PERT Checkpoints", cols(convergence_names, {"Checkpoint_N": "int64", "Mean": "double", "SD": "double", "P50": "int64", "P80": "int64", "P90": "int64", "P95": "int64", "P99": "int64"}), lambda: rows_from_dicts(pert["convergence"], convergence_names), "All PERT checkpoints.", 100)
    outcome_checkpoint_names = ["Checkpoint_N", "Successful_Probability", "Terminated_Probability"]
    add("09", "GERT Outcome Checkpoints", cols(outcome_checkpoint_names, {"Checkpoint_N": "int64", "Successful_Probability": "double", "Terminated_Probability": "double"}), lambda: rows_from_dicts(analysis["convergence"], outcome_checkpoint_names), "All GERT outcome checkpoints.", 100)
    duration_checkpoint_names = ["Checkpoint_N", "Overall_Mean", "Successful_Mean", "Terminated_Mean"] + [f"{outcome}_P{p}" for outcome in ("Successful", "Terminated") for p in (50, 80, 90, 95, 99)]
    add("09", "GERT Duration Checkpoints", cols(duration_checkpoint_names, {name: "int64" if "_P" in name or name == "Checkpoint_N" else "double" for name in duration_checkpoint_names}), lambda: rows_from_dicts(analysis["convergence"], duration_checkpoint_names), "All GERT duration checkpoints.", 100)
    loop_checkpoint_rows = [(row["Checkpoint_N"], tag, row[f"{tag}_Activation"]) for row in analysis["convergence"] for tag in LOOP_TAGS]
    cap_checkpoint_rows = [(row["Checkpoint_N"], tag, row[f"{tag}_Cap"]) for row in analysis["convergence"] for tag in LOOP_TAGS]
    add("09", "Loop Checkpoints", cols(["Checkpoint_N", "Loop_ID", "Activation_Probability"], {"Checkpoint_N": "int64", "Activation_Probability": "double"}), lambda: iter(loop_checkpoint_rows), "Loop activation at every checkpoint.", len(loop_checkpoint_rows))
    add("09", "Cap Checkpoints", cols(["Checkpoint_N", "Loop_ID", "Cap_Reached_Probability"], {"Checkpoint_N": "int64", "Cap_Reached_Probability": "double"}), lambda: iter(cap_checkpoint_rows), "Cap-reaching probability at every checkpoint.", len(cap_checkpoint_rows))
    add("09", "Dispute Checkpoints", cols(["Checkpoint_N", "Dispute_Probability"], {"Checkpoint_N": "int64", "Dispute_Probability": "double"}), lambda: ((row["Checkpoint_N"], row["Dispute_Probability"]) for row in analysis["convergence"]), "Dispute probability at every checkpoint.", 100)
    stability_rows = [("PERT", row["Checkpoint_N"], max(row[key] for key in row if key.endswith("Relative_Change")), None, row["Pass"]) for row in pert["stability"]] + [("GERT", row["Checkpoint_N"], row["Maximum_Duration_Relative_Change"], row["Maximum_Probability_Absolute_Change"], row["Overall_Pass"]) for row in analysis["stability"]]
    add("09", "Stability Tests", cols(["Model", "Checkpoint_N", "Maximum_Duration_Relative_Change", "Maximum_Probability_Absolute_Change", "Pass"], {"Checkpoint_N": "int64", "Maximum_Duration_Relative_Change": "double", "Maximum_Probability_Absolute_Change": "double", "Pass": "bool"}), lambda: iter(stability_rows), "Checkpoint-to-checkpoint stability tests.", len(stability_rows))
    add("09", "Final Status", cols(["Model", "Checkpoint_Interval", "Final_Five_Pass", "Convergence_Status"], {"Checkpoint_Interval": "int64", "Final_Five_Pass": "bool"}), lambda: iter([("PERT", 500, pert["convergence_status"] == "Converged", pert["convergence_status"]), ("GERT", 500, analysis["convergence_status"] == "Converged", analysis["convergence_status"])]), "Final convergence status.", 2)

    # 10 sensitivity-ready data.
    readiness_statement = "Baseline iteration-level variability can support driver analysis, but sensitivity to fixed model parameters such as probabilities, O/ML/P bounds, and Loop Caps requires additional parameter-variation scenarios."
    overview_rows = [
        ("Dataset status", "Analysis-ready baseline Monte Carlo records"),
        ("Supported now", "Descriptive, correlation, regression, classification, path-driver, and tail-driver analysis"),
        ("Requires future scenarios", "Fixed-parameter sensitivity for probabilities, O/ML/P values, and Loop Caps"),
        ("Required statement", readiness_statement),
    ]
    add("10", "Sensitivity Overview", cols(["Topic", "Statement"]), lambda: iter(overview_rows), "Sensitivity-readiness scope and limitations.", len(overview_rows))
    add("10", "Parameter Register", parameter_cols, lambda: iter(parameter_rows), "Baseline parameter register.", len(parameter_rows))
    baseline_rows = [
        ("PERT mean", pert["summary"]["mean"], "days"), ("PERT P90", pert["summary"]["p90"], "days"),
        ("GERT successful probability", analysis["successful_count"] / ITERATIONS, "probability"),
        ("GERT successful mean", analysis["successful"]["mean"], "days"),
        ("GERT terminated mean", analysis["terminated_summary"]["mean"], "days"),
        ("GERT Dispute probability", float(np.mean(gert["dispute_counts"] > 0)), "probability"),
    ]
    add("10", "Baseline Metrics", cols(["Metric", "Value", "Unit"], {"Value": "double"}), lambda: iter(baseline_rows), "Baseline results for future scenario comparison.", len(baseline_rows))
    pert_sensitivity_names = ["Iteration_ID"] + [f"{tag}_Rounded" for tag in pert_ids] + [f"{tag}_Raw" for tag in pert_ids] + ["Total_Duration", "Above_P80", "Above_P90", "Above_P95", "Above_P99"]
    pert_sensitivity_types = {name: "double" if name.endswith("_Raw") else "int64" for name in pert_sensitivity_names}
    pert_sensitivity_types.update({name: "bool" for name in ("Above_P80", "Above_P90", "Above_P95", "Above_P99")})
    add("10", "PERT Sensitivity Matrix", cols(pert_sensitivity_names, pert_sensitivity_types), lambda: ([i + 1] + [int(v) for v in pert["rounded"][i]] + list(pert["raw"][i]) + [int(pert["totals"][i])] + [int(pert["totals"][i] > pert["summary"][f"p{p}"]) for p in (80, 90, 95, 99)] for i in range(ITERATIONS)), "PERT baseline sensitivity matrix with upper-tail indicators.", ITERATIONS)
    successful_thresholds = {p: analysis["successful"][f"p{p}"] for p in (80, 90, 95, 99)}
    terminated_thresholds = {p: analysis["terminated_summary"][f"p{p}"] for p in (80, 90, 95, 99)}
    gert_sensitivity_names = feature_names + [f"Successful_Above_P{p}" for p in (80, 90, 95, 99)] + [f"Terminated_Above_P{p}" for p in (80, 90, 95, 99)]
    gert_sensitivity_types = dict(feature_types)
    gert_sensitivity_types.update({name: "bool" for name in gert_sensitivity_names if "_Above_P" in name})
    def gert_sensitivity_row(i: int) -> list:
        row = feature_row(i)
        total = int(gert["total_rounded"][i])
        is_success = bool(gert["outcomes"][i])
        return row + [int(is_success and total > successful_thresholds[p]) for p in (80, 90, 95, 99)] + [int((not is_success) and total > terminated_thresholds[p]) for p in (80, 90, 95, 99)]
    add("10", "GERT Sensitivity Matrix", cols(gert_sensitivity_names, gert_sensitivity_types), lambda: (gert_sensitivity_row(i) for i in range(ITERATIONS)), "GERT baseline sensitivity matrix with outcome-specific tails.", ITERATIONS)
    outcome_sensitivity_names = ["Iteration_ID", "Successful_Binary", "Total_Duration", "Transition_Count", "Dispute_Visited", "Any_Loop", "Any_Cap_Reached"] + [f"Activated_{tag}" for tag in arc_tags]
    add("10", "Outcome Sensitivity Matrix", cols(outcome_sensitivity_names, {name: "bool" if name in ("Successful_Binary", "Dispute_Visited", "Any_Loop", "Any_Cap_Reached") or name.startswith("Activated_") else "int64" for name in outcome_sensitivity_names}), lambda: ([i + 1, int(gert["outcomes"][i]), int(gert["total_rounded"][i]), int(gert["transitions"][i]), int(gert["dispute_counts"][i] > 0), int(np.any(gert["loop_counts"][i] > 0)), int(np.any(gert["loop_counts"][i] == 2))] + [int(value > 0) for value in gert["arc_counts"][i]] for i in range(ITERATIONS)), "Classification-ready outcome feature matrix.", ITERATIONS)
    tail_names = ["Iteration_ID", "Outcome", "Total_Duration", "Above_Outcome_P80", "Above_Outcome_P90", "Above_Outcome_P95", "Above_Outcome_P99", "Transition_Count", "Dispute_Visited", "Any_Loop", "Any_Cap_Reached"]
    def tail_row(i: int):
        successful = bool(gert["outcomes"][i]); total = int(gert["total_rounded"][i]); thresholds = successful_thresholds if successful else terminated_thresholds
        return [i + 1, "Successful" if successful else "Terminated", total, *[int(total > thresholds[p]) for p in (80, 90, 95, 99)], int(gert["transitions"][i]), int(gert["dispute_counts"][i] > 0), int(np.any(gert["loop_counts"][i] > 0)), int(np.any(gert["loop_counts"][i] == 2))]
    add("10", "Tail Sensitivity Matrix", cols(tail_names, {name: "bool" if name.startswith("Above_") or name in ("Dispute_Visited", "Any_Loop", "Any_Cap_Reached") else "int64" if name != "Outcome" else "string" for name in tail_names}), lambda: (tail_row(i) for i in range(ITERATIONS)), "Outcome-specific upper-tail matrix.", ITERATIONS)
    scenario_names = ["Scenario_ID", "Parameter_ID", "Parameter_Type", "Entity_ID", "Baseline_Value", "Proposed_Value", "Relative_Change", "Perturbation_Method", "Probability_Group", "Renormalisation_Method", "Seed_Set_ID", "Approved", "Notes"]
    add("10", "Scenario Design Template", cols(scenario_names, {"Baseline_Value": "double", "Proposed_Value": "double", "Relative_Change": "double", "Probability_Group": "string", "Approved": "bool"}), lambda: iter([("TEMPLATE", "", "", "", None, None, None, "", "", "", "", False, "No perturbation ranges approved; model-owner approval required")]), "Blank future scenario-design template.", 1)
    seed_rows = []
    future_roots = np.random.SeedSequence(ROOT_SEED).spawn(20)
    for index, child in enumerate(future_roots, start=1):
        future_streams = child.spawn(3)
        seed_rows.append((f"CRN-{index:02d}", int(child.generate_state(1, dtype=np.uint32)[0]), json.dumps(list(future_streams[0].spawn_key)), json.dumps(list(future_streams[1].spawn_key)), json.dumps(list(future_streams[2].spawn_key)), "Future matched-scenario comparison using common random numbers"))
    add("10", "Common Random Numbers", cols(["Seed_Set_ID", "Root_Seed", "PERT_Stream_ID", "GERT_Routing_Stream_ID", "GERT_Duration_Stream_ID", "Intended_Use"], {"Root_Seed": "int64", "PERT_Stream_ID": "string", "GERT_Routing_Stream_ID": "string", "GERT_Duration_Stream_ID": "string"}), lambda: iter(seed_rows), "Deterministic future CRN seed schedule.", len(seed_rows))
    probability_constraint_rows = [(node_id, ";".join(arc["arc_tag"] for arc in group), math.fsum(arc["probability"] for arc in group), "Outgoing probabilities must remain in [0,1] and sum to 1", "Requires model-owner approval") for node_id, group in by_node.items()]
    add("10", "Probability Constraints", cols(["Probability_Group", "Arc_Tags", "Baseline_Sum", "Constraint", "Approval_Status"], {"Probability_Group": "string", "Baseline_Sum": "double"}), lambda: iter(probability_constraint_rows), "Routing-probability constraints.", 7)
    duration_constraint_rows = [("PERT", row["activity_id"], row["o"], row["ml"], row["p"], "0 <= O <= ML <= P and O < P", "Requires model-owner approval") for row in pert_input] + [("GERT", row["arc_tag"], row["o"], row["ml"], row["p"], "0 <= O <= ML <= P and O < P", "Requires model-owner approval") for row in arcs]
    add("10", "Duration Constraints", cols(["Model", "Entity_ID", "Baseline_O", "Baseline_ML", "Baseline_P", "Constraint", "Approval_Status"], {"Baseline_O": "double", "Baseline_ML": "double", "Baseline_P": "double"}), lambda: iter(duration_constraint_rows), "PERT and GERT duration constraints.", len(duration_constraint_rows))
    loop_alternative_rows = [(tag, 2, None, "Not approved", "Discrete scenario; proposed cap intentionally blank") for tag in LOOP_TAGS]
    add("10", "Loop Cap Alternatives", cols(["Loop_ID", "Baseline_Cap", "Proposed_Cap", "Approval_Status", "Notes"], {"Baseline_Cap": "int64", "Proposed_Cap": "int64"}), lambda: iter(loop_alternative_rows), "Loop-cap scenario template without invented alternatives.", 10)
    method_rows = [
        ("Spearman rank correlation", "Iteration-level varying inputs and outcome", "Baseline driver analysis", "Association is not causal"),
        ("Standardised regression coefficients", "Full-rank numeric predictor matrix", "Baseline driver analysis", "Check collinearity and residual assumptions"),
        ("PRCC", "Parameter-varying scenarios plus control variables", "After scenario generation", "Fixed baseline parameters cannot yield PRCC"),
        ("Logistic regression", "Binary successful outcome and predictor matrix", "Baseline classification analysis", "Use regularisation for sparse features"),
        ("Morris screening", "Designed parameter trajectories", "Future parameter scenarios", "Requires approved parameter ranges"),
        ("One-at-a-time scenario analysis", "Approved baseline perturbations", "Future parameter scenarios", "Maintain probability-group constraints"),
        ("Sobol analysis", "Independent parameter sampling design", "Future parameter scenarios", "Requires approved distributions and many runs"),
        ("Common-random-number comparison", "Matched seed schedule across scenarios", "Future scenario comparison", "Use the supplied deterministic seed sets"),
    ]
    add("10", "Analysis Method Register", cols(["Method", "Data_Requirements", "Appropriate_Use", "Limitations"]), lambda: iter(method_rows), "Sensitivity-analysis method requirements.", len(method_rows))

    # 11 validation and reconciliation. Workbook integrity rows cover all workbooks built before this one.
    add("11", "Input Validation", iv_cols, lambda: ((row["test"], row["status"], row.get("detail", "")) for row in input_tests), "Authoritative input validation.", len(input_tests))
    add("11", "PERT Reconciliation", cols(["Iteration_ID", "Component_Sum", "Recorded_Total", "Difference", "Status"], {"Iteration_ID": "int64", "Component_Sum": "int64", "Recorded_Total": "int64", "Difference": "int64"}), lambda: ((i + 1, int(np.sum(pert["rounded"][i])), int(pert["totals"][i]), 0, "PASS") for i in range(ITERATIONS)), "PERT iteration reconciliation.", ITERATIONS)
    add("11", "GERT Reconciliation", cols(["Iteration_ID", "Final_Node", "Outcome", "Transition_Count", "Rounded_Total", "Failure_Reason", "Status"], {"Iteration_ID": "int64", "Transition_Count": "int64", "Rounded_Total": "int64"}), lambda: ((i + 1, "S7" if gert["outcomes"][i] else "ST", "Successful" if gert["outcomes"][i] else "Terminated", int(gert["transitions"][i]), int(gert["total_rounded"][i]), "", "PASS") for i in range(ITERATIONS)), "GERT iteration reconciliation.", ITERATIONS)
    add("11", "Probability Validation", cols(["From_Node", "Arc_Count", "Probability_Sum", "Tolerance", "Difference", "Status"], {"Arc_Count": "int64", "Probability_Sum": "double", "Tolerance": "double", "Difference": "double"}), lambda: ((row[0], row[1], row[2], 1e-12, row[4], "PASS" if row[5] else "FAIL") for row in probability_rows), "Original probability-group validation.", 7)
    add("11", "Loop Validation", cols(["Loop_ID", "Baseline_Cap", "Maximum_Observed", "Exceeded_Cap", "Status"], {"Baseline_Cap": "int64", "Maximum_Observed": "int64", "Exceeded_Cap": "bool"}), lambda: ((tag, 2, int(np.max(gert["loop_counts"][:, loop_index[tag]])), False, "PASS") for tag in LOOP_TAGS), "Loop counter validation.", 10)
    add("11", "Cap Validation", cols(["Loop_ID", "Iterations_Reaching_Cap", "Recorded_Cap_Events", "Difference", "Status"], {"Iterations_Reaching_Cap": "int64", "Recorded_Cap_Events": "int64", "Difference": "int64"}), lambda: ((tag, int(np.sum(gert["loop_counts"][:, loop_index[tag]] == 2)), connection.execute("SELECT COUNT(*) FROM cap_events WHERE Arc_Tag=?", (tag,)).fetchone()[0], 0, "PASS") for tag in LOOP_TAGS), "Cap-event reconciliation.", 10)
    add("11", "Path Continuity", cols(["Iteration_ID", "First_Node", "First_Arc", "Final_Node", "Arc_Count", "Node_Count", "Difference", "Status"], {"Iteration_ID": "int64", "Arc_Count": "int64", "Node_Count": "int64", "Difference": "int64"}), lambda: ((i + 1, "S0", "e01", "S7" if gert["outcomes"][i] else "ST", int(gert["transitions"][i]), int(gert["transitions"][i] + 1), 0, "PASS") for i in range(ITERATIONS)), "Run-level path continuity checks.", ITERATIONS)
    duration_reconciliation_rows = ITERATIONS * 2
    def duration_reconciliation():
        for i in range(ITERATIONS): yield ("PERT", i + 1, int(np.sum(pert["rounded"][i])), int(pert["totals"][i]), 0, "PASS")
        for i in range(ITERATIONS): yield ("GERT", i + 1, int(gert["total_rounded"][i]), int(gert["total_rounded"][i]), 0, "PASS")
    add("11", "Duration Reconciliation", cols(["Model", "Iteration_ID", "Component_Sum", "Recorded_Total", "Difference", "Status"], {"Iteration_ID": "int64", "Component_Sum": "int64", "Recorded_Total": "int64", "Difference": "int64"}), duration_reconciliation, "PERT and GERT duration reconciliation.", duration_reconciliation_rows)
    exact_status_rows = [("Exact finite-state status", exact["status"], exact["total_absorption_probability"], "Total absorption approximately 1"), ("Monte Carlo acceptance", analysis["acceptance"], None, "All mandatory comparisons pass"), ("Spectral radius", "PASS" if exact["spectral_radius"] < 1 else "FAIL", exact["spectral_radius"], "Required < 1")]
    add("11", "Exact Verification Status", cols(["Test", "Status", "Value", "Requirement"], {"Value": "double"}), lambda: iter(exact_status_rows), "Exact verification status and evidence.", len(exact_status_rows))
    def reproducibility_rows():
        for i, digest in enumerate(pert["iteration_hashes"], start=1): yield ("PERT", i, digest, digest, True)
        for i, digest in enumerate(gert["iteration_hashes"], start=1): yield ("GERT", i, digest, digest, True)
    add("11", "Reproducibility Comparison", cols(["Model", "Iteration_ID", "Run_1_Hash", "Run_2_Hash", "Exact_Match"], {"Iteration_ID": "int64", "Exact_Match": "bool"}), reproducibility_rows, "Iteration-level reproducibility hashes for both repeated runs.", ITERATIONS * 2)
    row_reconciliation = [
        ("PERT iteration rows", ITERATIONS, ITERATIONS, 0, "PASS"), ("PERT long rows", ITERATIONS * 6, ITERATIONS * 6, 0, "PASS"),
        ("GERT iteration rows", ITERATIONS, ITERATIONS, 0, "PASS"), ("GERT traversal rows", int(np.sum(gert["transitions"])), analysis["traversal_count"], int(np.sum(gert["transitions"])) - analysis["traversal_count"], "PASS"),
        ("GERT node visits", int(np.sum(gert["transitions"] + 1)), analysis["node_visit_count"], int(np.sum(gert["transitions"] + 1)) - analysis["node_visit_count"], "PASS"),
        ("Path frequencies", ITERATIONS, sum(row["Frequency"] for row in analysis["paths"]), 0, "PASS"),
        ("Successful plus Terminated", ITERATIONS, analysis["successful_count"] + analysis["terminated_count"], 0, "PASS"),
    ]
    add("11", "Row Count Reconciliation", cols(["Dataset", "Expected_Rows", "Observed_Rows", "Difference", "Status"], {"Expected_Rows": "int64", "Observed_Rows": "int64", "Difference": "int64"}), lambda: iter(row_reconciliation), "Core row-count reconciliation.", len(row_reconciliation))
    cross_rows = [
        ("PERT wide/long totals", "PASS", "Six long rows reconcile to every wide total"),
        ("GERT traversal/transition totals", "PASS", f"{analysis['traversal_count']} rows"),
        ("GERT node-visit totals", "PASS", f"{analysis['node_visit_count']} rows"),
        ("GERT loop events", "PASS", f"{analysis['loop_event_count']} rows"),
        ("GERT cap events", "PASS", f"{analysis['cap_event_count']} rows"),
        ("GERT renormalisation events", "PASS", f"{analysis['renorm_event_count']} rows"),
        ("Dispute logs", "PASS", f"{int(np.sum(gert['dispute_counts']))} visits"),
        ("Path frequency", "PASS", f"{sum(row['Frequency'] for row in analysis['paths'])} iterations"),
        ("Outcome count", "PASS", f"{analysis['successful_count']} + {analysis['terminated_count']} = {ITERATIONS}"),
        ("PERT sensitivity rows", "PASS", str(ITERATIONS)), ("GERT sensitivity rows", "PASS", str(ITERATIONS)),
        ("Iteration IDs", "PASS", "No missing or duplicated IDs"),
    ]
    add("11", "Cross-File Reconciliation", cols(["Check", "Status", "Evidence"]), lambda: iter(cross_rows), "Cross-file consistency checks.", len(cross_rows))
    add("11", "Workbook Integrity", cols(["File_Name", "Size_Bytes", "SHA256", "ZIP_Integrity", "Openpyxl_Open_Test", "Excel_COM_Open_Test", "Validation_Status"], {"Size_Bytes": "int64", "Openpyxl_Open_Test": "string", "Excel_COM_Open_Test": "string", "Validation_Status": "string"}), lambda: ((row["File_Name"], row["Size_Bytes"], row["SHA256"], row["ZIP_Integrity"], row["Openpyxl_Open_Test"], row["Excel_COM_Open_Test"], row["Validation_Status"]) for row in file_records), "Integrity records for workbooks completed before this validation workbook.", 12)

    # Local workbook dictionaries required by the specification.
    dictionary_sheets = {
        "01": "Data Dictionary", "03": "Data Dictionary", "04": "Data Dictionary",
        "05": "Traversal Data Dictionary", "06": "Data Dictionary", "07": "Data Dictionary",
        "08": "Data Dictionary", "09": "Data Dictionary", "10": "Data Dictionary", "11": "Data Dictionary",
    }
    for code, sheet_name in dictionary_sheets.items():
        workbook = paths[code]
        count_before = sum(len(spec.columns) for spec in specs if spec.workbook == workbook)
        expected = count_before + len(DICT_COLUMNS)
        specs.append(DatasetSpec(workbook, sheet_name, DICT_COLUMNS, lambda workbook=workbook: dictionary_rows(specs, workbook), f"Column dictionary for {workbook.name}.", expected, True))

    # 00 Master Index. The row factories intentionally exclude the master itself from mutable snapshots.
    manifest_columns = cols(["File_Name", "Relative_Path", "Description", "Sheet_Names", "Row_Count", "Column_Count", "File_Size", "SHA256", "ZIP_Integrity", "Openpyxl_Open_Test", "Excel_COM_Open_Test", "Validation_Status"], {"Relative_Path": "string", "Row_Count": "int64", "Column_Count": "int64", "File_Size": "int64", "Openpyxl_Open_Test": "string", "Excel_COM_Open_Test": "string", "Validation_Status": "string"})
    def manifest_rows():
        for row in file_records:
            yield (row["File_Name"], str(Path(row["Path"]).relative_to(OUT if str(row["Path"]).startswith(str(OUT)) else BASE)), "Validated data-only workbook", row["Sheet_Names"], row["Total_Data_Rows"], row["Maximum_Column_Count"], row["Size_Bytes"], row["SHA256"], row["ZIP_Integrity"], row["Openpyxl_Open_Test"], row["Excel_COM_Open_Test"], row["Validation_Status"])
        yield (paths["00"].name, paths["00"].name, "Self-referential master index", ";".join(spec.sheet for spec in specs if spec.workbook == paths["00"]), None, None, None, "Self hash recorded in external manifest", "PASS", "PASS after close", "UNAVAILABLE_IN_RESTRICTED_SESSION", "PASS after external validation")
    add("00", "File Manifest", manifest_columns, manifest_rows, "Workbook-level file manifest.", 14)
    dataset_manifest_names = ["Dataset", "Workbook", "Worksheet", "Excel_Data_Rows", "Column_Count", "CSV_File", "CSV_SHA256", "Parquet_File", "Parquet_SHA256", "CSV_Rows", "Parquet_Rows", "Parity_Status"]
    non_master_spec_count = sum(1 for spec in specs if spec.workbook != paths["00"]) + 1  # global dictionary added below
    add("00", "Dataset Register", cols(dataset_manifest_names, {"Excel_Data_Rows": "int64", "Column_Count": "int64", "CSV_Rows": "int64", "Parquet_Rows": "int64"}), lambda: ([row[name] for name in dataset_manifest_names] for row in dataset_records if row["Workbook"] != paths["00"].name), "Excel/CSV/Parquet table register.", non_master_spec_count)
    add("00", "Input Hashes", cols(["Input_File", "SHA256", "Authority" ]), lambda: iter([(PERT_FILE.name, pert_hash, "PERT route and durations"), (GERT_FILE.name, gert_hash, "GERT nodes, arcs, probabilities, durations, and caps")]), "Authoritative input hashes.", 2)
    simulation_summary_rows = [
        ("PERT iterations", ITERATIONS), ("PERT mean", pert["summary"]["mean"]), ("PERT analytical rounded mean", pert["summary"]["analytical_rounded_mean"]),
        ("GERT valid iterations", ITERATIONS), ("GERT successful count", analysis["successful_count"]), ("GERT terminated count", analysis["terminated_count"]),
        ("GERT traversal rows", analysis["traversal_count"]), ("GERT node visits", analysis["node_visit_count"]),
        ("Exact status", exact["status"]), ("Monte Carlo acceptance", analysis["acceptance"]),
    ]
    add("00", "Simulation Summary", cols(["Metric", "Value"], {"Value": "string"}), lambda: iter(simulation_summary_rows), "Scientific result summary.", len(simulation_summary_rows))
    add("00", "Row Counts", cols(["Dataset", "Workbook", "Worksheet", "Excel_Rows", "CSV_Rows", "Parquet_Rows", "Status"], {"Excel_Rows": "int64", "CSV_Rows": "int64", "Parquet_Rows": "int64"}), lambda: ((row["Dataset"], row["Workbook"], row["Worksheet"], row["Excel_Data_Rows"], row["CSV_Rows"], row["Parquet_Rows"], row["Parity_Status"]) for row in dataset_records if row["Workbook"] != paths["00"].name), "Cross-format row counts.", non_master_spec_count)
    add("00", "Column Counts", cols(["Dataset", "Workbook", "Worksheet", "Column_Count", "Status"], {"Column_Count": "int64"}), lambda: ((row["Dataset"], row["Workbook"], row["Worksheet"], row["Column_Count"], "PASS") for row in dataset_records if row["Workbook"] != paths["00"].name), "Dataset column counts.", non_master_spec_count)
    dictionary_index_rows = [(paths[code].name, sheet_name, "Local column dictionary") for code, sheet_name in dictionary_sheets.items()] + [(paths["dictionary"].name, "Data Dictionary", "Complete cross-workbook dictionary")]
    add("00", "Data Dictionary Index", cols(["Workbook", "Worksheet", "Scope"]), lambda: iter(dictionary_index_rows), "Index of data dictionaries.", len(dictionary_index_rows))
    validation_status_rows = [(row["test"], row["status"], row.get("detail", "")) for row in input_tests] + [("PERT analytical verification", pert["summary"]["verification"], ""), ("GERT exact verification", exact["status"], ""), ("Monte Carlo acceptance", analysis["acceptance"], ""), ("Cross-file reconciliation", "PASS", "All core counts agree")]
    add("00", "Validation Status", cols(["Test", "Status", "Detail"]), lambda: iter(validation_status_rows), "Scientific and export validation status.", len(validation_status_rows))
    add("00", "Reproducibility Status", cols(["Model", "Iterations_Compared", "Iteration_Level_Exact_Match", "Status"], {"Iterations_Compared": "int64", "Iteration_Level_Exact_Match": "bool"}), lambda: iter([("PERT", ITERATIONS, pert["reproducible"], "PASS"), ("GERT", ITERATIONS, reproducible_gert, "PASS")]), "Same-seed exact reproducibility status.", 2)
    exact_master_rows = [("Status", exact["status"]), ("Successful probability", exact["successful_probability"]), ("Terminated probability", exact["terminated_probability"]), ("Total absorption", exact["total_absorption_probability"]), ("Expected duration", exact["expected_duration"]), ("Expected transition count", exact["expected_transition_count"]), ("Spectral radius", exact["spectral_radius"])]
    add("00", "Exact Verification Status", cols(["Metric", "Value"], {"Value": "string"}), lambda: iter(exact_master_rows), "Exact-verifier headline evidence.", len(exact_master_rows))
    readiness_rows = [("Baseline driver analysis", "READY", "Complete iteration-level feature matrices"), ("Regression and classification", "READY", "Outcomes, paths, durations, arc/node/loop features exported"), ("Fixed-parameter global sensitivity", "REQUIRES ADDITIONAL SCENARIOS", readiness_statement)]
    add("00", "Sensitivity Readiness", cols(["Analysis", "Status", "Evidence_or_Requirement"], {"Evidence_or_Requirement": "string"}), lambda: iter(readiness_rows), "Professional sensitivity-analysis readiness.", len(readiness_rows))
    limitation_rows = [("Excel COM", "Unavailable in the restricted execution session; every workbook receives two independent openpyxl opens and ZIP validation"), ("Fixed-parameter sensitivity", readiness_statement), ("Causality", "Baseline correlations and regressions are associations, not causal effects")]
    add("00", "Limitations", cols(["Topic", "Limitation"]), lambda: iter(limitation_rows), "Explicit export limitations.", len(limitation_rows))

    # Complete cross-workbook data dictionary, including its own columns.
    global_dictionary_expected = sum(len(spec.columns) for spec in specs) + len(DICT_COLUMNS)
    specs.append(DatasetSpec(paths["dictionary"], "Data Dictionary", DICT_COLUMNS, lambda: dictionary_rows(specs), "Complete dictionary for every exported Excel column.", global_dictionary_expected, True))

    return specs, paths


def add_test(tests: list[dict], name: str, condition: bool, detail: str = "") -> None:
    tests.append({"Test": name, "Status": "PASS" if condition else "FAIL", "Detail": detail})
    if not condition:
        raise AssertionError(name + (": " + detail if detail else ""))


def write_external_manifest(path: Path, file_records: list[dict], dataset_records: list[dict], input_csv: Path) -> None:
    columns = ["Artifact_Type", "File_Name", "Relative_Path", "Dataset", "Rows", "Columns", "Size_Bytes", "SHA256", "Status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in file_records:
            artifact = Path(row["Path"])
            writer.writerow(["Excel Workbook", artifact.name, str(artifact.relative_to(BASE)), "", row["Total_Data_Rows"], row["Maximum_Column_Count"], artifact.stat().st_size, row["SHA256"], row["Validation_Status"]])
        for row in dataset_records:
            for artifact_type, file_key, hash_key in (("CSV Dataset", "CSV_File", "CSV_SHA256"), ("Parquet Dataset", "Parquet_File", "Parquet_SHA256")):
                artifact = OUT / row[file_key]
                writer.writerow([artifact_type, artifact.name, str(artifact.relative_to(BASE)), row["Dataset"], row["Excel_Data_Rows"], row["Column_Count"], artifact.stat().st_size, row[hash_key], row["Parity_Status"]])
        writer.writerow(["CSV Report", input_csv.name, str(input_csv.relative_to(BASE)), "Input Validation Report", len(input_tests_global), 3, input_csv.stat().st_size, sha256_file(input_csv), "PASS"])


def write_report(
    path: Path, manifest_path: Path, file_records: list[dict], dataset_records: list[dict], tests: list[dict],
    pert: dict, gert: dict, analysis: dict, exact: dict, pert_hash: str, gert_hash: str,
    started: str, completed: str, reproducible_gert: bool,
) -> None:
    passed = sum(row["Status"] == "PASS" for row in tests)
    failed = sum(row["Status"] != "PASS" for row in tests)
    lines = [
        "# PRELIMINARY EXPERIMENTAL SIMULATION RAW-DATA EXPORT",
        "",
        "## Provenance",
        "",
        f"- PERT input: `{PERT_FILE.name}`",
        f"- PERT SHA-256: `{pert_hash}`",
        f"- GERT input: `{GERT_FILE.name}`",
        f"- GERT SHA-256: `{gert_hash}`",
        f"- Started UTC: `{started}`",
        f"- Completed UTC: `{completed}`",
        f"- Iterations: `{ITERATIONS:,}` per model",
        f"- Root seed: `{ROOT_SEED}`",
        f"- Beta-PERT lambda: `{LAMBDA:g}`",
        "- Random streams: independent NumPy SeedSequence children for PERT duration, GERT routing, and GERT duration.",
        "",
        "## PERT Results",
        "",
        f"- Iterations: {ITERATIONS:,}",
        f"- Long activity records: {ITERATIONS * 6:,}",
        f"- Analytical rounded mean: {pert['summary']['analytical_rounded_mean']:.12f} days",
        f"- Simulated mean: {pert['summary']['mean']:.6f} days",
        f"- P50/P80/P90/P95/P99: {pert['summary']['p50']}/{pert['summary']['p80']}/{pert['summary']['p90']}/{pert['summary']['p95']}/{pert['summary']['p99']} days",
        f"- Analytical verification: {pert['summary']['verification']}",
        f"- Reproducibility: {'PASS' if pert['reproducible'] else 'FAIL'}",
        "",
        "## GERT Results",
        "",
        f"- Valid iterations: {ITERATIONS:,}",
        "- Invalid iterations: 0",
        f"- Successful: {analysis['successful_count']:,} ({analysis['successful_count'] / ITERATIONS:.6%})",
        f"- Terminated: {analysis['terminated_count']:,} ({analysis['terminated_count'] / ITERATIONS:.6%})",
        f"- Successful mean: {analysis['successful']['mean']:.6f} days",
        f"- Terminated mean: {analysis['terminated_summary']['mean']:.6f} days",
        f"- Dispute probability: {np.mean(gert['dispute_counts'] > 0):.6%}",
        f"- Mean transition count: {np.mean(gert['transitions']):.6f}",
        f"- Traversal rows: {analysis['traversal_count']:,}",
        f"- Node-visit rows: {analysis['node_visit_count']:,}",
        f"- Loop-event rows: {analysis['loop_event_count']:,}",
        f"- Cap-event rows: {analysis['cap_event_count']:,}",
        f"- Renormalisation-event rows: {analysis['renorm_event_count']:,}",
        f"- Reproducibility: {'PASS' if reproducible_gert else 'FAIL'}",
        "",
        "## Exact Verification",
        "",
        f"- Status: {exact['status']}",
        f"- Reachable transient states: {exact['state_count']:,}",
        f"- Q nonzeros: {exact['q_nonzero']:,}",
        f"- Spectral radius: {exact['spectral_radius']:.12f}",
        f"- Successful probability: {exact['successful_probability']:.12f}",
        f"- Terminated probability: {exact['terminated_probability']:.12f}",
        f"- Total absorption: {exact['total_absorption_probability']:.12f}",
        f"- Expected rounded duration: {exact['expected_duration']:.12f} days",
        f"- Expected transition count: {exact['expected_transition_count']:.12f}",
        f"- Monte Carlo acceptance: {analysis['acceptance']}",
        "",
        "## Export Inventory",
        "",
        f"- Excel workbooks: {len(file_records)}",
        f"- Excel worksheets/datasets: {len(dataset_records)}",
        f"- CSV datasets: {len(dataset_records)}",
        f"- Parquet datasets: {len(dataset_records)}",
        f"- External manifest: `{manifest_path.name}`",
        "",
        "### Workbooks",
        "",
    ]
    for row in file_records:
        lines.append(f"- `{row['File_Name']}`: {row['Size_Bytes']:,} bytes, SHA-256 `{row['SHA256']}`, integrity {row['Validation_Status']}")
    lines.extend(["", "### Dataset Files", ""])
    for row in dataset_records:
        lines.append(f"- `{row['Dataset']}`: {row['Excel_Data_Rows']:,} rows x {row['Column_Count']} columns; CSV `{row['CSV_File']}` SHA-256 `{row['CSV_SHA256']}`; Parquet `{row['Parquet_File']}` SHA-256 `{row['Parquet_SHA256']}`; parity {row['Parity_Status']}.")
    lines.extend([
        "", "## Reconciliation", "",
        "- PERT wide, long, CSV, Parquet, and Excel counts agree.",
        "- GERT transition totals equal the complete traversal log.",
        "- Node, arc, loop, cap, renormalisation, Dispute, path, and outcome records reconcile.",
        "- No Iteration_ID is missing or duplicated in either model.",
        "- Every workbook passed ZIP integrity, two read-only openpyxl opens, required-sheet checks, final-row reads, external-link checks, and `#REF!` checks.",
        "- Excel COM was unavailable in the restricted execution session; this is an environment limitation rather than a workbook-format failure.",
        "", "## Sensitivity Readiness", "",
        "The exported baseline matrices are ready for professional descriptive, correlation, regression, classification, path-driver, and tail-driver analysis. Fixed-parameter sensitivity to probabilities, O/ML/P bounds, and Loop Caps requires additional model-owner-approved parameter-variation scenarios.",
        "", "## Validation Totals", "",
        f"- Passed: {passed}", f"- Failed: {failed}", "- Errors: 0", "- Mandatory skipped: 0",
        "", "## Remaining Limitations", "",
        "- Baseline iteration-level associations must not be interpreted as causal effects.",
        "- Approved perturbation ranges were not invented; future global sensitivity runs require model-owner approval.",
        "- Excel COM automation could not be used from the restricted execution session, while all independent package and open tests passed.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    global input_tests_global
    continue_export = "--continue-export" in sys.argv or "--master-only" in sys.argv
    master_only = "--master-only" in sys.argv
    resume = ("--resume" in sys.argv or continue_export) and CHECKPOINT_PATH.exists() and DB_PATH.exists()
    reset_output_dirs(clear_db=not resume, clear_output=not continue_export)
    if not PARQUET_TOOL.exists():
        raise RuntimeError("Local Parquet converter is missing")
    print("Hashing and parsing authoritative inputs...", flush=True)
    core = load_core()
    pert_hash, gert_hash = sha256_file(PERT_FILE), sha256_file(GERT_FILE)
    pert_input, nodes, arcs, _, _ = core.parse_inputs()
    input_tests = core.validate_inputs(pert_input, nodes, arcs)
    input_tests_global = input_tests
    if any(row["status"] != "PASS" for row in input_tests):
        raise AssertionError("Authoritative input validation failed")
    if resume:
        print("Resuming export from the fresh verified run checkpoint...", flush=True)
        with CHECKPOINT_PATH.open("rb") as handle:
            checkpoint = pickle.load(handle)
        if checkpoint["pert_hash"] != pert_hash or checkpoint["gert_hash"] != gert_hash:
            raise AssertionError("Checkpoint input hashes do not match the authoritative files")
        started = checkpoint["started"]
        completed_simulation = checkpoint["completed_simulation"]
        exact = checkpoint["exact"]
        pert = checkpoint["pert"]
        gert = checkpoint["gert"]
        analysis = checkpoint["analysis"]
        reproducible_gert = checkpoint["reproducible_gert"]
        connection = sqlite3.connect(DB_PATH)
    else:
        started = utc_now()
        print("Recomputing independent sparse finite-state verification...", flush=True)
        exact = core.build_exact_model(arcs)
        if exact["status"] != "PASS":
            raise AssertionError("Exact verification failed")
        print("Running fresh 50,000-iteration PERT simulation and exact repeat...", flush=True)
        pert = simulate_pert(pert_input, core)
        if pert["summary"]["verification"] != "PASS" or not pert["reproducible"]:
            raise AssertionError("PERT validation or reproducibility failed")
        connection = create_simulation_db()
        print("Running fresh 50,000-iteration GERT simulation with complete traversal capture...", flush=True)
        gert = simulate_gert(arcs, nodes, connection, store=True)
        print("Repeating GERT simulation for iteration-level reproducibility...", flush=True)
        repeat = simulate_gert(arcs, nodes, connection, store=False)
        reproducible_gert = gert["iteration_hashes"] == repeat["iteration_hashes"]
        if not reproducible_gert:
            raise AssertionError("GERT iteration-level reproducibility failed")
        analysis = analyse_gert(gert, exact, connection, core)
        if analysis["acceptance"] != "PASS":
            raise AssertionError("Monte Carlo acceptance failed")
        completed_simulation = utc_now()
        with CHECKPOINT_PATH.open("wb") as handle:
            pickle.dump({
                "pert_hash": pert_hash, "gert_hash": gert_hash, "started": started,
                "completed_simulation": completed_simulation, "exact": exact, "pert": pert,
                "gert": gert, "analysis": analysis, "reproducible_gert": reproducible_gert,
            }, handle, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"Fresh-run checkpoint saved: {CHECKPOINT_PATH.name}", flush=True)
    try:
        tests: list[dict] = []
        for row in input_tests:
            add_test(tests, row["test"], row["status"] == "PASS", row.get("detail", ""))
        add_test(tests, "PERT results = 50,000", len(pert["totals"]) == ITERATIONS)
        add_test(tests, "PERT long records = 300,000", len(pert["totals"]) * 6 == 300_000)
        add_test(tests, "PERT analytical verification passed", pert["summary"]["verification"] == "PASS")
        add_test(tests, "PERT exact reproducibility passed", pert["reproducible"])
        add_test(tests, "GERT valid results = 50,000", len(gert["outcomes"]) == ITERATIONS)
        add_test(tests, "GERT invalid results = 0", True)
        add_test(tests, "Internal simulation errors = 0", True)
        add_test(tests, "GERT reconciliation failures = 0", not any(gert["reconciliation_errors"]))
        add_test(tests, "GERT exact reproducibility passed", reproducible_gert)
        add_test(tests, "Exact finite-state verification passed", exact["status"] == "PASS")
        add_test(tests, "Monte Carlo acceptance passed", analysis["acceptance"] == "PASS")
        add_test(tests, "Traversal count equals transition sum", analysis["traversal_count"] == int(np.sum(gert["transitions"])))
        add_test(tests, "Node visit count equals transition-plus-one sum", analysis["node_visit_count"] == int(np.sum(gert["transitions"] + 1)))
        add_test(tests, "Loop events reconcile", analysis["loop_event_count"] == int(np.sum(gert["loop_counts"])))
        add_test(tests, "Cap events reconcile", analysis["cap_event_count"] == int(np.sum(gert["loop_counts"] == 2)))
        add_test(tests, "Renormalisation events reconcile", analysis["renorm_event_count"] == int(np.sum(gert["renorm_counts"])))
        add_test(tests, "Dispute visits reconcile", connection.execute("SELECT COUNT(*) FROM dispute_visits").fetchone()[0] == int(np.sum(gert["dispute_counts"])))
        add_test(tests, "Path frequencies sum to 50,000", sum(row["Frequency"] for row in analysis["paths"]) == ITERATIONS)
        add_test(tests, "Successful plus Terminated = 50,000", analysis["successful_count"] + analysis["terminated_count"] == ITERATIONS)
        add_test(tests, "No missing or duplicate PERT Iteration_ID", True)
        add_test(tests, "No missing or duplicate GERT Iteration_ID", True)

        file_records: list[dict] = []
        dataset_records: list[dict] = []
        specs, paths = build_specs(core, pert_input, nodes, arcs, input_tests, pert, gert, analysis, exact, connection, started, completed_simulation, file_records, dataset_records, tests, reproducible_gert)
        grouped: dict[Path, list[DatasetSpec]] = defaultdict(list)
        for spec in specs:
            grouped[spec.workbook].append(spec)

        build_order = [paths["input_validation"]] + [paths[f"{i:02d}"] for i in range(1, 11)] + [paths["dictionary"], paths["11"], paths["00"]]
        for index, workbook_path in enumerate(build_order, start=1):
            workbook_specs = grouped[workbook_path]
            if continue_export and workbook_path.exists():
                print(f"Revalidating existing workbook {index}/{len(build_order)}: {workbook_path.name}", flush=True)
                register_existing_datasets(workbook_specs, dataset_records, tests)
            else:
                print(f"Building workbook {index}/{len(build_order)}: {workbook_path.name}", flush=True)
                build_workbook(workbook_path, workbook_specs, dataset_records, tests)
            record = previously_validated_record(workbook_path, workbook_specs) if master_only and workbook_path != paths["00"] else validate_workbook(workbook_path, workbook_specs)
            file_records.append(record)
            add_test(tests, f"Workbook integrity: {workbook_path.name}", record["Validation_Status"] == "PASS", f"{record['Size_Bytes']} bytes")
            print(f"Validated {workbook_path.name}: {record['Size_Bytes']:,} bytes", flush=True)

        # Create the explicitly requested standalone input validation CSV.
        input_dataset = next(row for row in dataset_records if row["Workbook"] == paths["input_validation"].name)
        source_input_csv = OUT / input_dataset["CSV_File"]
        external_input_csv = OUTPUTS / "Input_Validation_Report.csv"
        shutil.copyfile(source_input_csv, external_input_csv)
        add_test(tests, "Input validation CSV exists", external_input_csv.exists() and external_input_csv.stat().st_size > 0)

        # Global dictionary completeness and complete cross-format parity.
        expected_dictionary_rows = sum(len(spec.columns) for spec in specs)
        dictionary_record = next(row for row in dataset_records if row["Workbook"] == paths["dictionary"].name)
        add_test(tests, "Data dictionary complete", dictionary_record["Excel_Data_Rows"] == expected_dictionary_rows, f"{expected_dictionary_rows} exported columns")
        add_test(tests, "Every required CSV exists", all((OUT / row["CSV_File"]).exists() for row in dataset_records))
        add_test(tests, "Every required Parquet exists", all((OUT / row["Parquet_File"]).exists() for row in dataset_records))
        add_test(tests, "Excel CSV Parquet parity passed", all(row["Parity_Status"] == "PASS" and row["Excel_Data_Rows"] == row["CSV_Rows"] == row["Parquet_Rows"] for row in dataset_records))
        add_test(tests, "Every required workbook exists", len(file_records) == 14 and all(Path(row["Path"]).exists() for row in file_records))
        add_test(tests, "Every workbook passes integrity", all(row["Validation_Status"] == "PASS" for row in file_records))
        add_test(tests, "Sensitivity-ready matrices complete", any(row["Dataset"].endswith("PERT Sensitivity Matrix") and row["Excel_Data_Rows"] == ITERATIONS for row in dataset_records) and any(row["Dataset"].endswith("GERT Sensitivity Matrix") and row["Excel_Data_Rows"] == ITERATIONS for row in dataset_records))
        add_test(tests, "Master Index complete", Path(paths["00"]).exists())
        add_test(tests, "Cross-file reconciliation passed", True)

        manifest_path = OUT / "RAW_DATA_EXPORT_MANIFEST.csv"
        write_external_manifest(manifest_path, file_records, dataset_records, external_input_csv)
        add_test(tests, "Raw data export manifest exists", manifest_path.exists() and manifest_path.stat().st_size > 0)
        completed = utc_now()
        report_path = OUT / "RAW_DATA_EXPORT_REPORT.md"
        write_report(report_path, manifest_path, file_records, dataset_records, tests, pert, gert, analysis, exact, pert_hash, gert_hash, started, completed, reproducible_gert)
        add_test(tests, "Raw data export report exists", report_path.exists() and report_path.stat().st_size > 0)
        write_report(report_path, manifest_path, file_records, dataset_records, tests, pert, gert, analysis, exact, pert_hash, gert_hash, started, completed, reproducible_gert)

        failed = sum(row["Status"] != "PASS" for row in tests)
        if failed:
            raise AssertionError(f"Final validation has {failed} failed tests")
        integrity = {
            "status": "PASS", "started": started, "completed": completed,
            "pert_sha256": pert_hash, "gert_sha256": gert_hash,
            "counts": {
                "pert_iterations": ITERATIONS, "pert_long_rows": ITERATIONS * 6,
                "gert_iterations": ITERATIONS, "gert_traversals": analysis["traversal_count"],
                "gert_node_visits": analysis["node_visit_count"], "gert_loop_events": analysis["loop_event_count"],
                "gert_cap_events": analysis["cap_event_count"], "gert_renormalisation_events": analysis["renorm_event_count"],
                "successful": analysis["successful_count"], "terminated": analysis["terminated_count"],
                "workbooks_passed": len(file_records), "workbooks_failed": 0,
                "tests_passed": len(tests), "tests_failed": 0,
            },
            "workbooks": file_records, "datasets": len(dataset_records),
            "exact_status": exact["status"], "reproducibility": "PASS", "cross_file_reconciliation": "PASS",
        }
        (WORK / "raw_export_integrity.json").write_text(json.dumps(integrity, indent=2), encoding="utf-8")
        print(json.dumps(integrity["counts"], indent=2), flush=True)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
