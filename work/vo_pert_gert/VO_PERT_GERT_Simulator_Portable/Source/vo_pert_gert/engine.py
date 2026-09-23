from __future__ import annotations

import csv
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


LAMBDA = 4


@dataclass
class Activity:
    id: str
    name: str
    o: float
    ml: float
    p: float
    enabled: bool = True
    structural_zero: bool = False


@dataclass
class Arc(Activity):
    from_node: str = ""
    to_node: str = ""
    probability: float = 1.0
    loop_id: str = ""
    loop_cap: Optional[int] = None


@dataclass
class Node:
    id: str
    name: str
    logic: str = "XOR"
    terminal: str = ""


@dataclass
class Case:
    simulation_name: str = "VO PERT-GERT Monte Carlo Simulator"
    variation_order_id: str = ""
    variation_order_name: str = ""
    scenario_name: str = "Default"
    model_type: str = "Both"
    iterations: Optional[int] = None
    seed: int = 42
    notes: str = ""
    pert: List[Activity] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    start_node: str = "START"

    @property
    def requested_iterations(self) -> int:
        return self.iterations if self.iterations and self.iterations > 0 else 50000


def default_case() -> Case:
    return Case(
        variation_order_id="DEFAULT",
        variation_order_name="No attached case data",
        notes="Fallback demonstration network. Replace with supplied Word/spec/case data before research use.",
        pert=[
            Activity("P01", "Submission review", 2, 4, 7),
            Activity("P02", "Technical assessment", 3, 5, 9),
            Activity("P03", "Commercial assessment", 2, 6, 12),
            Activity("P04", "Approval and close", 1, 3, 5),
        ],
        nodes=[
            Node("START", "Start"),
            Node("ASSESS", "Assess"),
            Node("DISPUTE", "Dispute"),
            Node("SUCCESS", "Successful", terminal="Successful"),
            Node("TERM", "Terminated", terminal="Terminated"),
        ],
        arcs=[
            Arc("G01", "Initial assessment", 2, 4, 7, from_node="START", to_node="ASSESS", probability=1),
            Arc("G02", "Accept", 1, 3, 5, from_node="ASSESS", to_node="SUCCESS", probability=.55),
            Arc("G03", "Reject", 1, 2, 4, from_node="ASSESS", to_node="TERM", probability=.25),
            Arc("G04", "Dispute referral", 2, 5, 10, from_node="ASSESS", to_node="DISPUTE", probability=.20),
            Arc("G05", "Dispute resolves", 2, 4, 8, from_node="DISPUTE", to_node="SUCCESS", probability=.65),
            Arc("G06", "Dispute fails", 1, 3, 6, from_node="DISPUTE", to_node="TERM", probability=.25),
            Arc("G07", "Loop to assessment", 0, 0, 0, structural_zero=True, from_node="DISPUTE", to_node="ASSESS", probability=.10, loop_id="L01", loop_cap=2),
        ],
    )


def alpha_beta(o: float, ml: float, p: float, lam: int = LAMBDA) -> Tuple[float, float]:
    if p == o:
        raise ValueError("O and P must differ for stochastic Beta-PERT durations.")
    alpha = 1 + lam * ((ml - o) / (p - o))
    beta = 1 + lam * ((p - ml) / (p - o))
    return alpha, beta


def sample_duration(rng: random.Random, item: Activity) -> int:
    if item.structural_zero and item.o == item.ml == item.p == 0:
        return 0
    validate_duration(item)
    a, b = alpha_beta(item.o, item.ml, item.p)
    raw = item.o + rng.betavariate(a, b) * (item.p - item.o)
    return int(math.ceil(raw))


def validate_duration(item: Activity) -> None:
    if not (0 <= item.o <= item.ml <= item.p):
        raise ValueError(f"{item.id}: require 0 <= O <= ML <= P.")
    if item.o >= item.p:
        raise ValueError(f"{item.id}: require O < P unless explicitly structural zero.")


def nearest_rank(values: List[int]) -> List[Dict[str, int]]:
    if not values:
        return [{"Percentile": p, "Rank": 0, "Duration": 0} for p in range(1, 100)]
    ordered = sorted(values)
    n = len(ordered)
    rows = []
    for p in range(1, 100):
        rank = int(math.ceil((p / 100) * n))
        rows.append({"Percentile": p, "Rank": rank, "Duration": ordered[rank - 1]})
    return rows


def stats(values: List[int]) -> Dict[str, float]:
    if not values:
        return {k: 0 for k in ["Count", "Mean", "Ceiling of Mean", "Standard deviation", "Variance", "Median", "Minimum", "Maximum", "Range", "IQR", "Coefficient of variation"]}
    q = nearest_rank(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0
    p25 = q[24]["Duration"]
    p75 = q[74]["Duration"]
    return {
        "Count": len(values),
        "Mean": mean,
        "Ceiling of Mean": math.ceil(mean),
        "Standard deviation": sd,
        "Variance": sd * sd,
        "Median": q[49]["Duration"],
        "Minimum": min(values),
        "Maximum": max(values),
        "Range": max(values) - min(values),
        "IQR": p75 - p25,
        "Coefficient of variation": sd / mean if mean else 0,
    }


def validate_case(case: Case) -> List[str]:
    errors = []
    for item in case.pert:
        if item.enabled:
            try:
                if not (item.structural_zero and item.o == item.ml == item.p == 0):
                    validate_duration(item)
            except ValueError as e:
                errors.append(str(e))
    node_ids = {n.id for n in case.nodes}
    if case.start_node not in node_ids:
        errors.append("Start node is missing.")
    outgoing: Dict[str, List[Arc]] = {}
    for arc in case.arcs:
        if not arc.enabled:
            continue
        if arc.from_node not in node_ids or arc.to_node not in node_ids:
            errors.append(f"{arc.id}: from/to node is missing.")
        if arc.probability < 0:
            errors.append(f"{arc.id}: probability must be non-negative.")
        if not (arc.structural_zero and arc.o == arc.ml == arc.p == 0):
            try:
                validate_duration(arc)
            except ValueError as e:
                errors.append(str(e))
        outgoing.setdefault(arc.from_node, []).append(arc)
    terminals = {n.id for n in case.nodes if n.terminal}
    for n in case.nodes:
        if n.id not in terminals:
            total = sum(a.probability for a in outgoing.get(n.id, []))
            if not math.isclose(total, 1, abs_tol=1e-9):
                errors.append(f"{n.id}: outgoing probability total is {total:.12g}, expected 1.")
            if not outgoing.get(n.id):
                errors.append(f"{n.id}: non-terminal node has no outgoing arcs.")
    for node, arcs in outgoing.items():
        uncapped = [a for a in arcs if not a.loop_id or a.loop_cap is None]
        if arcs and not uncapped:
            errors.append(f"{node}: loop caps can remove every outgoing arc.")
    return errors


def run_pert(case: Case, iterations: Optional[int] = None) -> Dict:
    n = iterations or case.requested_iterations
    rng = random.Random(case.seed)
    enabled = [a for a in case.pert if a.enabled]
    totals: List[int] = []
    activity_rows: List[Dict] = []
    raw_activity: List[Dict] = []
    for i in range(1, n + 1):
        total = 0
        for a in enabled:
            d = sample_duration(rng, a)
            total += d
            raw_activity.append({"Iteration": i, "Activity ID": a.id, "Activity Name": a.name, "Duration": d})
        totals.append(int(math.ceil(total)))
    for a in enabled:
        vals = [r["Duration"] for r in raw_activity if r["Activity ID"] == a.id]
        row = {"Activity ID": a.id, "Activity Name": a.name}
        row.update(stats(vals))
        activity_rows.append(row)
    return {
        "totals": totals,
        "summary": stats(totals),
        "percentiles": nearest_rank(totals),
        "activity": activity_rows,
        "raw_activity": raw_activity,
        "convergence": convergence(totals, n, "PERT Total"),
    }


def weighted_choice(rng: random.Random, arcs: List[Arc], weights: List[float]) -> Arc:
    x = rng.random() * sum(weights)
    c = 0.0
    for arc, w in zip(arcs, weights):
        c += w
        if x <= c:
            return arc
    return arcs[-1]


def run_gert(case: Case, iterations: Optional[int] = None) -> Dict:
    n = iterations or case.requested_iterations
    rng = random.Random(case.seed + 1000003)
    nodes = {node.id: node for node in case.nodes}
    outgoing: Dict[str, List[Arc]] = {}
    for arc in case.arcs:
        if arc.enabled:
            outgoing.setdefault(arc.from_node, []).append(arc)
    iterations_rows, path_rows, invalid_rows = [], [], []
    arc_counts: Dict[str, int] = {a.id: 0 for a in case.arcs}
    node_counts: Dict[str, int] = {node.id: 0 for node in case.nodes}
    loop_counts: Dict[str, int] = {}
    cap_events, renorm_events, dispute_rows = [], [], []
    success, terminated = [], []
    for i in range(1, n + 1):
        current = case.start_node
        total = 0
        transitions = 0
        loops: Dict[str, int] = {}
        path = []
        visited_states = set()
        invalid = ""
        while True:
            node_counts[current] = node_counts.get(current, 0) + 1
            terminal = nodes[current].terminal
            if terminal in ("Successful", "Terminated"):
                break
            state = (current, tuple(sorted(loops.items())))
            if state in visited_states:
                invalid = "Repeated structural state detected"
                break
            visited_states.add(state)
            eligible, probs, suppressed = [], [], []
            for arc in outgoing.get(current, []):
                reached = arc.loop_id and arc.loop_cap is not None and loops.get(arc.loop_id, 0) >= arc.loop_cap
                if reached:
                    suppressed.append(arc)
                else:
                    eligible.append(arc)
                    probs.append(arc.probability)
            if not eligible or sum(probs) <= 0:
                invalid = "No eligible outgoing arc"
                break
            if suppressed:
                renorm_events.append({"Iteration": i, "Node": current, "Suppressed Arcs": ",".join(a.id for a in suppressed), "Original Remaining Probability": sum(probs)})
                for arc in suppressed:
                    cap_events.append({"Iteration": i, "Loop ID": arc.loop_id, "Arc ID": arc.id, "Node": current})
            arc = weighted_choice(rng, eligible, probs)
            duration = sample_duration(rng, arc)
            total += duration
            transitions += 1
            arc_counts[arc.id] = arc_counts.get(arc.id, 0) + 1
            path.append(arc.id)
            if arc.loop_id:
                loops[arc.loop_id] = loops.get(arc.loop_id, 0) + 1
                loop_counts[arc.loop_id] = loop_counts.get(arc.loop_id, 0) + 1
            if arc.to_node.upper() == "DISPUTE" or nodes[arc.to_node].name.lower() == "dispute":
                dispute_rows.append({"Iteration": i, "Duration at Entry": total})
            current = arc.to_node
            if transitions > 10000:
                invalid = "Transition guard exceeded"
                break
        if invalid:
            invalid_rows.append({"Iteration": i, "Reason": invalid, "Duration": total, "Path": " > ".join(path)})
            outcome = "Invalid"
        else:
            outcome = nodes[current].terminal
            if outcome == "Successful":
                success.append(math.ceil(total))
            elif outcome == "Terminated":
                terminated.append(math.ceil(total))
        iterations_rows.append({"Iteration": i, "Outcome": outcome, "Duration": math.ceil(total), "Transitions": transitions, "Path": " > ".join(path)})
        path_rows.append({"Path": " > ".join(path), "Outcome": outcome, "Duration": math.ceil(total)})
    valid = len(success) + len(terminated)
    return {
        "iterations": iterations_rows,
        "paths": path_rows,
        "invalid": invalid_rows,
        "success": success,
        "terminated": terminated,
        "outcome_summary": [
            {"Outcome": "Successful", "Count": len(success), "Probability": len(success) / valid if valid else 0},
            {"Outcome": "Terminated", "Count": len(terminated), "Probability": len(terminated) / valid if valid else 0},
            {"Outcome": "Invalid", "Count": len(invalid_rows), "Probability": len(invalid_rows) / n if n else 0},
        ],
        "successful_summary": stats(success),
        "terminated_summary": stats(terminated),
        "successful_percentiles": nearest_rank(success),
        "terminated_percentiles": nearest_rank(terminated),
        "arc_analysis": [{"Arc ID": k, "Traversals": v, "Activation Probability": v / n} for k, v in arc_counts.items()],
        "node_analysis": [{"Node ID": k, "Visits": v, "Visit Probability": v / n} for k, v in node_counts.items()],
        "loop_summary": [{"Loop ID": k, "Total Returns": v, "Mean Returns": v / n} for k, v in loop_counts.items()],
        "cap_events": cap_events,
        "renorm_events": renorm_events,
        "dispute": dispute_rows,
        "transition_counts": [{"Transitions": r["Transitions"]} for r in iterations_rows],
        "convergence": convergence(success, n, "GERT Successful Mean"),
    }


def convergence(values: List[int], n: int, label: str) -> List[Dict]:
    interval = max(100, math.floor(n / 100))
    rows = []
    previous = None
    for idx in range(interval, len(values) + 1, interval):
        chunk = values[:idx]
        mean = statistics.fmean(chunk) if chunk else 0
        change = abs(mean - previous) / previous if previous else 0
        rows.append({"Checkpoint": idx, "Metric": label, "Value": mean, "Relative Change": change, "Stable": change <= .01 if previous else False})
        previous = mean
    return rows


def load_case(path: Path) -> Case:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Case(
        **{k: v for k, v in data.items() if k not in {"pert", "nodes", "arcs"}},
        pert=[Activity(**x) for x in data.get("pert", [])],
        nodes=[Node(**x) for x in data.get("nodes", [])],
        arcs=[Arc(**x) for x in data.get("arcs", [])],
    )


def save_case(case: Case, path: Path) -> None:
    path.write_text(json.dumps(asdict(case), indent=2), encoding="utf-8")

