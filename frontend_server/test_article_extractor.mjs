import test from "node:test";
import assert from "node:assert/strict";

process.env.KOSIS_EXTRACTOR_TEST_MODE = "1";
const { embeddedJsonTextBlocks, extractArticle, selectStatisticSentences } = await import("./server.mjs");

test("extracts publisher JSON text blocks", () => {
  const html = '<script>{"content":"지난해 443개보다 2개 늘어난 역대 최대 규모다.","type":"text"}</script>';
  assert.deepEqual(embeddedJsonTextBlocks(html), ["지난해 443개보다 2개 늘어난 역대 최대 규모다."]);
});

test("ranks official statistics above company and event numbers", () => {
  const sentences = [
    "행사는 2025년 7일부터 열린다.",
    "A사의 매출은 20억원이었다.",
    "통계청 자료에 따르면 취업자 수는 전년보다 12만명 증가했다.",
  ];
  const selected = selectStatisticSentences(sentences, 1);
  assert.equal(selected[0].index, 2);
});

test("keeps a concrete KOSIS level claim ahead of rate-only sentences", () => {
  const sentences = [
    "작년 전체 수출액은 전년보다 8.2% 증가했다.",
    "지난달 반도체 수출 증가율은 31.5%를 기록했다.",
    "새해 수출 증가율은 1.8%에 그칠 것으로 전망했다.",
    "주력 품목인 반도체 수출액은 1419억달러로 역대 최대였다.",
  ];
  const selected = selectStatisticSentences(sentences, 1);
  assert.equal(selected[0].index, 3);
});

test("extractArticle reads JSON-only article body and preserves context", () => {
  const html = `
    <meta property="og:title" content="통합한국관 역대 최대">
    <meta property="article:published_time" content="2025-01-01T00:00:00+09:00">
    <script type="application/ld+json">{"@type":"NewsArticle","headline":"통합한국관 역대 최대"}</script>
    <script>{"content":"산업부는 445개사 규모로 통합한국관을 구성한다. 이는 지난해 443개보다 2개 늘어난 역대 최대 규모다. 생활가전 비중은 18%로 집계됐다.","type":"text"}</script>`;
  const result = extractArticle(html, "https://example.com/article");
  assert.equal(result.article.date, "2025-01-01");
  assert.ok(result.claims.some(({ claim_text }) => claim_text.includes("443개")));
  assert.ok(result.claims.some(({ claim_text }) => claim_text.includes("18%")));
});
