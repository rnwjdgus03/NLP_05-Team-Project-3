import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const inputPath = path.join(repoRoot, "data/gold/mcp_auto_gold_v3.csv");
const outputPath = path.join(repoRoot, "outputs/gold/mcp_auto_gold_v3.xlsx");
const previewPath = path.join(repoRoot, "outputs/gold/mcp_auto_gold_v3_preview.png");

const csvText = (await fs.readFile(inputPath, "utf8")).replace(/^\uFEFF/, "");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "mcp_auto_gold_v3" });
const sheet = workbook.worksheets.getItem("mcp_auto_gold_v3");
const used = sheet.getUsedRange();

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(2);
used.format.font = { name: "Aptos", size: 10, color: "#172033" };
used.format.verticalAlignment = "top";
used.format.wrapText = false;
sheet.getRange("A1:AX1").format = {
  fill: "#17365D",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#0F243E" },
};
sheet.getRange("A1:AX1").format.rowHeight = 42;
sheet.getRange("A:A").format.columnWidth = 21;
sheet.getRange("B:B").format.columnWidth = 25;
sheet.getRange("C:C").format.columnWidth = 12;
sheet.getRange("D:D").format.columnWidth = 34;
sheet.getRange("E:E").format.columnWidth = 12;
sheet.getRange("F:F").format.columnWidth = 30;
sheet.getRange("G:G").format.columnWidth = 48;
sheet.getRange("H:H").format.columnWidth = 22;
sheet.getRange("I:R").format.columnWidth = 17;
sheet.getRange("S:V").format.columnWidth = 16;
sheet.getRange("W:AE").format.columnWidth = 22;
sheet.getRange("AF:AP").format.columnWidth = 18;
sheet.getRange("AQ:AX").format.columnWidth = 26;
sheet.getRange("G2:G113").format.wrapText = true;
sheet.getRange("AT2:AT113").format.wrapText = true;
sheet.getRange("A2:AX113").format.borders = {
  insideHorizontal: { style: "thin", color: "#E5EAF0" },
};

const inspection = await workbook.inspect({
  kind: "table",
  range: "mcp_auto_gold_v3!A1:J8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 10,
  maxChars: 4000,
});
console.log(inspection.ndjson);

await fs.mkdir("outputs/gold", { recursive: true });
const preview = await workbook.render({
  sheetName: "mcp_auto_gold_v3",
  range: "A1:J12",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, previewPath }));
