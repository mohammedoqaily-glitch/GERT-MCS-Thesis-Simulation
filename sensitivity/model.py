from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np


BASE = Path(__file__).resolve().parents[1]
CORE_SOURCE = BASE / "work" / "final_preliminary" / "simulate_final.py"
PERT_INPUT_CANDIDATES = (
    Path(r"C:\Users\moham\OneDrive\Desktop\PERT Input.docx"),
    BASE / "release" / "VO_PERT_GERT_Full_Simulation_Package" / "01_AUTHORITATIVE_INPUTS" / "PERT Input.docx",
)
GERT_INPUT_CANDIDATES = (
    Path(r"C:\Users\moham\OneDrive\Desktop\GERT nput.docx"),
    BASE / "release" / "VO_PERT_GERT_Full_Simulation_Package" / "01_AUTHORITATIVE_INPUTS" / "GERT nput.docx",
)
LOOP_TAGS = ("e22", "e21", "e33", "e32", "e43", "e42", "e55", "e54", "e52", "e66")
TERMINALS = {"S7": "Successful Closure", "ST": "Non-Implementation Closure"}


@dataclass
class ModelDefinition:
    pert: list[dict]
    nodes: list[dict]
    arcs: list[dict]
    input_checks: list[dict]
    pert_hash: str
    gert_hash: str


@dataclass
class SimulationResult:
    scenario_id: str
    replications: int
    seed: int
    distribution: str
    totals: np.ndarray
    outcomes: np.ndarray
    dispute_visited: np.ndarray
    loop_counts: np.ndarray
    cap_hits: np.ndarray
    renormalisation_counts: np.ndarray
    transition_counts: np.ndarray
    route_counts: dict[str, int]
    arc_counts: np.ndarray | None = None
    arc_durations: np.ndarray | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_core():
    spec = importlib.util.spec_from_file_location("verified_scientific_core_for_sensitivity", CORE_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verified scientific core")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authoritative_input_paths() -> tuple[Path, Path]:
    pert = next((path for path in PERT_INPUT_CANDIDATES if path.exists()), None)
    gert = next((path for path in GERT_INPUT_CANDIDATES if path.exists()), None)
    if pert is None or gert is None:
        raise FileNotFoundError("The verified authoritative PERT and GERT input documents are unavailable")
    return pert, gert


def load_authoritative_model() -> ModelDefinition:
    core = load_core()
    pert_input, gert_input = authoritative_input_paths()
    core.PERT_FILE = pert_input
    core.GERT_FILE = gert_input
    pert, nodes, arcs, _, _ = core.parse_inputs()
    checks = core.validate_inputs(pert, nodes, arcs)
    if any(row["status"] != "PASS" for row in checks):
        raise AssertionError("Authoritative model input validation failed")
    model = ModelDefinition(
        pert=copy.deepcopy(pert),
        nodes=copy.deepcopy(nodes),
        arcs=copy.deepcopy(arcs),
        input_checks=copy.deepcopy(checks),
        pert_hash=sha256_file(pert_input),
        gert_hash=sha256_file(gert_input),
    )
    validate_model(model)
    return model


def clone_model(model: ModelDefinition) -> ModelDefinition:
    return copy.deepcopy(model)


def validate_model(model: ModelDefinition, tolerance: float = 1e-12) -> None:
    if len(model.pert) != 6 or len(model.nodes) != 10 or len(model.arcs) != 29:
        raise ValueError("Unexpected authoritative model dimensions")
    for row in [*model.pert, *model.arcs]:
        if not row["o"] <= row["ml"] <= row["p"]:
            raise ValueError(f"Invalid O/ML/P ordering for {row.get('activity_id', row.get('arc_tag'))}")
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for arc in model.arcs:
        outgoing[arc["from_node"]].append(arc)
        cap = arc["loop_cap"]
        if cap is not None and (not isinstance(cap, int) or cap < 0):
            raise ValueError(f"Invalid loop cap for {arc['arc_tag']}")
    for node, group in outgoing.items():
        total = math.fsum(arc["probability"] for arc in group)
        if not math.isclose(total, 1.0, abs_tol=tolerance):
            raise ValueError(f"Routing probabilities at {node} sum to {total}")
    e12 = next(arc for arc in model.arcs if arc["arc_tag"] == "e12")
    if (e12["from_node"], e12["to_node"]) != ("S1", "S2"):
        raise ValueError("Authoritative e12 mapping is not S1 -> S2")


def routing_groups(model: ModelDefinition) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for arc in model.arcs:
        groups[arc["from_node"]].append(arc)
    return dict(groups)


def perturb_probability(model: ModelDefinition, arc_tag: str, new_value: float) -> ModelDefinition:
    if not 0 <= new_value <= 1:
        raise ValueError("Probability must be in [0, 1]")
    modified = clone_model(model)
    target = next((arc for arc in modified.arcs if arc["arc_tag"] == arc_tag), None)
    if target is None:
        raise KeyError(arc_tag)
    group = [arc for arc in modified.arcs if arc["from_node"] == target["from_node"]]
    baseline = target["probability"]
    if len(group) < 2 or math.isclose(baseline, 1.0, abs_tol=1e-15):
        raise ValueError(f"{arc_tag} is not eligible for ordinary one-way perturbation")
    denominator = 1.0 - baseline
    if denominator <= 0 or (new_value >= 1 and any(arc is not target for arc in group)):
        raise ValueError("Perturbation would collapse the remaining routing alternatives")
    scale = (1.0 - new_value) / denominator
    for arc in group:
        arc["probability"] = new_value if arc is target else arc["probability"] * scale
    validate_model(modified)
    return modified


def scale_duration(model: ModelDefinition, arc_tag: str, scale: float) -> ModelDefinition:
    if scale <= 0:
        raise ValueError("Duration scale must be positive")
    modified = clone_model(model)
    target = next((arc for arc in modified.arcs if arc["arc_tag"] == arc_tag), None)
    if target is None:
        raise KeyError(arc_tag)
    for key in ("o", "ml", "p"):
        target[key] = target[key] * scale
    validate_model(modified)
    return modified


def set_loop_cap(model: ModelDefinition, arc_tag: str, cap: int) -> ModelDefinition:
    if not isinstance(cap, int) or cap < 0:
        raise ValueError("Loop cap must be a non-negative integer")
    modified = clone_model(model)
    target = next((arc for arc in modified.arcs if arc["arc_tag"] == arc_tag), None)
    if target is None or target["loop_cap"] is None:
        raise ValueError(f"{arc_tag} is not a capped loop transition")
    target["loop_cap"] = cap
    validate_model(modified)
    return modified


def model_fingerprint(model: ModelDefinition) -> str:
    payload = {
        "pert": model.pert,
        "arcs": model.arcs,
        "pert_hash": model.pert_hash,
        "gert_hash": model.gert_hash,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def beta_parameters(o: float, ml: float, p: float, lam: float = 4.0) -> tuple[float, float]:
    if p == o:
        return math.nan, math.nan
    return 1.0 + lam * (ml - o) / (p - o), 1.0 + lam * (p - ml) / (p - o)


def _draw_duration(rng: np.random.Generator, arc: dict, distribution: str) -> int:
    o, ml, p = arc["o"], arc["ml"], arc["p"]
    if p == o:
        raw = o
    elif distribution == "beta_pert":
        alpha, beta = beta_parameters(o, ml, p)
        raw = o + (p - o) * rng.beta(alpha, beta)
    elif distribution == "triangular":
        raw = rng.triangular(o, ml, p)
    else:
        raise ValueError(f"Unsupported duration distribution: {distribution}")
    return int(math.ceil(float(raw)))


def simulate_gert(
    model: ModelDefinition,
    replications: int,
    seed: int,
    distribution: str = "beta_pert",
    scenario_id: str = "baseline",
    watchdog_steps: int = 10000,
    capture_drivers: bool = False,
) -> SimulationResult:
    validate_model(model)
    outgoing = routing_groups(model)
    arc_tags = [arc["arc_tag"] for arc in model.arcs]
    arc_index = {tag: index for index, tag in enumerate(arc_tags)}
    loop_index = {tag: index for index, tag in enumerate(LOOP_TAGS)}
    root = np.random.SeedSequence(seed)
    streams = root.spawn(3)
    routing_rng = np.random.default_rng(streams[1])
    duration_rng = np.random.default_rng(streams[2])
    totals = np.zeros(replications, dtype=np.int32)
    outcomes = np.full(replications, -1, dtype=np.int8)
    dispute = np.zeros(replications, dtype=np.bool_)
    loop_counts = np.zeros((replications, len(LOOP_TAGS)), dtype=np.int8)
    cap_hits = np.zeros_like(loop_counts, dtype=np.bool_)
    renormalisation = np.zeros(replications, dtype=np.int16)
    transitions = np.zeros(replications, dtype=np.int16)
    arc_counts = np.zeros((replications, len(arc_tags)), dtype=np.int16) if capture_drivers else None
    arc_durations = np.zeros((replications, len(arc_tags)), dtype=np.int32) if capture_drivers else None
    routes: Counter[str] = Counter()

    for iteration in range(replications):
        node = "S1"
        counters = {tag: 0 for tag in LOOP_TAGS}
        total = 0
        route = ["e01"]
        visited_dispute = False
        step = 1
        while node not in TERMINALS:
            if step >= watchdog_steps:
                break
            group = outgoing[node]
            excluded = [arc for arc in group if arc["loop_cap"] is not None and counters[arc["arc_tag"]] >= arc["loop_cap"]]
            eligible = [arc for arc in group if arc not in excluded and arc["probability"] > 0]
            if not eligible:
                break
            denominator = math.fsum(arc["probability"] for arc in eligible)
            effective = np.asarray([arc["probability"] / denominator for arc in eligible], dtype=np.float64)
            draw = float(routing_rng.random())
            selected_index = min(int(np.searchsorted(np.cumsum(effective), draw, side="right")), len(eligible) - 1)
            selected = eligible[selected_index]
            duration = _draw_duration(duration_rng, selected, distribution)
            total += duration
            tag = selected["arc_tag"]
            route.append(tag)
            if capture_drivers:
                j = arc_index[tag]
                arc_counts[iteration, j] += 1
                arc_durations[iteration, j] += duration
            if selected["loop_cap"] is not None:
                counters[tag] += 1
                loop_counts[iteration, loop_index[tag]] = counters[tag]
                if counters[tag] == selected["loop_cap"]:
                    cap_hits[iteration, loop_index[tag]] = True
            if excluded:
                renormalisation[iteration] += 1
            node = selected["to_node"]
            visited_dispute = visited_dispute or node == "SD"
            step += 1
        totals[iteration] = total
        dispute[iteration] = visited_dispute
        transitions[iteration] = len(route)
        if node == "S7":
            outcomes[iteration] = 1
        elif node == "ST":
            outcomes[iteration] = 0
        routes[">".join(route)] += 1

    return SimulationResult(
        scenario_id=scenario_id,
        replications=replications,
        seed=seed,
        distribution=distribution,
        totals=totals,
        outcomes=outcomes,
        dispute_visited=dispute,
        loop_counts=loop_counts,
        cap_hits=cap_hits,
        renormalisation_counts=renormalisation,
        transition_counts=transitions,
        route_counts=dict(routes),
        arc_counts=arc_counts,
        arc_durations=arc_durations,
    )


def simulate_pert(model: ModelDefinition, replications: int, seed: int, distribution: str = "beta_pert") -> dict:
    root = np.random.SeedSequence(seed)
    rng = np.random.default_rng(root.spawn(3)[0])
    activity = np.zeros((replications, len(model.pert)), dtype=np.int16)
    for index, row in enumerate(model.pert):
        if distribution == "beta_pert":
            alpha, beta = beta_parameters(row["o"], row["ml"], row["p"])
            values = row["o"] + (row["p"] - row["o"]) * rng.beta(alpha, beta, replications)
        elif distribution == "triangular":
            values = rng.triangular(row["o"], row["ml"], row["p"], replications)
        else:
            raise ValueError(distribution)
        activity[:, index] = np.ceil(values).astype(np.int16)
    return {"totals": activity.sum(axis=1, dtype=np.int32), "activity_durations": activity}


def result_signature(result: SimulationResult) -> str:
    digest = hashlib.sha256()
    for array in (result.totals, result.outcomes, result.dispute_visited, result.loop_counts, result.renormalisation_counts):
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()
