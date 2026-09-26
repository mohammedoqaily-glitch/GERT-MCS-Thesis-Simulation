from __future__ import annotations

import math
from collections import Counter
from typing import Sequence

import numpy as np

from VO_GERT_MCS_Final_Appendix import (
    Arc,
    Activity,
    GertResult,
    PertResult,
    LOOP_TAGS,
    ROUTING_START_STATE,
    SUCCESS_STATE,
    TERMINATION_STATE,
    DISPUTE_STATE,
    TERMINAL_OUTCOMES,
    MAX_STEPS,
    choose_arc,
    outgoing_groups,
    spawn_generators,
    validate_duration_triplet,
)


def _sample_duration(
    rng: np.random.Generator,
    optimistic: float,
    most_likely: float,
    pessimistic: float,
    distribution: str,
    beta_pert_lambda: float,
) -> tuple[float, int]:
    validate_duration_triplet("Duration input", optimistic, most_likely, pessimistic)
    if optimistic == pessimistic:
        raw = float(optimistic)
    elif distribution == "beta_pert":
        alpha = 1.0 + beta_pert_lambda * (most_likely - optimistic) / (pessimistic - optimistic)
        beta = 1.0 + beta_pert_lambda * (pessimistic - most_likely) / (pessimistic - optimistic)
        raw = optimistic + (pessimistic - optimistic) * float(rng.beta(alpha, beta))
    elif distribution == "triangular":
        raw = float(rng.triangular(optimistic, most_likely, pessimistic))
    else:
        raise ValueError(f"Unsupported distribution: {distribution}")
    return raw, int(math.ceil(raw))


def run_pert_custom(
    activities: Sequence[Activity],
    replications: int,
    seed: int,
    distribution: str = "beta_pert",
    beta_pert_lambda: float = 4.0,
) -> PertResult:
    if replications <= 0:
        raise ValueError("Replications must be positive.")
    if beta_pert_lambda <= 0:
        raise ValueError("Beta-PERT lambda must be positive.")

    pert_rng, _, _ = spawn_generators(seed)
    raw = np.empty((replications, len(activities)), dtype=np.float64)
    rounded = np.empty((replications, len(activities)), dtype=np.int16)

    for column, item in enumerate(activities):
        if item.optimistic == item.pessimistic:
            raw[:, column] = item.optimistic
        elif distribution == "beta_pert":
            alpha = 1.0 + beta_pert_lambda * (item.most_likely - item.optimistic) / (item.pessimistic - item.optimistic)
            beta = 1.0 + beta_pert_lambda * (item.pessimistic - item.most_likely) / (item.pessimistic - item.optimistic)
            raw[:, column] = item.optimistic + (item.pessimistic - item.optimistic) * pert_rng.beta(alpha, beta, replications)
        elif distribution == "triangular":
            raw[:, column] = pert_rng.triangular(item.optimistic, item.most_likely, item.pessimistic, replications)
        else:
            raise ValueError(f"Unsupported distribution: {distribution}")
        rounded[:, column] = np.ceil(raw[:, column]).astype(np.int16)

    return PertResult(raw, rounded, rounded.sum(axis=1, dtype=np.int32))


def run_gert_custom(
    arcs: Sequence[Arc],
    replications: int,
    seed: int,
    distribution: str = "beta_pert",
    beta_pert_lambda: float = 4.0,
    max_steps: int = MAX_STEPS,
) -> GertResult:
    if replications <= 0:
        raise ValueError("Replications must be positive.")
    if beta_pert_lambda <= 0:
        raise ValueError("Beta-PERT lambda must be positive.")

    _, routing_rng, duration_rng = spawn_generators(seed)
    groups = outgoing_groups(arcs)
    totals = np.zeros(replications, dtype=np.int32)
    outcome_codes = np.full(replications, -1, dtype=np.int8)
    final_states = np.full(replications, "", dtype="U2")
    transition_counts = np.zeros(replications, dtype=np.int16)
    loop_counts = np.zeros((replications, len(LOOP_TAGS)), dtype=np.int8)
    dispute_visited = np.zeros(replications, dtype=np.bool_)
    renormalisation_counts = np.zeros(replications, dtype=np.int16)
    routes: list[str] = []
    route_counts: Counter[str] = Counter()
    computational_errors: list[str] = []

    loop_index = {tag: i for i, tag in enumerate(LOOP_TAGS)}

    for iteration in range(replications):
        state = ROUTING_START_STATE
        total_duration = 0
        arc_path = ["e01"]
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

            excluded = [arc for arc in group if arc.loop_cap is not None and counters.get(arc.tag, 0) >= arc.loop_cap]
            eligible = [arc for arc in group if arc not in excluded and arc.probability > 0]
            if not eligible:
                computational_errors.append(f"iteration {iteration + 1}: no eligible arc at {state}")
                break
            if excluded:
                renormalisations += 1

            selected = choose_arc(routing_rng, eligible)
            _, rounded_duration = _sample_duration(
                duration_rng,
                selected.optimistic,
                selected.most_likely,
                selected.pessimistic,
                distribution,
                beta_pert_lambda,
            )
            total_duration += rounded_duration
            arc_path.append(selected.tag)

            if selected.loop_cap is not None:
                counters[selected.tag] = counters.get(selected.tag, 0) + 1
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
        loop_counts[iteration] = [counters.get(tag, 0) for tag in LOOP_TAGS]
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
