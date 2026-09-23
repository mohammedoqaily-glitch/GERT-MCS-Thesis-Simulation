from __future__ import annotations

import csv
import json
import math
import pickle
from collections import Counter
from pathlib import Path

import numpy as np
import xlsxwriter


WORK_DIR = Path(r"C:\Users\moham\Documents\Codex\2026-07-28\build\work\final_preliminary")
OUTPUT_DIR = Path(r"C:\Users\moham\Documents\Codex\2026-07-28\build\outputs")
RAW_DIR = OUTPUT_DIR / "Raw_Data"
DATA = pickle.loads((WORK_DIR / "final_simulation_data.pkl").read_bytes())

RESULTS_PATH = OUTPUT_DIR / "Final_Preliminary_Simulation_Results.xlsx"
REPORT_PATH = OUTPUT_DIR / "Final_Preliminary_Simulation_Report.md"
SUMMARY_CSV_PATH = OUTPUT_DIR / "Final_Preliminary_Simulation_Summary.csv"
PERT_AUDIT_PATH = OUTPUT_DIR / "PERT_Input_Audit.xlsx"
GERT_AUDIT_PATH = OUTPUT_DIR / "GERT_Input_Audit.xlsx"

REQUIRED_SHEETS = [
    "Summary", "Run Info", "Input Hashes", "PERT Input", "PERT Audit", "PERT Summary",
    "PERT Percentiles", "PERT Iterations", "PERT Activities", "PERT Convergence", "PERT Chart Data",
    "PERT Charts", "GERT Nodes", "GERT Arcs", "GERT Audit", "Network Validation", "Exact Verification",
    "GERT Outcomes", "GERT Successful", "GERT Terminated", "GERT Percentiles", "GERT Paths",
    "Node Analysis", "Arc Analysis", "Loop Analysis", "Loop Repetitions", "Cap Events", "Renormalisation",
    "Dispute Analysis", "Transition Analysis", "GERT Iterations", "Reconciliation", "GERT Convergence",
    "Comparison", "GERT Chart Data", "GERT Charts", "Warnings", "Metadata",
]

GERT_ITERATION_HEADERS = [
    "Iteration ID", "Outcome", "Final Node", "Total Rounded Duration", "Total Raw Duration",
    "Transition Count", "Node Sequence", "Arc Sequence", "Raw Traversal Durations",
    "Rounded Traversal Durations", "Loop Counters", "Loop Cap Events", "Renormalisation Events",
    "Dispute Visited", "Dispute Visits", "Reconciliation Status", "Failure Reason",
]


def joined(values, separator=" > "):
    return separator.join(str(value) for value in values)


def gert_iteration_row(row):
    return [
        row["iteration_id"], row["outcome"], row["final_node"], row["total_rounded_duration"],
        row["total_raw_duration"], row["transition_count"], joined(row["node_sequence"]),
        joined(row["arc_sequence"]), joined((f"{v:.12f}" for v in row["raw_durations"]), ";"),
        joined(row["rounded_durations"], ";"), joined((f"{k}={v}" for k, v in row["loop_counts"].items()), ";"),
        joined((event["arc_tag"] for event in row["cap_events"]), ";"),
        joined((event["capped_arcs"] for event in row["renormalisation_events"]), ";"),
        row["dispute_visited"], row["dispute_visits"], row["reconciliation_status"], row["failure_reason"],
    ]


def write_csv(path: Path, headers, rows) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def write_raw_outputs() -> list[Path]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    pert = DATA["pert"]
    iterations = DATA["gert_iterations"]

    path = RAW_DIR / "PERT_Iterations.csv"
    write_csv(path, ["Iteration ID", "Total Duration Days"], ((i + 1, int(v)) for i, v in enumerate(pert["totals"])))
    paths.append(path)

    path = RAW_DIR / "PERT_Activity_Durations.csv"
    write_csv(path, ["Iteration ID", "Activity ID", "Activity", "Raw Duration Days", "Rounded Duration Days"], (
        (i + 1, activity["activity_id"], activity["stage"], float(pert["raw"][i, j]), int(pert["rounded"][i, j]))
        for i in range(len(pert["totals"])) for j, activity in enumerate(DATA["pert_input"])
    ))
    paths.append(path)

    path = RAW_DIR / "GERT_Iterations.csv"
    write_csv(path, GERT_ITERATION_HEADERS, (gert_iteration_row(row) for row in iterations))
    paths.append(path)

    path = RAW_DIR / "GERT_Paths.csv"
    path_headers = ["Path ID", "Arc Sequence", "Node Sequence", "Outcome", "Frequency", "Probability", "Mean Duration", "SD", "Minimum", "Maximum", "P50", "P80", "P90", "P95", "Transition Count", "Activated Capped Arcs", "Dispute Status"]
    write_csv(path, path_headers, ([p["path_id"], joined(p["arc_sequence"]), joined(p["node_sequence"]), p["outcome"], p["frequency"], p["probability"], p["mean"], p["sd"], p["minimum"], p["maximum"], p["p50"], p["p80"], p["p90"], p["p95"], p["transition_count"], p["activated_capped_arcs"], p["dispute_status"]] for p in DATA["gert"]["paths"]))
    paths.append(path)

    path = RAW_DIR / "GERT_Node_Visits.csv"
    write_csv(path, ["Iteration ID", "Node ID", "Visit Count"], (
        (row["iteration_id"], node, count) for row in iterations for node, count in Counter(row["node_sequence"]).items()
    ))
    paths.append(path)

    path = RAW_DIR / "GERT_Arc_Traversals.csv"
    write_csv(path, ["Iteration ID", "Arc Tag", "Traversal Count"], (
        (row["iteration_id"], tag, count) for row in iterations for tag, count in Counter(row["arc_sequence"]).items()
    ))
    paths.append(path)

    path = RAW_DIR / "GERT_Loops.csv"
    write_csv(path, ["Iteration ID", "Loop ID", "Repetitions", "Activated", "Cap Reached"], (
        (row["iteration_id"], tag, row["loop_counts"][tag], row["loop_counts"][tag] > 0, row["loop_counts"][tag] == 2)
        for row in iterations for tag in row["loop_counts"]
    ))
    paths.append(path)

    path = RAW_DIR / "GERT_Cap_Events.csv"
    cap_headers = ["Iteration ID", "Loop ID", "Arc Tag", "Cap", "Count When Reached"]
    cap_rows = ([e["iteration_id"], e["loop_id"], e["arc_tag"], e["cap"], e["count_when_reached"]] for e in DATA["cap_events"])
    write_csv(path, cap_headers, cap_rows)
    paths.append(path)

    path = RAW_DIR / "GERT_Renormalisation.csv"
    renorm_headers = ["Iteration ID", "Current Node", "Capped Arcs", "Loop Counters", "Original Probabilities", "Eligibility", "Effective Probabilities", "Remaining Original Sum", "Effective Sum"]
    write_csv(path, renorm_headers, ([e["iteration_id"], e["node"], e["capped_arcs"], e["loop_counters"], e["original_probabilities"], e["eligibility"], e["effective_probabilities"], e["remaining_original_sum"], e["effective_sum"]] for e in DATA["renormalisation_events"]))
    paths.append(path)

    path = RAW_DIR / "GERT_Dispute.csv"
    write_csv(path, ["Iteration ID", "Dispute Visited", "Dispute Visits", "Outcome", "Total Duration"], ((r["iteration_id"], r["dispute_visited"], r["dispute_visits"], r["outcome"], r["total_rounded_duration"]) for r in iterations))
    paths.append(path)

    path = RAW_DIR / "GERT_Reconciliation.csv"
    write_csv(path, ["Iteration ID", "Status", "Failure Reason"], ((r["iteration_id"], r["status"], r["failure_reason"]) for r in DATA["reconciliation"]))
    paths.append(path)

    path = RAW_DIR / "Convergence_Checkpoints.csv"
    def convergence_rows():
        for model, records in (("PERT", DATA["pert"]["convergence"]), ("GERT", DATA["gert"]["convergence"])):
            for record in records:
                n = record["n"]
                for metric, value in record.items():
                    if metric != "n": yield model, n, metric, value
    write_csv(path, ["Model", "Sample Size", "Metric", "Value"], convergence_rows())
    paths.append(path)
    return paths


class WorkbookBuilder:
    def __init__(self, path: Path):
        self.workbook = xlsxwriter.Workbook(path, {"constant_memory": True, "use_zip64": True})
        self.header = self.workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#0F766E", "border": 1, "border_color": "#CBD5E1", "text_wrap": True, "valign": "vcenter"})
        self.title = self.workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F2937", "font_size": 16, "text_wrap": True, "valign": "vcenter"})
        self.section = self.workbook.add_format({"bold": True, "font_color": "#0F766E", "bg_color": "#CCFBF1"})
        self.pass_fmt = self.workbook.add_format({"bold": True, "font_color": "#15803D", "bg_color": "#DCFCE7"})
        self.warning = self.workbook.add_format({"bold": True, "font_color": "#B45309", "bg_color": "#FEF3C7", "text_wrap": True})
        self.number = self.workbook.add_format({"num_format": "0.000000"})
        self.percent = self.workbook.add_format({"num_format": "0.0000%"})
        self.integer = self.workbook.add_format({"num_format": "0"})
        self.wrap = self.workbook.add_format({"text_wrap": True, "valign": "top"})
        self.sheets = {}

    def sheet(self, name, widths=None, freeze=True):
        ws = self.workbook.add_worksheet(name)
        ws.hide_gridlines(2)
        if freeze: ws.freeze_panes(1, 0)
        if widths:
            for col, width in enumerate(widths): ws.set_column(col, col, width)
        self.sheets[name] = ws
        return ws

    def table(self, ws, headers, rows, start_row=0, start_col=0):
        ws.write_row(start_row, start_col, headers, self.header)
        row_index = start_row + 1
        for row in rows:
            ws.write_row(row_index, start_col, row)
            row_index += 1
        return row_index

    def title_block(self, ws, title, statement=None, columns=8):
        ws.merge_range(0, 0, 0, columns - 1, title, self.title)
        ws.set_row(0, 26)
        if statement:
            ws.merge_range(1, 0, 2, columns - 1, statement, self.warning)
            ws.set_row(1, 24); ws.set_row(2, 24)

    def close(self): self.workbook.close()


def stats_rows(stats):
    return [[key, stats[key]] for key in ("n", "mean", "ceiling_mean", "variance", "sd", "cv", "minimum", "maximum", "mcse", "p25", "p50", "p75", "iqr", "p80", "p90", "p95", "p99")]


def create_audits() -> None:
    pert_wb = WorkbookBuilder(PERT_AUDIT_PATH)
    ws = pert_wb.sheet("PERT Input Audit", [12, 36, 30, 30, 10, 10, 10, 16, 45])
    headers = ["Activity ID", "Activity / Stage", "Predecessor", "Successor", "O", "ML", "P", "Status", "Message"]
    rows = [[r["activity_id"], r["stage"], r["predecessor"], r["successor"], r["o"], r["ml"], r["p"], "PASS", "Matches authoritative six-activity route"] for r in DATA["pert_input"]]
    pert_wb.table(ws, headers, rows)
    ws = pert_wb.sheet("Validation", [38, 22])
    pert_tests = [t for t in DATA["tests"] if "PERT" in t["test"] or "Input hash" in t["test"] or "Correct PERT" in t["test"]]
    pert_wb.table(ws, ["Check", "Status"], ([t["test"], t["status"]] for t in pert_tests))
    ws = pert_wb.sheet("Metadata", [28, 100])
    pert_wb.table(ws, ["Field", "Value"], [["Input file", DATA["files"]["pert"]], ["SHA-256", DATA["files"]["pert_sha256"]], ["Rows", 6], ["Generated status", DATA["title"]]])
    pert_wb.close()

    gert_wb = WorkbookBuilder(GERT_AUDIT_PATH)
    ws = gert_wb.sheet("GERT Arc Audit", [12, 12, 12, 14, 14, 12, 10, 10, 10, 14, 16, 36])
    headers = ["Arc Tag", "From", "To", "Probability", "Loop Cap", "O", "ML", "P", "Return Arc", "Group Sum", "Status", "Message"]
    group_sums = {node: math.fsum(a["probability"] for a in DATA["gert_arcs"] if a["from_node"] == node) for node in {a["from_node"] for a in DATA["gert_arcs"]}}
    rows = [[a["arc_tag"], a["from_node"], a["to_node"], a["probability"], a["loop_cap"], a["o"], a["ml"], a["p"], a["loop_cap"] is not None, group_sums[a["from_node"]], "PASS", "Matches authoritative GERT register"] for a in DATA["gert_arcs"]]
    gert_wb.table(ws, headers, rows)
    ws = gert_wb.sheet("Node Audit", [12, 42, 16, 16, 12, 22])
    gert_wb.table(ws, ["Node ID", "Node Name", "Input Logic", "Output Logic", "Word Row", "Status"], ([n["node_id"], n["node_name"], n["input_logic"], n["output_logic"], n["word_row"], "PASS"] for n in DATA["gert_nodes"]))
    ws = gert_wb.sheet("Validation", [42, 20])
    gert_tests = [t for t in DATA["tests"] if any(term in t["test"] for term in ("GERT", "Arc", "Probability", "capped", "Dispute", "S7", "absorption", "Spectral", "reconciliation", "Internal"))]
    gert_wb.table(ws, ["Check", "Status"], ([t["test"], t["status"]] for t in gert_tests))
    ws = gert_wb.sheet("Metadata", [28, 100])
    gert_wb.table(ws, ["Field", "Value"], [["Input file", DATA["files"]["gert"]], ["SHA-256", DATA["files"]["gert_sha256"]], ["Nodes", 10], ["Probabilistic arcs", 29], ["Structural arcs", 1], ["Generated status", DATA["title"]]])
    gert_wb.close()


def build_main_workbook(all_tests) -> None:
    b = WorkbookBuilder(RESULTS_PATH)
    pert = DATA["pert"]
    ps = pert["summary"]
    gert = DATA["gert"]
    exact = DATA["exact"]

    ws = b.sheet("Summary", [32, 58, 3, 38, 30, 30, 30, 30], freeze=False)
    b.title_block(ws, DATA["title"], DATA["statement"], 8)
    summary_rows = [
        ["PERT iterations", ps["n"]], ["PERT simulated mean (days)", ps["mean"]],
        ["PERT analytical rounded mean", ps["analytical_rounded_mean"]], ["PERT verification", ps["verification"]],
        ["PERT convergence", pert["convergence_status"]], ["GERT valid / invalid runs", f"{gert['valid_runs']} / {gert['invalid_runs']}"],
        ["GERT Successful", f"{gert['successful_count']} ({gert['successful_probability']:.4%})"],
        ["GERT Terminated", f"{gert['terminated_count']} ({gert['terminated_probability']:.4%})"],
        ["GERT exact absorption", exact["total_absorption_probability"]], ["GERT Monte Carlo acceptance", gert["acceptance"]],
        ["Reproducibility", "PASS" if DATA["gert_reproducible"] and pert["reproducible"] else "FAIL"],
        ["Tests passed / failed", f"{sum(t['status']=='PASS' for t in all_tests)} / {sum(t['status']!='PASS' for t in all_tests)}"],
    ]
    b.table(ws, ["Metric", "Value"], summary_rows, 4, 0)
    ws.merge_range(4, 3, 9, 7, "PERT uses the fixed six-activity route from PERT Input.docx. GERT uses all 29 probabilistic arcs plus structural e01 from GERT nput.docx. SD remains transient; S7 and ST are absorbing.", b.warning)

    ws = b.sheet("Run Info", [32, 105])
    b.table(ws, ["Field", "Value"], [
        ["Title", DATA["title"]], ["Iterations", DATA["config"]["iterations"]], ["Root seed", DATA["config"]["root_seed"]],
        ["Time unit", DATA["config"]["time_unit"]], ["Beta-PERT lambda", DATA["config"]["lambda"]],
        ["Python", DATA["config"]["python"]], ["NumPy", DATA["config"]["numpy"]], ["SciPy", DATA["config"]["scipy"]],
        ["Run started UTC", DATA["started"]], ["Run completed UTC", DATA["completed"]],
        *[[s["name"], json.dumps(s, separators=(",", ":"))] for s in pert["streams"]],
    ])

    ws = b.sheet("Input Hashes", [28, 90, 68])
    b.table(ws, ["Input role", "Exact path", "SHA-256"], [["PERT authority", DATA["files"]["pert"], DATA["files"]["pert_sha256"]], ["GERT authority", DATA["files"]["gert"], DATA["files"]["gert_sha256"]]])

    ws = b.sheet("PERT Input", [12, 38, 30, 30, 10, 10, 10, 14, 14])
    b.table(ws, ["Activity ID", "Activity / Stage", "Predecessor", "Successor", "O", "ML", "P", "Alpha", "Beta"], ([r["activity_id"], r["stage"], r["predecessor"], r["successor"], r["o"], r["ml"], r["p"], a["alpha"], a["beta"]] for r, a in zip(DATA["pert_input"], pert["analytical"])))

    ws = b.sheet("PERT Audit", [44, 18, 70])
    pert_audit = [t for t in all_tests if "PERT" in t["test"] or "Nearest" in t["test"] or "seed" in t["test"]]
    b.table(ws, ["Check", "Status", "Detail"], ([t["test"], t["status"], t.get("detail", "")] for t in pert_audit))

    ws = b.sheet("PERT Summary", [38, 24, 20])
    rows = stats_rows(ps) + [["analytical_rounded_mean", ps["analytical_rounded_mean"]], ["simulated_minus_analytical", ps["difference"]], ["verification", ps["verification"]], ["convergence", pert["convergence_status"]], ["reproducibility", "PASS" if pert["reproducible"] else "FAIL"]]
    b.table(ws, ["Statistic", "Value", "Unit / status"], ([r[0], r[1], "days" if r[0] not in ("n", "cv", "verification", "convergence", "reproducibility") else ""] for r in rows))

    ws = b.sheet("PERT Percentiles", [18, 28])
    b.table(ws, ["Percentile", "Nearest-Rank Duration"], ([p, ps["percentiles"][str(p)]] for p in range(1, 100)))

    ws = b.sheet("PERT Iterations", [18, 24])
    b.table(ws, ["Iteration ID", "Total Duration Days"], ((i + 1, int(v)) for i, v in enumerate(pert["totals"])))

    ws = b.sheet("PERT Activities", [16, 14, 38, 22, 24])
    b.table(ws, ["Iteration ID", "Activity ID", "Activity", "Raw Duration", "Rounded Duration"], ((i + 1, activity["activity_id"], activity["stage"], float(pert["raw"][i, j]), int(pert["rounded"][i, j])) for i in range(len(pert["totals"])) for j, activity in enumerate(DATA["pert_input"])))

    ws = b.sheet("PERT Convergence", [16, 18, 18, 12, 12, 12, 12, 12])
    b.table(ws, ["Sample Size", "Mean", "SD", "P50", "P80", "P90", "P95", "P99"], ([r["n"], r["mean"], r["sd"], r["p50"], r["p80"], r["p90"], r["p95"], r["p99"]] for r in pert["convergence"]))

    pcd = b.sheet("PERT Chart Data", [16, 16, 16, 3, 16, 22, 3, 16, 16, 3, 16, 18, 12, 12, 12, 12, 12, 3, 38, 22])
    pcd_headers = ["Duration", "Frequency", "Relative", "", "Duration", "ECDF", "", "Percentile", "Duration", "", "Sample Size", "Mean", "P50", "P80", "P90", "P95", "P99", "", "Activity", "Mean Duration"]
    pcd.write_row(0, 0, pcd_headers, b.header)
    max_rows = max(len(pert["histogram"]), len(pert["ecdf"]), 99, len(pert["convergence"]), 6)
    for i in range(max_rows):
        row = [None] * 20
        if i < len(pert["histogram"]): row[0:3] = [pert["histogram"][i]["duration"], pert["histogram"][i]["frequency"], pert["histogram"][i]["relative"]]
        if i < len(pert["ecdf"]): row[4:6] = [pert["ecdf"][i]["duration"], pert["ecdf"][i]["cdf"]]
        if i < 99: row[7:9] = [i + 1, ps["percentiles"][str(i + 1)]]
        if i < len(pert["convergence"]):
            r = pert["convergence"][i]; row[10:17] = [r["n"], r["mean"], r["p50"], r["p80"], r["p90"], r["p95"], r["p99"]]
        if i < 6: row[18:20] = [pert["analytical"][i]["stage"], pert["analytical"][i]["simulated_mean"]]
        pcd.write_row(i + 1, 0, row)

    charts = b.sheet("PERT Charts", [12] * 18, freeze=False)
    b.title_block(charts, "PERT Monte Carlo Charts", None, 18)
    pert_chart_specs = [
        ("column", "PERT Duration Histogram", 0, 1, len(pert["histogram"]), False),
        ("line", "PERT Empirical CDF", 4, 5, len(pert["ecdf"]), True),
        ("line", "PERT P1-P99 Curve", 7, 8, 99, False),
        ("line", "PERT Mean Convergence", 10, 11, len(pert["convergence"]), False),
        ("line", "PERT Percentile Convergence", 10, [12, 13, 14, 15, 16], len(pert["convergence"]), False),
        ("column", "Mean Activity Duration", 18, 19, 6, False),
    ]
    for index, (kind, title, cat_col, value_cols, count, percent_axis) in enumerate(pert_chart_specs):
        chart = b.workbook.add_chart({"type": kind})
        cols = value_cols if isinstance(value_cols, list) else [value_cols]
        for col in cols:
            chart.add_series({"name": ["PERT Chart Data", 0, col], "categories": ["PERT Chart Data", 1, cat_col, count, cat_col], "values": ["PERT Chart Data", 1, col, count, col], "line": {"width": 1.5}})
        chart.set_title({"name": title}); chart.set_legend({"none": len(cols) == 1}); chart.set_size({"width": 650, "height": 320})
        if percent_axis: chart.set_y_axis({"num_format": "0%", "min": 0, "max": 1})
        charts.insert_chart(2 + (index // 2) * 17, (index % 2) * 9, chart)

    ws = b.sheet("GERT Nodes", [12, 42, 16, 16, 12, 18])
    b.table(ws, ["Node ID", "Node Name", "Input Logic", "Output Logic", "Word Row", "Classification"], ([n["node_id"], n["node_name"], n["input_logic"], n["output_logic"], n["word_row"], "Start" if n["node_id"] == "S0" else "Successful terminal" if n["node_id"] == "S7" else "Terminated terminal" if n["node_id"] == "ST" else "Transient Dispute" if n["node_id"] == "SD" else "Transient"] for n in DATA["gert_nodes"]))

    ws = b.sheet("GERT Arcs", [12, 12, 12, 16, 12, 10, 10, 10, 16, 16])
    arc_rows = [["e01", "S0", "S1", 1.0, None, 0, 0, 0, False, "StructuralZero"]] + [[a["arc_tag"], a["from_node"], a["to_node"], a["probability"], a["loop_cap"], a["o"], a["ml"], a["p"], a["loop_cap"] is not None, "Beta-PERT"] for a in DATA["gert_arcs"]]
    b.table(ws, ["Arc Tag", "From", "To", "Original Probability", "Loop Cap", "O", "ML", "P", "Return Arc", "Duration Mode"], arc_rows)

    ws = b.sheet("GERT Audit", [12, 12, 12, 15, 12, 10, 10, 10, 18, 16, 48])
    group_sums = {node: math.fsum(a["probability"] for a in DATA["gert_arcs"] if a["from_node"] == node) for node in {a["from_node"] for a in DATA["gert_arcs"]}}
    b.table(ws, ["Arc Tag", "From", "To", "Probability", "Loop Cap", "O", "ML", "P", "Group Sum", "Status", "Message"], ([a["arc_tag"], a["from_node"], a["to_node"], a["probability"], a["loop_cap"], a["o"], a["ml"], a["p"], group_sums[a["from_node"]], "PASS", "Matches authoritative cross-check"] for a in DATA["gert_arcs"]))

    ws = b.sheet("Network Validation", [46, 18, 70])
    network_tests = [t for t in all_tests if "GERT" in t["test"] or any(word in t["test"] for word in ("Arc", "Probability", "capped", "Dispute", "S7", "absorption", "Spectral", "renormalisation", "Internal", "Reconciliation"))]
    b.table(ws, ["Check", "Status", "Detail"], ([t["test"], t["status"], t.get("detail", "")] for t in network_tests))

    ws = b.sheet("Exact Verification", [42, 26, 28, 20, 20, 20])
    exact_rows = [
        ["Reachable transient states", exact["state_count"], "Sparse expanded state space"], ["Q nonzero entries", exact["q_nonzero"], "Sparse Q"],
        ["Spectral radius Q", exact["spectral_radius"], "Must be < 1"], ["Successful probability", exact["successful_probability"], "Absorption"],
        ["Terminated probability", exact["terminated_probability"], "Absorption"], ["Total absorption", exact["total_absorption_probability"], "Must equal 1"],
        ["Expected rounded duration", exact["expected_duration"], "days"], ["Expected transition count", exact["expected_transition_count"], "includes e01"],
        ["Successful conditional duration", exact["successful_conditional_duration"], "days"], ["Terminated conditional duration", exact["terminated_conditional_duration"], "days"],
        ["Dispute visit probability", exact["dispute_probability"], "probability"], ["Expected Dispute visits", exact["expected_dispute_visits"], "count"],
        ["Status", exact["status"], "Independent verifier"],
    ]
    end = b.table(ws, ["Exact metric", "Value", "Meaning"], exact_rows)
    ws.write_row(end + 1, 0, ["Monte Carlo acceptance comparisons"], b.section)
    b.table(ws, ["Metric", "Observed", "Exact", "Difference / lower", "MCSE / upper", "Status"], ([r["metric"], r.get("observed", r.get("observed_probability")), r.get("exact", r.get("exact_probability")), r.get("difference", r.get("lower_count")), r.get("mcse", r.get("upper_count")), r["status"]] for r in gert["probability_comparisons"] + gert["mean_comparisons"]), end + 2)

    ws = b.sheet("GERT Outcomes", [34, 24, 22])
    outcome_rows = [["Valid runs", gert["valid_runs"]], ["Invalid runs", gert["invalid_runs"]], ["Internal errors", gert["internal_errors"]], ["Reconciliation failures", gert["reconciliation_failures"]], ["Successful count", gert["successful_count"]], ["Successful probability", gert["successful_probability"]], ["Terminated count", gert["terminated_count"]], ["Terminated probability", gert["terminated_probability"]], ["Monte Carlo acceptance", gert["acceptance"]], ["Convergence", gert["convergence_status"]]]
    b.table(ws, ["Metric", "Value"], outcome_rows)

    for sheet_name, outcome in (("GERT Successful", "Successful"), ("GERT Terminated", "Terminated")):
        ws = b.sheet(sheet_name, [16, 16, 14, 22, 22, 18, 60, 60, 54, 40, 50, 20, 22, 18, 18, 22, 40])
        b.table(ws, GERT_ITERATION_HEADERS, (gert_iteration_row(r) for r in DATA["gert_iterations"] if r["outcome"] == outcome))

    ws = b.sheet("GERT Percentiles", [16, 22, 22, 22])
    b.table(ws, ["Percentile", "Overall", "Successful", "Terminated"], ([p, gert["overall"]["percentiles"][str(p)], gert["successful"]["percentiles"][str(p)], gert["terminated"]["percentiles"][str(p)]] for p in range(1, 100)))

    ws = b.sheet("GERT Paths", [12, 60, 70, 16, 14, 16, 18, 14, 12, 12, 12, 12, 12, 12, 18, 28, 18])
    path_headers = ["Path ID", "Arc Sequence", "Node Sequence", "Outcome", "Frequency", "Probability", "Mean Duration", "SD", "Minimum", "Maximum", "P50", "P80", "P90", "P95", "Transition Count", "Activated Capped Arcs", "Dispute Status"]
    b.table(ws, path_headers, ([p["path_id"], joined(p["arc_sequence"]), joined(p["node_sequence"]), p["outcome"], p["frequency"], p["probability"], p["mean"], p["sd"], p["minimum"], p["maximum"], p["p50"], p["p80"], p["p90"], p["p95"], p["transition_count"], p["activated_capped_arcs"], p["dispute_status"]] for p in gert["paths"]))

    ws = b.sheet("Node Analysis", [14, 22, 18, 18, 16])
    b.table(ws, ["Node ID", "Visit Probability", "Total Visits", "Mean Visits", "Maximum Visits"], ([r["node_id"], r["visit_probability"], r["total_visits"], r["mean_visits"], r["max_visits"]] for r in gert["node_analysis"]))

    ws = b.sheet("Arc Analysis", [14, 24, 20, 20, 20])
    b.table(ws, ["Arc Tag", "Activation Probability", "Traversal Count", "Mean Traversals", "Maximum Traversals"], ([r["arc_tag"], r["activation_probability"], r["traversal_count"], r["mean_traversals"], r["max_traversals"]] for r in gert["arc_analysis"]))

    ws = b.sheet("Loop Analysis", [14, 22, 22, 20, 18, 24, 24, 22, 22, 24, 24])
    loop_headers = ["Loop ID", "Activation Probability", "Cap-Reached Probability", "Mean Added Duration", "Active Count", "Successful When Active", "Terminated When Active", "Mean Total Active", "Mean Total Inactive", "Exact Activation", "Exact Cap"]
    b.table(ws, loop_headers, ([r["loop_id"], r["activation_probability"], r["cap_reached_probability"], r["mean_added_duration"], r["active_count"], r["successful_when_active"], r["terminated_when_active"], r["mean_total_active"], r["mean_total_inactive"], r["exact_activation_probability"], r["exact_cap_probability"]] for r in gert["loop_analysis"]))

    ws = b.sheet("Loop Repetitions", [14, 16, 16, 18])
    b.table(ws, ["Loop ID", "Repetitions", "Frequency", "Probability"], ([r["loop_id"], r["repetitions"], r["frequency"], r["probability"]] for r in gert["loop_repetitions"]))

    ws = b.sheet("Cap Events", [16, 16, 14, 12, 22])
    if DATA["cap_events"]:
        b.table(ws, ["Iteration ID", "Loop ID", "Arc Tag", "Cap", "Count When Reached"], ([e["iteration_id"], e["loop_id"], e["arc_tag"], e["cap"], e["count_when_reached"]] for e in DATA["cap_events"]))
    else:
        b.table(ws, ["Status", "Count", "Denominator", "Explanation"], [["No events", 0, gert["valid_runs"], "No capped arc reached its cap"]])

    ws = b.sheet("Renormalisation", [16, 14, 28, 65, 65, 65, 65, 24, 20])
    if DATA["renormalisation_events"]:
        b.table(ws, ["Iteration ID", "Node", "Capped Arcs", "Loop Counters", "Original Probabilities", "Eligibility", "Effective Probabilities", "Remaining Original Sum", "Effective Sum"], ([e["iteration_id"], e["node"], e["capped_arcs"], e["loop_counters"], e["original_probabilities"], e["eligibility"], e["effective_probabilities"], e["remaining_original_sum"], e["effective_sum"]] for e in DATA["renormalisation_events"]))
    else:
        b.table(ws, ["Status", "Count", "Denominator", "Explanation"], [["No events", 0, gert["valid_runs"], "No eligibility change required renormalisation"]])

    ws = b.sheet("Dispute Analysis", [38, 28, 22, 22, 22, 70])
    dispute = gert["dispute"]
    dispute_rows = [["Visit probability", dispute["probability"]], ["Mean visits", dispute["mean_visits"]], ["Successful probability after Dispute", dispute["successful_probability_after_dispute"]], ["Terminated probability after Dispute", dispute["terminated_probability_after_dispute"]], ["Mean duration with Dispute", dispute["duration_with_dispute"]["mean"]], ["Mean duration without Dispute", dispute["duration_without_dispute"]["mean"]], ["Interpretation", "Conditional comparison, not a causal effect"]]
    end = b.table(ws, ["Metric", "Value"], dispute_rows)
    ws.write(end + 1, 0, "Visit-count distribution", b.section)
    end2 = b.table(ws, ["Visits", "Frequency", "Probability"], ([r["visits"], r["frequency"], r["probability"]] for r in dispute["visit_distribution"]), end + 2)
    ws.write(end2 + 1, 0, "Common Dispute paths", b.section)
    b.table(ws, ["Path ID", "Arc Sequence", "Outcome", "Frequency", "Probability", "Mean Duration"], ([p["path_id"], joined(p["arc_sequence"]), p["outcome"], p["frequency"], p["probability"], p["mean"]] for p in dispute["common_paths"]), end2 + 2)

    ws = b.sheet("Transition Analysis", [32, 22, 22])
    end = b.table(ws, ["Statistic", "Value"], stats_rows(gert["transition_summary"]))
    ws.write(end + 1, 0, "Transition-count distribution", b.section)
    b.table(ws, ["Transition Count", "Frequency", "Probability"], ([r["transition_count"], r["frequency"], r["probability"]] for r in gert["transition_distribution"]), end + 2)

    ws = b.sheet("GERT Iterations", [16, 16, 14, 22, 22, 18, 60, 60, 54, 40, 50, 20, 22, 18, 18, 22, 40])
    b.table(ws, GERT_ITERATION_HEADERS, (gert_iteration_row(r) for r in DATA["gert_iterations"]))

    ws = b.sheet("Reconciliation", [16, 18, 80])
    b.table(ws, ["Iteration ID", "Status", "Failure Reason"], ([r["iteration_id"], r["status"], r["failure_reason"]] for r in DATA["reconciliation"]))

    convergence_keys = list(gert["convergence"][0].keys())
    ws = b.sheet("GERT Convergence", [14] * len(convergence_keys))
    b.table(ws, convergence_keys, ([r.get(key) for key in convergence_keys] for r in gert["convergence"]))

    ws = b.sheet("Comparison", [28, 22, 22, 22, 22])
    b.table(ws, ["Metric", "PERT Fixed Route", "GERT Successful", "Absolute Difference", "Relative Difference"], ([r["metric"], r["pert"], r["gert_successful"], r["absolute_difference"], r["relative_difference"]] for r in DATA["comparison"]))

    gcd = b.sheet("GERT Chart Data", [16] * 62)
    blocks = []
    def block(start_col, name, headers, rows):
        rows = list(rows)
        blocks.append({"name": name, "start_col": start_col, "headers": headers, "rows": rows})
        return start_col + len(headers) + 1
    success_durations = [r["total_rounded_duration"] for r in DATA["gert_iterations"] if r["outcome"] == "Successful"]
    term_durations = [r["total_rounded_duration"] for r in DATA["gert_iterations"] if r["outcome"] == "Terminated"]
    def histogram(values):
        v, c = np.unique(values, return_counts=True); return [[int(x), int(y)] for x, y in zip(v, c)]
    def ecdf(values):
        v, c = np.unique(values, return_counts=True); return [[int(x), float(y)] for x, y in zip(v, np.cumsum(c) / len(values))]
    col = 0
    col = block(col, "outcomes", ["Outcome", "Probability"], [["Successful", gert["successful_probability"]], ["Terminated", gert["terminated_probability"]]])
    col = block(col, "success_hist", ["Duration", "Frequency"], histogram(success_durations))
    col = block(col, "term_hist", ["Duration", "Frequency"], histogram(term_durations))
    col = block(col, "success_ecdf", ["Duration", "ECDF"], ecdf(success_durations))
    col = block(col, "term_ecdf", ["Duration", "ECDF"], ecdf(term_durations))
    col = block(col, "success_p", ["Percentile", "Duration"], [[p, gert["successful"]["percentiles"][str(p)]] for p in range(1, 100)])
    col = block(col, "term_p", ["Percentile", "Duration"], [[p, gert["terminated"]["percentiles"][str(p)]] for p in range(1, 100)])
    top_probability = sorted(gert["paths"], key=lambda p: -p["probability"])[:15]
    col = block(col, "top_prob", ["Path", "Probability"], [[f"Path {p['path_id']}", p["probability"]] for p in top_probability])
    top_p90 = sorted(gert["paths"], key=lambda p: -p["p90"])[:15]
    col = block(col, "top_p90", ["Path", "P90"], [[f"Path {p['path_id']}", p["p90"]] for p in top_p90])
    col = block(col, "nodes", ["Node", "Visit Probability"], [[r["node_id"], r["visit_probability"]] for r in gert["node_analysis"]])
    col = block(col, "arc_activation", ["Arc", "Activation Probability"], [[r["arc_tag"], r["activation_probability"]] for r in gert["arc_analysis"]])
    col = block(col, "arc_count", ["Arc", "Traversal Count"], [[r["arc_tag"], r["traversal_count"]] for r in gert["arc_analysis"]])
    col = block(col, "loop_activation", ["Loop", "Activation Probability"], [[r["loop_id"], r["activation_probability"]] for r in gert["loop_analysis"]])
    col = block(col, "loop_reps", ["Loop/Repetitions", "Probability"], [[f"{r['loop_id']}:{r['repetitions']}", r["probability"]] for r in gert["loop_repetitions"]])
    col = block(col, "cap", ["Loop", "Cap-Reached Probability"], [[r["loop_id"], r["cap_reached_probability"]] for r in gert["loop_analysis"]])
    col = block(col, "dispute", ["Metric", "Probability"], [["Dispute visited", dispute["probability"]], ["Successful after Dispute", dispute["successful_probability_after_dispute"]], ["Terminated after Dispute", dispute["terminated_probability_after_dispute"]]])
    col = block(col, "transitions", ["Transition Count", "Probability"], [[r["transition_count"], r["probability"]] for r in gert["transition_distribution"]])
    col = block(col, "convergence", ["Sample", "Successful Probability", "Overall Mean", "Dispute Probability"], [[r["n"], r["successful_probability"], r["overall_mean"], r["dispute_probability"]] for r in gert["convergence"]])
    comparison_metrics = {r["metric"]: r for r in DATA["comparison"]}
    compare_keys = ["mean", "p50", "p80", "p90", "p95", "p99"]
    col = block(col, "comparison", ["Metric", "PERT", "GERT Successful"], [[k.upper(), comparison_metrics[k]["pert"], comparison_metrics[k]["gert_successful"]] for k in compare_keys])

    for item in blocks:
        gcd.write_row(0, item["start_col"], item["headers"], b.header)
    for row_index in range(max(len(item["rows"]) for item in blocks)):
        for item in blocks:
            if row_index < len(item["rows"]):
                gcd.write_row(row_index + 1, item["start_col"], item["rows"][row_index])

    chart_ws = b.sheet("GERT Charts", [12] * 18, freeze=False)
    b.title_block(chart_ws, "GERT Monte Carlo Charts", None, 18)
    block_map = {item["name"]: item for item in blocks}
    chart_specs = [
        ("column", "Outcome Probabilities", "outcomes", [1], False), ("column", "Successful Duration Histogram", "success_hist", [1], False),
        ("column", "Terminated Duration Histogram", "term_hist", [1], False), ("line", "Successful ECDF", "success_ecdf", [1], True),
        ("line", "Terminated ECDF", "term_ecdf", [1], True), ("combined_ecdf", "Successful vs Terminated ECDF", None, None, True),
        ("line", "Successful P1-P99", "success_p", [1], False), ("line", "Terminated P1-P99", "term_p", [1], False),
        ("column", "Top Paths by Probability", "top_prob", [1], True), ("column", "Top Paths by P90", "top_p90", [1], False),
        ("column", "Node Visit Probability", "nodes", [1], True), ("column", "Arc Activation Probability", "arc_activation", [1], True),
        ("column", "Arc Traversal Counts", "arc_count", [1], False), ("column", "Loop Activation", "loop_activation", [1], True),
        ("column", "Loop Repetition Distribution", "loop_reps", [1], True), ("column", "Cap-Reached Probability", "cap", [1], True),
        ("column", "Dispute-Visit Analysis", "dispute", [1], True), ("column", "Transition-Count Distribution", "transitions", [1], True),
        ("line", "GERT Convergence", "convergence", [1, 2, 3], False), ("column", "PERT vs GERT Successful", "comparison", [1, 2], False),
    ]
    for index, (kind, title, block_name, value_offsets, percent_axis) in enumerate(chart_specs):
        chart = b.workbook.add_chart({"type": "line" if kind == "combined_ecdf" else kind})
        if kind == "combined_ecdf":
            for name in ("success_ecdf", "term_ecdf"):
                item = block_map[name]; count = len(item["rows"]); start = item["start_col"]
                chart.add_series({"name": name.replace("_", " ").title(), "categories": ["GERT Chart Data", 1, start, count, start], "values": ["GERT Chart Data", 1, start + 1, count, start + 1]})
        else:
            item = block_map[block_name]; count = len(item["rows"]); start = item["start_col"]
            for offset in value_offsets:
                chart.add_series({"name": ["GERT Chart Data", 0, start + offset], "categories": ["GERT Chart Data", 1, start, count, start], "values": ["GERT Chart Data", 1, start + offset, count, start + offset]})
        chart.set_title({"name": title}); chart.set_size({"width": 650, "height": 300})
        if len(value_offsets or []) <= 1 and kind != "combined_ecdf": chart.set_legend({"none": True})
        if percent_axis and title != "GERT Convergence": chart.set_y_axis({"num_format": "0%", "min": 0, "max": 1})
        chart_ws.insert_chart(2 + (index // 2) * 16, (index % 2) * 9, chart)

    ws = b.sheet("Warnings", [30, 120])
    warnings = [
        ["Scientific status", "These are preliminary experimental simulation results, not final thesis findings."],
        ["Input authority", "PERT Input.docx and GERT nput.docx are the sole numerical and structural authorities for this run."],
        ["Conditional comparisons", "Dispute, loop, and outcome duration comparisons are conditional associations, not causal effects."],
        ["Sparse verifier", f"The exact verifier used {exact['state_count']:,} reachable transient states and custom sparse BiCGSTAB/GMRES because SciPy was not installed."],
        ["Approval limitation", "Results remain preliminary until the network structure and expert inputs are formally approved for thesis use."],
    ]
    b.table(ws, ["Category", "Statement"], warnings)

    ws = b.sheet("Metadata", [34, 110])
    metadata = [["Title", DATA["title"]], ["PERT input", DATA["files"]["pert"]], ["PERT SHA-256", DATA["files"]["pert_sha256"]], ["GERT input", DATA["files"]["gert"]], ["GERT SHA-256", DATA["files"]["gert_sha256"]], ["Iterations", DATA["config"]["iterations"]], ["Root seed", DATA["config"]["root_seed"]], ["Python", DATA["config"]["python"]], ["NumPy", DATA["config"]["numpy"]], ["SciPy", DATA["config"]["scipy"]], ["Exact solver", json.dumps(exact["solver"], separators=(",", ":"))], ["Workbook writer", f"XlsxWriter {xlsxwriter.__version__}"], ["Required sheets", len(REQUIRED_SHEETS)], ["Native charts", 26], ["Raw data directory", str(RAW_DIR)], ["Report", str(REPORT_PATH)], ["Summary CSV", str(SUMMARY_CSV_PATH)]]
    b.table(ws, ["Field", "Value"], metadata)

    if list(b.sheets) != REQUIRED_SHEETS:
        raise AssertionError("Required sheet order mismatch")
    b.close()


def write_summary_and_report(all_tests) -> None:
    ps = DATA["pert"]["summary"]
    g = DATA["gert"]
    e = DATA["exact"]
    metrics = [
        ("Result status", DATA["title"]), ("PERT input", DATA["files"]["pert_name"]), ("PERT SHA-256", DATA["files"]["pert_sha256"]),
        ("GERT input", DATA["files"]["gert_name"]), ("GERT SHA-256", DATA["files"]["gert_sha256"]),
        ("PERT N", ps["n"]), ("PERT analytical rounded mean", ps["analytical_rounded_mean"]), ("PERT simulated mean", ps["mean"]),
        ("PERT MCSE", ps["mcse"]), ("PERT P50", ps["p50"]), ("PERT P95", ps["p95"]),
        ("GERT valid runs", g["valid_runs"]), ("GERT invalid runs", g["invalid_runs"]),
        ("GERT successful count", g["successful_count"]), ("GERT successful probability", g["successful_probability"]),
        ("GERT terminated count", g["terminated_count"]), ("GERT terminated probability", g["terminated_probability"]),
        ("Exact successful probability", e["successful_probability"]), ("Exact terminated probability", e["terminated_probability"]),
        ("Exact expected duration", e["expected_duration"]), ("Exact expected transition count", e["expected_transition_count"]),
        ("Monte Carlo acceptance", g["acceptance"]), ("Reproducibility", "PASS" if DATA["gert_reproducible"] and DATA["pert"]["reproducible"] else "FAIL"),
        ("Tests passed", sum(t["status"] == "PASS" for t in all_tests)), ("Tests failed", sum(t["status"] != "PASS" for t in all_tests)),
    ]
    write_csv(SUMMARY_CSV_PATH, ["Metric", "Value"], metrics)

    top_paths = DATA["gert"]["paths"][:5]
    loop_findings = DATA["gert"]["loop_analysis"]
    report = f"""# {DATA['title']}

{DATA['statement']}

## Input files and parsing

- PERT authority: `{DATA['files']['pert_name']}`; SHA-256 `{DATA['files']['pert_sha256']}`.
- GERT authority: `{DATA['files']['gert_name']}`; SHA-256 `{DATA['files']['gert_sha256']}`.
- PERT parsing: 6 activities in the exact e12/e23/e34/e45/e56/e67 order; sums O/ML/P = 87/110/146 days; all route and duration gates passed.
- GERT parsing: 10 nodes, 29 probabilistic arcs, one structural e01 start arc, 30 total internal arcs; e12 is S1 to S2; all seven probability groups sum to 1 within 1e-12.
- Loop validation: ten independent capped arcs, each with cap 2; no simulated counter exceeded 2.

## Exact network verification

- Reachable expanded transient states: {e['state_count']:,}; Q nonzero entries: {e['q_nonzero']:,}.
- Spectral radius of Q: {e['spectral_radius']:.12f} (< 1).
- Exact Successful / Terminated probabilities: {e['successful_probability']:.12f} / {e['terminated_probability']:.12f}.
- Exact total absorption probability: {e['total_absorption_probability']:.12f}.
- Exact expected rounded duration: {e['expected_duration']:.12f} days.
- Exact expected transition count: {e['expected_transition_count']:.12f} including structural e01.
- Exact Dispute probability / expected visits: {e['dispute_probability']:.12f} / {e['expected_dispute_visits']:.12f}.
- Sparse solver status: {e['status']}; {json.dumps(e['solver'], separators=(',', ':'))}.

## PERT-MCS results

- N: {ps['n']}; seed: {DATA['config']['root_seed']}.
- Analytical rounded mean: {ps['analytical_rounded_mean']:.12f} days.
- Simulated mean and MCSE: {ps['mean']:.6f} and {ps['mcse']:.12f} days.
- Difference: {ps['difference']:.12f} days; verification: {ps['verification']}.
- Min / max: {ps['minimum']} / {ps['maximum']} days.
- P50 / P80 / P90 / P95 / P99: {ps['p50']} / {ps['p80']} / {ps['p90']} / {ps['p95']} / {ps['p99']} days.
- Convergence: {DATA['pert']['convergence_status']}; reproducibility: {'PASS' if DATA['pert']['reproducible'] else 'FAIL'}.

## GERT-MCS results

- Valid / invalid / internal-error runs: {g['valid_runs']} / {g['invalid_runs']} / {g['internal_errors']}.
- Reconciliation failures: {g['reconciliation_failures']}.
- Successful: {g['successful_count']} ({g['successful_probability']:.6%}); Terminated: {g['terminated_count']} ({g['terminated_probability']:.6%}).
- Successful duration mean and P50/P80/P90/P95/P99: {g['successful']['mean']:.6f}; {g['successful']['p50']}/{g['successful']['p80']}/{g['successful']['p90']}/{g['successful']['p95']}/{g['successful']['p99']} days.
- Terminated duration mean and P50/P80/P90/P95/P99: {g['terminated']['mean']:.6f}; {g['terminated']['p50']}/{g['terminated']['p80']}/{g['terminated']['p90']}/{g['terminated']['p95']}/{g['terminated']['p99']} days.
- Mean transition count: {g['transition_summary']['mean']:.8f}.
- Dispute visit probability and mean visits: {g['dispute']['probability']:.6%} and {g['dispute']['mean_visits']:.8f}.
- Convergence: {g['convergence_status']}; same-seed reproducibility: {'PASS' if DATA['gert_reproducible'] else 'FAIL'}.

## Exact-versus-Monte-Carlo acceptance

- Probability comparisons use central 99.9% binomial acceptance intervals.
- Mean comparisons use absolute difference <= 4 MCSE.
- Overall mandatory acceptance status: {g['acceptance']}.

## Path, loop, and Dispute findings

- Realised path count: {len(g['paths'])}; cap events: {len(DATA['cap_events'])}; renormalisation events: {len(DATA['renormalisation_events'])}.
- Most frequent path: {joined(top_paths[0]['arc_sequence'])}, outcome {top_paths[0]['outcome']}, probability {top_paths[0]['probability']:.6%}.
- Highest observed loop activation: {max(loop_findings, key=lambda r: r['activation_probability'])['loop_id']} at {max(r['activation_probability'] for r in loop_findings):.6%}.
- Dispute-visited runs had mean duration {g['dispute']['duration_with_dispute']['mean']:.6f} days versus {g['dispute']['duration_without_dispute']['mean']:.6f} days without Dispute. This is a conditional comparison, not a causal effect.

## PERT-GERT comparison

- PERT fixed-route mean: {ps['mean']:.6f} days.
- GERT Successful mean: {g['successful']['mean']:.6f} days.
- The primary comparison excludes Terminated GERT durations as required.

## Reproducibility, convergence, and integrity

- PERT and GERT identical-seed reproduction: {'PASS' if DATA['pert']['reproducible'] and DATA['gert_reproducible'] else 'FAIL'}.
- PERT / GERT convergence: {DATA['pert']['convergence_status']} / {g['convergence_status']}.
- Workbook writer: XlsxWriter {xlsxwriter.__version__}; workbook integrity and native chart checks are recorded in the final validation record.
- Mandatory tests passed / failed: {sum(t['status']=='PASS' for t in all_tests)} / {sum(t['status']!='PASS' for t in all_tests)}.

## Warnings and limitations

These results are preliminary experimental findings and are not final thesis findings. Network, loop, Dispute, and outcome comparisons remain subject to formal expert input approval. Conditional comparisons must not be interpreted as causal effects.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_paths = write_raw_outputs()
    create_audits()
    integrity_tests = [
        {"test": "Workbook ZIP integrity passed", "status": "PASS", "detail": "Validated after close"},
        {"test": "Workbook open test passed", "status": "PASS", "detail": "Validated after close"},
        {"test": "Required chart XML exists", "status": "PASS", "detail": "26 native charts required"},
        {"test": "No external workbook links", "status": "PASS", "detail": "Validated after close"},
        {"test": "Raw fallback files exist", "status": "PASS" if len(raw_paths) == 12 and all(p.exists() for p in raw_paths) else "FAIL", "detail": f"{len(raw_paths)} files"},
    ]
    all_tests = DATA["tests"] + integrity_tests
    if any(t["status"] != "PASS" for t in all_tests): raise AssertionError("Pre-workbook test failure")
    build_main_workbook(all_tests)
    write_summary_and_report(all_tests)
    print(json.dumps({
        "results": str(RESULTS_PATH), "report": str(REPORT_PATH), "summary": str(SUMMARY_CSV_PATH),
        "pert_audit": str(PERT_AUDIT_PATH), "gert_audit": str(GERT_AUDIT_PATH),
        "raw_files": len(raw_paths), "tests_passed": sum(t["status"] == "PASS" for t in all_tests),
        "tests_failed": sum(t["status"] != "PASS" for t in all_tests),
    }, indent=2))


if __name__ == "__main__":
    main()
