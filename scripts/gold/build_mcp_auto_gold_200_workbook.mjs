import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const inputPath = path.join(repoRoot, "data/gold/mcp_auto_gold_200.csv");
const outputPath = path.join(repoRoot, "outputs/gold/mcp_auto_gold_200.xlsx");
const summaryPreviewPath = path.join(repoRoot, "outputs/gold/mcp_auto_gold_200_summary_preview.png");
const dataPreviewPath = path.join(repoRoot, "outputs/gold/mcp_auto_gold_200_data_preview.png");

const csvText = (await fs.readFile(inputPath, "utf8")).replace(/^\uFEFF/, "");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "mcp_auto_gold_200" });
const data = workbook.worksheets.getItem("mcp_auto_gold_200");
const summary = workbook.worksheets.add("Summary");

data.showGridLines = false;
data.freezePanes.freezeRows(1);
data.freezePanes.freezeColumns(2);
data.getUsedRange().format.font = { name: "Aptos", size: 10, color: "#172033" };
data.getUsedRange().format.verticalAlignment = "top";
data.getRange("A1:AX1").format = {
  fill: "#17365D",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#0F243E" },
};
data.getRange("A1:AX1").format.rowHeight = 42;
data.getRange("A:A").format.columnWidth = 22;
data.getRange("B:B").format.columnWidth = 28;
data.getRange("C:C").format.columnWidth = 12;
data.getRange("D:D").format.columnWidth = 36;
data.getRange("E:E").format.columnWidth = 12;
data.getRange("F:F").format.columnWidth = 32;
data.getRange("G:G").format.columnWidth = 48;
data.getRange("H:H").format.columnWidth = 22;
data.getRange("I:R").format.columnWidth = 17;
data.getRange("S:V").format.columnWidth = 18;
data.getRange("W:AE").format.columnWidth = 22;
data.getRange("AF:AP").format.columnWidth = 18;
data.getRange("AQ:AX").format.columnWidth = 28;
data.getRange("G2:G201").format.wrapText = true;
data.getRange("AT2:AT201").format.wrapText = true;
data.getRange("A2:AX201").format.borders = {
  insideHorizontal: { style: "thin", color: "#E5EAF0" },
};
const table = data.tables.add("A1:AX201", true, "McpAutoGold200Table");
table.style = "TableStyleMedium2";
table.showFilterButton = true;
data.getRange("V2:V201").conditionalFormats.add("containsText", {
  text: "FULL_KOSIS",
  format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
});
data.getRange("V2:V201").conditionalFormats.add("containsText", {
  text: "CODEBOOK_KOSIS",
  format: { fill: "#DBEAFE", font: { color: "#1E40AF" } },
});
data.getRange("V2:V201").conditionalFormats.add("containsText", {
  text: "MEASUREMENT_ERROR",
  format: { fill: "#FEE2E2", font: { color: "#991B1B" } },
});

summary.showGridLines = false;
summary.getRange("A1:F1").merge();
summary.getRange("A1").values = [["KOSIS MCP 자동 골드셋 200"]];
summary.getRange("A1:F1").format = {
  fill: "#17365D",
  font: { name: "Aptos Display", size: 18, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
};
summary.getRange("A1:F1").format.rowHeight = 36;
summary.getRange("A3:B10").values = [
  ["항목", "값"],
  ["전체 측정값", null],
  ["FULL_KOSIS", null],
  ["CODEBOOK_KOSIS", null],
  ["MCP_NOT_VERIFIABLE", null],
  ["MEASUREMENT_ERROR", null],
  ["gold_verifiable=Y", null],
  ["title/url 누락 행", null],
];
summary.getRange("B4").formulas = [["=COUNTA('mcp_auto_gold_200'!B2:B201)"]];
summary.getRange("B5").formulas = [["=COUNTIF('mcp_auto_gold_200'!V2:V201,\"FULL_KOSIS\")"]];
summary.getRange("B6").formulas = [["=COUNTIF('mcp_auto_gold_200'!V2:V201,\"CODEBOOK_KOSIS\")"]];
summary.getRange("B7").formulas = [["=COUNTIF('mcp_auto_gold_200'!V2:V201,\"MCP_NOT_VERIFIABLE\")"]];
summary.getRange("B8").formulas = [["=COUNTIF('mcp_auto_gold_200'!V2:V201,\"MEASUREMENT_ERROR\")"]];
summary.getRange("B9").formulas = [["=COUNTIF('mcp_auto_gold_200'!S2:S201,\"Y\")"]];
summary.getRange("B10").formulas = [["=COUNTBLANK('mcp_auto_gold_200'!D2:D201)+COUNTBLANK('mcp_auto_gold_200'!F2:F201)"]];
summary.getRange("A3:B3").format = {
  fill: "#DCE6F1",
  font: { bold: true, color: "#17365D" },
  borders: { preset: "outside", style: "thin", color: "#9FBAD0" },
};
summary.getRange("A4:B10").format.borders = {
  insideHorizontal: { style: "thin", color: "#D9E2F3" },
  bottom: { style: "thin", color: "#9FBAD0" },
};
summary.getRange("B4:B10").format.numberFormat = "#,##0";
summary.getRange("B4:B10").format.font = { bold: true, color: "#17365D" };
summary.getRange("A3:A10").format.columnWidth = 28;
summary.getRange("B3:B10").format.columnWidth = 14;
summary.getRange("A12:F12").merge();
summary.getRange("A12").values = [["FULL_KOSIS는 세부 좌표·실제값 확정, CODEBOOK_KOSIS는 KOSIS 통계표 확인·세부값 검증 대기입니다."]];
summary.getRange("A12:F12").format = {
  fill: "#FFF4CC",
  font: { color: "#7C5700", italic: true },
  wrapText: true,
};
summary.getRange("A12:F12").format.rowHeight = 34;
summary.freezePanes.freezeRows(1);

const summaryCheck = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:B10",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 2,
  maxChars: 3000,
});
console.log(summaryCheck.ndjson);
const dataCheck = await workbook.inspect({
  kind: "table",
  range: "mcp_auto_gold_200!A1:J10",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 10,
  maxChars: 4000,
});
console.log(dataCheck.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
  maxChars: 2000,
});
console.log(formulaErrors.ndjson);

await fs.mkdir("outputs/gold", { recursive: true });
const summaryPreview = await workbook.render({
  sheetName: "Summary",
  range: "A1:F12",
  scale: 1.4,
  format: "png",
});
await fs.writeFile(summaryPreviewPath, new Uint8Array(await summaryPreview.arrayBuffer()));
const dataPreview = await workbook.render({
  sheetName: "mcp_auto_gold_200",
  range: "A1:J12",
  scale: 1,
  format: "png",
});
await fs.writeFile(dataPreviewPath, new Uint8Array(await dataPreview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, summaryPreviewPath, dataPreviewPath }));
