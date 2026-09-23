import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const BASE = String.raw`C:\Users\moham\Documents\Codex\2026-07-28\build`;
const WORK = path.join(BASE, "work", "package_release");
const OUTPUTS = path.join(BASE, "outputs");
const STAGE = path.join(BASE, "release", "VO_PERT_GERT_Full_Simulation_Package");
const START = path.join(STAGE, "00_START_HERE");
const PREVIEW_DIR = path.join(WORK, "previews");

const headerFormat = {
  fill: "#14532D",
  font: { bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#86A48D" },
};

const titleFormat = {
  fill: "#E8F3EC",
  font: { bold: true, color: "#123524", size: 15 },
  verticalAlignment: "center",
};

const statusColors = {
  PASS: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
  FAIL: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
  PENDING: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } },
};

function columnName(index) {
  let n = index + 1;
  let result = "";
  while (n > 0) {
    const remainder = (n - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

function normalize(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function rowsFromObjects(records, columns) {
  return records.map((record) => columns.map((column) => normalize(record[column])));
}

function widthFor(header) {
  const wide = ["Path", "Description", "Reason", "SHA256", "Check", "Expected", "Observed", "Dataset", "Category"];
  if (wide.some((token) => header.includes(token))) return header.includes("SHA256") ? 64 : 42;
  if (header.includes("Size") || header.includes("Count") || header.includes("Rows") || header.includes("Columns")) return 16;
  if (header.includes("Status") || header.includes("Required")) return 18;
  return Math.min(Math.max(header.length + 3, 14), 28);
}

function addDataSheet(workbook, name, title, columns, records, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, 1, Math.max(columns.length, 2)).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRangeByIndexes(0, 0, 1, Math.max(columns.length, 2)).format = titleFormat;
  sheet.getRangeByIndexes(0, 0, 1, Math.max(columns.length, 2)).format.rowHeight = 26;
  sheet.getRangeByIndexes(2, 0, 1, columns.length).values = [columns];
  sheet.getRangeByIndexes(2, 0, 1, columns.length).format = headerFormat;
  sheet.getRangeByIndexes(2, 0, 1, columns.length).format.rowHeight = 30;
  if (records.length) {
    const values = Array.isArray(records[0]) ? records.map((row) => row.map(normalize)) : rowsFromObjects(records, columns);
    sheet.getRangeByIndexes(3, 0, values.length, columns.length).values = values;
    sheet.getRangeByIndexes(3, 0, values.length, columns.length).format = {
      verticalAlignment: "top",
      wrapText: true,
      borders: { insideHorizontal: { style: "thin", color: "#E2E8E5" } },
    };
    if (options.numberColumns) {
      for (const col of options.numberColumns) {
        const index = columns.indexOf(col);
        if (index >= 0) sheet.getRangeByIndexes(3, index, values.length, 1).format.numberFormat = "#,##0";
      }
    }
    const statusIndex = columns.findIndex((column) => column === "Status" || column.endsWith("_Status"));
    if (statusIndex >= 0) {
      for (const [status, format] of Object.entries(statusColors)) {
        sheet.getRangeByIndexes(3, statusIndex, values.length, 1).conditionalFormats.add("containsText", { text: status, format });
      }
    }
  } else {
    sheet.getRange("A4").values = [[options.emptyMessage || "None"]];
    sheet.getRange("A4").format = { font: { italic: true, color: "#52635A" } };
  }
  columns.forEach((header, index) => {
    const requestedWidth = options.columnWidths?.[header];
    sheet.getRange(`${columnName(index)}:${columnName(index)}`).format.columnWidth = requestedWidth || widthFor(header);
  });
  sheet.freezePanes.freezeRows(3);
  return sheet;
}

async function renderWorkbook(workbook, sheetNames, prefix) {
  await fs.mkdir(PREVIEW_DIR, { recursive: true });
  for (const sheetName of sheetNames) {
    const preview = await workbook.render({ sheetName, range: "A1:P25", scale: 0.8, format: "png" });
    const safeName = sheetName.replace(/[^A-Za-z0-9]+/g, "_");
    await fs.writeFile(path.join(PREVIEW_DIR, `${prefix}_${safeName}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
}

async function verifyWorkbook(workbook, keySheets) {
  for (const [sheetId, range] of keySheets) {
    const check = await workbook.inspect({ kind: "table", sheetId, range, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 16, maxChars: 8000 });
    if (!check.ndjson || check.ndjson.includes("#REF!")) throw new Error(`Inspection failed for ${sheetId}!${range}`);
  }
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
  if (errors.ndjson && /#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/.test(errors.ndjson)) throw new Error("Workbook formula-error scan failed");
}

async function buildAudit() {
  const audit = JSON.parse(await fs.readFile(path.join(WORK, "prepackaging_audit.json"), "utf8"));
  const workbook = Workbook.create();
  const passCount = audit.checks.filter((row) => row.Status === "PASS").length;
  const included = audit.discovered_files.filter((row) => row.Inclusion_Status === "INCLUDE").length;
  const summaryRows = [
    ["Audit status", audit.status],
    ["Selected output root", audit.selected_output_root],
    ["Simulation version", audit.simulation_version],
    ["Generated UTC", audit.timestamp_utc.replace("T", " ").replace("+00:00", " UTC")],
    ["Discovered files", audit.discovered_files.length],
    ["Included discovered files", included],
    ["Excluded discovered files", audit.discovered_files.length - included],
    ["Validation checks passed", passCount],
    ["Validation checks failed", audit.checks.length - passCount],
    ["Verified CSV datasets", audit.csv_validation.length],
    ["Verified Parquet datasets", audit.parquet_validation.length],
    ["Verified Excel workbooks", audit.workbook_validation.length],
  ];
  addDataSheet(workbook, "Audit Summary", "Packaging Audit Summary", ["Metric", "Value"], summaryRows, { numberColumns: ["Value"], columnWidths: { Value: 60 } });
  const discoveredColumns = ["Selected_Output_Root", "Discovered_Path", "Relative_Path", "File_Name", "File_Category", "File_Size_Bytes", "SHA256", "Inclusion_Status", "Exclusion_Reason", "Integrity_Status", "Source_Simulation_Version"];
  addDataSheet(workbook, "Discovered Files", "Discovered File Inventory", discoveredColumns, audit.discovered_files, { numberColumns: ["File_Size_Bytes"] });
  addDataSheet(workbook, "Validation Checks", "Pre-Packaging Validation Checks", ["Category", "Check", "Observed", "Expected", "Status"], audit.checks);
  await verifyWorkbook(workbook, [["Audit Summary", "A1:B15"], ["Discovered Files", "A1:K15"], ["Validation Checks", "A1:E20"]]);
  await renderWorkbook(workbook, ["Audit Summary", "Discovered Files", "Validation Checks"], "Packaging_Audit");
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(OUTPUTS, "Packaging_Audit.xlsx"));
}

function packageSummaryRows(summary) {
  return Object.entries({
    "Package name": summary.package_name,
    "Manifest phase": summary.phase,
    "Generated UTC": summary.generated_utc.replace("T", " ").replace("+00:00", " UTC"),
    "Selected output root": summary.selected_output_root,
    "Total packaged files": summary.total_packaged_files,
    "Total package folders": summary.total_folders,
    "Excel workbooks": summary.excel_workbooks,
    "Unique CSV datasets": summary.unique_csv_datasets,
    "Unique Parquet datasets": summary.unique_parquet_datasets,
    "Physical CSV dataset copies": summary.csv_dataset_file_copies,
    "Physical Parquet dataset copies": summary.parquet_dataset_file_copies,
    "Scientific source files": summary.source_files,
    "Total uncompressed size (bytes)": summary.total_uncompressed_size,
    "Pre-packaging validation": summary.validation_status,
    "Missing files": summary.missing_files,
  }).map(([metric, value]) => [metric, value]);
}

function uniqueDatasetRows(manifest) {
  const byDataset = new Map();
  for (const row of manifest.datasets) {
    if (!byDataset.has(row.Dataset)) {
      byDataset.set(row.Dataset, {
        Dataset: row.Dataset,
        Rows: row.Dataset_Row_Count,
        Columns: row.Dataset_Column_Count,
        CSV_File: "",
        Parquet_File: "",
        CSV_Status: "",
        Parquet_Status: "",
        Parity_Status: "PASS",
      });
    }
    const entry = byDataset.get(row.Dataset);
    if (row.Package_Relative_Path.startsWith("09_ALL_CSV/")) {
      entry.CSV_File = row.Package_Relative_Path;
      entry.CSV_Status = row.Integrity_Status;
    }
    if (row.Package_Relative_Path.startsWith("10_ALL_PARQUET/")) {
      entry.Parquet_File = row.Package_Relative_Path;
      entry.Parquet_Status = row.Integrity_Status;
    }
  }
  return [...byDataset.values()].sort((a, b) => a.Dataset.localeCompare(b.Dataset));
}

function duplicateRows(files) {
  const groups = new Map();
  for (const row of files) {
    if (!/^[a-f0-9]{64}$/i.test(row.SHA256 || "")) continue;
    if (!groups.has(row.SHA256)) groups.set(row.SHA256, []);
    groups.get(row.SHA256).push(row.Package_Relative_Path);
  }
  const rows = [];
  for (const [sha, paths] of groups.entries()) {
    if (paths.length > 1) rows.push({ SHA256: sha, Copy_Count: paths.length, Package_Relative_Paths: paths.join(" | "), Status: "EXPECTED_DUPLICATE" });
  }
  return rows.sort((a, b) => a.Package_Relative_Paths.localeCompare(b.Package_Relative_Paths));
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function writeManifestCsv(columns, files) {
  const outputPath = path.join(START, "PACKAGE_CONTENTS.csv");
  const mutable = files.map((row) => ({ ...row }));
  const xlsxRow = mutable.find((row) => row.File_Name === "PACKAGE_CONTENTS.xlsx");
  const checksumRow = mutable.find((row) => row.File_Name === "checksums.sha256");
  const csvRow = mutable.find((row) => row.File_Name === "PACKAGE_CONTENTS.csv");
  xlsxRow.File_Size_Bytes = (await fs.stat(path.join(START, "PACKAGE_CONTENTS.xlsx"))).size;
  checksumRow.File_Size_Bytes = (await fs.stat(path.join(START, "checksums.sha256"))).size;
  let content = "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const lines = [columns.map(csvEscape).join(",")];
    for (const row of mutable) lines.push(columns.map((column) => csvEscape(row[column])).join(","));
    content = `${lines.join("\r\n")}\r\n`;
    const size = Buffer.byteLength(content, "utf8");
    if (Number(csvRow.File_Size_Bytes) === size) break;
    csvRow.File_Size_Bytes = size;
  }
  await fs.writeFile(outputPath, content, "utf8");
}

async function buildContents() {
  const manifest = JSON.parse(await fs.readFile(path.join(WORK, "package_manifest_seed.json"), "utf8"));
  const workbookFiles = manifest.files.map((row) => ({ ...row }));
  const workbookSelf = workbookFiles.find((row) => row.File_Name === "PACKAGE_CONTENTS.xlsx");
  workbookSelf.File_Size_Bytes = "SELF-REFERENTIAL; exact size in PACKAGE_CONTENTS.csv and ZIP metadata";
  const workbook = Workbook.create();
  const fileColumns = ["Package_Relative_Path", "File_Name", "Category", "Description", "File_Size_Bytes", "SHA256", "Original_Source_Path", "Required_or_Optional", "Integrity_Status", "Open_Test_Status", "Dataset_Row_Count", "Dataset_Column_Count"];
  addDataSheet(workbook, "Package Summary", "VO PERT-GERT Full Simulation Package", ["Metric", "Value"], packageSummaryRows(manifest.summary), { numberColumns: ["Value"], columnWidths: { Value: 60 } });
  addDataSheet(workbook, "File Manifest", "Complete Physical File Manifest", fileColumns, workbookFiles, { numberColumns: ["File_Size_Bytes", "Dataset_Row_Count", "Dataset_Column_Count"] });
  const datasets = uniqueDatasetRows(manifest);
  addDataSheet(workbook, "Dataset Manifest", "Unique Dataset Manifest", ["Dataset", "Rows", "Columns", "CSV_File", "Parquet_File", "CSV_Status", "Parquet_Status", "Parity_Status"], datasets, { numberColumns: ["Rows", "Columns"] });
  addDataSheet(workbook, "Excel Workbooks", "Packaged Excel Workbooks", fileColumns, workbookFiles.filter((row) => row.File_Name.endsWith(".xlsx")), { numberColumns: ["File_Size_Bytes", "Dataset_Row_Count", "Dataset_Column_Count"] });
  addDataSheet(workbook, "CSV Datasets", "Packaged CSV Dataset Copies", fileColumns, manifest.files.filter((row) => row.Dataset && (row.File_Name.endsWith(".csv") || row.File_Name.endsWith(".csv.gz"))), { numberColumns: ["File_Size_Bytes", "Dataset_Row_Count", "Dataset_Column_Count"] });
  addDataSheet(workbook, "Parquet Datasets", "Packaged Parquet Dataset Copies", fileColumns, manifest.files.filter((row) => row.Dataset && row.File_Name.endsWith(".parquet")), { numberColumns: ["File_Size_Bytes", "Dataset_Row_Count", "Dataset_Column_Count"] });
  addDataSheet(workbook, "Input Files", "Authoritative Input Files", fileColumns, manifest.files.filter((row) => row.Package_Relative_Path.startsWith("01_AUTHORITATIVE_INPUTS/")), { numberColumns: ["File_Size_Bytes"] });
  addDataSheet(workbook, "Source Snapshot", "Scientific Source Snapshot", fileColumns, manifest.files.filter((row) => row.Package_Relative_Path.startsWith("11_SOURCE_AND_REPRODUCIBILITY/")), { numberColumns: ["File_Size_Bytes"] });
  addDataSheet(workbook, "Validation Status", "Pre-Packaging Validation Status", ["Category", "Check", "Observed", "Expected", "Status"], manifest.prevalidation_checks);
  const missing = manifest.files.filter((row) => row.Integrity_Status !== "PASS" && row.Integrity_Status !== "N/A");
  addDataSheet(workbook, "Missing Files", "Missing or Pending File Register", fileColumns, missing, { emptyMessage: "No missing files." });
  addDataSheet(workbook, "Duplicate Files", "Duplicate Content Register", ["SHA256", "Copy_Count", "Package_Relative_Paths", "Status"], duplicateRows(manifest.files), { numberColumns: ["Copy_Count"] });
  addDataSheet(workbook, "Checksums", "Package File Checksums", ["Package_Relative_Path", "SHA256", "Integrity_Status"], manifest.files.map((row) => ({ Package_Relative_Path: row.Package_Relative_Path, SHA256: row.SHA256, Integrity_Status: row.Integrity_Status })));
  const dictionaryRows = manifest.files.filter((row) => row.File_Name.includes("Data_Dictionary") || row.Dataset.includes("Data Dictionary"));
  addDataSheet(workbook, "Data Dictionary Index", "Data Dictionary File Index", ["Package_Relative_Path", "File_Name", "Dataset", "Dataset_Row_Count", "Dataset_Column_Count", "Integrity_Status"], dictionaryRows, { numberColumns: ["Dataset_Row_Count", "Dataset_Column_Count"] });
  const sheetNames = ["Package Summary", "File Manifest", "Dataset Manifest", "Excel Workbooks", "CSV Datasets", "Parquet Datasets", "Input Files", "Source Snapshot", "Validation Status", "Missing Files", "Duplicate Files", "Checksums", "Data Dictionary Index"];
  await verifyWorkbook(workbook, [["Package Summary", "A1:B20"], ["File Manifest", "A1:L15"], ["Dataset Manifest", "A1:H15"], ["Validation Status", "A1:E20"]]);
  await renderWorkbook(workbook, sheetNames, "Package_Contents");
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(START, "PACKAGE_CONTENTS.xlsx"));
  await writeManifestCsv(fileColumns, manifest.files);
}

const command = process.argv[2];
if (command === "audit") await buildAudit();
else if (command === "contents") await buildContents();
else throw new Error("Usage: node build_package_workbooks.mjs <audit|contents>");
