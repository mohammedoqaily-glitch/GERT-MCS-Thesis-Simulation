#!/usr/bin/env python3
"""Reproducible PERT-MCS and GERT-MCS simulation for the MSc thesis appendix.

Purpose
-------
This self-contained Python 3.12 script reproduces the verified Variation Order
lifecycle simulation used for the thesis results.  The model definition below
is a direct transcription of the two authoritative Word inputs whose SHA-256
digests are recorded in ``AUTHORITATIVE_INPUT_HASHES``.

Dependencies: NumPy only (plus the Python standard library).
Baseline configuration: 50,000 PERT replications and 50,000 GERT replications,
root seed 42, NumPy Generator/PCG64 child streams, Beta-PERT lambda = 4, and
ceiling to whole working days immediately after each activity/arc draw.

PERT-MCS samples the six activities of the fixed reference route once per
replication and therefore represents temporal uncertainty only.  GERT-MCS
samples one eligible outgoing arc at each state under XOR logic and therefore
represents both temporal and structural uncertainty.  Each capped return arc
has its own traversal counter; after its cap is reached it is excluded and the
remaining outgoing probabilities are proportionally renormalised.

Reproducibility note: a SeedSequence rooted at ``--seed`` spawns three PCG64
streams in a fixed order: PERT duration, GERT routing, and GERT duration.  The
same Python/NumPy versions, inputs, configuration, and seed reproduce the same
arrays and exported files.  Output files contain no timestamps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np


SCRIPT_VERSION = "1.0.0"
DEFAULT_REPLICATIONS = 50_000
DEFAULT_SEED = 42
BETA_PERT_LAMBDA = 4.0
MAX_STEPS = 100_000
PROBABILITY_TOLERANCE = 1e-12

START_STATE = "S0"
ROUTING_START_STATE = "S1"
SUCCESS_STATE = "S7"
TERMINATION_STATE = "ST"
DISPUTE_STATE = "SD"
TERMINAL_OUTCOMES = {SUCCESS_STATE: "Successful Closeout", TERMINATION_STATE: "Withdrawn/Rejected"}
REQUIRED_STATE_IDS = {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "SD", "S7", "ST"}
REQUIRED_PERT_TAGS = {"e12", "e23", "e34", "e45", "e56", "e67"}
REQUIRED_GERT_TAGS = {
    "e12", "e1T", "e23", "e24", "e22", "e21", "e2T", "e34", "e33", "e32",
    "e3T", "e3D", "e45", "e46", "e43", "e42", "e4D", "e56", "e57", "e55",
    "e54", "e52", "e5D", "e67", "e66", "e6D", "eD3", "eD7", "eDT",
}

AUTHORITATIVE_INPUT_HASHES = {
    "PERT Input.docx": "7984b5b2e29928345772f0110ea1fa1c9ceb4121dc2e3aed4737112a98bc1f58",
    "GERT nput.docx": "dc34b00fcd3988146da0760ac18499eeca9d8596601c09445ca5d956c4ae6387",
}


@dataclass(frozen=True)
class Activity:
    """One fixed-route PERT activity with Beta-PERT duration parameters."""

    tag: str
    stage: str
    predecessor: str
    successor: str
    optimistic: float
    most_likely: float
    pessimistic: float


@dataclass(frozen=True)
class Arc:
    """One stochastic GERT transition in an XOR routing group."""

    tag: str
    from_state: str
    to_state: str
    probability: float
    loop_cap: int | None
    optimistic: float
    most_likely: float
    pessimistic: float


@dataclass
class PertResult:
    """PERT-MCS arrays retained for audit and export."""

    raw_durations: np.ndarray
    rounded_durations: np.ndarray
    totals: np.ndarray


@dataclass
class GertResult:
    """GERT-MCS arrays and route counts retained for audit and export."""

    totals: np.ndarray
    outcome_codes: np.ndarray
    final_states: np.ndarray
    transition_counts: np.ndarray
    loop_counts: np.ndarray
    dispute_visited: np.ndarray
    renormalisation_counts: np.ndarray
    routes: list[str]
    route_counts: Counter[str]
    computational_errors: list[str]


STATES: Mapping[str, str] = {
    "S0": "Start / Trigger",
    "S1": "Identification",
    "S2": "Evaluation / Proposal",
    "S3": "Determination / Instruction",
    "S4": "Implementation",
    "S5": "Inspection / Verification",
    "S6": "Valuation / Certification",
    "SD": "Dispute / DAAB",
    "S7": "Successful Closeout",
    "ST": "Withdrawn / Rejected",
}

# Fixed PERT reference route transcribed from PERT Input.docx.
PERT_ACTIVITIES: tuple[Activity, ...] = (
    Activity("e12", "Identification", "Start VO Trigger", "Evaluation / Proposal", 5, 7, 10),
    Activity("e23", "Evaluation / Proposal", "Identification", "Approval / Instruction", 5, 7, 10),
    Activity("e34", "Approval / Instruction", "Evaluation / Proposal", "Implementation", 10, 14, 20),
    Activity("e45", "Implementation (Control Point)", "Approval / Instruction", "Inspection / Verification", 50, 60, 80),
    Activity("e56", "Inspection / Verification", "Implementation", "Valuation & Adjustment", 10, 12, 14),
    Activity("e67", "Valuation & Adjustment (Consolidation)", "Inspection / Verification", "Final Closeout", 7, 10, 12),
)

# GERT arcs retain the exact ordering in GERT nput.docx.  That ordering matters
# because inverse-CDF routing maps a uniform draw onto this cumulative sequence.
GERT_ARCS: tuple[Arc, ...] = (
    Arc("e12", "S1", "S2", 0.60, None, 5, 7, 10),
    Arc("e1T", "S1", "ST", 0.40, None, 2, 3, 4),
    Arc("e23", "S2", "S3", 0.01, None, 5, 7, 10),
    Arc("e24", "S2", "S4", 0.90, None, 12, 15, 17),
    Arc("e22", "S2", "S2", 0.04, 2, 7, 9, 12),
    Arc("e21", "S2", "S1", 0.04, 2, 3, 5, 7),
    Arc("e2T", "S2", "ST", 0.01, None, 7, 10, 12),
    Arc("e34", "S3", "S4", 0.90, None, 10, 14, 20),
    Arc("e33", "S3", "S3", 0.04, 2, 4, 7, 10),
    Arc("e32", "S3", "S2", 0.04, 2, 10, 14, 20),
    Arc("e3T", "S3", "ST", 0.01, None, 10, 14, 20),
    Arc("e3D", "S3", "SD", 0.01, None, 10, 14, 20),
    Arc("e45", "S4", "S5", 0.90, None, 50, 60, 80),
    Arc("e46", "S4", "S6", 0.05, None, 40, 45, 50),
    Arc("e43", "S4", "S3", 0.02, 2, 5, 7, 10),
    Arc("e42", "S4", "S2", 0.01, 2, 7, 10, 12),
    Arc("e4D", "S4", "SD", 0.02, None, 7, 10, 12),
    Arc("e56", "S5", "S6", 0.90, None, 10, 12, 14),
    Arc("e57", "S5", "S7", 0.05, None, 7, 10, 12),
    Arc("e55", "S5", "S5", 0.01, 2, 2, 5, 7),
    Arc("e54", "S5", "S4", 0.02, 2, 7, 10, 12),
    Arc("e52", "S5", "S2", 0.01, 2, 7, 10, 12),
    Arc("e5D", "S5", "SD", 0.01, None, 7, 10, 12),
    Arc("e67", "S6", "S7", 0.95, None, 7, 10, 12),
    Arc("e66", "S6", "S6", 0.04, 2, 5, 7, 10),
    Arc("e6D", "S6", "SD", 0.01, None, 7, 10, 12),
    Arc("eD3", "SD", "S3", 0.90, None, 5, 7, 10),
    Arc("eD7", "SD", "S7", 0.05, None, 5, 7, 10),
    Arc("eDT", "SD", "ST", 0.05, None, 5, 7, 10),
)

LOOP_TAGS: tuple[str, ...] = tuple(arc.tag for arc in GERT_ARCS if arc.loop_cap is not None)
LOOP_INDEX = {tag: index for index, tag in enumerate(LOOP_TAGS)}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replications", type=int, default=DEFAULT_REPLICATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=Path("appendix_outputs"))
    parser.add_argument(
        "--run-sensitivity",
        action="store_true",
        help="Run the thesis one-way/robustness scenario design after the baseline.",
    )
    parser.add_argument(
        "--sensitivity-replications",
        type=int,
        default=DEFAULT_REPLICATIONS,
        help="Replications per sensitivity scenario (50,000 in the thesis analysis).",
    )
    return parser.parse_args()


def validate_duration_triplet(identifier: str, optimistic: float, most_likely: float, pessimistic: float) -> None:
    values = np.asarray([optimistic, most_likely, pessimistic], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{identifier}: O/M/P values must be finite.")
    if optimistic < 0:
        raise ValueError(f"{identifier}: optimistic duration cannot be negative.")
    if not optimistic <= most_likely <= pessimistic:
        raise ValueError(
            f"{identifier}: require optimistic <= most-likely <= pessimistic; "
            f"received {optimistic}, {most_likely}, {pessimistic}."
        )


def beta_pert_shapes(
    optimistic: float,
    most_likely: float,
    pessimistic: float,
    shape: float = BETA_PERT_LAMBDA,
) -> tuple[float, float] | None:
    """Return conventional Beta-PERT alpha/beta, or None for a constant."""

    validate_duration_triplet("Beta-PERT input", optimistic, most_likely, pessimistic)
    if optimistic == pessimistic:
        return None
    alpha = 1.0 + shape * (most_likely - optimistic) / (pessimistic - optimistic)
    beta = 1.0 + shape * (pessimistic - most_likely) / (pessimistic - optimistic)
    if not (math.isfinite(alpha) and math.isfinite(beta) and alpha > 0 and beta > 0):
        raise ValueError("Beta-PERT shape parameters must be finite and positive.")
    return alpha, beta


def sample_duration(
    rng: np.random.Generator,
    optimistic: float,
    most_likely: float,
    pessimistic: float,
    distribution: str = "beta_pert",
) -> tuple[float, int]:
    """Sample one duration and apply the authoritative per-draw ceiling."""

    validate_duration_triplet("Duration input", optimistic, most_likely, pessimistic)
    if optimistic == pessimistic:
        raw = float(optimistic)
    elif distribution == "beta_pert":
        shapes = beta_pert_shapes(optimistic, most_likely, pessimistic)
        if shapes is None:  # Defensive; handled by the equality branch above.
            raw = float(optimistic)
        else:
            alpha, beta = shapes
            raw = optimistic + (pessimistic - optimistic) * float(rng.beta(alpha, beta))
    elif distribution == "triangular":
        raw = float(rng.triangular(optimistic, most_likely, pessimistic))
    else:
        raise ValueError(f"Unsupported duration distribution: {distribution}")
    return raw, int(math.ceil(raw))


def outgoing_groups(arcs: Sequence[Arc]) -> dict[str, list[Arc]]:
    groups: dict[str, list[Arc]] = defaultdict(list)
    for arc in arcs:
        groups[arc.from_state].append(arc)
    return dict(groups)


def reachable_states(arcs: Sequence[Arc], start: str) -> set[str]:
    graph: dict[str, list[str]] = defaultdict(list)
    for arc in arcs:
        if arc.probability > 0:
            graph[arc.from_state].append(arc.to_state)
    visited = {start}
    queue = deque([start])
    while queue:
        state = queue.popleft()
        for neighbour in graph.get(state, []):
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)
    return visited


def can_reach_terminal(arcs: Sequence[Arc], terminal: str) -> set[str]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for arc in arcs:
        if arc.probability > 0:
            reverse[arc.to_state].append(arc.from_state)
    visited = {terminal}
    queue = deque([terminal])
    while queue:
        state = queue.popleft()
        for predecessor in reverse.get(state, []):
            if predecessor not in visited:
                visited.add(predecessor)
                queue.append(predecessor)
    return visited


def validate_model(activities: Sequence[Activity], arcs: Sequence[Arc]) -> list[dict[str, str]]:
    """Validate durations, XOR groups, terminals, caps, identifiers, and reachability."""

    checks: list[dict[str, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append({"test": name, "status": "PASS" if condition else "FAIL", "detail": detail})
        if not condition:
            raise ValueError(f"{name}: {detail}" if detail else name)

    check("Required state set", set(STATES) == REQUIRED_STATE_IDS, f"observed {sorted(STATES)}")
    check("PERT activity count", len(activities) == 6, f"observed {len(activities)}")
    check("GERT stochastic arc count", len(arcs) == 29, f"observed {len(arcs)}")
    check("Unique PERT tags", len({item.tag for item in activities}) == len(activities))
    check("Unique GERT arc tags", len({arc.tag for arc in arcs}) == len(arcs))
    check("Required PERT activity set", {item.tag for item in activities} == REQUIRED_PERT_TAGS)
    check("Required GERT arc set", {arc.tag for arc in arcs} == REQUIRED_GERT_TAGS)
    check("Valid state identifiers", all(arc.from_state in STATES and arc.to_state in STATES for arc in arcs))

    for item in activities:
        validate_duration_triplet(item.tag, item.optimistic, item.most_likely, item.pessimistic)
    for arc in arcs:
        validate_duration_triplet(arc.tag, arc.optimistic, arc.most_likely, arc.pessimistic)
    check("All duration triples valid", True)

    probabilities = np.asarray([arc.probability for arc in arcs], dtype=float)
    check("Probabilities finite", bool(np.isfinite(probabilities).all()))
    check("Probabilities non-negative", bool(np.all(probabilities >= 0)))
    check("At least one positive arc per routing group", True)

    groups = outgoing_groups(arcs)
    expected_groups = {"S1", "S2", "S3", "S4", "S5", "S6", "SD"}
    check("Expected XOR routing groups", set(groups) == expected_groups, f"observed {sorted(groups)}")
    for state, group in groups.items():
        total = math.fsum(arc.probability for arc in group)
        check(f"XOR probability sum at {state}", math.isclose(total, 1.0, abs_tol=PROBABILITY_TOLERANCE), f"sum={total:.17g}")

    check("Successful state absorbing", SUCCESS_STATE not in groups)
    check("Termination state absorbing", TERMINATION_STATE not in groups)
    check("Dispute state non-absorbing", DISPUTE_STATE in groups and len(groups[DISPUTE_STATE]) == 3)
    check("Structural start reaches S1", START_STATE in STATES and ROUTING_START_STATE in STATES)

    for arc in arcs:
        if arc.loop_cap is not None:
            check(
                f"Loop cap valid for {arc.tag}",
                isinstance(arc.loop_cap, int) and arc.loop_cap >= 0,
                f"cap={arc.loop_cap}",
            )
    check("Ten independently capped arcs", LOOP_TAGS == ("e22", "e21", "e33", "e32", "e43", "e42", "e55", "e54", "e52", "e66"))

    reached = reachable_states(arcs, ROUTING_START_STATE)
    check("Successful closeout reachable", SUCCESS_STATE in reached)
    check("Withdrawal/rejection reachable", TERMINATION_STATE in reached)
    check("Dispute reachable", DISPUTE_STATE in reached)
    success_predecessors = can_reach_terminal(arcs, SUCCESS_STATE)
    check("Every transient state can reach success", expected_groups <= success_predecessors)
    arc_by_tag = {arc.tag: arc for arc in arcs}
    check(
        "PERT and GERT nominal durations agree",
        all(
            (
                item.optimistic,
                item.most_likely,
                item.pessimistic,
            )
            == (
                arc_by_tag[item.tag].optimistic,
                arc_by_tag[item.tag].most_likely,
                arc_by_tag[item.tag].pessimistic,
            )
            for item in activities
        ),
    )
    return checks


def spawn_generators(seed: int) -> tuple[np.random.Generator, np.random.Generator, np.random.Generator]:
    """Create the three authoritative independent PCG64 child streams."""

    root = np.random.SeedSequence(seed)
    children = root.spawn(3)
    return tuple(np.random.Generator(np.random.PCG64(child)) for child in children)  # type: ignore[return-value]


def run_pert(
    activities: Sequence[Activity],
    replications: int,
    seed: int,
    distribution: str = "beta_pert",
) -> PertResult:
    """Run fixed-route PERT-MCS with one sample per activity and replication."""

    if replications <= 0:
        raise ValueError("Replications must be positive.")
    pert_rng, _, _ = spawn_generators(seed)
    raw = np.empty((replications, len(activities)), dtype=np.float64)
    rounded = np.empty((replications, len(activities)), dtype=np.int16)
    for column, item in enumerate(activities):
        if item.optimistic == item.pessimistic:
            raw[:, column] = item.optimistic
        elif distribution == "beta_pert":
            shapes = beta_pert_shapes(item.optimistic, item.most_likely, item.pessimistic)
            if shapes is None:
                raw[:, column] = item.optimistic
            else:
                alpha, beta = shapes
                raw[:, column] = item.optimistic + (item.pessimistic - item.optimistic) * pert_rng.beta(
                    alpha, beta, replications
                )
        elif distribution == "triangular":
            raw[:, column] = pert_rng.triangular(
                item.optimistic, item.most_likely, item.pessimistic, replications
            )
        else:
            raise ValueError(f"Unsupported duration distribution: {distribution}")
        rounded[:, column] = np.ceil(raw[:, column]).astype(np.int16)
    totals = rounded.sum(axis=1, dtype=np.int32)
    return PertResult(raw, rounded, totals)


def choose_arc(rng: np.random.Generator, eligible: Sequence[Arc]) -> Arc:
    denominator = math.fsum(arc.probability for arc in eligible)
    if not math.isfinite(denominator) or denominator <= 0:
        raise RuntimeError("No positive finite probability remains in an XOR group.")
    effective = np.asarray([arc.probability / denominator for arc in eligible], dtype=np.float64)
    if not math.isclose(float(effective.sum()), 1.0, abs_tol=PROBABILITY_TOLERANCE):
        raise RuntimeError("Effective XOR probabilities do not sum to one.")
    draw = float(rng.random())
    index = min(int(np.searchsorted(np.cumsum(effective), draw, side="right")), len(eligible) - 1)
    return eligible[index]


def run_gert(
    arcs: Sequence[Arc],
    replications: int,
    seed: int,
    distribution: str = "beta_pert",
    max_steps: int = MAX_STEPS,
) -> GertResult:
    """Run the authoritative capped-loop XOR GERT-MCS simulation."""

    if replications <= 0:
        raise ValueError("Replications must be positive.")
    if max_steps < 2:
        raise ValueError("Maximum steps must allow the structural start arc and at least one stochastic arc.")

    _, routing_rng, duration_rng = spawn_generators(seed)
    groups = outgoing_groups(arcs)
    totals = np.zeros(replications, dtype=np.int32)
    outcome_codes = np.full(replications, -1, dtype=np.int8)  # 1 success, 0 withdrawn/rejected, -1 error
    final_states = np.full(replications, "", dtype="U2")
    transition_counts = np.zeros(replications, dtype=np.int16)
    loop_counts = np.zeros((replications, len(LOOP_TAGS)), dtype=np.int8)
    dispute_visited = np.zeros(replications, dtype=np.bool_)
    renormalisation_counts = np.zeros(replications, dtype=np.int16)
    routes: list[str] = []
    route_counts: Counter[str] = Counter()
    computational_errors: list[str] = []

    for iteration in range(replications):
        state = ROUTING_START_STATE
        total_duration = 0
        arc_path = ["e01"]  # S0 -> S1 is a zero-duration structural arc.
        counters = {tag: 0 for tag in LOOP_TAGS}
        visited_dispute = False
        renormalisations = 0

        while state not in TERMINAL_OUTCOMES:
            if len(arc_path) >= max_steps:
                computational_errors.append(f"iteration {iteration + 1}: maximum-step safeguard triggered")
                break
            group = groups.get(state)
            if not group:
                computational_errors.append(f"iteration {iteration + 1}: no outgoing group at {state}")
                break

            excluded = [
                arc
                for arc in group
                if arc.loop_cap is not None and counters[arc.tag] >= arc.loop_cap
            ]
            eligible = [arc for arc in group if arc not in excluded and arc.probability > 0]
            if not eligible:
                computational_errors.append(f"iteration {iteration + 1}: no eligible arc at {state}")
                break
            if excluded:
                renormalisations += 1

            selected = choose_arc(routing_rng, eligible)
            _, rounded_duration = sample_duration(
                duration_rng,
                selected.optimistic,
                selected.most_likely,
                selected.pessimistic,
                distribution,
            )
            total_duration += rounded_duration
            arc_path.append(selected.tag)

            if selected.loop_cap is not None:
                counters[selected.tag] += 1
                if counters[selected.tag] > selected.loop_cap:
                    computational_errors.append(
                        f"iteration {iteration + 1}: {selected.tag} exceeded cap {selected.loop_cap}"
                    )
                    break

            state = selected.to_state
            if state == DISPUTE_STATE:
                visited_dispute = True

        totals[iteration] = total_duration
        final_states[iteration] = state
        transition_counts[iteration] = len(arc_path)
        loop_counts[iteration] = [counters[tag] for tag in LOOP_TAGS]
        dispute_visited[iteration] = visited_dispute
        renormalisation_counts[iteration] = renormalisations
        route = ">".join(arc_path)
        routes.append(route)
        route_counts[route] += 1
        if state == SUCCESS_STATE:
            outcome_codes[iteration] = 1
        elif state == TERMINATION_STATE:
            outcome_codes[iteration] = 0

    return GertResult(
        totals=totals,
        outcome_codes=outcome_codes,
        final_states=final_states,
        transition_counts=transition_counts,
        loop_counts=loop_counts,
        dispute_visited=dispute_visited,
        renormalisation_counts=renormalisation_counts,
        routes=routes,
        route_counts=route_counts,
        computational_errors=computational_errors,
    )


def nearest_rank(values: Sequence[int] | np.ndarray, percentile: int) -> int:
    """Return the nearest-rank percentile at rank ceil(percentile * N / 100)."""

    if not 1 <= percentile <= 99:
        raise ValueError("Percentile must be between 1 and 99.")
    array = np.sort(np.asarray(values))
    if array.size == 0:
        raise ValueError("Cannot calculate a percentile of an empty sample.")
    rank = math.ceil(percentile * array.size / 100)
    return int(array[rank - 1])


def duration_summary(values: Sequence[int] | np.ndarray) -> dict[str, float | int]:
    """Summarise durations using sample variance/SD and nearest-rank quantiles."""

    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        raise ValueError("Cannot summarise an empty duration population.")
    if not np.isfinite(array).all() or np.any(array < 0):
        raise ValueError("Durations must be finite and non-negative.")
    return {
        "n": int(array.size),
        "mean": float(array.mean()),
        "variance": float(array.var(ddof=1)) if array.size > 1 else 0.0,
        "standard_deviation": float(array.std(ddof=1)) if array.size > 1 else 0.0,
        "minimum": int(array.min()),
        "maximum": int(array.max()),
        "p50": nearest_rank(array, 50),
        "p80": nearest_rank(array, 80),
        "p90": nearest_rank(array, 90),
        "p95": nearest_rank(array, 95),
        "p99": nearest_rank(array, 99),
    }


def wilson_interval(count: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    proportion = count / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)) / denominator
    return centre - margin, centre + margin


def path_diagnostics(result: GertResult) -> list[dict[str, float | int | str]]:
    first_outcome_by_route: dict[str, str] = {}
    for route, final_state in zip(result.routes, result.final_states):
        first_outcome_by_route.setdefault(route, TERMINAL_OUTCOMES[final_state])
    rows = []
    for rank, (route, count) in enumerate(
        sorted(result.route_counts.items(), key=lambda item: (-item[1], item[0])), start=1
    ):
        rows.append(
            {
                "rank": rank,
                "arc_sequence": route,
                "count": count,
                "probability_all_replications": count / len(result.totals),
                "terminal_outcome": first_outcome_by_route[route],
            }
        )
    return rows


def replay_route(route: str, arcs: Sequence[Arc]) -> str:
    """Replay an arc-tag sequence and return its terminal state, rejecting illegal paths."""

    tags = route.split(">")
    if not tags or tags[0] != "e01":
        raise ValueError(f"Route does not begin with structural arc e01: {route}")
    arc_by_tag = {arc.tag: arc for arc in arcs}
    state = ROUTING_START_STATE
    for tag in tags[1:]:
        arc = arc_by_tag.get(tag)
        if arc is None:
            raise ValueError(f"Route contains unknown arc {tag}: {route}")
        if arc.from_state != state:
            raise ValueError(f"Arc {tag} is not outgoing from {state}: {route}")
        state = arc.to_state
        if state in TERMINAL_OUTCOMES and tag != tags[-1]:
            raise ValueError(f"Route continues after terminal state {state}: {route}")
    return state


def loop_diagnostics(result: GertResult) -> tuple[list[dict[str, float | int | str]], list[dict[str, float | int]]]:
    rows = []
    for index, tag in enumerate(LOOP_TAGS):
        counts = result.loop_counts[:, index]
        rows.append(
            {
                "loop_arc": tag,
                "activated_count": int(np.sum(counts > 0)),
                "activation_probability_all_replications": float(np.mean(counts > 0)),
                "cap_reached_count": int(np.sum(counts == 2)),
                "cap_reached_probability_all_replications": float(np.mean(counts == 2)),
                "mean_traversals_all_replications": float(counts.mean()),
                "maximum_traversals": int(counts.max()),
            }
        )

    successful = result.outcome_codes == 1
    total_depth = result.loop_counts.sum(axis=1)
    depth_rows = []
    for depth in sorted(np.unique(total_depth[successful])):
        mask = successful & (total_depth == depth)
        depth_rows.append(
            {
                "total_loop_traversals": int(depth),
                "successful_count": int(mask.sum()),
                "share_of_successful": float(mask.sum() / successful.sum()),
                "mean_successful_duration": float(result.totals[mask].mean()),
            }
        )
    return rows, depth_rows


def summarise_results(pert: PertResult, gert: GertResult, seed: int) -> dict[str, object]:
    if gert.computational_errors:
        raise RuntimeError("GERT simulation contains computational errors.")
    success = gert.outcome_codes == 1
    terminated = gert.outcome_codes == 0
    valid = success | terminated
    if not valid.all():
        raise RuntimeError("Every GERT replication must reach a legitimate terminal state.")
    success_count = int(success.sum())
    terminated_count = int(terminated.sum())
    success_ci = wilson_interval(success_count, len(gert.totals))
    terminated_ci = wilson_interval(terminated_count, len(gert.totals))
    loop_rows, depth_rows = loop_diagnostics(gert)

    successful_p90 = nearest_rank(gert.totals[success], 90)
    successful_p95 = nearest_rank(gert.totals[success], 95)
    successful_p99 = nearest_rank(gert.totals[success], 99)
    tails = {}
    for label, threshold in (("p90", successful_p90), ("p95", successful_p95), ("p99", successful_p99)):
        tail = success & (gert.totals >= threshold)
        tails[label] = {
            "threshold_working_days": threshold,
            "count": int(tail.sum()),
            "feedback_or_self_loop_share": float(np.mean(gert.loop_counts[tail].sum(axis=1) > 0)),
            "dispute_share": float(gert.dispute_visited[tail].mean()),
        }

    return {
        "configuration": {
            "script_version": SCRIPT_VERSION,
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "replications": len(pert.totals),
            "root_seed": seed,
            "rng": "numpy.random.Generator(numpy.random.PCG64(child_seed_sequence))",
            "stream_spawn_keys": {"PERT duration": [0], "GERT routing": [1], "GERT duration": [2]},
            "beta_pert_lambda": BETA_PERT_LAMBDA,
            "rounding": "ceil immediately after each activity or realised arc draw",
            "percentiles": "nearest-rank: rank = ceil(p * N / 100)",
            "variance_and_sd": "sample definitions (ddof=1)",
            "rate_denominator": "all valid GERT replications unless explicitly conditional",
            "authoritative_input_hashes": AUTHORITATIVE_INPUT_HASHES,
        },
        "pert_mcs": duration_summary(pert.totals),
        "gert_mcs": {
            "combined_outcomes": duration_summary(gert.totals),
            "successful_closeout": duration_summary(gert.totals[success]),
            "withdrawn_rejected": duration_summary(gert.totals[terminated]),
            "successful_count": success_count,
            "withdrawn_rejected_count": terminated_count,
            "successful_probability": success_count / len(gert.totals),
            "successful_probability_wilson_95": list(success_ci),
            "withdrawn_rejected_probability": terminated_count / len(gert.totals),
            "withdrawn_rejected_probability_wilson_95": list(terminated_ci),
            "dispute_diversion_count": int(gert.dispute_visited.sum()),
            "dispute_diversion_probability": float(gert.dispute_visited.mean()),
            "any_loop_count": int(np.sum(gert.loop_counts.sum(axis=1) > 0)),
            "any_loop_probability": float(np.mean(gert.loop_counts.sum(axis=1) > 0)),
            "at_least_two_loops_given_success": float(
                np.mean(gert.loop_counts[success].sum(axis=1) >= 2)
            ),
            "mean_transition_count": float(gert.transition_counts.mean()),
            "renormalisation_run_probability": float(np.mean(gert.renormalisation_counts > 0)),
            "exact_route_count": len(gert.route_counts),
            "loop_depth_successful": depth_rows,
            "upper_tail_diagnostics": tails,
        },
        "loop_arcs": loop_rows,
    }


def verify_execution(
    activities: Sequence[Activity],
    arcs: Sequence[Arc],
    pert: PertResult,
    gert: GertResult,
    model_checks: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Execute the appendix acceptance checks on the realised arrays."""

    checks = list(model_checks)

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append({"test": name, "status": "PASS" if condition else "FAIL", "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}" if detail else name)

    n = len(gert.totals)
    success = gert.outcome_codes == 1
    terminated = gert.outcome_codes == 0
    check("PERT replication accounting", len(pert.totals) == n, f"PERT={len(pert.totals)}, GERT={n}")
    check("GERT replication accounting", int(success.sum() + terminated.sum()) == n)
    check("No computational termination", not gert.computational_errors)
    check("Terminated runs end at ST", bool(np.all(gert.final_states[terminated] == TERMINATION_STATE)))
    check("Successful runs end at S7", bool(np.all(gert.final_states[success] == SUCCESS_STATE)))
    check("Dispute is never terminal", bool(np.all(gert.final_states != DISPUTE_STATE)))
    check("Loop caps respected", bool(np.all(gert.loop_counts <= 2)))
    check("Loop counts non-negative", bool(np.all(gert.loop_counts >= 0)))
    check("Path counts reconcile", sum(gert.route_counts.values()) == n)
    check("One route per replication", len(gert.routes) == n)
    check("Every route starts with e01", all(route == "e01" or route.startswith("e01>") for route in gert.routes))
    replayed_states = np.asarray([replay_route(route, arcs) for route in gert.routes], dtype="U2")
    check("Every realised route follows valid connected arcs", bool(np.array_equal(replayed_states, gert.final_states)))
    check("No route continues after a terminal transition", bool(np.all(np.isin(replayed_states, list(TERMINAL_OUTCOMES)))))
    check("PERT durations finite", bool(np.isfinite(pert.raw_durations).all()))
    check("PERT totals non-negative", bool(np.all(pert.totals >= 0)))
    check("GERT totals finite", bool(np.isfinite(gert.totals).all()))
    check("GERT totals non-negative", bool(np.all(gert.totals >= 0)))
    check("No empty outcome subset", bool(success.any() and terminated.any()))
    check(
        "PERT activity ceiling applied once",
        bool(np.array_equal(pert.rounded_durations, np.ceil(pert.raw_durations).astype(np.int16))),
    )
    check("PERT totals are sums of rounded activities", bool(np.array_equal(pert.totals, pert.rounded_durations.sum(axis=1))))
    check("Transition counts agree with routes", all(count == route.count(">") + 1 for count, route in zip(gert.transition_counts, gert.routes)))

    groups = outgoing_groups(arcs)
    check(
        "All original XOR groups sum to one",
        all(math.isclose(math.fsum(a.probability for a in group), 1.0, abs_tol=PROBABILITY_TOLERANCE) for group in groups.values()),
    )
    watchdog_model = (Arc("watchdog", "S1", "S1", 1.0, None, 0, 0, 0),)
    watchdog_result = run_gert(watchdog_model, 1, seed=0, max_steps=3)
    check(
        "Maximum-step safeguard terminates a non-absorbing path",
        watchdog_result.outcome_codes[0] == -1
        and any("maximum-step safeguard" in message for message in watchdog_result.computational_errors),
    )
    return checks


def result_signature(pert: PertResult, gert: GertResult) -> str:
    """Hash all result-defining arrays and ordered routes for reproducibility."""

    digest = hashlib.sha256()
    for array in (
        pert.raw_durations,
        pert.rounded_durations,
        pert.totals,
        gert.totals,
        gert.outcome_codes,
        gert.final_states,
        gert.transition_counts,
        gert.loop_counts,
        gert.dispute_visited,
        gert.renormalisation_counts,
    ):
        digest.update(np.ascontiguousarray(array).tobytes())
    for route in gert.routes:
        digest.update(route.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def perturb_probability(arcs: Sequence[Arc], target_tag: str, new_probability: float) -> tuple[Arc, ...]:
    """Change one XOR probability and preserve the other relative proportions."""

    if not 0 <= new_probability < 1:
        raise ValueError("A perturbed routing probability must be in [0, 1).")
    target = next((arc for arc in arcs if arc.tag == target_tag), None)
    if target is None:
        raise KeyError(target_tag)
    baseline = target.probability
    if math.isclose(baseline, 1.0):
        raise ValueError("A deterministic arc cannot be perturbed this way.")
    scale = (1.0 - new_probability) / (1.0 - baseline)
    modified = tuple(
        replace(
            arc,
            probability=(
                new_probability
                if arc.tag == target_tag
                else arc.probability * scale
                if arc.from_state == target.from_state
                else arc.probability
            ),
        )
        for arc in arcs
    )
    validate_model(PERT_ACTIVITIES, modified)
    return modified


def scale_arc_duration(arcs: Sequence[Arc], target_tag: str, factor: float) -> tuple[Arc, ...]:
    if factor <= 0:
        raise ValueError("Duration scaling factor must be positive.")
    if not any(arc.tag == target_tag for arc in arcs):
        raise KeyError(target_tag)
    return tuple(
        replace(
            arc,
            optimistic=arc.optimistic * factor,
            most_likely=arc.most_likely * factor,
            pessimistic=arc.pessimistic * factor,
        )
        if arc.tag == target_tag
        else arc
        for arc in arcs
    )


def set_loop_cap(arcs: Sequence[Arc], target_tag: str, cap: int) -> tuple[Arc, ...]:
    if not isinstance(cap, int) or cap < 0:
        raise ValueError("Loop cap must be a non-negative integer.")
    target = next((arc for arc in arcs if arc.tag == target_tag), None)
    if target is None or target.loop_cap is None:
        raise ValueError(f"{target_tag} is not a capped loop arc.")
    return tuple(replace(arc, loop_cap=cap) if arc.tag == target_tag else arc for arc in arcs)


def sensitivity_metrics(result: GertResult) -> dict[str, float | int]:
    success = result.outcome_codes == 1
    terminated = result.outcome_codes == 0
    return {
        "successful_count": int(success.sum()),
        "withdrawn_rejected_count": int(terminated.sum()),
        "successful_probability": float(success.mean()),
        "mean_successful_duration": float(result.totals[success].mean()),
        "successful_p90": nearest_rank(result.totals[success], 90),
        "successful_p95": nearest_rank(result.totals[success], 95),
        "dispute_probability": float(result.dispute_visited.mean()),
        "any_loop_probability": float(np.mean(result.loop_counts.sum(axis=1) > 0)),
        "computational_error_count": len(result.computational_errors),
    }


def sensitivity_scenarios(seed: int) -> list[dict[str, object]]:
    """Return the 111-scenario design used by the separate thesis analysis."""

    scenarios: list[dict[str, object]] = [
        {"scenario": "baseline", "kind": "baseline", "seed": seed, "distribution": "beta_pert"}
    ]
    for arc in GERT_ARCS:
        for level, value in (("low", max(0.0, arc.probability * 0.75)), ("high", min(0.99, arc.probability * 1.25))):
            scenarios.append(
                {
                    "scenario": f"routing_{arc.tag}_{level}",
                    "kind": "probability",
                    "target": arc.tag,
                    "value": value,
                    "seed": seed,
                    "distribution": "beta_pert",
                }
            )
    for tag in ("e45", "e24", "e56", "e67", "e12"):
        for level, factor in (("low", 0.90), ("high", 1.10)):
            scenarios.append(
                {
                    "scenario": f"duration_{tag}_{level}",
                    "kind": "duration",
                    "target": tag,
                    "value": factor,
                    "seed": seed,
                    "distribution": "beta_pert",
                }
            )
    for tag in LOOP_TAGS:
        for level, cap in (("low", 1), ("high", 3)):
            scenarios.append(
                {
                    "scenario": f"loopcap_{tag}_{level}",
                    "kind": "loop_cap",
                    "target": tag,
                    "value": cap,
                    "seed": seed,
                    "distribution": "beta_pert",
                }
            )
    scenarios.append(
        {"scenario": "distribution_triangular", "kind": "distribution", "seed": seed, "distribution": "triangular"}
    )
    for alternate_seed in (101, 202, 303, 404, 505, 606, 707, 808, 909, 1010):
        scenarios.append(
            {
                "scenario": f"seed_{alternate_seed}",
                "kind": "seed",
                "seed": alternate_seed,
                "distribution": "beta_pert",
            }
        )
    for probability in np.arange(0.0, 0.5000001, 0.05):
        scenarios.append(
            {
                "scenario": f"threshold_e1T_{int(round(probability * 100)):03d}",
                "kind": "probability",
                "target": "e1T",
                "value": float(probability),
                "seed": seed,
                "distribution": "beta_pert",
            }
        )
    if len(scenarios) != 111:
        raise AssertionError(f"Expected 111 sensitivity scenarios, constructed {len(scenarios)}.")
    return scenarios


def run_sensitivity_suite(replications: int, seed: int) -> list[dict[str, object]]:
    """Execute the documented 111-scenario one-way and robustness design."""

    rows: list[dict[str, object]] = []
    for specification in sensitivity_scenarios(seed):
        arcs = GERT_ARCS
        kind = str(specification["kind"])
        if kind == "probability":
            arcs = perturb_probability(arcs, str(specification["target"]), float(specification["value"]))
        elif kind == "duration":
            arcs = scale_arc_duration(arcs, str(specification["target"]), float(specification["value"]))
        elif kind == "loop_cap":
            arcs = set_loop_cap(arcs, str(specification["target"]), int(specification["value"]))
        result = run_gert(
            arcs,
            replications,
            int(specification["seed"]),
            distribution=str(specification["distribution"]),
        )
        row = dict(specification)
        row.update(sensitivity_metrics(result))
        rows.append(row)
    return rows


def write_csv(path: Path, rows: Iterable[Mapping[str, object]], columns: Sequence[str] | None = None) -> None:
    materialised = list(rows)
    if not materialised:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    # Scenario rows are heterogeneous: baseline rows have no target/value while
    # intervention rows do. Preserve the ordered union rather than silently
    # discarding fields absent from the first row.
    fieldnames = list(columns) if columns else list(
        dict.fromkeys(key for row in materialised for key in row)
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialised)


def write_outputs(
    output: Path,
    pert: PertResult,
    gert: GertResult,
    summary: dict[str, object],
    checks: Sequence[dict[str, str]],
    signature: str,
    sensitivity_rows: Sequence[dict[str, object]] | None,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = dict(summary)
    payload["result_signature_sha256"] = signature
    (output / "simulation_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "verification_tests.json").write_text(
        json.dumps(list(checks), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )

    write_csv(
        output / "pert_iterations.csv",
        (
            {
                "iteration": index + 1,
                **{item.tag: int(pert.rounded_durations[index, column]) for column, item in enumerate(PERT_ACTIVITIES)},
                "total_rounded_duration": int(pert.totals[index]),
            }
            for index in range(len(pert.totals))
        ),
    )
    write_csv(
        output / "gert_iterations.csv",
        (
            {
                "iteration": index + 1,
                "outcome": TERMINAL_OUTCOMES[gert.final_states[index]],
                "final_state": gert.final_states[index],
                "total_rounded_duration": int(gert.totals[index]),
                "transition_count_including_e01": int(gert.transition_counts[index]),
                "total_loop_traversals": int(gert.loop_counts[index].sum()),
                "any_loop": int(gert.loop_counts[index].sum() > 0),
                "dispute_visited": int(gert.dispute_visited[index]),
                "renormalisation_event_count": int(gert.renormalisation_counts[index]),
                "arc_sequence": gert.routes[index],
            }
            for index in range(len(gert.totals))
        ),
    )
    write_csv(output / "path_frequencies.csv", path_diagnostics(gert))
    loop_rows, depth_rows = loop_diagnostics(gert)
    write_csv(output / "loop_arc_diagnostics.csv", loop_rows)
    write_csv(output / "successful_loop_depth_diagnostics.csv", depth_rows)
    if sensitivity_rows:
        write_csv(output / "sensitivity_scenarios.csv", sensitivity_rows)


def main() -> None:
    arguments = parse_arguments()
    if arguments.replications <= 0:
        raise SystemExit("--replications must be positive")
    model_checks = validate_model(PERT_ACTIVITIES, GERT_ARCS)

    pert = run_pert(PERT_ACTIVITIES, arguments.replications, arguments.seed)
    gert = run_gert(GERT_ARCS, arguments.replications, arguments.seed)
    checks = verify_execution(PERT_ACTIVITIES, GERT_ARCS, pert, gert, model_checks)
    summary = summarise_results(pert, gert, arguments.seed)

    # A second independent execution from the same seed is the strongest direct
    # test that no hidden global random state or execution-order dependency exists.
    repeated_pert = run_pert(PERT_ACTIVITIES, arguments.replications, arguments.seed)
    repeated_gert = run_gert(GERT_ARCS, arguments.replications, arguments.seed)
    signature = result_signature(pert, gert)
    repeated_signature = result_signature(repeated_pert, repeated_gert)
    reproducibility_passed = signature == repeated_signature
    checks.append(
        {
            "test": "Fresh same-seed rerun is byte-identical",
            "status": "PASS" if reproducibility_passed else "FAIL",
            "detail": f"first={signature}; second={repeated_signature}",
        }
    )
    if not reproducibility_passed:
        raise AssertionError("Fresh same-seed rerun was not reproducible.")

    sensitivity_rows = None
    if arguments.run_sensitivity:
        sensitivity_rows = run_sensitivity_suite(arguments.sensitivity_replications, arguments.seed)
        if any(int(row["computational_error_count"]) != 0 for row in sensitivity_rows):
            raise AssertionError("A sensitivity scenario encountered a computational termination.")

    if any(row["status"] != "PASS" for row in checks):
        raise AssertionError("One or more appendix verification checks failed.")
    write_outputs(arguments.output, pert, gert, summary, checks, signature, sensitivity_rows)
    print(json.dumps({"status": "PASS", "result_signature_sha256": signature, **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
