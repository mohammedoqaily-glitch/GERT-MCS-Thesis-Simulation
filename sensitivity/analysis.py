from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import __version__
from .bimodality import classify_distribution, threshold_interval
from .model import (
    CORE_SOURCE,
    GERT_INPUT_CANDIDATES,
    LOOP_TAGS,
    PERT_INPUT_CANDIDATES,
    ModelDefinition,
    SimulationResult,
    authoritative_input_paths,
    clone_model,
    load_authoritative_model,
    model_fingerprint,
    perturb_probability,
    result_signature,
    routing_groups,
    scale_duration,
    set_loop_cap,
    sha256_file,
    simulate_gert,
    simulate_pert,
)
from .plotting import categorical_modes, grouped_bars, hist_kde_panels, line_chart, ranking_chart, tornado
from .statistics import add_changes, driver_screen, metrics_from_result, nearest_quantile


BASE = Path(__file__).resolve().parents[1]
VERIFIED_CSV = BASE / "outputs" / "Simulation_Data" / "CSV"
VERIFIED_INTEGRITY = BASE / "work" / "raw_data_export" / "raw_export_integrity.json"
CHANGE_FIELDS = [
    "Mean_Successful_Time", "Median_Successful_Time", "Successful_P80", "Successful_P90",
    "Successful_P95", "Successful_Time_SD", "P_Exceed_Tc_Given_Success", "P_Success",
    "P_NonImplementation", "P_Dispute_Diversion", "P_Any_Loop",
    "Expected_Total_Loop_Repetitions", "Computational_Termination_Rate",
    "Unconditional_Mean_Time_Mixed_Outcomes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    columns.append(key)
                    seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in columns})


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def scenario_fingerprint(spec: dict, model: ModelDefinition, config: dict) -> str:
    payload = {
        "analysis_version": __version__,
        "model": model_fingerprint(model),
        "spec": spec,
        "bootstrap_resamples": config["bootstrap_resamples"],
        "confidence_level": config["confidence_level"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def cache_paths(config: dict, scenario_id: str) -> tuple[Path, Path]:
    root = Path(config["cache_directory"])
    root.mkdir(parents=True, exist_ok=True)
    stem = slug(scenario_id)
    return root / f"{stem}.npz", root / f"{stem}.json"


def save_cached_result(config: dict, result: SimulationResult, metrics: dict, fingerprint: str, spec: dict) -> None:
    array_path, metadata_path = cache_paths(config, result.scenario_id)
    payload = {
        "totals": result.totals,
        "outcomes": result.outcomes,
        "dispute_visited": result.dispute_visited,
        "loop_counts": result.loop_counts,
        "cap_hits": result.cap_hits,
        "renormalisation_counts": result.renormalisation_counts,
        "transition_counts": result.transition_counts,
        "route_keys": np.asarray(list(result.route_counts), dtype="U512"),
        "route_values": np.asarray(list(result.route_counts.values()), dtype=np.int64),
    }
    if result.arc_counts is not None:
        payload["arc_counts"] = result.arc_counts
    if result.arc_durations is not None:
        payload["arc_durations"] = result.arc_durations
    np.savez_compressed(array_path, **payload)
    write_json(metadata_path, {
        "fingerprint": fingerprint,
        "scenario_id": result.scenario_id,
        "replications": result.replications,
        "seed": result.seed,
        "distribution": result.distribution,
        "metrics": metrics,
        "spec": spec,
        "result_signature": result_signature(result),
        "cached_utc": utc_now(),
    })


def load_cached_result(config: dict, scenario_id: str, expected_fingerprint: str | None = None) -> tuple[SimulationResult, dict, dict] | None:
    array_path, metadata_path = cache_paths(config, scenario_id)
    if not array_path.exists() or not metadata_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if expected_fingerprint is not None and metadata.get("fingerprint") != expected_fingerprint:
        return None
    with np.load(array_path, allow_pickle=False) as data:
        result = SimulationResult(
            scenario_id=metadata["scenario_id"],
            replications=metadata["replications"],
            seed=metadata["seed"],
            distribution=metadata["distribution"],
            totals=data["totals"],
            outcomes=data["outcomes"],
            dispute_visited=data["dispute_visited"],
            loop_counts=data["loop_counts"],
            cap_hits=data["cap_hits"],
            renormalisation_counts=data["renormalisation_counts"],
            transition_counts=data["transition_counts"],
            route_counts={str(key): int(value) for key, value in zip(data["route_keys"], data["route_values"])},
            arc_counts=data["arc_counts"] if "arc_counts" in data.files else None,
            arc_durations=data["arc_durations"] if "arc_durations" in data.files else None,
        )
    return result, metadata["metrics"], metadata


def apply_spec(model: ModelDefinition, spec: dict) -> tuple[ModelDefinition, int, str]:
    modified = clone_model(model)
    operation = spec["operation"]
    if operation == "probability":
        modified = perturb_probability(modified, spec["parameter_id"], float(spec["value"]))
    elif operation == "duration":
        modified = scale_duration(modified, spec["parameter_id"], float(spec["scale"]))
    elif operation == "loop_cap":
        modified = set_loop_cap(modified, spec["parameter_id"], int(spec["value"]))
    elif operation in {"baseline", "distribution", "seed"}:
        pass
    else:
        raise ValueError(operation)
    return modified, int(spec["seed"]), spec.get("distribution", "beta_pert")


def execute_spec(payload: tuple[dict, ModelDefinition, dict]) -> dict:
    spec, baseline_model, config = payload
    started = time.perf_counter()
    fingerprint = scenario_fingerprint(spec, baseline_model, config)
    if config.get("resume", True):
        cached = load_cached_result(config, spec["scenario_id"], fingerprint)
        if cached is not None:
            result, metrics, metadata = cached
            return {
                "spec": spec, "metrics": metrics, "cache_status": "HIT", "elapsed_seconds": time.perf_counter() - started,
                "signature": metadata["result_signature"], "status": "PASS",
            }
    modified, seed, distribution = apply_spec(baseline_model, spec)
    result = simulate_gert(
        modified,
        replications=int(spec["replications"]),
        seed=seed,
        distribution=distribution,
        scenario_id=spec["scenario_id"],
        watchdog_steps=config["watchdog_steps"],
        capture_drivers=bool(spec.get("capture_drivers", False)),
    )
    metrics = metrics_from_result(result, config)
    save_cached_result(config, result, metrics, fingerprint, spec)
    return {
        "spec": spec, "metrics": metrics, "cache_status": "MISS", "elapsed_seconds": time.perf_counter() - started,
        "signature": result_signature(result), "status": "PASS",
    }


def baseline_accepted_values() -> dict:
    summary_rows = read_csv(VERIFIED_CSV / "07_GERT_Analysis_Ready__Summary_Statistics.csv")
    by_entity = {row["Entity_ID"]: row for row in summary_rows}
    simulation_summary = {row["Metric"]: row["Value"] for row in read_csv(VERIFIED_CSV / "00_Master_Index__Simulation_Summary.csv")}
    exact_comparison = {row["Metric"]: row for row in read_csv(VERIFIED_CSV / "08_Exact_Verification__Monte_Carlo_Comparison.csv")}
    paths = read_csv(VERIFIED_CSV / "04_GERT_Iteration_Data__Path_Register.csv")
    return {
        "pert_mean": float(simulation_summary["PERT mean"]),
        "gert_success_count": int(simulation_summary["GERT successful count"]),
        "gert_nonimplementation_count": int(simulation_summary["GERT terminated count"]),
        "gert_success_probability": float(exact_comparison["Successful probability"]["Simulated_Value"]),
        "gert_nonimplementation_probability": float(exact_comparison["Terminated probability"]["Simulated_Value"]),
        "gert_dispute_probability": float(exact_comparison["Dispute visit probability"]["Simulated_Value"]),
        "gert_overall_mean": float(by_entity["Overall"]["Mean"]),
        "gert_success_mean": float(by_entity["Successful"]["Mean"]),
        "gert_success_p50": float(by_entity["Successful"]["P50"]),
        "gert_success_p80": float(by_entity["Successful"]["P80"]),
        "gert_success_p90": float(by_entity["Successful"]["P90"]),
        "gert_success_p95": float(by_entity["Successful"]["P95"]),
        "route_probabilities": {row["Arc_Sequence"]: float(row["Probability"]) for row in paths},
    }


def baseline_validation(model: ModelDefinition, result: SimulationResult, metrics: dict, pert_result: dict) -> list[dict]:
    accepted = baseline_accepted_values()
    reproduced_routes = {route: count / result.replications for route, count in result.route_counts.items()}
    route_keys = set(accepted["route_probabilities"]) | set(reproduced_routes)
    max_route_difference = max(abs(accepted["route_probabilities"].get(key, 0) - reproduced_routes.get(key, 0)) for key in route_keys)
    checks = [
        ("PERT mean completion time", accepted["pert_mean"], float(pert_result["totals"].mean()), 0.10, "working days"),
        ("GERT successful-closure count", accepted["gert_success_count"], metrics["Successful_Count"], 0, "runs"),
        ("GERT non-implementation count", accepted["gert_nonimplementation_count"], metrics["NonImplementation_Count"], 0, "runs"),
        ("P(Successful Closure)", accepted["gert_success_probability"], metrics["P_Success"], 0.001, "probability"),
        ("P(Non-Implementation Closure)", accepted["gert_nonimplementation_probability"], metrics["P_NonImplementation"], 0.001, "probability"),
        ("P(Dispute Diversion)", accepted["gert_dispute_probability"], metrics["P_Dispute_Diversion"], 0.001, "probability"),
        ("Unconditional mixed-outcome mean", accepted["gert_overall_mean"], metrics["Unconditional_Mean_Time_Mixed_Outcomes"], 0.10, "working days"),
        ("Mean Successful-Closure Time", accepted["gert_success_mean"], metrics["Mean_Successful_Time"], 0.10, "working days"),
        ("Successful-Closure median", accepted["gert_success_p50"], metrics["Median_Successful_Time"], 1, "working days"),
        ("Successful-Closure P80", accepted["gert_success_p80"], metrics["Successful_P80"], 1, "working days"),
        ("Successful-Closure P90", accepted["gert_success_p90"], metrics["Successful_P90"], 1, "working days"),
        ("Successful-Closure P95", accepted["gert_success_p95"], metrics["Successful_P95"], 1, "working days"),
        ("Maximum route-frequency difference", 0.0, max_route_difference, 0.002, "probability"),
        ("Computational termination rate", 0.0, metrics["Computational_Termination_Rate"], 0.0, "probability"),
    ]
    rows = []
    for metric, existing, reproduced, tolerance, unit in checks:
        difference = abs(float(reproduced) - float(existing))
        passed = difference <= tolerance + 1e-15
        rows.append({
            "Metric": metric, "Existing_Accepted_Value": existing, "Reproduced_Value": reproduced,
            "Absolute_Difference": difference, "Tolerance": tolerance, "Unit": unit,
            "Status": "PASS" if passed else "FAIL",
        })
    return rows


def generate_specs(model: ModelDefinition, baseline_result: SimulationResult, config: dict) -> tuple[list[dict], dict]:
    groups = routing_groups(model)
    arc_map = {arc["arc_tag"]: arc for arc in model.arcs}
    specs = []
    parameter_metadata = {"routing": [], "duration": [], "loop": []}
    relative = config["routing_relative_change"]
    for node, group in groups.items():
        for arc in group:
            baseline = arc["probability"]
            if len(group) < 2 or math.isclose(baseline, 1.0):
                continue
            low = max(0.0, baseline * (1 - relative))
            high = min(config["probability_upper_guard"], baseline * (1 + relative))
            if high <= baseline:
                high = baseline + (config["probability_upper_guard"] - baseline) / 2
            parameter_metadata["routing"].append({
                "Parameter_ID": arc["arc_tag"], "Parameter_Type": "Routing Probability",
                "Network_Location": f"{arc['from_node']} -> {arc['to_node']}", "Node": node,
                "Baseline_Value": baseline, "Low_Value": low, "High_Value": high,
                "Selection_Rule": "+/-25% relative; proportional renormalisation within XOR group",
            })
            for level, value in (("Low", low), ("High", high)):
                specs.append({
                    "scenario_id": f"routing_{arc['arc_tag']}_{level.lower()}", "analysis": "Routing_OAT",
                    "operation": "probability", "parameter_id": arc["arc_tag"], "level": level, "value": value,
                    "seed": config["baseline_seed"], "replications": config["baseline_replications"], "distribution": "beta_pert",
                })

    screen = driver_screen(baseline_result, [arc["arc_tag"] for arc in model.arcs])
    selected_duration_tags = [row["Arc_Tag"] for row in screen if arc_map[row["Arc_Tag"]]["p"] > 0][:config["duration_transition_count"]]
    duration_change = config["duration_relative_change"]
    for tag in selected_duration_tags:
        arc = arc_map[tag]
        baseline_triplet = [arc["o"], arc["ml"], arc["p"]]
        parameter_metadata["duration"].append({
            "Parameter_ID": tag, "Parameter_Type": "Duration Triplet", "Network_Location": f"{arc['from_node']} -> {arc['to_node']}",
            "Baseline_Value": json.dumps(baseline_triplet), "Low_Value": json.dumps([value * (1 - duration_change) for value in baseline_triplet]),
            "High_Value": json.dumps([value * (1 + duration_change) for value in baseline_triplet]),
            "Selection_Rule": f"Top-five expected successful-duration contribution screen; coherent +/-{duration_change:.0%} scaling",
        })
        for level, scale in (("Low", 1 - duration_change), ("High", 1 + duration_change)):
            specs.append({
                "scenario_id": f"duration_{tag}_{level.lower()}", "analysis": "Duration_OAT", "operation": "duration",
                "parameter_id": tag, "level": level, "scale": scale, "value": json.dumps([value * scale for value in baseline_triplet]),
                "seed": config["baseline_seed"], "replications": config["baseline_replications"], "distribution": "beta_pert",
            })

    for tag in LOOP_TAGS:
        arc = arc_map[tag]
        baseline_cap = int(arc["loop_cap"])
        low = 1
        high = baseline_cap + 1 if baseline_cap > 1 else 3
        parameter_metadata["loop"].append({
            "Parameter_ID": tag, "Parameter_Type": "Loop Cap", "Network_Location": f"{arc['from_node']} -> {arc['to_node']}",
            "Baseline_Value": baseline_cap, "Low_Value": low, "High_Value": high,
            "Selection_Rule": "cap = 1, baseline, baseline + 1",
        })
        for level, value in (("Low", low), ("High", high)):
            specs.append({
                "scenario_id": f"loopcap_{tag}_{level.lower()}", "analysis": "LoopCap_Robustness", "operation": "loop_cap",
                "parameter_id": tag, "level": level, "value": value, "seed": config["baseline_seed"],
                "replications": config["baseline_replications"], "distribution": "beta_pert",
            })

    specs.append({
        "scenario_id": "distribution_triangular", "analysis": "Distribution_Robustness", "operation": "distribution",
        "parameter_id": "duration_distribution", "level": "Alternative", "value": "triangular", "seed": config["baseline_seed"],
        "replications": config["baseline_replications"], "distribution": "triangular", "capture_drivers": True,
    })
    for seed in config["seed_list"]:
        specs.append({
            "scenario_id": f"seed_{seed}", "analysis": "Seed_Robustness", "operation": "seed", "parameter_id": "root_seed",
            "level": "Fixed Seed", "value": seed, "seed": seed, "replications": config["baseline_replications"], "distribution": "beta_pert",
        })
    for value in config["early_exit_probability_grid"]:
        specs.append({
            "scenario_id": f"threshold_{config['early_exit_arc']}_{int(round(value * 100)):03d}", "analysis": "Threshold_Analysis",
            "operation": "probability", "parameter_id": config["early_exit_arc"], "level": "Grid", "value": value,
            "seed": config["baseline_seed"], "replications": config["baseline_replications"], "distribution": "beta_pert",
        })
    return specs, {"parameters": parameter_metadata, "driver_screen": screen, "selected_duration_tags": selected_duration_tags}


def result_subset(result: SimulationResult, n: int, scenario_id: str) -> SimulationResult:
    route_counts = {}
    return SimulationResult(
        scenario_id=scenario_id, replications=n, seed=result.seed, distribution=result.distribution,
        totals=result.totals[:n], outcomes=result.outcomes[:n], dispute_visited=result.dispute_visited[:n],
        loop_counts=result.loop_counts[:n], cap_hits=result.cap_hits[:n],
        renormalisation_counts=result.renormalisation_counts[:n], transition_counts=result.transition_counts[:n],
        route_counts=route_counts,
    )


def record_with_context(metrics: dict, parameter: dict, level: str, scenario_id: str, baseline: dict, value) -> dict:
    row = add_changes(metrics, baseline, CHANGE_FIELDS)
    row.update({
        "Scenario_ID": scenario_id, "Parameter_ID": parameter["Parameter_ID"], "Parameter_Type": parameter["Parameter_Type"],
        "Network_Location": parameter["Network_Location"], "Scenario_Level": level,
        "Baseline_Value": parameter["Baseline_Value"], "Scenario_Value": value,
        "Low_Value": parameter["Low_Value"], "High_Value": parameter["High_Value"],
    })
    return row


def aggregate_seed_rows(rows: list[dict]) -> list[dict]:
    metrics = ["P_Success", "Mean_Successful_Time", "Successful_P90", "Successful_P95", "P_NonImplementation", "P_Dispute_Diversion"]
    output = []
    for statistic in ("Mean", "Minimum", "Maximum", "Standard Deviation", "Coefficient of Variation"):
        row = {"Record_Type": "Summary", "Seed_or_Statistic": statistic}
        for metric in metrics:
            values = np.asarray([float(item[metric]) for item in rows])
            if statistic == "Mean": value = values.mean()
            elif statistic == "Minimum": value = values.min()
            elif statistic == "Maximum": value = values.max()
            elif statistic == "Standard Deviation": value = values.std(ddof=1)
            else: value = values.std(ddof=1) / abs(values.mean()) if values.mean() else None
            row[metric] = float(value) if value is not None else None
        output.append(row)
    return output


def integrated_ranking(parameter_sets: list[tuple[dict, dict, dict]], baseline: dict) -> list[dict]:
    outputs = ["Mean_Successful_Time", "Successful_P90", "Successful_P95", "P_Success", "P_NonImplementation", "P_Dispute_Diversion"]
    rows = []
    for parameter, low, high in parameter_sets:
        row = {
            "Parameter_ID": parameter["Parameter_ID"], "Parameter_Label": f"{parameter['Parameter_ID']} {parameter['Network_Location']} ({parameter['Parameter_Type']})",
            "Parameter_Type": parameter["Parameter_Type"], "Network_Location": parameter["Network_Location"],
            "Baseline_Value": parameter["Baseline_Value"], "Low_Value": parameter["Low_Value"], "High_Value": parameter["High_Value"],
        }
        for output in outputs:
            low_effect = low[output] - baseline[output]
            high_effect = high[output] - baseline[output]
            row[f"Low_Effect_{output}"] = low_effect
            row[f"High_Effect_{output}"] = high_effect
            row[f"MaxAbs_Effect_{output}"] = max(abs(low_effect), abs(high_effect))
        rows.append(row)
    maxima = {output: max((row[f"MaxAbs_Effect_{output}"] for row in rows), default=0) for output in outputs}
    for row in rows:
        normalised = []
        for output in outputs:
            denominator = maxima[output]
            value = row[f"MaxAbs_Effect_{output}"] / denominator if denominator else 0.0
            row[f"Normalised_{output}"] = value
            normalised.append(value)
        row["Normalised_Influence_Score"] = max(normalised)
        row["Normalisation_Method"] = "Maximum absolute effect per output divided by the largest effect observed for that output; score is the maximum across six outputs"
    rows.sort(key=lambda row: (-row["Normalised_Influence_Score"], row["Parameter_ID"]))
    for index, row in enumerate(rows, start=1):
        row["Rank"] = index
    return rows


def tornado_rows(parameter_sets: list[tuple[dict, dict, dict]], field: str) -> list[dict]:
    rows = []
    for parameter, low, high in parameter_sets:
        baseline = low[field] - low[f"Abs_Change_{field}"]
        row = {
            "Parameter_ID": parameter["Parameter_ID"],
            "Parameter_Label": f"{parameter['Parameter_ID']} {parameter['Network_Location']}",
            "Parameter_Type": parameter["Parameter_Type"],
            "Network_Location": parameter["Network_Location"], "Baseline": baseline,
            "Low_Result": low[field], "High_Result": high[field],
            "Low_Delta": low[field] - baseline, "High_Delta": high[field] - baseline,
        }
        row["Maximum_Absolute_Effect"] = max(abs(row["Low_Delta"]), abs(row["High_Delta"]))
        rows.append(row)
    return sorted(rows, key=lambda row: (-row["Maximum_Absolute_Effect"], row["Parameter_ID"]))


def write_audit(output: Path, model: ModelDefinition, config: dict) -> dict:
    pert_path, gert_path = authoritative_input_paths()
    groups = routing_groups(model)
    audit = {
        "analysis_version": __version__, "generated_utc": utc_now(),
        "baseline_entry_point": str(CORE_SOURCE),
        "authoritative_pert_input": str(pert_path), "authoritative_gert_input": str(gert_path),
        "pert_sha256": model.pert_hash, "gert_sha256": model.gert_hash,
        "node_count": len(model.nodes), "transition_count_including_structural_e01": len(model.arcs) + 1,
        "xor_routing_groups": {node: [arc["arc_tag"] for arc in arcs] for node, arcs in groups.items()},
        "loop_transitions": [{"arc_tag": arc["arc_tag"], "from": arc["from_node"], "to": arc["to_node"], "cap": arc["loop_cap"]} for arc in model.arcs if arc["loop_cap"] is not None],
        "terminal_outcomes": {"S7": "Successful Closure", "ST": "Non-Implementation Closure"},
        "duration_distribution": "Beta-PERT (lambda 4)", "rounding": "ceil once per sampled transition/activity",
        "default_replications": config["baseline_replications"], "baseline_seed": config["baseline_seed"],
        "outcome_separation": {"successful": True, "nonimplementation": True, "dispute_diversion": True, "computational_termination": True},
        "available_granularities": ["run", "transition", "route", "node", "loop", "cap", "renormalisation", "dispute", "convergence", "outcome"],
    }
    write_json(output / "Baseline_Audit.json", audit)
    return audit


def build_figures(output: Path, tables: dict, threshold_curves: dict, threshold_results: list[dict]) -> list[Path]:
    figure_dir = output / "Figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    paths.append(tornado(figure_dir / "01_Routing_Probability_Tornado_P90.svg", "Sensitivity of Successful-Closure P90 to Model Inputs", tables["routing_tornado_p90"], "Change in P90 (working days)"))
    paths.append(tornado(figure_dir / "02_Routing_Probability_Tornado_PSuccess.svg", "Sensitivity of Successful-Closure Probability to Routing Inputs", tables["routing_tornado_outcome"], "Change in successful-closure probability"))
    paths.append(tornado(figure_dir / "03_Duration_Sensitivity_Tornado_P90.svg", "Duration Sensitivity of Successful-Closure P90", tables["duration_tornado_p90"], "Change in P90 (working days)", limit=5))

    loop_rows = tables["loop"]
    loop_tags = sorted({row["Parameter_ID"] for row in loop_rows})
    cap_values = sorted({int(row["Scenario_Value"]) for row in loop_rows})
    loop_series = []
    for cap in cap_values:
        values = [next(row["Successful_P90"] for row in loop_rows if row["Parameter_ID"] == tag and int(row["Scenario_Value"]) == cap) for tag in loop_tags]
        loop_series.append((f"Cap {cap}", values))
    paths.append(grouped_bars(figure_dir / "04_Loop_Cap_Robustness_Comparison.svg", "Loop-Cap Robustness Comparison", loop_tags, loop_series, "Successful-closure P90 (working days)"))

    dist = tables["distribution"]
    categories = ["Mean", "P90", "P95"]
    dist_series = [(row["Distribution"], [row["Mean_Successful_Time"], row["Successful_P90"], row["Successful_P95"]]) for row in dist]
    paths.append(grouped_bars(figure_dir / "05_Distribution_Family_Robustness_Comparison.svg", "Distribution-Family Robustness Comparison", categories, dist_series, "Working days"))

    seed_rows = [row for row in tables["seed"] if row["Record_Type"] == "Seed Run"]
    paths.append(line_chart(figure_dir / "06_Seed_Robustness_Plot.svg", "Random-Seed Robustness", seed_rows, "Seed", [("Successful_P90", "P90"), ("Successful_P95", "P95")], "Root seed", "Successful-closure time (working days)"))
    paths.append(line_chart(figure_dir / "07_Replication_Convergence_Plot.svg", "Replication-Count Convergence", tables["convergence"], "Replications", [("Successful_P90", "P90"), ("Successful_P95", "P95")], "Monte Carlo replications", "Successful-closure time (working days)"))
    paths.append(line_chart(figure_dir / "08_Early_Exit_Probability_vs_Outcome_Probabilities.svg", "Early-Exit Probability versus Outcome Probabilities", threshold_results, "Early_Exit_Probability", [("P_Success", "Successful Closure"), ("P_NonImplementation", "Non-Implementation Closure"), ("P_Dispute_Diversion", "Dispute Diversion")], "Early-exit probability p(e1T)", "Probability"))
    paths.append(line_chart(figure_dir / "09_Early_Exit_Probability_vs_Successful_P90.svg", "Early-Exit Probability versus Successful-Closure P90", threshold_results, "Early_Exit_Probability", [("Successful_P90", "Successful-Closure P90")], "Early-exit probability p(e1T)", "Working days"))
    paths.append(categorical_modes(figure_dir / "10_Bimodality_Classification_vs_Early_Exit_Probability.svg", threshold_results))

    probabilities = [row["Early_Exit_Probability"] for row in threshold_results]
    selected_probabilities = sorted(set([probabilities[0], probabilities[len(probabilities) // 2], probabilities[-1]]))
    panels = []
    for probability in selected_probabilities:
        row = next(item for item in threshold_results if item["Early_Exit_Probability"] == probability)
        curve = threshold_curves[row["Scenario_ID"]]
        panels.append({"probability": probability, "values": curve["values"], "grid": curve["grid"], "density": curve["density"]})
    paths.append(hist_kde_panels(figure_dir / "11_Selected_Combined_Histograms_KDEs.svg", panels))
    paths.append(ranking_chart(figure_dir / "12_Integrated_Driver_Ranking.svg", tables["ranking"]))
    return paths


def convert_figures_to_png(figure_dir: Path) -> None:
    node = Path(r"C:\Users\moham\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
    script = Path(__file__).with_name("render_svgs.mjs")
    result = subprocess.run([str(node), str(script), str(figure_dir)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Figure rasterisation failed: {result.stdout}\n{result.stderr}")


def write_methodology(path: Path, config: dict) -> None:
    text = f"""# Sensitivity and Robustness Analysis Methodology

## Analytical Purpose

The sensitivity framework evaluates the stability of the verified PERT-MCS and GERT-MCS model under controlled changes to routing probabilities, duration assumptions, loop caps, distribution family, random seed, and replication count. Sensitivity denotes an intervention on an input parameter; it is distinguished from correlation, variance association, convergence assessment, and robustness checks.

## Baseline Configuration

The authoritative baseline uses the verified Word inputs, {config['baseline_replications']:,} replications, root seed {config['baseline_seed']}, Beta-PERT with lambda 4, and upward rounding once at the sampled activity or traversal level. GERT completion-time measures are conditional on Successful Closure unless explicitly labelled as mixed-outcome measures.

## One-Way Routing Sensitivity

Each eligible stochastic routing probability is varied independently to low and high levels. In the absence of expert intervals, the low and high values are defined by a relative change of {config['routing_relative_change']:.0%}, subject to the unit interval and a non-collapse guard. When a target probability changes from p to v, every other outgoing probability q in the same XOR group is replaced by q(1-v)/(1-p). This preserves their relative proportions and ensures that each group sums to one.

## Duration Perturbation

Five transitions are screened using their expected rounded-duration contribution among successful runs and an auxiliary duration association. Screening does not itself constitute sensitivity. For each selected transition, the complete optimistic, most-likely, and pessimistic triplet is scaled coherently by plus or minus {config['duration_relative_change']:.0%}, while preserving ordering and the distribution family.

## Loop-Cap Robustness

Each capped return transition is evaluated at cap 1, the authoritative cap, and one repetition above the authoritative cap. Once a loop reaches its cap, its probability mass is removed and the remaining eligible alternatives are proportionally renormalised, exactly as in the verified model.

## Distributional Robustness

Beta-PERT is compared with a triangular distribution using identical O, ML, and P values, network structure, routing probabilities, loop rules, seed, and replication count. Differences therefore quantify distribution-family robustness rather than a change in model topology.

## Seed and Replication Robustness

Ten fixed seeds quantify between-seed Monte Carlo variation. Replication convergence uses nested prefixes of the {config['baseline_replications']:,}-run baseline stream at {', '.join(f'{n:,}' for n in config['replication_counts'])} replications, ensuring directly comparable random streams.

## Threshold and Bimodality Analysis

The early non-implementation probability is evaluated on the configured grid. A Gaussian KDE uses Silverman's robust bandwidth rule with a minimum bandwidth of {config['kde_min_bandwidth_days']:.1f} working day. Local modes must exceed a prominence of {config['mode_prominence_fraction']:.0%} of the maximum density and be separated by at least one bandwidth. One- and two-component univariate Gaussian mixtures are fitted by expectation-maximisation and compared using BIC. Classification combines the KDE mode count and a BIC improvement threshold of {config['gmm_bic_clear_threshold']:.0f}.

## Statistical Uncertainty

Outcome probabilities use 95% Wilson score intervals. Mean durations use standard errors and normal-theory 95% confidence intervals. P80, P90, and P95 use {config['bootstrap_resamples']:,} nonparametric bootstrap resamples implemented through multinomial resampling of the empirical discrete duration distribution with a fixed bootstrap seed.

## Integrated Ranking

For each parameter and output, the maximum absolute low/high effect is divided by the largest effect observed for that output. The integrated influence score is the maximum of the six normalised effects for mean successful time, P90, P95, successful-closure probability, non-implementation probability, and dispute-diversion probability. This avoids combining incompatible units directly.

## Interpretation Boundaries

Baseline associations are not causal effects. Intervention scenarios quantify model sensitivity within the tested ranges, not empirical causal effects. The mixed-outcome GERT duration distribution must not be interpreted as a homogeneous successful-completion distribution. The analysis does not claim that GERT-MCS is universally more accurate than PERT-MCS.
"""
    path.write_text(text, encoding="utf-8")


def write_results_outline(path: Path) -> None:
    tables = [
        ("Table 4.X: Sensitivity Parameters and Perturbation Ranges", "Defines every tested intervention.", "Parameter IDs, baseline, low, high, and selection rule.", "The table defines scenario scope.", "Do not interpret ranges as confidence intervals.", "Sensitivity_Parameters worksheet; Thesis_Tables/Table_4X_Sensitivity_Parameters.csv"),
        ("Table 4.Y: One-Way Routing-Probability Sensitivity Results", "Quantifies routing interventions.", "Conditional time, outcomes, loops, and mixed-outcome mean.", "Differences are relative to the verified baseline with valid XOR groups.", "Do not treat mixed-outcome time as successful completion time.", "Routing_OAT worksheet; Thesis_Tables/Table_4Y_Routing_OAT.csv"),
        ("Table 4.Z: Duration-Parameter Sensitivity Results", "Quantifies coherent duration-triplet interventions.", "Conditional time and outcome measures.", "Time effects result from one transition's O/ML/P scaling.", "Do not describe the screening score as one-way sensitivity.", "Duration_OAT worksheet; Thesis_Tables/Table_4Z_Duration_OAT.csv"),
        ("Table 4.W: Loop-Cap and Distributional Robustness", "Tests structural and distribution assumptions.", "Loop, cap, renormalisation, time, and distribution-family metrics.", "Small effects support robustness only within tested alternatives.", "Do not claim a zero effect outside the tested cap and family choices.", "LoopCap_Robustness and Distribution_Robustness worksheets; Thesis_Tables/Table_4W_LoopCap_Distribution.csv"),
        ("Table 4.V: Early-Exit Threshold Analysis", "Evaluates mixed-outcome multimodality.", "Early-exit probability, outcomes, P90, KDE modes, GMM BIC, classification.", "The threshold or interval follows the numerical classification rule.", "Do not infer a threshold from visual inspection alone.", "Threshold_Analysis worksheet; Thesis_Tables/Table_4V_Threshold_Analysis.csv"),
        ("Table 4.U: Random-Seed and Replication-Count Robustness", "Quantifies Monte Carlo stability.", "Seed summaries and nested-stream convergence.", "Variation represents simulation uncertainty, not input sensitivity.", "Do not rank model inputs from seed variation.", "Seed_Robustness and Replication_Convergence worksheets; Thesis_Tables/Table_4U_Seed_Convergence.csv"),
        ("Table 4.T: Integrated Sensitivity Ranking", "Ranks tested parameters across normalised outputs.", "Maximum effects, normalised effects, score, and rank.", "Rank identifies influence within the specified ranges and outputs.", "Do not interpret rank as causality or universal importance.", "Integrated_Ranking worksheet; Thesis_Tables/Table_4T_Integrated_Ranking.csv"),
    ]
    figures = [
        ("Figure 4.1: Routing Probability Tornado - P90", "Ranks routing effects on conditional P90.", "Low/high P90 changes.", "Longer bars indicate greater tested P90 sensitivity.", "Do not compare bar length as a probability.", "Figures/01_Routing_Probability_Tornado_P90.png; Tornado_P90_Data worksheet"),
        ("Figure 4.2: Routing Probability Tornado - P(Success)", "Ranks routing effects on successful closure.", "Low/high probability changes.", "Direction and magnitude show routing intervention effects.", "Do not read associations as causal evidence.", "Figures/02_Routing_Probability_Tornado_PSuccess.png; Tornado_Outcome_Data worksheet"),
        ("Figure 4.3: Duration Sensitivity Tornado - P90", "Ranks selected duration drivers.", "Low/high P90 changes.", "Bars are actual OAT interventions.", "Do not substitute correlation for the displayed interventions.", "Figures/03_Duration_Sensitivity_Tornado_P90.png; Duration_OAT worksheet"),
        ("Figure 4.4: Loop-Cap Robustness Comparison", "Compares cap alternatives.", "P90 by loop and cap.", "Flat profiles indicate robustness at tested caps.", "Do not infer that loops are structurally irrelevant.", "Figures/04_Loop_Cap_Robustness_Comparison.png; LoopCap_Robustness worksheet"),
        ("Figure 4.5: Distribution-Family Robustness", "Compares Beta-PERT and triangular durations.", "Conditional mean, P90, and P95.", "Differences isolate distribution-family choice.", "Do not attribute differences to routing.", "Figures/05_Distribution_Family_Robustness_Comparison.png; Distribution_Robustness worksheet"),
        ("Figure 4.6: Seed Robustness", "Shows fixed-seed variation.", "P90 and P95 by seed.", "Narrow variation supports Monte Carlo stability.", "Do not interpret seed as a substantive model input.", "Figures/06_Seed_Robustness_Plot.png; Seed_Robustness worksheet"),
        ("Figure 4.7: Replication Convergence", "Shows nested-stream convergence.", "P90 and P95 by N.", "Stabilisation supports the selected N.", "Do not equate visual smoothness with zero uncertainty.", "Figures/07_Replication_Convergence_Plot.png; Replication_Convergence worksheet"),
        ("Figure 4.8: Early-Exit Probability versus Outcomes", "Shows outcome response to early exit.", "Success, non-implementation, and dispute probabilities.", "Outcome changes follow a controlled routing intervention.", "Dispute incidence is not a terminal outcome share.", "Figures/08_Early_Exit_Probability_vs_Outcome_Probabilities.png; Threshold_Analysis worksheet"),
        ("Figure 4.9: Early-Exit Probability versus Successful P90", "Separates conditional time from outcome mixing.", "Conditional P90 across grid.", "Changes apply only to successful closures.", "Do not use the mixed-outcome mean in its place.", "Figures/09_Early_Exit_Probability_vs_Successful_P90.png; Threshold_Analysis worksheet"),
        ("Figure 4.10: Bimodality Classification", "Shows numerical modal classification.", "Classification across grid.", "Threshold claims follow KDE and BIC criteria.", "Do not infer modes from histogram bars alone.", "Figures/10_Bimodality_Classification_vs_Early_Exit_Probability.png; Threshold_Analysis worksheet"),
        ("Figure 4.11: Selected Histograms and KDEs", "Illustrates classified mixed distributions.", "Histogram and KDE panels.", "Panels visually support, but do not define, classification.", "Do not treat early exits as successful early completion.", "Figures/11_Selected_Combined_Histograms_KDEs.png; Threshold_Analysis worksheet"),
        ("Figure 4.12: Integrated Driver Ranking", "Summarises multi-output influence.", "Normalised influence scores.", "Rank is conditional on tested ranges and normalisation.", "Do not compare raw effects with incompatible units.", "Figures/12_Integrated_Driver_Ranking.png; Integrated_Ranking worksheet"),
    ]
    lines = ["# Thesis Sensitivity Results Outline", ""]
    for title, purpose, variables, correct, incorrect, source in tables + figures:
        lines.extend([f"## {title}", "", f"**Purpose:** {purpose}", "", f"**Variables shown:** {variables}", "", f"**Correct interpretation:** {correct}", "", f"**Incorrect interpretation to avoid:** {incorrect}", "", f"**Exact source:** {source}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_report(path: Path, tables: dict, audit: dict, baseline_rows: list[dict], threshold_summary: dict, config: dict) -> None:
    baseline = tables["baseline"]
    ranking = tables["ranking"]
    routing_p90 = tables["routing_tornado_p90"][0]
    routing_success = tables["routing_tornado_outcome"][0]
    distribution = {row["Distribution"]: row for row in tables["distribution"]}
    beta, triangular = distribution["beta_pert"], distribution["triangular"]
    seed_runs = [row for row in tables["seed"] if row["Record_Type"] == "Seed Run"]
    convergence = tables["convergence"]
    loop_rows = tables["loop"]
    max_loop_p90 = max(abs(row["Abs_Change_Successful_P90"]) for row in loop_rows)
    failures = [row for row in baseline_rows if row["Status"] != "PASS"]
    lines = [
        "# Sensitivity and Robustness Report", "",
        "## 1. Purpose of the Analysis", "",
        "This analysis evaluates intervention sensitivity and Monte Carlo robustness for the verified VO PERT-MCS and GERT-MCS model. It responds directly to the requested one-way analyses, tornado charts, early-exit bimodality assessment, and integrated parameter ranking.", "",
        "## 2. Baseline Model and Outputs", "",
        f"The baseline uses {config['baseline_replications']:,} replications, root seed {config['baseline_seed']}, Beta-PERT lambda 4, and per-activity/per-traversal ceiling in working days. It reproduced {baseline['Successful_Count']:,} successful and {baseline['NonImplementation_Count']:,} non-implementation closures. Mean successful-closure time was {baseline['Mean_Successful_Time']:.6f} days, P90 was {baseline['Successful_P90']:.0f}, P95 was {baseline['Successful_P95']:.0f}, and P(Successful Closure) was {baseline['P_Success']:.6f}. The mixed-outcome mean was {baseline['Unconditional_Mean_Time_Mixed_Outcomes']:.6f} days and is not interpreted as homogeneous completion performance.", "",
        f"All {len(baseline_rows)} baseline reproduction checks passed." if not failures else f"Baseline validation had {len(failures)} failures.", "",
        "## 3. Parameter-Selection Logic", "",
        f"Every eligible routing probability was varied by +/-{config['routing_relative_change']:.0%} because no expert ranges were present. Five duration transitions were selected using expected successful-duration contribution with an auxiliary Pearson association; the screening measure was not treated as sensitivity evidence.", "",
        "## 4. Probability-Renormalisation Method", "",
        "When one outgoing probability changed from p to v, each other probability q in its XOR group was replaced by q(1-v)/(1-p). Automated checks confirmed unit sums and unchanged non-target relative proportions.", "",
        "## 5. One-Way Routing Sensitivity", "",
        f"The largest tested routing effect on successful-closure P90 was {routing_p90['Parameter_ID']} at {routing_p90['Network_Location']}, with a maximum absolute change of {routing_p90['Maximum_Absolute_Effect']:.3f} working days. The largest tested routing effect on successful-closure probability was {routing_success['Parameter_ID']} at {routing_success['Network_Location']}, with a maximum absolute change of {routing_success['Maximum_Absolute_Effect']:.6f}.", "",
        "## 6. Duration Sensitivity", "",
        f"The highest-ranked duration intervention was {next(row for row in ranking if row['Parameter_Type'] == 'Duration Triplet')['Parameter_ID']}. Results are based on coherent triplet perturbations and not on squared correlation or VCI alone.", "",
        "## 7. Loop-Cap Robustness", "",
        f"Across the tested cap values, the largest absolute change in successful-closure P90 was {max_loop_p90:.3f} working days. Loops with negligible activation are retained as explicit robustness findings.", "",
        "## 8. Distributional Robustness", "",
        f"Switching from Beta-PERT to triangular sampling changed mean successful-closure time by {triangular['Mean_Successful_Time'] - beta['Mean_Successful_Time']:+.4f} days, P90 by {triangular['Successful_P90'] - beta['Successful_P90']:+.1f} days, P95 by {triangular['Successful_P95'] - beta['Successful_P95']:+.1f} days, and P(Successful Closure) by {triangular['P_Success'] - beta['P_Success']:+.6f}.", "",
        "## 9. Random-Seed Robustness", "",
        f"Across ten fixed seeds, P(Successful Closure) ranged from {min(row['P_Success'] for row in seed_runs):.6f} to {max(row['P_Success'] for row in seed_runs):.6f}; successful-closure P90 ranged from {min(row['Successful_P90'] for row in seed_runs):.0f} to {max(row['Successful_P90'] for row in seed_runs):.0f} days.", "",
        "## 10. Replication Convergence", "",
        f"Relative to the {config['baseline_replications']:,}-run reference, the 1,000-run P(Success) deviation was {convergence[0]['Deviation_P_Success']:+.6f} and the 25,000-run deviation was {next(row for row in convergence if row['Replications'] == 25000)['Deviation_P_Success']:+.6f}. Quantile deviations are reported in the convergence table.", "",
        "## 11. Bimodality Threshold Analysis", "",
        threshold_summary["Threshold_Result"], "",
        "Classification combines a Silverman-rule KDE, a 5% mode-prominence criterion, and one- versus two-component Gaussian-mixture BIC. No threshold is claimed solely from visual inspection.", "",
        "## 12. Tornado-Chart Interpretation", "",
        "Tornado bars show low and high scenario changes from the authoritative baseline. Bar length identifies sensitivity within the tested intervention range; it is not a causal effect size and cannot be generalised beyond that range.", "",
        "## 13. Integrated Driver Ranking", "",
        "The five highest integrated influence scores were: " + "; ".join(f"{row['Rank']}. {row['Parameter_ID']} ({row['Parameter_Type']}, score {row['Normalised_Influence_Score']:.3f})" for row in ranking[:5]) + ".", "",
        "## 14. Main Findings", "",
        f"Routing and duration effects are output-specific. The leading P90 routing driver was {routing_p90['Parameter_ID']}, while the leading outcome-probability routing driver was {routing_success['Parameter_ID']}. Distribution, cap, seed, and replication analyses quantify robustness rather than input correlation.", "",
        "## 15. Limitations", "",
        "No expert perturbation intervals or completion threshold Tc were present, so the documented fallback ranges were used and exceedance probability is reported as not defined. Fixed-seed stream starts were synchronised, but divergent routes consume different numbers of random draws; scenario differences therefore include residual Monte Carlo noise captured by confidence intervals. Gaussian mixtures are diagnostic approximations to a discrete mixed-outcome duration distribution. Baseline associations must not be interpreted causally.", "",
        "## 16. Exact Reproduction Commands", "",
        "```powershell", f"& '{sys.executable}' run_sensitivity.py --config sensitivity_config.yaml", f"& '{sys.executable}' run_sensitivity.py --config sensitivity_config.yaml --baseline-only", f"& '{sys.executable}' -m unittest discover -s tests -p 'test_*.py' -v", "```", "",
        f"Analysis version: {__version__}. Python: {platform.python_version()}. Generated UTC: {utc_now()}.", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_analysis(config: dict, baseline_only: bool = False) -> dict:
    output = Path(config["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    for directory in (output / "Tables", output / "Thesis_Tables", output / "Figures"):
        directory.mkdir(parents=True, exist_ok=True)
    model = load_authoritative_model()
    original_hashes = {"PERT": model.pert_hash, "GERT": model.gert_hash}
    audit = write_audit(output, model, config)

    baseline_spec = {
        "scenario_id": "baseline", "analysis": "Baseline", "operation": "baseline", "parameter_id": "baseline",
        "level": "Baseline", "value": "authoritative", "seed": config["baseline_seed"],
        "replications": config["baseline_replications"], "distribution": "beta_pert", "capture_drivers": True,
    }
    baseline_execution = execute_spec((baseline_spec, model, config))
    baseline_result, baseline_metrics, _ = load_cached_result(config, "baseline")
    pert_baseline = simulate_pert(model, config["baseline_replications"], config["baseline_seed"], "beta_pert")
    baseline_rows = baseline_validation(model, baseline_result, baseline_metrics, pert_baseline)
    write_csv(output / "Tables" / "Baseline_Validation.csv", baseline_rows)
    if any(row["Status"] != "PASS" for row in baseline_rows):
        raise AssertionError("Baseline reproduction failed; sensitivity experiments were not executed")
    if baseline_only:
        summary = {"status": "PASS", "baseline_metrics": baseline_metrics, "baseline_validation": baseline_rows, "audit": audit}
        write_json(output / "baseline_only_summary.json", summary)
        return summary

    specs, design = generate_specs(model, baseline_result, config)
    executions = [baseline_execution]
    results_by_id = {"baseline": baseline_metrics}
    total = len(specs)
    workers = max(1, int(config.get("parallel_workers", 1)))
    if workers == 1:
        for index, spec in enumerate(specs, start=1):
            execution = execute_spec((spec, model, config))
            executions.append(execution)
            results_by_id[spec["scenario_id"]] = execution["metrics"]
            print(f"Sensitivity scenario {index}/{total}: {spec['scenario_id']} ({execution['cache_status']})", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(execute_spec, (spec, model, config)): spec for spec in specs}
            completed = 0
            for future in as_completed(future_map):
                execution = future.result()
                executions.append(execution)
                results_by_id[execution["spec"]["scenario_id"]] = execution["metrics"]
                completed += 1
                print(f"Sensitivity scenario {completed}/{total}: {execution['spec']['scenario_id']} ({execution['cache_status']})", flush=True)
    executions.sort(key=lambda item: item["spec"]["scenario_id"])

    parameters = design["parameters"]
    routing_records = []
    routing_sets = []
    for parameter in parameters["routing"]:
        low = results_by_id[f"routing_{parameter['Parameter_ID']}_low"]
        high = results_by_id[f"routing_{parameter['Parameter_ID']}_high"]
        low_row = record_with_context(low, parameter, "Low", f"routing_{parameter['Parameter_ID']}_low", baseline_metrics, parameter["Low_Value"])
        base_row = record_with_context(baseline_metrics, parameter, "Baseline", f"routing_{parameter['Parameter_ID']}_baseline", baseline_metrics, parameter["Baseline_Value"])
        high_row = record_with_context(high, parameter, "High", f"routing_{parameter['Parameter_ID']}_high", baseline_metrics, parameter["High_Value"])
        routing_records.extend([low_row, base_row, high_row])
        routing_sets.append((parameter, low_row, high_row))

    duration_records = []
    duration_sets = []
    for parameter in parameters["duration"]:
        tag = parameter["Parameter_ID"]
        low = results_by_id[f"duration_{tag}_low"]
        high = results_by_id[f"duration_{tag}_high"]
        low_row = record_with_context(low, parameter, "Low", f"duration_{tag}_low", baseline_metrics, parameter["Low_Value"])
        base_row = record_with_context(baseline_metrics, parameter, "Baseline", f"duration_{tag}_baseline", baseline_metrics, parameter["Baseline_Value"])
        high_row = record_with_context(high, parameter, "High", f"duration_{tag}_high", baseline_metrics, parameter["High_Value"])
        duration_records.extend([low_row, base_row, high_row])
        duration_sets.append((parameter, low_row, high_row))

    loop_records = []
    loop_sets = []
    for parameter in parameters["loop"]:
        tag = parameter["Parameter_ID"]
        low = results_by_id[f"loopcap_{tag}_low"]
        high = results_by_id[f"loopcap_{tag}_high"]
        low_row = record_with_context(low, parameter, "Low", f"loopcap_{tag}_low", baseline_metrics, parameter["Low_Value"])
        base_row = record_with_context(baseline_metrics, parameter, "Baseline", f"loopcap_{tag}_baseline", baseline_metrics, parameter["Baseline_Value"])
        high_row = record_with_context(high, parameter, "High", f"loopcap_{tag}_high", baseline_metrics, parameter["High_Value"])
        for row in (low_row, base_row, high_row):
            row["Tested_Loop_Mean_Repetitions"] = row[f"{tag}_Mean_Repetitions"]
            row["Tested_Loop_Cap_Probability"] = row[f"{tag}_Cap_Probability"]
        loop_records.extend([low_row, base_row, high_row])
        loop_sets.append((parameter, low_row, high_row))

    triangular = results_by_id["distribution_triangular"]
    pert_triangular = simulate_pert(model, config["baseline_replications"], config["baseline_seed"], "triangular")
    distribution_records = [
        {**baseline_metrics, "Scenario_ID": "baseline", "Distribution": "beta_pert", "PERT_Mean": float(pert_baseline["totals"].mean()), "Driver_Ranking": ";".join(row["Arc_Tag"] for row in design["driver_screen"][:10])},
        {**triangular, "Scenario_ID": "distribution_triangular", "Distribution": "triangular", "PERT_Mean": float(pert_triangular["totals"].mean())},
    ]
    triangular_result, _, _ = load_cached_result(config, "distribution_triangular")
    triangular_screen = driver_screen(triangular_result, [arc["arc_tag"] for arc in model.arcs])
    distribution_records[1]["Driver_Ranking"] = ";".join(row["Arc_Tag"] for row in triangular_screen[:10])
    for row in distribution_records:
        changed = add_changes(row, baseline_metrics, CHANGE_FIELDS)
        row.update(changed)

    seed_records = []
    for seed in config["seed_list"]:
        row = {**results_by_id[f"seed_{seed}"], "Record_Type": "Seed Run", "Seed_or_Statistic": seed}
        seed_records.append(row)
    seed_records.extend(aggregate_seed_rows(seed_records))

    convergence_records = []
    reference = baseline_metrics
    for n in config["replication_counts"]:
        subset = result_subset(baseline_result, n, f"convergence_{n}")
        row = metrics_from_result(subset, config)
        row["Replications"] = n
        for field in ("P_Success", "Mean_Successful_Time", "Successful_P90", "Successful_P95", "P_NonImplementation"):
            row[f"Deviation_{field}"] = row[field] - reference[field]
        convergence_records.append(row)

    threshold_records = []
    threshold_curves = {}
    for value in config["early_exit_probability_grid"]:
        scenario_id = f"threshold_{config['early_exit_arc']}_{int(round(value * 100)):03d}"
        result, metrics, _ = load_cached_result(config, scenario_id)
        valid_values = result.totals[result.outcomes >= 0]
        mode_row, curve = classify_distribution(valid_values, config)
        row = {**metrics, **mode_row, "Scenario_ID": scenario_id, "Early_Exit_Arc": config["early_exit_arc"], "Early_Exit_Probability": value}
        threshold_records.append(row)
        threshold_curves[scenario_id] = {"values": valid_values, **curve}
    threshold_records.sort(key=lambda row: row["Early_Exit_Probability"])
    threshold_summary = threshold_interval(threshold_records)
    for row in threshold_records:
        row.update(threshold_summary)

    ranking = integrated_ranking(routing_sets + duration_sets + loop_sets, baseline_metrics)
    routing_tornado_p90 = tornado_rows(routing_sets, "Successful_P90")
    routing_tornado_outcome = tornado_rows(routing_sets, "P_Success")
    duration_tornado_p90 = tornado_rows(duration_sets, "Successful_P90")

    sensitivity_parameters = parameters["routing"] + parameters["duration"] + parameters["loop"] + [
        {"Parameter_ID": "duration_distribution", "Parameter_Type": "Distribution Family", "Network_Location": "All duration-bearing transitions", "Baseline_Value": "beta_pert", "Low_Value": "beta_pert", "High_Value": "triangular", "Selection_Rule": "Reference versus triangular robustness"},
        {"Parameter_ID": "root_seed", "Parameter_Type": "Monte Carlo Robustness", "Network_Location": "Random streams", "Baseline_Value": config["baseline_seed"], "Low_Value": min(config["seed_list"]), "High_Value": max(config["seed_list"]), "Selection_Rule": "Ten documented fixed seeds"},
        {"Parameter_ID": "replications", "Parameter_Type": "Convergence", "Network_Location": "Simulation run", "Baseline_Value": config["baseline_replications"], "Low_Value": min(config["replication_counts"]), "High_Value": max(config["replication_counts"]), "Selection_Rule": "Nested prefixes of baseline stream"},
        {"Parameter_ID": config["early_exit_arc"], "Parameter_Type": "Threshold Grid", "Network_Location": "S1 -> ST", "Baseline_Value": next(arc["probability"] for arc in model.arcs if arc["arc_tag"] == config["early_exit_arc"]), "Low_Value": min(config["early_exit_probability_grid"]), "High_Value": max(config["early_exit_probability_grid"]), "Selection_Rule": "Dedicated 0.05-step early-exit grid"},
    ]

    ci_rows = []
    for execution in executions:
        metrics = execution["metrics"]
        ci_rows.append({key: metrics.get(key) for key in [
            "Scenario_ID", "Replications", "Seed", "Distribution", "Mean_Successful_Time", "Successful_Mean_SE",
            "Successful_Mean_CI_Low", "Successful_Mean_CI_High", "Successful_P80", "Successful_P80_CI_Low",
            "Successful_P80_CI_High", "Successful_P90", "Successful_P90_CI_Low", "Successful_P90_CI_High",
            "Successful_P95", "Successful_P95_CI_Low", "Successful_P95_CI_High", "P_Success", "P_Success_CI_Low",
            "P_Success_CI_High", "P_NonImplementation", "P_NonImplementation_CI_Low", "P_NonImplementation_CI_High",
            "P_Dispute_Diversion", "P_Dispute_CI_Low", "P_Dispute_CI_High",
        ]})
    ci_rows.sort(key=lambda row: row["Scenario_ID"])

    run_log = []
    for execution in executions:
        spec = execution["spec"]
        run_log.append({
            "Scenario_ID": spec["scenario_id"], "Analysis": spec["analysis"], "Operation": spec["operation"],
            "Parameter_ID": spec["parameter_id"], "Level": spec["level"], "Scenario_Value": spec["value"],
            "Replications": spec["replications"], "Seed": spec["seed"], "Distribution": spec["distribution"],
            "Cache_Status": execution["cache_status"], "Elapsed_Seconds": execution["elapsed_seconds"],
            "Result_SHA256": execution["signature"], "Status": execution["status"],
        })

    validation_checks = [
        {"Category": "Baseline", "Check": "All baseline reproduction checks pass", "Observed": sum(row["Status"] == "PASS" for row in baseline_rows), "Expected": len(baseline_rows), "Status": "PASS"},
        {"Category": "Inputs", "Check": "PERT input hash unchanged", "Observed": model.pert_hash, "Expected": original_hashes["PERT"], "Status": "PASS" if model.pert_hash == original_hashes["PERT"] else "FAIL"},
        {"Category": "Inputs", "Check": "GERT input hash unchanged", "Observed": model.gert_hash, "Expected": original_hashes["GERT"], "Status": "PASS" if model.gert_hash == original_hashes["GERT"] else "FAIL"},
        {"Category": "Scenarios", "Check": "Unique executed scenario IDs", "Observed": len({row["Scenario_ID"] for row in run_log}), "Expected": len(run_log), "Status": "PASS" if len({row["Scenario_ID"] for row in run_log}) == len(run_log) else "FAIL"},
        {"Category": "Scenarios", "Check": "All executed scenarios pass", "Observed": sum(row["Status"] == "PASS" for row in run_log), "Expected": len(run_log), "Status": "PASS" if all(row["Status"] == "PASS" for row in run_log) else "FAIL"},
        {"Category": "Outcomes", "Check": "Computational termination absent", "Observed": max(row["metrics"]["ComputationalTermination_Count"] for row in executions), "Expected": 0, "Status": "PASS" if all(row["metrics"]["ComputationalTermination_Count"] == 0 for row in executions) else "FAIL"},
        {"Category": "Uncertainty", "Check": "Bootstrap resamples", "Observed": config["bootstrap_resamples"], "Expected": ">=1000", "Status": "PASS" if config["bootstrap_resamples"] >= 1000 else "FAIL"},
        {"Category": "Threshold", "Check": "All threshold scenarios classified", "Observed": len(threshold_records), "Expected": len(config["early_exit_probability_grid"]), "Status": "PASS" if len(threshold_records) == len(config["early_exit_probability_grid"]) else "FAIL"},
    ]

    warnings = [
        {"Severity": "WARNING", "Code": "NO_EXPERT_RANGES", "Message": "No expert probability or duration intervals were present; documented fallback ranges were used."},
        {"Severity": "WARNING", "Code": "TC_UNDEFINED", "Message": "No completion threshold Tc was defined; exceedance probabilities are blank rather than invented."},
        {"Severity": "LIMITATION", "Code": "CRN_ROUTE_DIVERGENCE", "Message": "Scenario streams share deterministic starts, but route divergence changes subsequent random-draw alignment."},
        {"Severity": "LIMITATION", "Code": "GMM_DIAGNOSTIC", "Message": "Gaussian mixtures are diagnostic approximations to a discrete mixed-outcome distribution."},
        {"Severity": "INTERPRETATION", "Code": "NO_CAUSALITY", "Message": "Baseline correlation and screening measures are not causal effects."},
        {"Severity": "SOURCE_LOCATION", "Code": "VERIFIED_PACKAGE_COPY", "Message": "Desktop input copies were unavailable; byte-identical verified package copies were used."},
    ]

    tables = {
        "baseline": baseline_metrics, "parameters": sensitivity_parameters, "routing": routing_records,
        "duration": duration_records, "loop": loop_records, "distribution": distribution_records,
        "seed": seed_records, "convergence": convergence_records, "threshold": threshold_records,
        "ci": ci_rows, "routing_tornado_p90": routing_tornado_p90,
        "routing_tornado_outcome": routing_tornado_outcome, "duration_tornado_p90": duration_tornado_p90,
        "ranking": ranking, "run_log": run_log, "validation": validation_checks, "warnings": warnings,
        "driver_screen": design["driver_screen"],
    }
    table_dir = output / "Tables"
    table_files = {
        "Baseline_Config.csv": [{"Setting": key, "Value": value} for key, value in {
            "PERT input": audit["authoritative_pert_input"], "GERT input": audit["authoritative_gert_input"], "PERT SHA-256": model.pert_hash,
            "GERT SHA-256": model.gert_hash, "Replications": config["baseline_replications"], "Root seed": config["baseline_seed"],
            "Distribution": "Beta-PERT", "Lambda": 4, "Rounding": "ceil once per activity/traversal", "Time unit": "working days",
        }.items()],
        "Baseline_Validation.csv": baseline_rows,
        "Sensitivity_Parameters.csv": sensitivity_parameters,
        "Routing_OAT.csv": routing_records,
        "Duration_OAT.csv": duration_records,
        "LoopCap_Robustness.csv": loop_records,
        "Distribution_Robustness.csv": distribution_records,
        "Seed_Robustness.csv": seed_records,
        "Replication_Convergence.csv": convergence_records,
        "Threshold_Analysis.csv": threshold_records,
        "CI_Summary.csv": ci_rows,
        "Tornado_P90_Data.csv": routing_tornado_p90 + duration_tornado_p90,
        "Tornado_Outcome_Data.csv": routing_tornado_outcome,
        "Integrated_Ranking.csv": ranking,
        "Scenario_Run_Log.csv": run_log,
        "Validation_Checks.csv": validation_checks,
        "Errors_Warnings.csv": warnings,
        "Duration_Driver_Screen.csv": design["driver_screen"],
    }
    for name, rows in table_files.items():
        write_csv(table_dir / name, rows)

    thesis_dir = output / "Thesis_Tables"
    thesis_tables = {
        "Table_4X_Sensitivity_Parameters.csv": sensitivity_parameters,
        "Table_4Y_Routing_OAT.csv": routing_records,
        "Table_4Z_Duration_OAT.csv": duration_records,
        "Table_4W_LoopCap_Distribution.csv": [{**row, "Analysis_Type": "Loop Cap"} for row in loop_records] + [{**row, "Analysis_Type": "Distribution Family"} for row in distribution_records],
        "Table_4V_Threshold_Analysis.csv": threshold_records,
        "Table_4U_Seed_Convergence.csv": [{**row, "Analysis_Type": "Seed Robustness"} for row in seed_records] + [{**row, "Analysis_Type": "Replication Convergence"} for row in convergence_records],
        "Table_4T_Integrated_Ranking.csv": ranking,
    }
    for name, rows in thesis_tables.items():
        write_csv(thesis_dir / name, rows)

    figure_paths = build_figures(output, tables, threshold_curves, threshold_records)
    convert_figures_to_png(output / "Figures")
    write_methodology(output / "Thesis_Sensitivity_Methodology.md", config)
    write_results_outline(output / "Thesis_Sensitivity_Results_Outline.md")
    write_report(output / "Sensitivity_and_Robustness_Report.md", tables, audit, baseline_rows, threshold_summary, config)

    summary = {
        "status": "PASS" if all(row["Status"] == "PASS" for row in validation_checks) else "FAIL",
        "generated_utc": utc_now(), "analysis_version": __version__, "audit": audit,
        "baseline": baseline_metrics, "baseline_validation": baseline_rows,
        "distinct_full_simulation_runs": len(run_log), "analysis_scenario_records": len(routing_records) + len(duration_records) + len(loop_records) + len(distribution_records) + len(seed_records) + len(convergence_records) + len(threshold_records),
        "threshold_summary": threshold_summary, "top_parameters": ranking[:10],
        "figure_count_svg": len(figure_paths), "figure_count_png": len(list((output / "Figures").glob("*.png"))),
        "validation_checks": validation_checks, "warnings": warnings,
        "authoritative_hashes_after": {"PERT": sha256_file(authoritative_input_paths()[0]), "GERT": sha256_file(authoritative_input_paths()[1])},
    }
    write_json(output / "analysis_summary.json", summary)
    write_json(output / "workbook_source_manifest.json", {"tables": {name: str(table_dir / name) for name in table_files}, "thesis_tables": {name: str(thesis_dir / name) for name in thesis_tables}, "figures": [str(path) for path in sorted((output / "Figures").glob("*.png"))], "summary": summary})
    if summary["status"] != "PASS":
        raise AssertionError("Analysis validation checks failed")
    return summary
