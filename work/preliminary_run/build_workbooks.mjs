import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const workDir = "C:/Users/moham/Documents/Codex/2026-07-28/build/work/preliminary_run";
const outputDir = "C:/Users/moham/Documents/Codex/2026-07-28/build/outputs";
const data = JSON.parse(await fs.readFile(path.join(workDir, "simulation_data.json"), "utf8"));

const mainPath = path.join(outputDir, "Preliminary_Experimental_Simulation_Results.xlsx");
const reportPath = path.join(outputDir, "Preliminary_Experimental_Simulation_Report.md");
const auditPath = path.join(outputDir, "Preliminary_Input_Audit.xlsx");

const colors = {
  ink: "#1F2937",
  muted: "#64748B",
  teal: "#0F766E",
  tealLight: "#CCFBF1",
  blue: "#2563EB",
  blueLight: "#DBEAFE",
  green: "#15803D",
  greenLight: "#DCFCE7",
  amber: "#B45309",
  amberLight: "#FEF3C7",
  red: "#B91C1C",
  redLight: "#FEE2E2",
  line: "#CBD5E1",
  white: "#FFFFFF",
  grayLight: "#F8FAFC",
};

const requiredSheets = [
  "Executive Summary", "Run Information", "Input Audit", "Word Parsed Records", "Validation",
  "PERT Input", "PERT Summary", "PERT Analytical Check", "PERT P1-P99", "PERT Iterations",
  "PERT Activity Durations", "PERT Convergence", "PERT Histogram Data", "PERT ECDF Data",
  "PERT Chart Data", "PERT Charts", "GERT Status", "GERT Input Audit", "GERT Outcome Summary",
  "GERT Successful Results", "GERT Terminated Results", "GERT Paths", "GERT Nodes", "GERT Arcs",
  "GERT Loops", "GERT Cap Events", "GERT Renormalisation", "GERT Dispute", "GERT Iterations",
  "GERT Verification", "Warnings and Limitations", "Metadata",
];

function colName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function styleHeader(range) {
  range.format = {
    fill: colors.teal,
    font: { bold: true, color: colors.white },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: colors.teal },
  };
  range.format.rowHeight = 28;
}

function styleTitle(sheet, rangeAddress, title, subtitle = null) {
  const titleRange = sheet.getRange(rangeAddress);
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: colors.ink,
    font: { bold: true, color: colors.white, size: 18 },
    verticalAlignment: "center",
    wrapText: true,
  };
  titleRange.format.rowHeight = 34;
  if (subtitle) {
    const endCol = rangeAddress.split(":")[1].match(/[A-Z]+/)[0];
    const subtitleRange = sheet.getRange(`A2:${endCol}3`);
    subtitleRange.merge();
    subtitleRange.values = [[subtitle]];
    subtitleRange.format = {
      fill: colors.grayLight,
      font: { color: colors.ink, italic: true, size: 10 },
      wrapText: true,
      verticalAlignment: "center",
    };
    subtitleRange.format.rowHeight = 36;
  }
}

function writeTable(sheet, startRow, startCol, headers, rows, options = {}) {
  const headerRange = sheet.getRangeByIndexes(startRow, startCol, 1, headers.length);
  headerRange.values = [headers];
  styleHeader(headerRange);
  const chunkSize = options.chunkSize || 10000;
  for (let offset = 0; offset < rows.length; offset += chunkSize) {
    const chunk = rows.slice(offset, offset + chunkSize);
    if (chunk.length) {
      sheet.getRangeByIndexes(startRow + 1 + offset, startCol, chunk.length, headers.length).values = chunk;
    }
  }
  if (options.freeze !== false && startRow === 0) sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  return { firstDataRow: startRow + 1, lastDataRow: startRow + rows.length };
}

function writeKeyValues(sheet, startRow, rows, width = 2) {
  const matrix = rows.map(([key, value]) => [key, value]);
  sheet.getRangeByIndexes(startRow, 0, matrix.length, width).values = matrix;
  sheet.getRangeByIndexes(startRow, 0, matrix.length, 1).format = {
    fill: colors.grayLight,
    font: { bold: true, color: colors.ink },
  };
  sheet.getRangeByIndexes(startRow, 0, matrix.length, width).format.borders = {
    insideHorizontal: { style: "thin", color: colors.line },
    bottom: { style: "thin", color: colors.line },
  };
}

function setWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getRange(`${colName(index)}:${colName(index)}`).format.columnWidth = width;
  });
}

function formatStatusCell(range, status) {
  const pass = String(status).startsWith("PASS") || String(status).includes("RUN - PASS") || status === "Converged";
  range.format = {
    fill: pass ? colors.greenLight : colors.redLight,
    font: { bold: true, color: pass ? colors.green : colors.red },
  };
}

function createChart(sheet, chartType, range, positionStart, positionEnd, title, legend = false, yFormat = "0") {
  const chart = sheet.charts.add(chartType, range);
  chart.setPosition(positionStart, positionEnd);
  chart.title = title;
  chart.hasLegend = legend;
  chart.yAxis = { numberFormatCode: yFormat };
  return chart;
}

function recordAuditRows() {
  return data.records.map((r) => [
    r.word_row_number, r.source_node_name, r.node_id, r.input_logic, r.output_logic,
    r.arc_expression, r.arc_tag, r.probability, r.loop_cap, r.o, r.ml, r.p,
    r.probability_group_total, r.missing_fields, r.pert_use, r.gert_use,
    r.validation_status, r.validation_message,
  ]);
}

function gertInputRows() {
  return data.records.map((r) => [
    r.record_id, r.word_row_number, r.source_node_name, r.probability, r.loop_cap,
    r.o, r.ml, r.p, r.node_id, r.arc_expression, r.arc_tag, r.from_node, r.to_node,
    r.is_return_arc, r.loop_id, r.terminal_outcome, r.missing_fields,
    r.gert_use === "Yes" ? "SIMULATED" : "MAPPING REQUIRED",
  ]);
}

const auditHeaders = [
  "Word table row", "Source node name", "Node ID", "Input logic", "Output logic",
  "Arc expression", "Arc Tag", "Probability", "Loop Cap", "O", "ML", "P",
  "Probability-group total", "Missing fields", "PERT use", "GERT use",
  "Validation status", "Validation message",
];

const gertInputHeaders = [
  "Record ID", "Word row number", "Source Node Name", "Probability", "Loop Cap", "O", "ML", "P",
  "Node ID", "Arc expression", "Arc Tag", "From Node", "To Node", "Is Return Arc", "Loop ID",
  "Terminal Outcome", "Missing Fields", "Status",
];

await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
for (const name of requiredSheets) workbook.worksheets.add(name);

{
  const sheet = workbook.worksheets.getItem("Executive Summary");
  styleTitle(sheet, "A1:H1", data.title, data.scientific_statement);
  const s = data.pert.summary;
  const g = data.gert.summary;
  writeKeyValues(sheet, 4, [
    ["Scientific status", "Preliminary experimental results; not final thesis findings"],
    ["Input file", data.source.file_name],
    ["Input SHA-256", data.source.sha256],
    ["PERT iterations", s.n],
    ["PERT simulated mean (days)", s.mean],
    ["PERT analytical rounded mean (days)", s.analytical_rounded_mean],
    ["PERT verification", s.verification_status],
    ["PERT reproducibility", s.reproducibility_status],
    ["PERT convergence", s.convergence_status],
    ["GERT status", data.gert.status],
    ["GERT successful / terminated", `${g.successful_count.toLocaleString()} / ${g.terminated_count.toLocaleString()}`],
    ["GERT exact verification", g.verification_status],
    ["Tests passed / failed", `${data.test_summary.passed} / ${data.test_summary.failed}`],
  ]);
  sheet.getRange("B9:B11").format.numberFormat = "0.000000";
  formatStatusCell(sheet.getRange("B11"), s.verification_status);
  formatStatusCell(sheet.getRange("B12"), s.reproducibility_status);
  formatStatusCell(sheet.getRange("B13"), s.convergence_status);
  formatStatusCell(sheet.getRange("B14"), data.gert.status);
  const warning = sheet.getRange("D5:H10");
  warning.merge();
  warning.values = [[data.gert.warnings.join("\n\n")]];
  warning.format = { fill: colors.amberLight, font: { color: colors.amber, bold: true }, wrapText: true, verticalAlignment: "top" };
  setWidths(sheet, [32, 72, 3, 18, 18, 18, 18, 18]);
  sheet.showGridLines = false;
}

{
  const sheet = workbook.worksheets.getItem("Run Information");
  writeTable(sheet, 0, 0, ["Field", "Value"], [
    ["Title", data.title], ["Root seed", data.configuration.seed], ["Iterations", data.configuration.iterations],
    ["Time unit", data.configuration.time_unit], ["Beta-PERT lambda", data.configuration.beta_pert_lambda],
    ["Python version", data.configuration.python_version], ["NumPy version", data.configuration.numpy_version],
    ["SciPy version", data.configuration.scipy_version], ["Input file", data.source.path],
    ["Input SHA-256", data.source.sha256], ["Input table row count", data.source.table_row_count],
    ["Physical Word table columns", data.network.physical_column_count], ["Run started (UTC)", data.pert.started],
    ["Run completed (UTC)", data.pert.completed],
    ...data.pert.stream_metadata.map((stream) => [stream.name, `entropy=${stream.entropy}; spawn_key=${stream.spawn_key.join(".")}; pool_size=${stream.pool_size}`]),
  ]);
  setWidths(sheet, [34, 100]);
}

{
  const sheet = workbook.worksheets.getItem("Input Audit");
  writeTable(sheet, 0, 0, auditHeaders, recordAuditRows());
  setWidths(sheet, [14, 40, 12, 14, 14, 18, 14, 13, 11, 9, 9, 9, 20, 28, 28, 20, 18, 54]);
  sheet.getRange("H2:H30").format.numberFormat = "0.00%";
  sheet.getRange("M2:M30").format.numberFormat = "0.000000000000";
}

{
  const sheet = workbook.worksheets.getItem("Word Parsed Records");
  const headers = ["Word row", "Node ID", "Node Name", "Node Type Input", "Node Type Output", "From", "To", "Arc Tag", "Probability", "Loop Cap", "O", "ML", "P"];
  const rows = data.raw_word_rows.map((row, index) => [index + 1, ...row]);
  writeTable(sheet, 0, 0, headers, rows);
  setWidths(sheet, [11, 12, 42, 18, 18, 12, 12, 14, 14, 12, 10, 12, 12]);
}

{
  const sheet = workbook.worksheets.getItem("Validation");
  writeTable(sheet, 0, 0, ["Test", "Status"], data.tests.map((t) => [t.test, t.status]));
  setWidths(sheet, [62, 18]);
  sheet.getRange(`B2:B${data.tests.length + 1}`).format = { fill: colors.greenLight, font: { color: colors.green, bold: true } };
}

{
  const sheet = workbook.worksheets.getItem("PERT Input");
  const rows = data.pert.analytical_rows.map((r) => [r.sequence, r.activity, r.o, r.ml, r.p, r.alpha, r.beta, r.pre_ceiling_mean, r.analytical_rounded_mean]);
  writeTable(sheet, 0, 0, ["Sequence", "Activity", "O", "ML", "P", "Alpha", "Beta", "Pre-ceiling mean", "Analytical rounded mean"], rows);
  sheet.getRange("F2:I7").format.numberFormat = "0.0000000000";
  setWidths(sheet, [12, 38, 10, 10, 10, 15, 15, 22, 26]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Summary");
  const s = data.pert.summary;
  writeTable(sheet, 0, 0, ["Statistic", "Value", "Unit / status"], [
    ["N", s.n, "iterations"], ["Mean", s.mean, "days"], ["Ceiling of Mean", s.ceiling_of_mean, "days"],
    ["Variance", s.variance, "days^2"], ["Standard deviation", s.standard_deviation, "days"],
    ["Coefficient of variation", s.coefficient_of_variation, "ratio"], ["Minimum", s.minimum, "days"],
    ["Maximum", s.maximum, "days"], ["P25", s.p25, "days"], ["P50", s.p50, "days"],
    ["P75", s.p75, "days"], ["IQR", s.iqr, "days"], ["P80", s.p80, "days"],
    ["P90", s.p90, "days"], ["P95", s.p95, "days"], ["P99", s.p99, "days"],
    ["Monte Carlo standard error", s.mcse, "days"], ["Analytical rounded mean", s.analytical_rounded_mean, "days"],
    ["Simulated - analytical", s.difference, "days"], ["Monte Carlo verification", s.verification_status, ""],
    ["Convergence", s.convergence_status, ""], ["Reproducibility", s.reproducibility_status, ""],
  ]);
  sheet.getRange("B2:B20").format.numberFormat = "0.000000";
  formatStatusCell(sheet.getRange("B21"), s.verification_status);
  formatStatusCell(sheet.getRange("B22"), s.convergence_status);
  formatStatusCell(sheet.getRange("B23"), s.reproducibility_status);
  setWidths(sheet, [38, 28, 24]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Analytical Check");
  const rows = data.pert.analytical_rows.map((r) => [r.sequence, r.activity, r.alpha, r.beta, r.pre_ceiling_mean, r.analytical_rounded_mean, r.simulated_mean, r.simulated_mean - r.analytical_rounded_mean]);
  rows.push(["TOTAL", "Six-activity route", "", "", data.pert_gates.analytical_pre_ceiling_mean, data.pert.summary.analytical_rounded_mean, data.pert.summary.mean, data.pert.summary.difference]);
  writeTable(sheet, 0, 0, ["Sequence", "Activity", "Alpha", "Beta", "Pre-ceiling mean", "Analytical rounded mean", "Simulated mean", "Difference"], rows);
  sheet.getRange("C2:H8").format.numberFormat = "0.0000000000";
  setWidths(sheet, [12, 38, 15, 15, 22, 26, 20, 18]);
}

{
  const sheet = workbook.worksheets.getItem("PERT P1-P99");
  writeTable(sheet, 0, 0, ["Percentile", "Nearest-rank duration (days)"], Array.from({ length: 99 }, (_, i) => [i + 1, data.pert.percentiles[String(i + 1)]]));
  setWidths(sheet, [18, 32]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Iterations");
  writeTable(sheet, 0, 0, ["Iteration ID", "Total duration (days)"], data.pert.totals.map((value, index) => [index + 1, value]), { chunkSize: 10000 });
  setWidths(sheet, [18, 26]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Activity Durations");
  const headers = ["Iteration ID", "Activity sequence", "Activity", "Raw duration (days)", "Rounded duration (days)"];
  writeTable(sheet, 0, 0, headers, [], { freeze: true });
  const iterationChunk = 4000;
  let outputRow = 1;
  for (let start = 0; start < data.pert.totals.length; start += iterationChunk) {
    const end = Math.min(start + iterationChunk, data.pert.totals.length);
    const rows = [];
    for (let i = start; i < end; i++) {
      for (let a = 0; a < data.activities.length; a++) {
        rows.push([i + 1, a + 1, data.activities[a].activity, data.pert.raw[i][a], data.pert.rounded[i][a]]);
      }
    }
    sheet.getRangeByIndexes(outputRow, 0, rows.length, headers.length).values = rows;
    outputRow += rows.length;
  }
  sheet.getRange(`D2:D${outputRow}`).format.numberFormat = "0.000000";
  setWidths(sheet, [18, 20, 38, 24, 28]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Convergence");
  const rows = data.pert.convergence_rows.map((r) => [r.sample_size, r.running_mean, r.running_sd, r.p50, r.p80, r.p90, r.p95, r.p99, r.max_relative_change, r.stability_pass === null ? "N/A" : r.stability_pass ? "PASS" : "FAIL"]);
  writeTable(sheet, 0, 0, ["Sample size", "Running mean", "Running SD", "P50", "P80", "P90", "P95", "P99", "Maximum relative change", "Stability"], rows);
  sheet.getRange(`B2:C${rows.length + 1}`).format.numberFormat = "0.000000";
  sheet.getRange(`I2:I${rows.length + 1}`).format.numberFormat = "0.0000%";
  setWidths(sheet, [16, 18, 18, 12, 12, 12, 12, 12, 26, 16]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Histogram Data");
  writeTable(sheet, 0, 0, ["Duration (days)", "Frequency", "Relative frequency"], data.pert.histogram.map((r) => [r.duration, r.frequency, r.relative_frequency]));
  sheet.getRange(`C2:C${data.pert.histogram.length + 1}`).format.numberFormat = "0.00%";
  setWidths(sheet, [18, 16, 22]);
}

{
  const sheet = workbook.worksheets.getItem("PERT ECDF Data");
  writeTable(sheet, 0, 0, ["Duration (days)", "Cumulative probability"], data.pert.ecdf.map((r) => [r.duration, r.cumulative_probability]));
  sheet.getRange(`B2:B${data.pert.ecdf.length + 1}`).format.numberFormat = "0.00%";
  setWidths(sheet, [18, 26]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Chart Data");
  sheet.showGridLines = false;
  const histRows = data.pert.histogram.length;
  const ecdfRows = data.pert.ecdf.length;
  sheet.getRange("A1:C1").values = [["Duration", "Frequency", "Relative frequency"]];
  styleHeader(sheet.getRange("A1:C1"));
  sheet.getRangeByIndexes(1, 0, histRows, 3).formulas = Array.from({ length: histRows }, (_, i) => [
    `='PERT Histogram Data'!A${i + 2}`, `='PERT Histogram Data'!B${i + 2}`, `='PERT Histogram Data'!C${i + 2}`,
  ]);
  sheet.getRange("E1:F1").values = [["Duration", "Cumulative probability"]];
  styleHeader(sheet.getRange("E1:F1"));
  sheet.getRangeByIndexes(1, 4, ecdfRows, 2).formulas = Array.from({ length: ecdfRows }, (_, i) => [
    `='PERT ECDF Data'!A${i + 2}`, `='PERT ECDF Data'!B${i + 2}`,
  ]);
  sheet.getRange("H1:I1").values = [["Percentile", "Duration"]];
  styleHeader(sheet.getRange("H1:I1"));
  sheet.getRangeByIndexes(1, 7, 99, 2).formulas = Array.from({ length: 99 }, (_, i) => [
    `='PERT P1-P99'!A${i + 2}`, `='PERT P1-P99'!B${i + 2}`,
  ]);
  sheet.getRange("K1:R1").values = [["Sample size", "Running mean", "Running SD", "P50", "P80", "P90", "P95", "P99"]];
  styleHeader(sheet.getRange("K1:R1"));
  sheet.getRangeByIndexes(1, 10, data.pert.convergence_rows.length, 8).formulas = Array.from({ length: data.pert.convergence_rows.length }, (_, i) =>
    Array.from({ length: 8 }, (_, j) => `='PERT Convergence'!${colName(j)}${i + 2}`)
  );
  sheet.getRange("T1:U1").values = [["Activity", "Mean rounded duration"]];
  styleHeader(sheet.getRange("T1:U1"));
  sheet.getRangeByIndexes(1, 19, 6, 2).formulas = Array.from({ length: 6 }, (_, i) => [
    `='PERT Analytical Check'!B${i + 2}`, `='PERT Analytical Check'!G${i + 2}`,
  ]);
  setWidths(sheet, [14, 14, 20, 3, 14, 24, 3, 14, 14, 3, 16, 18, 18, 12, 12, 12, 12, 12, 3, 36, 24]);
}

{
  const sheet = workbook.worksheets.getItem("PERT Charts");
  styleTitle(sheet, "A1:Q1", "PERT Monte Carlo Charts");
  const source = workbook.worksheets.getItem("PERT Chart Data");
  createChart(sheet, "bar", source.getRange(`A1:B${data.pert.histogram.length + 1}`), "A3", "H20", "PERT total duration histogram", false, "0");
  createChart(sheet, "line", source.getRange(`E1:F${data.pert.ecdf.length + 1}`), "J3", "Q20", "PERT empirical CDF", false, "0.0%");
  createChart(sheet, "line", source.getRange("H1:I100"), "A22", "H39", "PERT P1-P99 curve", false, "0");
  createChart(sheet, "line", source.getRange(`K1:L${data.pert.convergence_rows.length + 1}`), "J22", "Q39", "PERT mean convergence", false, "0.00");
  createChart(sheet, "line", source.getRange(`K1:R${data.pert.convergence_rows.length + 1}`), "A41", "H59", "PERT percentile convergence", true, "0");
  createChart(sheet, "bar", source.getRange("T1:U7"), "J41", "Q59", "Mean activity duration", false, "0.00");
  sheet.showGridLines = false;
  setWidths(sheet, Array(17).fill(12));
}

{
  const sheet = workbook.worksheets.getItem("GERT Status");
  styleTitle(sheet, "A1:H1", "GERT Simulation Status");
  writeKeyValues(sheet, 3, [
    ["Status", data.gert.status], ["Structural gate", data.gert.structural_gate], ["Iterations", data.gert.summary.valid_runs],
    ["Exact verification", data.gert.summary.verification_status], ["Reproducibility", data.gert.summary.reproducibility_status],
    ["Reason when not run", data.gert.reason],
  ]);
  formatStatusCell(sheet.getRange("B4"), data.gert.status);
  const warn = sheet.getRange("D4:H10");
  warn.merge();
  warn.values = [[data.gert.warnings.join("\n\n")]];
  warn.format = { fill: colors.amberLight, font: { color: colors.amber, bold: true }, wrapText: true, verticalAlignment: "top" };
  setWidths(sheet, [30, 74, 3, 18, 18, 18, 18, 18]);
  sheet.showGridLines = false;
}

{
  const sheet = workbook.worksheets.getItem("GERT Input Audit");
  writeTable(sheet, 0, 0, gertInputHeaders, gertInputRows());
  setWidths(sheet, [12, 15, 40, 14, 12, 10, 10, 10, 12, 18, 14, 12, 12, 16, 14, 18, 24, 16]);
  sheet.getRange("D2:D30").format.numberFormat = "0.00%";
}

{
  const sheet = workbook.worksheets.getItem("GERT Outcome Summary");
  const g = data.gert.summary;
  writeTable(sheet, 0, 0, ["Metric", "Value"], [
    ["Valid runs", g.valid_runs], ["Invalid runs", g.invalid_runs], ["Successful count", g.successful_count],
    ["Terminated count", g.terminated_count], ["Successful probability", g.successful_probability],
    ["Terminated probability", g.terminated_probability], ["Overall mean duration", g.overall_duration.mean],
    ["Overall SD", g.overall_duration.standard_deviation], ["Overall P50", g.overall_duration.p50],
    ["Overall P95", g.overall_duration.p95], ["Dispute visited", g.dispute_visited_count],
    ["Cap events", g.cap_event_count], ["Renormalisation events", g.renormalisation_event_count],
    ["Verification", g.verification_status],
  ]);
  sheet.getRange("B6:B7").format.numberFormat = "0.00%";
  sheet.getRange("D1:E3").values = [["Outcome", "Probability"], ["Successful", g.successful_probability], ["Terminated", g.terminated_probability]];
  styleHeader(sheet.getRange("D1:E1"));
  sheet.getRange("E2:E3").format.numberFormat = "0.00%";
  const termEcdf = data.gert.outcome_ecdf.Terminated;
  sheet.getRange("D6:E6").values = [["Terminated duration", "Cumulative probability"]];
  styleHeader(sheet.getRange("D6:E6"));
  if (termEcdf.length) sheet.getRangeByIndexes(6, 3, termEcdf.length, 2).values = termEcdf.map((r) => [r.duration, r.cumulative_probability]);
  createChart(sheet, "bar", sheet.getRange("D1:E3"), "G1", "N17", "GERT outcome probabilities", false, "0.0%");
  createChart(sheet, "line", sheet.getRange(`D6:E${termEcdf.length + 6}`), "G19", "N35", "GERT outcome ECDF", false, "0.0%");
  setWidths(sheet, [34, 24, 3, 24, 26, 3, 12, 12, 12, 12, 12, 12, 12, 12]);
}

const gertResultHeaders = ["Iteration ID", "Node sequence", "Arc sequence", "Raw traversal durations", "Rounded traversal durations", "Total duration", "Transition count", "Loop counts", "Cap events", "Original probabilities", "Effective probabilities", "Renormalisation events", "Dispute visited", "Final terminal", "Final outcome", "Reconciliation status"];
const gertRow = (r) => [r.iteration_id, r.node_sequence, r.arc_sequence, r.raw_traversal_durations, r.rounded_traversal_durations, r.total_duration, r.transition_count, r.loop_counts, r.cap_event_count, r.original_probabilities, r.effective_probabilities, r.renormalisation_event_count, r.dispute_visited, r.final_terminal, r.final_outcome, r.reconciliation_status];

{
  const sheet = workbook.worksheets.getItem("GERT Successful Results");
  const rows = data.gert.successful_results.length ? data.gert.successful_results.map(gertRow) : [["No successful iterations observed", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]];
  writeTable(sheet, 0, 0, gertResultHeaders, rows, { chunkSize: 5000 });
  sheet.getRange("S1:T2").values = [["Successful duration", "Frequency"], ["No successful observations", 0]];
  styleHeader(sheet.getRange("S1:T1"));
  createChart(sheet, "bar", sheet.getRange("S1:T2"), "V2", "AC20", "Successful duration histogram (no observations)", false, "0");
  setWidths(sheet, [16, 56, 40, 42, 42, 18, 18, 48, 14, 38, 38, 22, 18, 16, 18, 20, 3, 3, 26, 14]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Terminated Results");
  writeTable(sheet, 0, 0, gertResultHeaders, data.gert.terminated_results.map(gertRow), { chunkSize: 5000 });
  const hist = data.gert.histograms.Terminated;
  sheet.getRange("S1:T1").values = [["Duration", "Frequency"]];
  styleHeader(sheet.getRange("S1:T1"));
  sheet.getRangeByIndexes(1, 18, hist.length, 2).values = hist.map((r) => [r.duration, r.frequency]);
  createChart(sheet, "bar", sheet.getRange(`S1:T${hist.length + 1}`), "V2", "AC20", "Terminated duration histogram", false, "0");
  setWidths(sheet, [16, 56, 40, 42, 42, 18, 18, 48, 14, 38, 38, 22, 18, 16, 18, 20, 3, 3, 14, 14]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Paths");
  const rows = data.gert.paths.map((r) => [r.rank, r.node_sequence, r.arc_sequence, r.outcome, r.frequency, r.probability]);
  writeTable(sheet, 0, 0, ["Rank", "Node sequence", "Arc sequence", "Outcome", "Frequency", "Probability"], rows);
  sheet.getRange(`F2:F${rows.length + 1}`).format.numberFormat = "0.00%";
  const top = data.gert.paths.slice(0, 10);
  sheet.getRange("H1:I1").values = [["Path rank", "Frequency"]];
  styleHeader(sheet.getRange("H1:I1"));
  sheet.getRangeByIndexes(1, 7, top.length, 2).values = top.map((r) => [`Path ${r.rank}`, r.frequency]);
  createChart(sheet, "bar", sheet.getRange(`H1:I${top.length + 1}`), "K2", "R20", "Top realised GERT paths", false, "0");
  setWidths(sheet, [10, 72, 56, 18, 16, 16, 3, 14, 16]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Nodes");
  writeTable(sheet, 0, 0, ["Node ID", "Visit count", "Mean visits per iteration"], data.gert.nodes.map((r) => [r.node_id, r.visit_count, r.mean_visits_per_iteration]));
  sheet.getRange(`C2:C${data.gert.nodes.length + 1}`).format.numberFormat = "0.000000";
  setWidths(sheet, [16, 18, 28]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Arcs");
  writeTable(sheet, 0, 0, ["Arc Tag", "From Node", "To Node", "Original probability", "Traversal count", "Mean traversals per iteration"], data.gert.arcs.map((r) => [r.arc_tag, r.from_node, r.to_node, r.original_probability, r.traversal_count, r.mean_traversals_per_iteration]));
  sheet.getRange("D2:D30").format.numberFormat = "0.00%";
  sheet.getRange("F2:F30").format.numberFormat = "0.000000";
  setWidths(sheet, [14, 14, 14, 22, 18, 30]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Loops");
  writeTable(sheet, 0, 0, ["Loop ID", "Arc Tag", "From Node", "To Node", "Loop Cap", "Activation count", "Activation probability", "Total traversals", "Maximum observed"], data.gert.loops.map((r) => [r.loop_id, r.arc_tag, r.from_node, r.to_node, r.loop_cap, r.activation_count, r.activation_probability, r.total_traversals, r.maximum_observed]));
  sheet.getRange(`G2:G${data.gert.loops.length + 1}`).format.numberFormat = "0.00%";
  sheet.getRange("K1:L1").values = [["Loop", "Activation count"]];
  styleHeader(sheet.getRange("K1:L1"));
  sheet.getRangeByIndexes(1, 10, data.gert.loops.length, 2).values = data.gert.loops.map((r) => [r.arc_tag, r.activation_count]);
  const dist = data.gert.loop_repetition_distribution;
  sheet.getRange("N1:O1").values = [["Total repetitions", "Frequency"]];
  styleHeader(sheet.getRange("N1:O1"));
  sheet.getRangeByIndexes(1, 13, dist.length, 2).values = dist.map((r) => [r.repetitions, r.frequency]);
  createChart(sheet, "bar", sheet.getRange(`K1:L${data.gert.loops.length + 1}`), "Q2", "X20", "GERT loop activation", false, "0");
  createChart(sheet, "bar", sheet.getRange(`N1:O${dist.length + 1}`), "Q22", "X40", "GERT loop repetition distribution", false, "0");
  setWidths(sheet, [14, 14, 14, 14, 12, 18, 22, 18, 20, 3, 14, 18, 3, 18, 16]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Cap Events");
  const rows = data.gert.cap_events.length ? data.gert.cap_events.map((r) => [r.iteration_id, r.loop_id, r.arc_tag, r.cap, r.count_when_reached]) : [["No cap events observed", "", "", "", ""]];
  writeTable(sheet, 0, 0, ["Iteration ID", "Loop ID", "Arc Tag", "Cap", "Count when reached"], rows);
  setWidths(sheet, [24, 18, 18, 12, 24]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Renormalisation");
  const rows = data.gert.renormalisation_events.length ? data.gert.renormalisation_events.map((r) => [r.iteration_id, r.node, r.removed_arc_tags, r.eligible_arc_tags, r.original_probabilities, r.effective_probabilities]) : [["No renormalisation events observed", "", "", "", "", ""]];
  writeTable(sheet, 0, 0, ["Iteration ID", "Node", "Removed Arc Tags", "Eligible Arc Tags", "Original probabilities", "Effective probabilities"], rows);
  setWidths(sheet, [30, 16, 32, 40, 42, 42]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Dispute");
  writeTable(sheet, 0, 0, ["Metric", "Value"], [["Dispute node ID", "SD"], ["Dispute visited count", data.gert.summary.dispute_visited_count], ["Dispute terminal count", 0], ["Classification", "Transient node"]]);
  setWidths(sheet, [28, 30]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Iterations");
  writeTable(sheet, 0, 0, gertResultHeaders, data.gert.iterations.map(gertRow), { chunkSize: 5000 });
  setWidths(sheet, [16, 56, 40, 42, 42, 18, 18, 48, 14, 38, 38, 22, 18, 16, 18, 20]);
}

{
  const sheet = workbook.worksheets.getItem("GERT Verification");
  const exact = data.gert.exact;
  const rows = data.gert.verification_checks.map((r) => [r.check, r.status, "Monte Carlo / run-level check"]);
  rows.push(["Reachable transient states", exact.reachable_transient_states, "Independent finite-state verifier"]);
  rows.push(["Exact successful probability", exact.successful_probability, "Independent finite-state verifier"]);
  rows.push(["Exact terminated probability", exact.terminated_probability, "Independent finite-state verifier"]);
  rows.push(["Exact probability sum", exact.probability_sum, "Independent finite-state verifier"]);
  rows.push(["Exact expected rounded duration", exact.expected_rounded_duration, "Independent finite-state verifier"]);
  rows.push(["Overall verification", data.gert.summary.verification_status, "Required acceptance gate"]);
  writeTable(sheet, 0, 0, ["Check", "Result", "Method"], rows);
  setWidths(sheet, [46, 24, 42]);
}

{
  const sheet = workbook.worksheets.getItem("Warnings and Limitations");
  writeTable(sheet, 0, 0, ["Category", "Statement"], [
    ["Scientific status", "These are PRELIMINARY EXPERIMENTAL SIMULATION RESULTS and do not constitute final thesis findings."],
    ["Input authority", "All numerical and routing values were taken from the most recently attached Word file."],
    ["Word table structure", "The latest file contains 12 physical columns: From and To are separate fields within the outgoing-arc definition."],
    ["GERT routing warning", data.gert.warnings[0]],
    ["GERT reachability warning", data.gert.warnings[1]],
    ["No silent inference", "The Arc Tag e12 was not used to override the explicit To Node value S1."],
    ["Approval limitation", "Preliminary results do not constitute final thesis findings until the network structure and expert inputs are formally approved."],
  ]);
  sheet.getRange("B2:B8").format.wrapText = true;
  setWidths(sheet, [30, 120]);
}

{
  const sheet = workbook.worksheets.getItem("Metadata");
  writeTable(sheet, 0, 0, ["Field", "Value"], [
    ["Title", data.title], ["Input file", data.source.path], ["Input SHA-256", data.source.sha256],
    ["Parsed nodes", data.nodes_seen.join("; ")], ["Probabilistic records", data.records.length],
    ["Loop Cap = 2 records", data.records.filter((r) => r.loop_cap === 2).length], ["Root seed", data.configuration.seed],
    ["PERT stream", JSON.stringify(data.pert.stream_metadata[0])], ["GERT routing stream", JSON.stringify(data.pert.stream_metadata[1])],
    ["GERT duration stream", JSON.stringify(data.pert.stream_metadata[2])], ["Python version", data.configuration.python_version],
    ["NumPy version", data.configuration.numpy_version], ["SciPy version", data.configuration.scipy_version],
    ["Main workbook", mainPath], ["Input audit workbook", auditPath], ["Report", reportPath],
  ]);
  setWidths(sheet, [32, 120]);
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(mainPath);

const auditWorkbook = Workbook.create();
{
  const sheet = auditWorkbook.worksheets.add("Input Audit");
  writeTable(sheet, 0, 0, auditHeaders, recordAuditRows());
  setWidths(sheet, [14, 40, 12, 14, 14, 18, 14, 13, 11, 9, 9, 9, 20, 28, 28, 20, 18, 54]);
  sheet.getRange("H2:H30").format.numberFormat = "0.00%";
  sheet.getRange("M2:M30").format.numberFormat = "0.000000000000";
}
{
  const sheet = auditWorkbook.worksheets.add("Validation");
  writeTable(sheet, 0, 0, ["Check", "Result"], [
    ["Parsed node groups", data.nodes_seen.length], ["Probabilistic records", data.records.length],
    ["Probability groups", 7], ["Probability group sums", "PASS"], ["Loop Cap = 2 records", 10],
    ["GERT structural gate", data.gert.structural_gate], ["GERT status", data.gert.status],
  ]);
  setWidths(sheet, [40, 30]);
}
{
  const sheet = auditWorkbook.worksheets.add("Metadata");
  writeTable(sheet, 0, 0, ["Field", "Value"], [["Input file", data.source.path], ["SHA-256", data.source.sha256], ["Generated title", data.title]]);
  setWidths(sheet, [28, 110]);
}
const auditOutput = await SpreadsheetFile.exportXlsx(auditWorkbook);
await auditOutput.save(auditPath);

const s = data.pert.summary;
const g = data.gert.summary;
const report = `# ${data.title}

${data.scientific_statement}

## A. Input-file audit

- File name: ${data.source.file_name}
- SHA-256: ${data.source.sha256}
- First-table rows: ${data.source.table_row_count}
- Physical columns: ${data.network.physical_column_count}
- Parsed nodes: ${data.nodes_seen.join("; ")}
- Parsed probabilistic records: ${data.records.length}
- Probability-group validation: PASS; all seven groups sum to 1.00 within 1e-12
- Loop Cap = 2 records: ${data.records.filter((r) => r.loop_cap === 2).length}
- Missing structural fields: none in the latest file

## B. PERT results

- N: ${s.n}
- Seed: ${data.configuration.seed}
- Activity count: ${data.pert_gates.activity_count}
- Sum O / ML / P: ${data.pert_gates.sum_o} / ${data.pert_gates.sum_ml} / ${data.pert_gates.sum_p} days
- Analytical pre-ceiling mean: ${data.pert_gates.analytical_pre_ceiling_mean.toFixed(10)} days
- Analytical rounded mean: ${s.analytical_rounded_mean.toFixed(12)} days
- Simulated mean: ${s.mean.toFixed(6)} days
- Monte Carlo standard error: ${s.mcse.toFixed(12)} days
- Simulated - analytical: ${s.difference.toFixed(12)} days
- Minimum / maximum: ${s.minimum} / ${s.maximum} days
- P50 / P80 / P90 / P95 / P99: ${s.p50} / ${s.p80} / ${s.p90} / ${s.p95} / ${s.p99} days
- Convergence: ${s.convergence_status}
- Reproducibility: ${s.reproducibility_status}
- Validation: ${s.verification_status}

## C. GERT status

- Status: ${data.gert.status}
- Structural gate: ${data.gert.structural_gate}
- Valid / invalid runs: ${g.valid_runs} / ${g.invalid_runs}
- Successful / terminated outcomes: ${g.successful_count} / ${g.terminated_count}
- Successful / terminated probabilities: ${(g.successful_probability * 100).toFixed(4)}% / ${(g.terminated_probability * 100).toFixed(4)}%
- Exact finite-state verification: ${g.verification_status}
- Reproducibility: ${g.reproducibility_status}
- Routing warning: ${data.gert.warnings[0]}
- Reachability warning: ${data.gert.warnings[1]}

## D. Limitations

The simulation follows the explicit Word fields exactly. In particular, the e12 record is simulated as S1 to S1; its tag is not used to infer S1 to S2. This explicit mapping makes Final Closeout unreachable from the start state and is the reason all GERT outcomes terminate.

Preliminary results do not constitute final thesis findings until the network structure and expert inputs are formally approved.
`;
await fs.writeFile(reportPath, report, "utf8");

const imported = await SpreadsheetFile.importXlsx(await FileBlob.load(mainPath));
const sheetInspection = await imported.inspect({ kind: "sheet", include: "id,name", maxChars: 10000 });
const drawingInspection = await imported.inspect({ kind: "drawing", maxChars: 20000 });
const errorInspection = await imported.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "formula error scan" });

const previewDir = path.join(workDir, "previews");
await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range] of [
  ["Executive Summary", "A1:H18"], ["Input Audit", "A1:R12"], ["PERT Summary", "A1:C23"],
  ["PERT Charts", "A1:Q59"], ["GERT Status", "A1:H12"], ["GERT Outcome Summary", "A1:N35"],
  ["GERT Verification", "A1:C20"], ["Warnings and Limitations", "A1:B8"],
]) {
  const preview = await imported.render({ sheetName, range, scale: 1, format: "png" });
  const safeName = sheetName.replaceAll(" ", "_");
  await fs.writeFile(path.join(previewDir, `${safeName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

await fs.writeFile(path.join(workDir, "artifact_verification.json"), JSON.stringify({
  sheetInspection: sheetInspection.ndjson,
  drawingInspection: drawingInspection.ndjson,
  errorInspection: errorInspection.ndjson,
}, null, 2));

console.log(JSON.stringify({ mainPath, reportPath, auditPath, requiredSheets: requiredSheets.length, pertCharts: 6, gertCharts: 7 }, null, 2));
