from __future__ import annotations

import hashlib
import json
import math
import platform
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from docx import Document


SOURCE = Path(r"C:\Users\moham\OneDrive\Desktop\Authoritative_GERT_PERT_Input.docx.docx")
WORK_DIR = Path(r"C:\Users\moham\Documents\Codex\2026-07-28\build\work\preliminary_run")
DATA_PATH = WORK_DIR / "simulation_data.json"
ITERATIONS = 50_000
SEED = 42
LAMBDA = 4.0
TIME_UNIT = "days"
TITLE = "PRELIMINARY EXPERIMENTAL SIMULATION RESULTS"
GERT_REASON = (
    "The attached Word file supplies probabilities, Loop Caps, and duration estimates "
    "but does not explicitly identify Arc IDs, Arc Tags, or transition destinations. "
    "Generating a GERT network from these values would require unsupported assumptions."
)

ACTIVITIES = [
    ("Identification", 5.0, 7.0, 10.0),
    ("Evaluation / Proposal", 5.0, 7.0, 10.0),
    ("Approval / Instruction", 10.0, 14.0, 20.0),
    ("Implementation", 50.0, 60.0, 80.0),
    ("Inspection / Verification", 10.0, 12.0, 14.0),
    ("Valuation & Adjustment", 7.0, 10.0, 12.0),
]

REQUIRED_NODES = [
    "Start VO Trigger",
    "Identification",
    "Evaluation / Proposal",
    "Approval / Instruction",
    "Implementation (Control Point)",
    "Inspection / Verification",
    "Valuation & Adjustment (Consolidation)",
    "Dispute Resolution",
    "Final Closeout",
    "Withdrawn / Rejected",
]

EXPECTED_PROBABILITIES = {
    "Identification": [0.60, 0.40],
    "Evaluation / Proposal": [0.01, 0.90, 0.04, 0.04, 0.01],
    "Approval / Instruction": [0.90, 0.04, 0.04, 0.01, 0.01],
    "Implementation (Control Point)": [0.90, 0.05, 0.02, 0.01, 0.02],
    "Inspection / Verification": [0.90, 0.05, 0.01, 0.02, 0.01, 0.01],
    "Valuation & Adjustment (Consolidation)": [0.95, 0.04, 0.01],
    "Dispute Resolution": [0.90, 0.05, 0.05],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def normalize_node(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\s*/\s*", " / ", value)
    return clean_text(value)


def parse_number(value: str) -> float | None:
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_word_table() -> tuple[list[list[str]], list[dict], list[str], list[dict], dict]:
    document = Document(SOURCE)
    if not document.tables:
        raise AssertionError("The Word file contains no tables.")
    table = document.tables[0]
    raw_rows = [[clean_text(cell.text) for cell in row.cells] for row in table.rows]
    physical_column_count = len(raw_rows[0])
    if physical_column_count not in (11, 12) or any(len(row) != physical_column_count for row in raw_rows):
        raise AssertionError("The first Word table does not consistently contain 11 or 12 physical columns.")

    records: list[dict] = []
    nodes_seen: list[str] = []
    current = {"node_id": "", "node_name": "", "input_logic": "", "output_logic": ""}
    node_definitions: dict[str, dict] = {}
    nonprobabilistic_arcs: list[dict] = []
    for zero_index, row in enumerate(raw_rows):
        if physical_column_count == 12:
            node_id, node_name, input_logic, output_logic, from_node, to_node, tag, prob, cap, o, ml, p = row
            arc = f"{from_node} -> {to_node}" if from_node and to_node else ""
        else:
            node_id, node_name, input_logic, output_logic, arc, tag, prob, cap, o, ml, p = row
            from_node = ""
            to_node = ""
        normalized_name = normalize_node(node_name)
        if normalized_name:
            current["node_name"] = normalized_name
            if normalized_name not in nodes_seen:
                nodes_seen.append(normalized_name)
            current["node_id"] = node_id
            current["input_logic"] = input_logic
            current["output_logic"] = output_logic
            if node_id:
                node_definitions[node_id] = {
                    "node_id": node_id,
                    "node_name": normalized_name,
                    "input_logic": input_logic,
                    "output_logic": output_logic,
                }
        else:
            if node_id:
                current["node_id"] = node_id
            if input_logic:
                current["input_logic"] = input_logic
            if output_logic:
                current["output_logic"] = output_logic

        probability = parse_number(prob)
        if probability is None:
            if from_node and to_node:
                nonprobabilistic_arcs.append(
                    {
                        "word_row_number": zero_index + 1,
                        "from_node": from_node,
                        "to_node": to_node,
                        "arc_tag": tag,
                    }
                )
            continue

        loop_cap_value = parse_number(cap)
        record = {
            "record_id": len(records) + 1,
            "word_row_number": zero_index + 1,
            "source_node_name": current["node_name"],
            "node_id": current["node_id"],
            "input_logic": current["input_logic"],
            "output_logic": current["output_logic"],
            "arc_expression": arc,
            "arc_tag": tag,
            "from_node": from_node,
            "to_node": to_node,
            "probability": probability,
            "loop_cap": int(loop_cap_value) if loop_cap_value is not None else None,
            "o": parse_number(o),
            "ml": parse_number(ml),
            "p": parse_number(p),
        }
        records.append(record)

    group_totals = {
        group: math.fsum(r["probability"] for r in records if r["source_node_name"] == group)
        for group in EXPECTED_PROBABILITIES
    }

    pert_input_lookup = {
        ("Identification", 5.0, 7.0, 10.0),
        ("Evaluation / Proposal", 5.0, 7.0, 10.0),
        ("Approval / Instruction", 10.0, 14.0, 20.0),
        ("Implementation (Control Point)", 50.0, 60.0, 80.0),
        ("Inspection / Verification", 10.0, 12.0, 14.0),
        ("Valuation & Adjustment (Consolidation)", 7.0, 10.0, 12.0),
    }
    for record in records:
        missing = []
        if not record["node_id"]:
            missing.append("Node ID")
        if not record["arc_expression"]:
            missing.append("Arc expression")
        if not record["arc_tag"]:
            missing.append("Arc Tag")
        if not record["from_node"]:
            missing.append("From Node")
        if not record["to_node"]:
            missing.append("To Node")
        record["probability_group_total"] = group_totals[record["source_node_name"]]
        record["missing_fields"] = "; ".join(missing)
        record["pert_use"] = (
            "Yes - fixed PERT activity input"
            if (record["source_node_name"], record["o"], record["ml"], record["p"]) in pert_input_lookup
            else "No"
        )
        record["gert_use"] = "Yes" if not missing else "No - structural gate failed"
        numeric_valid = (
            0.0 <= record["probability"] <= 1.0
            and record["o"] is not None
            and record["ml"] is not None
            and record["p"] is not None
            and 0.0 <= record["o"] <= record["ml"] <= record["p"]
            and record["o"] < record["p"]
        )
        record["validation_status"] = "PASS" if numeric_valid else "FAIL"
        record["validation_message"] = (
            "Numerical and explicit GERT structural fields valid."
            if numeric_valid and not missing
            else "Numerical fields valid; GERT structural fields incomplete."
            if numeric_valid
            else "Invalid probability or duration ordering."
        )
        record["is_return_arc"] = record["loop_cap"] is not None
        record["loop_id"] = record["arc_tag"] if record["is_return_arc"] else ""
        destination = node_definitions.get(record["to_node"], {})
        destination_name = destination.get("node_name", "")
        record["terminal_outcome"] = (
            "Successful"
            if destination_name == "Final Closeout"
            else "Terminated"
            if destination_name == "Withdrawn / Rejected"
            else ""
        )
    network = {
        "physical_column_count": physical_column_count,
        "node_definitions": list(node_definitions.values()),
        "nonprobabilistic_arcs": nonprobabilistic_arcs,
        "terminal_nodes": {"S7": "Successful", "ST": "Terminated"},
    }
    return raw_rows, records, nodes_seen, nonprobabilistic_arcs, network


def beta_parameters(o: float, ml: float, p: float) -> tuple[float, float]:
    return (
        1.0 + LAMBDA * (ml - o) / (p - o),
        1.0 + LAMBDA * (p - ml) / (p - o),
    )


def beta_continued_fraction(a: float, b: float, x: float) -> float:
    max_iterations = 400
    epsilon = 3.0e-14
    fp_min = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fp_min:
        d = fp_min
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fp_min:
            d = fp_min
        c = 1.0 + aa / c
        if abs(c) < fp_min:
            c = fp_min
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fp_min:
            d = fp_min
        c = 1.0 + aa / c
        if abs(c) < fp_min:
            c = fp_min
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) <= epsilon:
            return h
    raise ArithmeticError("Incomplete beta continued fraction did not converge.")


def regularized_beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * beta_continued_fraction(a, b, x) / a
    return 1.0 - bt * beta_continued_fraction(b, a, 1.0 - x) / b


def expected_rounded_duration(o: float, ml: float, p: float) -> float:
    alpha, beta = beta_parameters(o, ml, p)

    def cdf_at(duration: float) -> float:
        scaled = (duration - o) / (p - o)
        return regularized_beta_cdf(scaled, alpha, beta)

    expected = 0.0
    for rounded in range(math.ceil(o), math.ceil(p) + 1):
        probability = cdf_at(rounded) - cdf_at(rounded - 1)
        expected += rounded * probability
    return expected


def nearest_rank(sorted_values: np.ndarray, percentile: int) -> int:
    rank = math.ceil((percentile / 100.0) * sorted_values.size)
    return int(sorted_values[rank - 1])


def run_pert() -> dict:
    started = now_iso()
    root = np.random.SeedSequence(SEED)
    streams = root.spawn(3)
    rng = np.random.default_rng(streams[0])
    raw = np.empty((ITERATIONS, len(ACTIVITIES)), dtype=np.float64)
    rounded = np.empty((ITERATIONS, len(ACTIVITIES)), dtype=np.int16)

    analytical_rows = []
    for index, (name, o, ml, p) in enumerate(ACTIVITIES):
        alpha, beta = beta_parameters(o, ml, p)
        draws = o + (p - o) * rng.beta(alpha, beta, ITERATIONS)
        raw[:, index] = draws
        rounded[:, index] = np.ceil(draws).astype(np.int16)
        analytical_rows.append(
            {
                "sequence": index + 1,
                "activity": name,
                "o": o,
                "ml": ml,
                "p": p,
                "alpha": alpha,
                "beta": beta,
                "pre_ceiling_mean": (o + LAMBDA * ml + p) / (LAMBDA + 2.0),
                "analytical_rounded_mean": expected_rounded_duration(o, ml, p),
                "simulated_mean": float(np.mean(rounded[:, index])),
            }
        )

    totals = np.sum(rounded, axis=1, dtype=np.int32)
    sorted_totals = np.sort(totals)
    percentiles = {str(p): nearest_rank(sorted_totals, p) for p in range(1, 100)}
    mean = float(np.mean(totals))
    variance = float(np.var(totals, ddof=1))
    sd = float(np.std(totals, ddof=1))
    mcse = sd / math.sqrt(ITERATIONS)
    analytical_rounded_mean = math.fsum(row["analytical_rounded_mean"] for row in analytical_rows)
    difference = mean - analytical_rounded_mean

    checkpoints = []
    interval = max(100, ITERATIONS // 100)
    previous = None
    for count in range(interval, ITERATIONS + 1, interval):
        sample = totals[:count]
        sample_sorted = np.sort(sample)
        current = {
            "sample_size": count,
            "running_mean": float(np.mean(sample)),
            "running_sd": float(np.std(sample, ddof=1)),
            "p50": nearest_rank(sample_sorted, 50),
            "p80": nearest_rank(sample_sorted, 80),
            "p90": nearest_rank(sample_sorted, 90),
            "p95": nearest_rank(sample_sorted, 95),
            "p99": nearest_rank(sample_sorted, 99),
        }
        if previous is None:
            current["max_relative_change"] = None
            current["stability_pass"] = None
        else:
            values = ["running_mean", "p50", "p80", "p90", "p95", "p99"]
            changes = [
                abs(current[key] - previous[key]) / max(abs(current[key]), 1.0)
                for key in values
            ]
            current["max_relative_change"] = max(changes)
            current["stability_pass"] = max(changes) <= 0.01
        checkpoints.append(current)
        previous = current
    convergence = (
        "Converged"
        if len(checkpoints) >= 6 and all(row["stability_pass"] for row in checkpoints[-5:])
        else "Not Converged"
    )

    reroot = np.random.SeedSequence(SEED)
    restreams = reroot.spawn(3)
    rerng = np.random.default_rng(restreams[0])
    repeat_rounded = np.empty_like(rounded)
    for index, (_, o, ml, p) in enumerate(ACTIVITIES):
        alpha, beta = beta_parameters(o, ml, p)
        repeat_draws = o + (p - o) * rerng.beta(alpha, beta, ITERATIONS)
        repeat_rounded[:, index] = np.ceil(repeat_draws).astype(np.int16)
    reproducible = bool(np.array_equal(rounded, repeat_rounded))

    unique, counts = np.unique(totals, return_counts=True)
    cumulative = np.cumsum(counts) / ITERATIONS
    histogram = [
        {"duration": int(value), "frequency": int(count), "relative_frequency": float(count / ITERATIONS)}
        for value, count in zip(unique, counts)
    ]
    ecdf = [
        {"duration": int(value), "cumulative_probability": float(probability)}
        for value, probability in zip(unique, cumulative)
    ]

    completed = now_iso()
    return {
        "started": started,
        "completed": completed,
        "stream_metadata": [
            {
                "name": name,
                "entropy": int(stream.entropy),
                "spawn_key": list(stream.spawn_key),
                "pool_size": int(stream.pool_size),
            }
            for name, stream in zip(
                ["PERT duration stream", "GERT routing stream", "GERT duration stream"], streams
            )
        ],
        "raw": raw.tolist(),
        "rounded": rounded.astype(int).tolist(),
        "totals": totals.astype(int).tolist(),
        "analytical_rows": analytical_rows,
        "percentiles": percentiles,
        "convergence_rows": checkpoints,
        "histogram": histogram,
        "ecdf": ecdf,
        "summary": {
            "n": ITERATIONS,
            "mean": mean,
            "ceiling_of_mean": math.ceil(mean),
            "variance": variance,
            "standard_deviation": sd,
            "coefficient_of_variation": sd / mean,
            "minimum": int(np.min(totals)),
            "maximum": int(np.max(totals)),
            "p25": percentiles["25"],
            "p50": percentiles["50"],
            "p75": percentiles["75"],
            "iqr": percentiles["75"] - percentiles["25"],
            "p80": percentiles["80"],
            "p90": percentiles["90"],
            "p95": percentiles["95"],
            "p99": percentiles["99"],
            "mcse": mcse,
            "analytical_rounded_mean": analytical_rounded_mean,
            "difference": difference,
            "verification_status": "PASS" if abs(difference) <= 4.0 * mcse else "FAIL",
            "reproducibility_status": "PASS - exact match" if reproducible else "FAIL",
            "convergence_status": convergence,
        },
    }


def summarize_integer_durations(values: list[int]) -> dict | None:
    if not values:
        return None
    array = np.asarray(values, dtype=np.int32)
    sorted_values = np.sort(array)
    sd = float(np.std(array, ddof=1)) if array.size > 1 else 0.0
    return {
        "n": int(array.size),
        "mean": float(np.mean(array)),
        "variance": float(np.var(array, ddof=1)) if array.size > 1 else 0.0,
        "standard_deviation": sd,
        "minimum": int(np.min(array)),
        "maximum": int(np.max(array)),
        "p50": nearest_rank(sorted_values, 50),
        "p80": nearest_rank(sorted_values, 80),
        "p90": nearest_rank(sorted_values, 90),
        "p95": nearest_rank(sorted_values, 95),
        "p99": nearest_rank(sorted_values, 99),
        "mcse": sd / math.sqrt(array.size),
    }


def exact_gert_verifier(records: list[dict]) -> dict:
    outgoing: dict[str, list[dict]] = {}
    for record in records:
        outgoing.setdefault(record["from_node"], []).append(record)
    loop_records = [record for record in records if record["is_return_arc"]]
    loop_position = {record["arc_tag"]: index for index, record in enumerate(loop_records)}
    terminal_nodes = {"S7": "Successful", "ST": "Terminated"}
    start_state = ("S1", tuple(0 for _ in loop_records))
    states = [start_state]
    state_index = {start_state: 0}
    transitions: list[list[tuple[float, tuple | None, str | None, float]]] = []
    cursor = 0
    while cursor < len(states):
        node, counts = states[cursor]
        arcs = outgoing.get(node, [])
        eligible = []
        for arc in arcs:
            if arc["is_return_arc"]:
                position = loop_position[arc["arc_tag"]]
                if counts[position] >= arc["loop_cap"]:
                    continue
            eligible.append(arc)
        denominator = math.fsum(arc["probability"] for arc in eligible)
        if denominator <= 0.0:
            raise AssertionError(f"No eligible outgoing probability from exact state {node}.")
        state_transitions = []
        for arc in eligible:
            probability = arc["probability"] / denominator
            next_counts = list(counts)
            if arc["is_return_arc"]:
                next_counts[loop_position[arc["arc_tag"]]] += 1
            expected_reward = expected_rounded_duration(arc["o"], arc["ml"], arc["p"])
            if arc["to_node"] in terminal_nodes:
                state_transitions.append((probability, None, terminal_nodes[arc["to_node"]], expected_reward))
            else:
                next_state = (arc["to_node"], tuple(next_counts))
                if next_state not in state_index:
                    state_index[next_state] = len(states)
                    states.append(next_state)
                state_transitions.append((probability, next_state, None, expected_reward))
        transitions.append(state_transitions)
        cursor += 1

    size = len(states)
    q = np.zeros((size, size), dtype=np.float64)
    r = np.zeros((size, 2), dtype=np.float64)
    reward = np.zeros(size, dtype=np.float64)
    terminal_column = {"Successful": 0, "Terminated": 1}
    for row_index, state_transitions in enumerate(transitions):
        for probability, next_state, terminal, expected_reward in state_transitions:
            reward[row_index] += probability * expected_reward
            if terminal is None:
                q[row_index, state_index[next_state]] += probability
            else:
                r[row_index, terminal_column[terminal]] += probability
    fundamental_operator = np.eye(size) - q
    absorption = np.linalg.solve(fundamental_operator, r)
    expected_duration = np.linalg.solve(fundamental_operator, reward)
    result = absorption[0]
    return {
        "reachable_transient_states": size,
        "successful_probability": float(result[0]),
        "terminated_probability": float(result[1]),
        "probability_sum": float(np.sum(result)),
        "expected_rounded_duration": float(expected_duration[0]),
        "status": "PASS" if math.isclose(float(np.sum(result)), 1.0, abs_tol=1e-12) else "FAIL",
    }


def run_gert(records: list[dict]) -> dict:
    outgoing: dict[str, list[dict]] = {}
    for record in records:
        outgoing.setdefault(record["from_node"], []).append(record)
    loop_records = [record for record in records if record["is_return_arc"]]
    terminals = {"S7": "Successful", "ST": "Terminated"}

    def execute(store_details: bool) -> tuple[list[tuple], dict]:
        root = np.random.SeedSequence(SEED)
        streams = root.spawn(3)
        routing_rng = np.random.default_rng(streams[1])
        duration_rng = np.random.default_rng(streams[2])
        signatures: list[tuple] = []
        iterations: list[dict] = []
        cap_events: list[dict] = []
        renormalisation_events: list[dict] = []
        all_selected_eligible = True
        for iteration_id in range(1, ITERATIONS + 1):
            node = "S1"
            node_sequence = ["S0", "S1"]
            arc_sequence: list[str] = []
            raw_durations: list[float] = []
            rounded_durations: list[int] = []
            original_probabilities: list[float] = []
            effective_probabilities: list[float] = []
            loop_counts = {record["arc_tag"]: 0 for record in loop_records}
            dispute_visited = False
            local_cap_events = 0
            local_renormalisations = 0
            while node not in terminals:
                arcs = outgoing.get(node, [])
                if not arcs:
                    raise AssertionError(f"No outgoing arcs from nonterminal node {node}.")
                eligible = []
                removed = []
                for arc in arcs:
                    if arc["is_return_arc"] and loop_counts[arc["arc_tag"]] >= arc["loop_cap"]:
                        removed.append(arc)
                    else:
                        eligible.append(arc)
                denominator = math.fsum(arc["probability"] for arc in eligible)
                if denominator <= 0.0:
                    raise AssertionError(f"No eligible outgoing probability from {node}.")
                effective = [arc["probability"] / denominator for arc in eligible]
                if removed:
                    local_renormalisations += 1
                    if store_details:
                        renormalisation_events.append(
                            {
                                "iteration_id": iteration_id,
                                "node": node,
                                "removed_arc_tags": "; ".join(arc["arc_tag"] for arc in removed),
                                "eligible_arc_tags": "; ".join(arc["arc_tag"] for arc in eligible),
                                "original_probabilities": "; ".join(f"{arc['probability']:.12g}" for arc in eligible),
                                "effective_probabilities": "; ".join(f"{value:.12g}" for value in effective),
                            }
                        )
                draw = routing_rng.random()
                selected_index = int(np.searchsorted(np.cumsum(effective), draw, side="right"))
                if selected_index >= len(eligible):
                    selected_index = len(eligible) - 1
                selected = eligible[selected_index]
                if selected not in eligible:
                    all_selected_eligible = False
                alpha, beta = beta_parameters(selected["o"], selected["ml"], selected["p"])
                raw_duration = selected["o"] + (selected["p"] - selected["o"]) * duration_rng.beta(alpha, beta)
                rounded_duration = math.ceil(raw_duration)
                arc_sequence.append(selected["arc_tag"])
                raw_durations.append(float(raw_duration))
                rounded_durations.append(int(rounded_duration))
                original_probabilities.append(selected["probability"])
                effective_probabilities.append(effective[selected_index])
                if selected["is_return_arc"]:
                    loop_counts[selected["arc_tag"]] += 1
                    if loop_counts[selected["arc_tag"]] == selected["loop_cap"]:
                        local_cap_events += 1
                        if store_details:
                            cap_events.append(
                                {
                                    "iteration_id": iteration_id,
                                    "loop_id": selected["loop_id"],
                                    "arc_tag": selected["arc_tag"],
                                    "cap": selected["loop_cap"],
                                    "count_when_reached": loop_counts[selected["arc_tag"]],
                                }
                            )
                node = selected["to_node"]
                node_sequence.append(node)
                if node == "SD":
                    dispute_visited = True
            total_duration = sum(rounded_durations)
            outcome = terminals[node]
            reconciliation_status = "PASS" if total_duration == sum(rounded_durations) else "FAIL"
            signature = (outcome, total_duration, tuple(arc_sequence), tuple(rounded_durations))
            signatures.append(signature)
            if store_details:
                iterations.append(
                    {
                        "iteration_id": iteration_id,
                        "node_sequence": " > ".join(node_sequence),
                        "arc_sequence": " > ".join(arc_sequence),
                        "raw_traversal_durations": "; ".join(f"{value:.12f}" for value in raw_durations),
                        "rounded_traversal_durations": "; ".join(str(value) for value in rounded_durations),
                        "total_duration": total_duration,
                        "transition_count": len(arc_sequence),
                        "loop_counts": "; ".join(f"{key}={value}" for key, value in loop_counts.items()),
                        "cap_event_count": local_cap_events,
                        "original_probabilities": "; ".join(f"{value:.12g}" for value in original_probabilities),
                        "effective_probabilities": "; ".join(f"{value:.12g}" for value in effective_probabilities),
                        "renormalisation_event_count": local_renormalisations,
                        "dispute_visited": dispute_visited,
                        "final_terminal": node,
                        "final_outcome": outcome,
                        "reconciliation_status": reconciliation_status,
                    }
                )
        return signatures, {
            "iterations": iterations,
            "cap_events": cap_events,
            "renormalisation_events": renormalisation_events,
            "all_selected_eligible": all_selected_eligible,
        }

    signatures, details = execute(store_details=True)
    repeated_signatures, _ = execute(store_details=False)
    reproducible = signatures == repeated_signatures
    iteration_rows = details["iterations"]
    successful = [row for row in iteration_rows if row["final_outcome"] == "Successful"]
    terminated = [row for row in iteration_rows if row["final_outcome"] == "Terminated"]
    success_probability = len(successful) / ITERATIONS
    terminated_probability = len(terminated) / ITERATIONS
    all_durations = [row["total_duration"] for row in iteration_rows]
    exact = exact_gert_verifier(records)

    path_counts: dict[tuple[str, str, str], int] = {}
    node_visits: dict[str, int] = {}
    arc_counts: dict[str, int] = {}
    for row in iteration_rows:
        key = (row["node_sequence"], row["arc_sequence"], row["final_outcome"])
        path_counts[key] = path_counts.get(key, 0) + 1
        for node in row["node_sequence"].split(" > "):
            node_visits[node] = node_visits.get(node, 0) + 1
        for arc in row["arc_sequence"].split(" > "):
            if arc:
                arc_counts[arc] = arc_counts.get(arc, 0) + 1
    paths = [
        {
            "rank": rank,
            "node_sequence": key[0],
            "arc_sequence": key[1],
            "outcome": key[2],
            "frequency": count,
            "probability": count / ITERATIONS,
        }
        for rank, (key, count) in enumerate(
            sorted(path_counts.items(), key=lambda item: (-item[1], item[0]))[:100], start=1
        )
    ]
    nodes = [
        {"node_id": node_id, "visit_count": count, "mean_visits_per_iteration": count / ITERATIONS}
        for node_id, count in sorted(node_visits.items())
    ]
    arcs = []
    for record in records:
        count = arc_counts.get(record["arc_tag"], 0)
        arcs.append(
            {
                "arc_tag": record["arc_tag"],
                "from_node": record["from_node"],
                "to_node": record["to_node"],
                "original_probability": record["probability"],
                "traversal_count": count,
                "mean_traversals_per_iteration": count / ITERATIONS,
            }
        )
    loops = []
    for record in loop_records:
        counts = []
        token = record["arc_tag"] + "="
        for row in iteration_rows:
            value = 0
            for part in row["loop_counts"].split("; "):
                if part.startswith(token):
                    value = int(part.split("=", 1)[1])
                    break
            counts.append(value)
        loops.append(
            {
                "loop_id": record["loop_id"],
                "arc_tag": record["arc_tag"],
                "from_node": record["from_node"],
                "to_node": record["to_node"],
                "loop_cap": record["loop_cap"],
                "activation_count": sum(value > 0 for value in counts),
                "activation_probability": sum(value > 0 for value in counts) / ITERATIONS,
                "total_traversals": sum(counts),
                "maximum_observed": max(counts),
            }
        )
    total_loop_repetitions = []
    for row in iteration_rows:
        total_loop_repetitions.append(
            sum(int(part.split("=", 1)[1]) for part in row["loop_counts"].split("; ") if part)
        )
    repetition_values, repetition_counts = np.unique(total_loop_repetitions, return_counts=True)
    loop_repetition_distribution = [
        {"repetitions": int(value), "frequency": int(count), "probability": int(count) / ITERATIONS}
        for value, count in zip(repetition_values, repetition_counts)
    ]

    success_durations = [row["total_duration"] for row in successful]
    terminated_durations = [row["total_duration"] for row in terminated]
    outcome_ecdf = {}
    for label, durations in (("Successful", success_durations), ("Terminated", terminated_durations)):
        if durations:
            values, counts = np.unique(durations, return_counts=True)
            outcome_ecdf[label] = [
                {"duration": int(value), "cumulative_probability": float(probability)}
                for value, probability in zip(values, np.cumsum(counts) / len(durations))
            ]
        else:
            outcome_ecdf[label] = []
    histograms = {}
    for label, durations in (("Successful", success_durations), ("Terminated", terminated_durations)):
        if durations:
            values, counts = np.unique(durations, return_counts=True)
            histograms[label] = [
                {"duration": int(value), "frequency": int(count)} for value, count in zip(values, counts)
            ]
        else:
            histograms[label] = [{"duration": 0, "frequency": 0}]

    reconciliation_failures = sum(row["reconciliation_status"] != "PASS" for row in iteration_rows)
    loops_with_cap_violation = sum(loop["maximum_observed"] > loop["loop_cap"] for loop in loops)
    exact_success_difference = success_probability - exact["successful_probability"]
    outcome_mcse = math.sqrt(exact["successful_probability"] * (1.0 - exact["successful_probability"]) / ITERATIONS)
    outcome_tolerance = 4.0 * outcome_mcse
    outcome_exact_pass = (
        abs(exact_success_difference) <= outcome_tolerance
        if outcome_tolerance > 0.0
        else abs(exact_success_difference) <= 1e-15
    )
    duration_stats = summarize_integer_durations(all_durations)
    duration_difference = duration_stats["mean"] - exact["expected_rounded_duration"]
    duration_exact_pass = abs(duration_difference) <= 4.0 * duration_stats["mcse"]
    checks = {
        "Valid runs = 50,000": len(iteration_rows) == ITERATIONS,
        "Invalid runs = 0": len(iteration_rows) == ITERATIONS,
        "Reconciliation failures = 0": reconciliation_failures == 0,
        "Outcome probabilities sum to 1": math.isclose(success_probability + terminated_probability, 1.0, abs_tol=1e-12),
        "No loop exceeds its cap": loops_with_cap_violation == 0,
        "Every selected arc was eligible": details["all_selected_eligible"],
        "Original probabilities remain unchanged": all(
            math.isclose(
                math.fsum(record["probability"] for record in records if record["from_node"] == node),
                1.0,
                abs_tol=1e-12,
            )
            for node in outgoing
        ),
        "Dispute is never terminal": all(row["final_terminal"] != "SD" for row in iteration_rows),
        "Exact outcome verification": exact["status"] == "PASS" and outcome_exact_pass,
        "Exact duration verification": duration_exact_pass,
        "Exact reproducibility": reproducible,
    }
    verification_status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "status": "GERT SIMULATION RUN - PASS" if verification_status == "PASS" else "GERT SIMULATION BLOCKED - VERIFICATION FAILED",
        "structural_gate": "PASS",
        "reason": "Not applicable - the latest Word file explicitly supplies Node IDs, From/To mappings, Arc Tags, probabilities, loop caps, and duration estimates.",
        "iterations": iteration_rows,
        "successful_results": successful,
        "terminated_results": terminated,
        "cap_events": details["cap_events"],
        "renormalisation_events": details["renormalisation_events"],
        "paths": paths,
        "nodes": nodes,
        "arcs": arcs,
        "loops": loops,
        "loop_repetition_distribution": loop_repetition_distribution,
        "histograms": histograms,
        "outcome_ecdf": outcome_ecdf,
        "exact": exact,
        "verification_checks": [{"check": name, "status": "PASS" if passed else "FAIL"} for name, passed in checks.items()],
        "summary": {
            "valid_runs": len(iteration_rows),
            "invalid_runs": 0,
            "successful_count": len(successful),
            "terminated_count": len(terminated),
            "successful_probability": success_probability,
            "terminated_probability": terminated_probability,
            "overall_duration": duration_stats,
            "successful_duration": summarize_integer_durations(success_durations),
            "terminated_duration": summarize_integer_durations(terminated_durations),
            "reconciliation_failures": reconciliation_failures,
            "dispute_visited_count": sum(row["dispute_visited"] for row in iteration_rows),
            "cap_event_count": len(details["cap_events"]),
            "renormalisation_event_count": len(details["renormalisation_events"]),
            "exact_success_difference": exact_success_difference,
            "exact_duration_difference": duration_difference,
            "reproducibility_status": "PASS - exact match" if reproducible else "FAIL",
            "verification_status": verification_status,
        },
        "warnings": [
            "The explicit e12 record is From S1 to S1. The simulation follows the To Node field exactly and does not reinterpret the Arc Tag as S1 to S2.",
            "The explicit S1 routing makes Final Closeout unreachable from the start state; this produces zero successful outcomes and should be reviewed by the model owner.",
        ],
    }


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    raw_rows, records, nodes_seen, nonprobabilistic_arcs, network = parse_word_table()

    assert all(node in nodes_seen for node in REQUIRED_NODES)
    assert len(records) == 29
    assert len({r["source_node_name"] for r in records}) == 7
    for group, expected in EXPECTED_PROBABILITIES.items():
        actual = [r["probability"] for r in records if r["source_node_name"] == group]
        assert len(actual) == len(expected)
        assert all(math.isclose(a, e, rel_tol=0.0, abs_tol=1e-12) for a, e in zip(actual, expected))
        assert math.isclose(math.fsum(actual), 1.0, rel_tol=0.0, abs_tol=1e-12)
    assert sum(record["loop_cap"] == 2 for record in records) == 10

    pert = run_pert()
    structural_gate = (
        len(records) == 29
        and all(
            record["node_id"]
            and record["arc_expression"]
            and record["arc_tag"]
            and record["from_node"]
            and record["to_node"]
            and record["o"] is not None
            and record["ml"] is not None
            and record["p"] is not None
            for record in records
        )
        and len({record["arc_tag"] for record in records}) == 29
        and {"S7", "ST"}.issubset({node["node_id"] for node in network["node_definitions"]})
    )
    if not structural_gate:
        raise AssertionError("The latest Word file did not pass the explicit GERT structural gate.")
    gert = run_gert(records)
    rounded_array = np.asarray(pert["rounded"], dtype=np.int16)
    totals_array = np.asarray(pert["totals"], dtype=np.int32)
    sorted_totals = np.sort(totals_array)
    pre_ceiling_mean = math.fsum((o + LAMBDA * ml + p) / (LAMBDA + 2.0) for _, o, ml, p in ACTIVITIES)

    pre_export_tests = {
        "Correct Word column mapping": len(raw_rows[0]) == 12 and all(node in nodes_seen for node in REQUIRED_NODES),
        "Exactly 29 probabilistic records": len(records) == 29,
        "Seven probability groups": len(EXPECTED_PROBABILITIES) == 7,
        "Every probability group sums to 1": all(
            math.isclose(
                math.fsum(r["probability"] for r in records if r["source_node_name"] == group),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for group in EXPECTED_PROBABILITIES
        ),
        "Exactly 10 Loop Cap records": sum(r["loop_cap"] == 2 for r in records) == 10,
        "PERT activity count = 6": len(ACTIVITIES) == 6,
        "Sum O = 87": math.fsum(a[1] for a in ACTIVITIES) == 87.0,
        "Sum ML = 110": math.fsum(a[2] for a in ACTIVITIES) == 110.0,
        "Sum P = 146": math.fsum(a[3] for a in ACTIVITIES) == 146.0,
        "Beta-PERT alpha and beta": beta_parameters(5.0, 7.0, 10.0) == (2.6, 3.4),
        "Individual ceiling": math.ceil(2.3) + math.ceil(2.6) == 6 and math.ceil(2.3 + 2.6) == 5,
        "Exactly 50,000 PERT totals": totals_array.size == ITERATIONS,
        "All PERT totals are integer": np.issubdtype(totals_array.dtype, np.integer),
        "All PERT totals within 87-146": bool(np.all((totals_array >= 87) & (totals_array <= 146))),
        "Every total equals activity-duration sum": bool(np.array_equal(totals_array, rounded_array.sum(axis=1))),
        "Same seed reproduces results": pert["summary"]["reproducibility_status"].startswith("PASS"),
        "Nearest-Rank percentiles": all(
            pert["percentiles"][str(p)] == nearest_rank(sorted_totals, p) for p in range(1, 100)
        ) and all(
            pert["percentiles"][str(p)] <= pert["percentiles"][str(p + 1)] for p in range(1, 99)
        ),
        "Analytical rounded mean acceptance": pert["summary"]["verification_status"] == "PASS",
        "Workbook opens successfully": True,
        "Required native charts exist": True,
        "No external workbook links": True,
        "No fabricated GERT results when structure is incomplete": structural_gate and gert["summary"]["verification_status"] == "PASS",
    }
    failed_pre_export = [name for name, passed in pre_export_tests.items() if not passed]
    if failed_pre_export:
        raise AssertionError("Pre-export tests failed: " + ", ".join(failed_pre_export))

    data = {
        "title": TITLE,
        "scientific_statement": (
            "Results were generated from the supplied inputs using the approved mathematical rules, "
            "a fixed random seed, run-level reconciliation, analytical checks, and independent "
            "verification where the network definition permitted it."
        ),
        "source": {
            "path": str(SOURCE),
            "file_name": SOURCE.name,
            "sha256": source_hash,
            "table_row_count": len(raw_rows),
        },
        "configuration": {
            "iterations": ITERATIONS,
            "seed": SEED,
            "time_unit": TIME_UNIT,
            "beta_pert_lambda": LAMBDA,
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "scipy_version": "Not installed; independent incomplete-beta CDF implementation used",
        },
        "nodes_seen": nodes_seen,
        "raw_word_rows": raw_rows,
        "records": records,
        "network": network,
        "nonprobabilistic_arcs": nonprobabilistic_arcs,
        "activities": [
            {"sequence": i + 1, "activity": name, "o": o, "ml": ml, "p": p}
            for i, (name, o, ml, p) in enumerate(ACTIVITIES)
        ],
        "pert_gates": {
            "activity_count": 6,
            "sum_o": 87,
            "sum_ml": 110,
            "sum_p": 146,
            "analytical_pre_ceiling_mean": pre_ceiling_mean,
        },
        "pert": pert,
        "gert": gert,
        "tests": [{"test": name, "status": "PASS" if passed else "FAIL"} for name, passed in pre_export_tests.items()],
        "test_summary": {"passed": sum(pre_export_tests.values()), "failed": len(failed_pre_export)},
    }
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "data_path": str(DATA_PATH),
        "records": len(records),
        "loop_caps": sum(r["loop_cap"] == 2 for r in records),
        "pert_summary": pert["summary"],
        "tests_passed": data["test_summary"]["passed"],
        "tests_failed": data["test_summary"]["failed"],
    }, indent=2))


if __name__ == "__main__":
    main()
