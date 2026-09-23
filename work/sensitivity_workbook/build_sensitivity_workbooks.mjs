import fs from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(process.argv[2] || ".");
const outputDir = path.join(root, "outputs", "Sensitivity_Analysis");
const tableDir = path.join(outputDir, "Tables");
const thesisDir = path.join(outputDir, "Thesis_Tables");
const figureDir = path.join(outputDir, "Figures");
const previewDir = path.join(root, "work", "sensitivity_workbook", "previews");

const mainSheets = [
  ["Baseline_Config", "Baseline_Config.csv"],
  ["Baseline_Validation", "Baseline_Validation.csv"],
  ["Sensitivity_Parameters", "Sensitivity_Parameters.csv"],
  ["Routing_OAT", "Routing_OAT.csv"],
  ["Duration_OAT", "Duration_OAT.csv"],
  ["LoopCap_Robustness", "LoopCap_Robustness.csv"],
  ["Distribution_Robustness", "Distribution_Robustness.csv"],
  ["Seed_Robustness", "Seed_Robustness.csv"],
  ["Replication_Convergence", "Replication_Convergence.csv"],
  ["Threshold_Analysis", "Threshold_Analysis.csv"],
  ["CI_Summary", "CI_Summary.csv"],
  ["Tornado_P90_Data", "Tornado_P90_Data.csv"],
  ["Tornado_Outcome_Data", "Tornado_Outcome_Data.csv"],
  ["Integrated_Ranking", "Integrated_Ranking.csv"],
  ["Scenario_Run_Log", "Scenario_Run_Log.csv"],
  ["Validation_Checks", "Validation_Checks.csv"],
  ["Errors_Warnings", "Errors_Warnings.csv"],
  ["Duration_Driver_Screen", "Duration_Driver_Screen.csv"],
];

const thesisSheets = [
  ["Table_4X_Parameters", "Table_4X_Sensitivity_Parameters.csv"],
  ["Table_4Y_Routing_OAT", "Table_4Y_Routing_OAT.csv"],
  ["Table_4Z_Duration_OAT", "Table_4Z_Duration_OAT.csv"],
  ["Table_4W_Robustness", "Table_4W_LoopCap_Distribution.csv"],
  ["Table_4V_Threshold", "Table_4V_Threshold_Analysis.csv"],
  ["Table_4U_Seed_Conv", "Table_4U_Seed_Convergence.csv"],
  ["Table_4T_Ranking", "Table_4T_Integrated_Ranking.csv"],
];

const COLORS = {
  navy: "#12344D",
  teal: "#0B6B69",
  paleTeal: "#D9EEEB",
  paleBlue: "#E8F0F6",
  green: "#E2F2E8",
  greenText: "#23633B",
  amber: "#FFF1CC",
  amberText: "#7A5100",
  red: "#FBE1E1",
  redText: "#8A2424",
  gray: "#64748B",
  paleGray: "#F4F7F9",
  border: "#C8D4DC",
  white: "#FFFFFF",
};

function csvDimensions(csvText) {
  const lines = csvText.trimEnd().split(/\r?\n/);
  const first = lines[0] || "";
  let columns = 1;
  let quoted = false;
  for (let i = 0; i < first.length; i += 1) {
    if (first[i] === '"') {
      if (quoted && first[i + 1] === '"') i += 1;
      else quoted = !quoted;
    } else if (first[i] === "," && !quoted) columns += 1;
  }
  return { rows: lines.length, columns };
}

function columnLetters(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function safeName(value) {
  return value.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 200);
}

function preferredWidth(header) {
  const key = header.toLowerCase();
  if (/(message|method|rule|definition|threshold_result|selection)/.test(key)) return 52;
  if (/(path|sha256|hash)/.test(key)) return 34;
  if (/(parameter_label|metric|check|network_location)/.test(key)) return 30;
  if (/(scenario_id|parameter_id|classification|distribution|analysis)/.test(key)) return 22;
  if (/(status|severity|unit|level|rank|seed)/.test(key)) return 15;
  return 17;
}

function numberFormat(header) {
  const key = header.toLowerCase();
  if (/(count|replications|valid_runs|seed$|rank$|mode_count)/.test(key)) return "#,##0";
  if (/^(p_|probability|.*_probability|.*_rate|.*_frequency|.*_weight)/.test(key)) return "0.0000";
  if (/(ci_low|ci_high|mean|median|p80|p90|p95|time|days|effect|delta|score|deviation|elapsed|bandwidth|bic)/.test(key)) return "0.000";
  return null;
}

function formatImportedSheet(workbook, sheetName, dimensions, tableIndex) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const { rows, columns } = dimensions;
  const used = sheet.getRangeByIndexes(0, 0, rows, columns);
  const header = sheet.getRangeByIndexes(0, 0, 1, columns);
  const values = header.values[0].map((value) => String(value ?? ""));

  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  if (columns > 12) sheet.freezePanes.freezeColumns(2);
  used.format.font = { name: "Aptos", size: 10, color: "#17232D" };
  used.format.verticalAlignment = "center";
  header.format = {
    fill: COLORS.navy,
    font: { name: "Aptos", size: 10, bold: true, color: COLORS.white },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: COLORS.navy },
  };
  header.format.rowHeight = 38;
  if (rows > 1) {
    sheet.getRangeByIndexes(1, 0, rows - 1, columns).format.borders = {
      bottom: { style: "thin", color: "#E5EBEF" },
    };
  }

  for (let col = 0; col < columns; col += 1) {
    const column = sheet.getRangeByIndexes(0, col, rows, 1);
    column.format.columnWidth = preferredWidth(values[col]);
    const format = numberFormat(values[col]);
    if (format && rows > 1) sheet.getRangeByIndexes(1, col, rows - 1, 1).format.numberFormat = format;
  }

  const lastCell = `${columnLetters(columns - 1)}${rows}`;
  if (rows > 1) {
    const table = sheet.tables.add(`A1:${lastCell}`, true, `T${String(tableIndex).padStart(2, "0")}_${safeName(sheetName)}`);
    table.style = "TableStyleMedium2";
    table.showBandedRows = true;
    table.showFilterButton = true;
  }

  const statusIndex = values.findIndex((value) => value === "Status");
  if (statusIndex >= 0 && rows > 1) {
    const statusRange = sheet.getRangeByIndexes(1, statusIndex, rows - 1, 1);
    statusRange.conditionalFormats.add("containsText", { text: "PASS", format: { fill: COLORS.green, font: { bold: true, color: COLORS.greenText } } });
    statusRange.conditionalFormats.add("containsText", { text: "FAIL", format: { fill: COLORS.red, font: { bold: true, color: COLORS.redText } } });
  }
  const severityIndex = values.findIndex((value) => value === "Severity");
  if (severityIndex >= 0 && rows > 1) {
    const severityRange = sheet.getRangeByIndexes(1, severityIndex, rows - 1, 1);
    severityRange.conditionalFormats.add("containsText", { text: "WARNING", format: { fill: COLORS.amber, font: { bold: true, color: COLORS.amberText } } });
    severityRange.conditionalFormats.add("containsText", { text: "LIMITATION", format: { fill: COLORS.paleBlue, font: { color: COLORS.navy } } });
  }
  const influenceIndex = values.findIndex((value) => value === "Normalised_Influence_Score");
  if (influenceIndex >= 0 && rows > 1) {
    sheet.getRangeByIndexes(1, influenceIndex, rows - 1, 1).conditionalFormats.add("dataBar", { color: COLORS.teal, gradient: true });
  }
}

async function importCsvSheets(workbook, directory, definitions, startIndex = 1) {
  const dimensionsBySheet = new Map();
  for (let index = 0; index < definitions.length; index += 1) {
    const [sheetName, fileName] = definitions[index];
    const csvText = await fs.readFile(path.join(directory, fileName), "utf8");
    const dimensions = csvDimensions(csvText);
    const imported = await Workbook.fromCSV(csvText, { sheetName });
    const importedSheet = imported.worksheets.getItem(sheetName);
    const values = importedSheet.getRangeByIndexes(0, 0, dimensions.rows, dimensions.columns).values;
    const sheet = workbook.worksheets.add(sheetName);
    sheet.getRangeByIndexes(0, 0, dimensions.rows, dimensions.columns).values = values;
    formatImportedSheet(workbook, sheetName, dimensions, startIndex + index);
    dimensionsBySheet.set(sheetName, dimensions);
  }
  return dimensionsBySheet;
}

function addReadme(workbook) {
  const sheet = workbook.worksheets.add("README");
  sheet.showGridLines = false;
  sheet.getRange("A1:H1").merge();
  sheet.getRange("A1").values = [["PERT-MCS and GERT-MCS Sensitivity & Robustness Results"]];
  sheet.getRange("A1:H1").format = {
    fill: COLORS.navy,
    font: { name: "Aptos Display", size: 20, bold: true, color: COLORS.white },
    verticalAlignment: "center",
  };
  sheet.getRange("A1:H1").format.rowHeight = 40;
  sheet.getRange("A3:B10").values = [
    ["Purpose", "Consolidated, analysis-ready outputs for the verified preliminary PERT-MCS and GERT-MCS sensitivity and robustness study."],
    ["Analysis version", "1.0.0"],
    ["Generated date", "2026-07-31"],
    ["Baseline", "50,000 replications; root seed 42; Beta-PERT lambda 4; upward rounding once per activity/traversal."],
    ["Routing OAT", "+/-25% relative perturbation with proportional within-XOR renormalisation and a 0.99 upper guard."],
    ["Duration OAT", "Five screened transitions; coherent +/-10% scaling of optimistic, most-likely, and pessimistic values."],
    ["Robustness", "Loop caps baseline +/-1, triangular duration alternative, 10 fixed seeds, and 1k-50k convergence prefixes."],
    ["Uncertainty", "95% mean CIs, Wilson probability CIs, and 1,000-resample empirical bootstrap quantile CIs."],
  ];
  sheet.getRange("A3:A10").format = { fill: COLORS.paleTeal, font: { bold: true, color: COLORS.navy } };
  sheet.getRange("B3:B10").format.wrapText = true;

  sheet.getRange("A12:D12").merge();
  sheet.getRange("A12").values = [["Reproducibility audit"]];
  sheet.getRange("A12:D12").format = { fill: COLORS.teal, font: { bold: true, color: COLORS.white } };
  sheet.getRange("A13:B19").values = [
    ["Audit item", "Workbook result"],
    ["Executed full simulations", null],
    ["Passed run validations", null],
    ["Passed baseline checks", null],
    ["Failed simulation scenarios", null],
    ["PNG figures", 12],
    ["SVG figures", 12],
  ];
  sheet.getRange("B14").formulas = [["=COUNTA('Scenario_Run_Log'!A2:A112)"]];
  sheet.getRange("B15").formulas = [["=COUNTIF('Validation_Checks'!E2:E9,\"PASS\")"]];
  sheet.getRange("B16").formulas = [["=COUNTIF('Baseline_Validation'!G2:G15,\"PASS\")"]];
  sheet.getRange("B17").formulas = [["=COUNTIF('Scenario_Run_Log'!M2:M112,\"FAIL\")"]];
  sheet.getRange("A13:B13").format = { fill: COLORS.navy, font: { bold: true, color: COLORS.white } };
  sheet.getRange("A14:A19").format = { fill: COLORS.paleGray, font: { bold: true, color: COLORS.navy } };
  sheet.getRange("B14:B19").format.numberFormat = "#,##0";
  sheet.getRange("B14:B19").conditionalFormats.add("cellIs", { operator: "greaterThanOrEqual", formula: 0, format: { font: { color: COLORS.greenText } } });

  sheet.getRange("A21:H21").merge();
  sheet.getRange("A21").values = [["Interpretation and limits"]];
  sheet.getRange("A21:H21").format = { fill: COLORS.teal, font: { bold: true, color: COLORS.white } };
  sheet.getRange("A22:H27").values = [
    ["Sensitivity is an intervention analysis; the duration-driver screen is only a selection aid and is not treated as causal evidence.", null, null, null, null, null, null, null],
    ["Successful-closure completion measures are conditional on Successful Closure. Mixed-outcome time is separately labelled.", null, null, null, null, null, null, null],
    ["The early-exit threshold classification combines Silverman KDE mode prominence with one- versus two-component Gaussian-mixture BIC.", null, null, null, null, null, null, null],
    ["No completion threshold Tc was supplied; exceedance probability is blank rather than invented.", null, null, null, null, null, null, null],
    ["No expert perturbation intervals were supplied; documented fallback ranges are therefore used.", null, null, null, null, null, null, null],
    ["Authoritative inputs were read from byte-identical verified package copies because the Desktop originals were unavailable.", null, null, null, null, null, null, null],
  ];
  sheet.getRange("A22:H27").merge(true);
  sheet.getRange("A22:H27").format = { wrapText: true, fill: COLORS.paleGray, font: { color: "#253746" } };
  sheet.getRange("A22:H27").format.rowHeight = 31;
  sheet.getRange("A1:H27").format.font.name = "Aptos";
  sheet.getRange("A1:A27").format.columnWidth = 28;
  sheet.getRange("B1:B27").format.columnWidth = 72;
  sheet.getRange("C1:H27").format.columnWidth = 14;
  sheet.freezePanes.freezeRows(1);
}

async function addFigureGallery(workbook) {
  const sheet = workbook.worksheets.add("Figures");
  sheet.showGridLines = false;
  sheet.getRange("A1:Q1").merge();
  sheet.getRange("A1").values = [["Publication Figure Gallery"]];
  sheet.getRange("A1:Q1").format = { fill: COLORS.navy, font: { name: "Aptos Display", size: 18, bold: true, color: COLORS.white } };
  sheet.getRange("A1:Q1").format.rowHeight = 36;
  for (let col = 0; col < 17; col += 1) sheet.getRangeByIndexes(0, col, 135, 1).format.columnWidth = 11;
  const names = (await fs.readdir(figureDir)).filter((name) => name.toLowerCase().endsWith(".png")).sort();
  for (let index = 0; index < names.length; index += 1) {
    const row = 2 + Math.floor(index / 2) * 22;
    const col = index % 2 === 0 ? 0 : 9;
    const captionRange = sheet.getRangeByIndexes(row, col, 1, 8);
    captionRange.merge();
    captionRange.values = [[names[index].replace(/\.png$/i, "").replaceAll("_", " ")]];
    captionRange.format = { fill: COLORS.paleTeal, font: { bold: true, color: COLORS.navy }, wrapText: true };
    const bytes = await fs.readFile(path.join(figureDir, names[index]));
    sheet.images.add({
      dataUrl: `data:image/png;base64,${bytes.toString("base64")}`,
      anchor: { from: { row: row + 1, col }, extent: { widthPx: 545, heightPx: 340 } },
    });
  }
  sheet.freezePanes.freezeRows(1);
}

async function renderWorkbook(workbook, folder, sheetNames) {
  await fs.mkdir(folder, { recursive: true });
  const files = [];
  for (const sheetName of sheetNames) {
    const isReadme = sheetName === "README";
    const isFigures = sheetName === "Figures";
    const preview = await workbook.render({
      sheetName,
      range: isReadme ? "A1:H27" : (isFigures ? "A1:Q134" : "A1:L20"),
      scale: isFigures ? 0.55 : 0.9,
      format: "png",
    });
    const file = path.join(folder, `${safeName(sheetName)}.png`);
    await fs.writeFile(file, new Uint8Array(await preview.arrayBuffer()));
    files.push(file);
  }
  return files;
}

async function makeContactSheet(files, destination, title) {
  const tileWidth = 420;
  const tileHeight = 280;
  const columns = 3;
  const rows = Math.ceil(files.length / columns);
  const composites = [];
  for (let index = 0; index < files.length; index += 1) {
    const image = await sharp(files[index]).resize({ width: tileWidth - 20, height: tileHeight - 42, fit: "contain", background: "#FFFFFF" }).png().toBuffer();
    composites.push({ input: image, left: (index % columns) * tileWidth + 10, top: Math.floor(index / columns) * tileHeight + 38 });
    const label = path.basename(files[index], ".png").replaceAll("_", " ");
    const labelSvg = Buffer.from(`<svg width="${tileWidth - 20}" height="28"><text x="4" y="19" font-family="Arial" font-size="14" font-weight="700" fill="#12344D">${label}</text></svg>`);
    composites.push({ input: labelSvg, left: (index % columns) * tileWidth + 10, top: Math.floor(index / columns) * tileHeight + 8 });
  }
  const titleSvg = Buffer.from(`<svg width="${columns * tileWidth}" height="34"><rect width="100%" height="100%" fill="#12344D"/><text x="14" y="23" font-family="Arial" font-size="18" font-weight="700" fill="#FFFFFF">${title}</text></svg>`);
  const canvas = sharp({ create: { width: columns * tileWidth, height: rows * tileHeight + 34, channels: 4, background: "#EEF3F6" } });
  await canvas.composite([{ input: titleSvg, left: 0, top: 0 }, ...composites.map((entry) => ({ ...entry, top: entry.top + 34 }))]).png().toFile(destination);
}

async function validateWorkbook(workbook, keyRange) {
  const key = await workbook.inspect({ kind: "table", range: keyRange, include: "values,formulas", tableMaxRows: 20, tableMaxCols: 12, maxChars: 6000 });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
    maxChars: 4000,
  });
  return { key: key.ndjson, errors: errors.ndjson };
}

async function buildMainWorkbook() {
  const workbook = Workbook.create();
  addReadme(workbook);
  await importCsvSheets(workbook, tableDir, mainSheets, 1);
  await addFigureGallery(workbook);
  const sheetNames = ["README", ...mainSheets.map(([name]) => name), "Figures"];
  const inspections = await validateWorkbook(workbook, "README!A1:H27");
  const previews = await renderWorkbook(workbook, path.join(previewDir, "main"), sheetNames);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  const destination = path.join(outputDir, "Sensitivity_and_Robustness_Results.xlsx");
  await output.save(destination);
  await makeContactSheet(previews, path.join(previewDir, "Sensitivity_Workbook_Contact_Sheet.png"), "Sensitivity workbook sheet previews");
  return { destination, sheetNames, inspections };
}

async function buildThesisWorkbook() {
  const workbook = Workbook.create();
  await importCsvSheets(workbook, thesisDir, thesisSheets, 101);
  const sheetNames = thesisSheets.map(([name]) => name);
  const inspections = await validateWorkbook(workbook, `${sheetNames[0]}!A1:L20`);
  const previews = await renderWorkbook(workbook, path.join(previewDir, "thesis"), sheetNames);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  const destination = path.join(outputDir, "Thesis_Ready_Tables.xlsx");
  await output.save(destination);
  await makeContactSheet(previews, path.join(previewDir, "Thesis_Workbook_Contact_Sheet.png"), "Thesis-ready table previews");
  return { destination, sheetNames, inspections };
}

await fs.mkdir(previewDir, { recursive: true });
const main = await buildMainWorkbook();
const thesis = await buildThesisWorkbook();
const publicationFigures = (await fs.readdir(figureDir))
  .filter((name) => name.toLowerCase().endsWith(".png"))
  .sort()
  .map((name) => path.join(figureDir, name));
await makeContactSheet(
  publicationFigures,
  path.join(previewDir, "Publication_Figures_Contact_Sheet.png"),
  "Publication figure previews",
);
const manifest = {
  generated_utc: new Date().toISOString(),
  main_workbook: main.destination,
  main_sheet_count: main.sheetNames.length,
  main_sheets: main.sheetNames,
  thesis_workbook: thesis.destination,
  thesis_sheet_count: thesis.sheetNames.length,
  thesis_sheets: thesis.sheetNames,
  main_formula_error_scan: main.inspections.errors,
  thesis_formula_error_scan: thesis.inspections.errors,
};
await fs.writeFile(path.join(outputDir, "workbook_validation_manifest.json"), JSON.stringify(manifest, null, 2));
console.log(JSON.stringify(manifest, null, 2));
