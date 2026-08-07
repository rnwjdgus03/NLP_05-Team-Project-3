import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const inputPath = path.join(repoRoot, "data/gold/mcp_full_gold_200.csv");
const outputDir = path.join(repoRoot, "outputs/gold");
const outputPath = `${outputDir}/mcp_full_gold_200.xlsx`;
const summaryPreviewPath = `${outputDir}/mcp_full_gold_200_summary_preview.png`;
const dataPreviewPath = `${outputDir}/mcp_full_gold_200_data_preview.png`;

const csvText = (await fs.readFile(inputPath, "utf8")).replace(/^\uFEFF/, "");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Gold 200" });
const data = workbook.worksheets.getItem("Gold 200");
const summary = workbook.worksheets.add("Summary");

data.showGridLines = false;
data.freezePanes.freezeRows(1);
data.freezePanes.freezeColumns(4);
data.getUsedRange().format.font = { name: "Aptos", size: 10, color: "#172033" };
data.getUsedRange().format.verticalAlignment = "top";
data.getRange("A1:AJ1").format = {
  fill: "#17365D",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#0F243E" },
};
data.getRange("A1:AJ1").format.rowHeight = 42;
data.getRange("A:C").format.columnWidth = 15;
data.getRange("D:D").format.columnWidth = 36;
data.getRange("E:E").format.columnWidth = 12;
data.getRange("F:F").format.columnWidth = 38;
data.getRange("G:G").format.columnWidth = 58;
data.getRange("H:O").format.columnWidth = 15;
data.getRange("P:W").format.columnWidth = 20;
data.getRange("X:AF").format.columnWidth = 18;
data.getRange("AG:AJ").format.columnWidth = 30;
data.getRange("D2:G201").format.wrapText = true;
data.getRange("AE2:AH201").format.wrapText = true;
data.getRange("I2:I201").format.numberFormat = "0.##########";
data.getRange("AA2:AD201").format.numberFormat = "#,##0.##########";
data.getRange("A2:AJ201").format.borders = {
  insideHorizontal: { style: "thin", color: "#E5EAF0" },
};
const table = data.tables.add("A1:AJ201", true, "McpFullGold200Table");
table.style = "TableStyleMedium2";
table.showFilterButton = true;
data.getRange("K2:K201").conditionalFormats.add("containsText", {
  text: "SUPPORTS",
  format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
});
data.getRange("K2:K201").conditionalFormats.add("containsText", {
  text: "REFUTES",
  format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
});
data.getRange("L2:L201").conditionalFormats.add("containsText", {
  text: "FULL_KOSIS_MCP",
  format: { fill: "#DBEAFE", font: { color: "#1E40AF", bold: true } },
});

summary.showGridLines = false;
summary.freezePanes.freezeRows(1);
summary.getRange("A1:F1").merge();
summary.getRange("A1").values = [["KOSIS MCP 실제조회 골드셋 200"]];
summary.getRange("A1:F1").format = {
  fill: "#17365D",
  font: { name: "Aptos Display", size: 18, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
};
summary.getRange("A1:F1").format.rowHeight = 38;
summary.getRange("A3:B12").values = [
  ["검증 항목", "값"],
  ["전체 행", null],
  ["SUPPORTS", null],
  ["REFUTES", null],
  ["FULL_KOSIS_MCP", null],
  ["gold_ready=Y", null],
  ["human_reviewed=N", null],
  ["제목·URL 공란", null],
  ["실제값·증빙URL 공란", null],
  ["고유 claim 수", null],
];
summary.getRange("B4").formulas = [["=COUNTA('Gold 200'!A2:A201)"]];
summary.getRange("B5").formulas = [["=COUNTIF('Gold 200'!K2:K201,\"SUPPORTS\")"]];
summary.getRange("B6").formulas = [["=COUNTIF('Gold 200'!K2:K201,\"REFUTES\")"]];
summary.getRange("B7").formulas = [["=COUNTIF('Gold 200'!L2:L201,\"FULL_KOSIS_MCP\")"]];
summary.getRange("B8").formulas = [["=COUNTIF('Gold 200'!N2:N201,\"Y\")"]];
summary.getRange("B9").formulas = [["=COUNTIF('Gold 200'!O2:O201,\"N\")"]];
summary.getRange("B10").formulas = [["=COUNTBLANK('Gold 200'!D2:D201)+COUNTBLANK('Gold 200'!F2:F201)"]];
summary.getRange("B11").formulas = [["=COUNTBLANK('Gold 200'!AD2:AD201)+COUNTBLANK('Gold 200'!AH2:AH201)"]];
summary.getRange("B12").formulas = [["=COUNTA('Gold 200'!B2:B201)"]];
summary.getRange("A3:B3").format = {
  fill: "#DCE6F1",
  font: { bold: true, color: "#17365D" },
  borders: { preset: "outside", style: "thin", color: "#9FBAD0" },
};
summary.getRange("A4:B12").format.borders = {
  insideHorizontal: { style: "thin", color: "#D9E2F3" },
  bottom: { style: "thin", color: "#9FBAD0" },
};
summary.getRange("B4:B12").format.numberFormat = "#,##0";
summary.getRange("B4:B12").format.font = { bold: true, color: "#17365D" };
summary.getRange("A3:A12").format.columnWidth = 28;
summary.getRange("B3:B12").format.columnWidth = 15;

summary.getRange("D3:E3").values = [["KOSIS 통계표", "행 수"]];
summary.getRange("D4:D13").values = [
  ["DT_1R11001_FRM101"], ["DT_1R11006_FRM101"], ["DT_1J22042"], ["DT_1J22003"],
  ["DT_1DA7001S"], ["DT_1DA7002S"], ["INH_1B8000F_01"], ["DT_1K41012"],
  ["DT_1KC2020"], ["DT_1EA1011"],
];
summary.getRange("E4").formulas = [["=COUNTIF('Gold 200'!Q2:Q201,D4)"]];
summary.getRange("E4:E13").fillDown();
summary.getRange("D3:E3").format = {
  fill: "#DCE6F1",
  font: { bold: true, color: "#17365D" },
  borders: { preset: "outside", style: "thin", color: "#9FBAD0" },
};
summary.getRange("D4:E13").format.borders = { insideHorizontal: { style: "thin", color: "#D9E2F3" } };
summary.getRange("D3:D13").format.columnWidth = 25;
summary.getRange("E3:E13").format.columnWidth = 12;
summary.getRange("E4:E13").format.numberFormat = "#,##0";

summary.getRange("A15:F16").merge();
summary.getRange("A15").values = [["모든 행은 KOSIS MCP kosis_get_data 실제 응답에서 현재값과 필요 시 비교값을 확보했고, 사람 검수 없이 자동 라벨링했습니다."]];
summary.getRange("A15:F16").format = {
  fill: "#FFF4CC",
  font: { color: "#7C5700", italic: true },
  wrapText: true,
  verticalAlignment: "center",
};

const summaryCheck = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:F16",
  include: "values,formulas",
  tableMaxRows: 16,
  tableMaxCols: 6,
  maxChars: 5000,
});
console.log(summaryCheck.ndjson);
const dataCheck = await workbook.inspect({
  kind: "table",
  range: "Gold 200!A1:L8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 12,
  maxChars: 5000,
});
console.log(dataCheck.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 2500,
});
console.log(formulaErrors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const summaryPreview = await workbook.render({ sheetName: "Summary", range: "A1:F16", scale: 1.4, format: "png" });
await fs.writeFile(summaryPreviewPath, new Uint8Array(await summaryPreview.arrayBuffer()));
const dataPreview = await workbook.render({ sheetName: "Gold 200", range: "A1:L12", scale: 1, format: "png" });
await fs.writeFile(dataPreviewPath, new Uint8Array(await dataPreview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, summaryPreviewPath, dataPreviewPath }));
