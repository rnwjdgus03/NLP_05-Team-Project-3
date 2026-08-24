import { readFile, writeFile } from "node:fs/promises";

process.env.KOSIS_EXTRACTOR_TEST_MODE = "1";
const { extractArticle, fetchArticleHtml } = await import("./server.mjs");

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("usage: node audit_extractor.mjs LOCK.json OUTPUT.json");
const input = JSON.parse(await readFile(inputPath, "utf8"));
const rows = Array.isArray(input) ? input : input.urls ?? input.rows ?? input.articles ?? Object.values(input.records ?? {});
const results = [];
for (let index = 0; index < rows.length; index += 1) {
  const row = rows[index];
  try {
    const { html, finalUrl } = await fetchArticleHtml(row.url);
    const extracted = extractArticle(html, finalUrl);
    results.push({ index: index + 1, url: row.url, status: "SUCCEEDED", extracted_claims: extracted.article.extracted_claims,
      claims: extracted.claims.map(({ claim_text }) => claim_text) });
  } catch (error) {
    results.push({ index: index + 1, url: row.url, status: "FAILED", error: error.message });
  }
  console.log(`${index + 1}/${rows.length} ${results.at(-1).status}`);
}
const summary = {
  total: results.length,
  succeeded: results.filter(({ status }) => status === "SUCCEEDED").length,
  failed: results.filter(({ status }) => status === "FAILED").length,
  results,
};
await writeFile(outputPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ total: summary.total, succeeded: summary.succeeded, failed: summary.failed }));
