import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { randomUUID } from "node:crypto";

const root = fileURLToPath(new URL("./public/", import.meta.url));
const host = process.env.KOSIS_FRONTEND_HOST ?? "127.0.0.1";
const port = Number(process.env.KOSIS_FRONTEND_PORT ?? "3000");
const apiBase = process.env.KOSIS_API_BASE_URL ?? "http://127.0.0.1:8000";
const apiKey = process.env.KOSIS_SERVICE_API_KEY ?? "";
const maxBodyBytes = 1_000_000;
const maxArticleBytes = 5_000_000;
const configuredMaxArticleClaims = Number(process.env.KOSIS_MAX_ARTICLE_CLAIMS ?? "4");
const maxArticleClaims = Number.isInteger(configuredMaxArticleClaims)
  ? Math.min(8, Math.max(1, configuredMaxArticleClaims)) : 4;
const claimSessionTtlMs = 30 * 60 * 1000;
const maxClaimSessions = 200;
const claimSessions = new Map();

const mime = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".ico": "image/x-icon",
};

function commonHeaders(contentType = "application/json; charset=utf-8") {
  return {
    "Content-Type": contentType,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
  };
}

function sendJson(response, status, payload) {
  response.writeHead(status, commonHeaders());
  response.end(JSON.stringify(payload));
}

async function readBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxBodyBytes) throw Object.assign(new Error("request too large"), { status: 413 });
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function readJsonBody(request) {
  const body = await readBody(request);
  try {
    return JSON.parse(body.toString("utf8"));
  } catch {
    throw Object.assign(new Error("올바른 JSON 요청이 아닙니다."), { status: 400 });
  }
}

function backendPath(pathname) {
  if (pathname === "/api/verifications") return "/v1/verifications";
  const match = pathname.match(/^\/api\/verifications\/([a-f0-9]{32})(\/result)?$/);
  if (!match) return null;
  return `/v1/verifications/${match[1]}${match[2] ?? ""}`;
}

function isPrivateAddress(address) {
  if (address === "::1" || address === "::" || address.startsWith("fc") || address.startsWith("fd") || address.startsWith("fe80:")) return true;
  if (address.startsWith("::ffff:")) return isPrivateAddress(address.slice(7));
  if (isIP(address) !== 4) return false;
  const [a, b] = address.split(".").map(Number);
  return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || a >= 224;
}

async function validatePublicUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw Object.assign(new Error("올바른 기사 URL을 입력해 주세요."), { status: 422 }); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw Object.assign(new Error("공개 HTTP/HTTPS 기사 URL만 사용할 수 있습니다."), { status: 422 });
  }
  const addresses = await lookup(url.hostname, { all: true, verbatim: true });
  if (!addresses.length || addresses.some(({ address }) => isPrivateAddress(address))) {
    throw Object.assign(new Error("내부망 또는 허용되지 않은 주소에는 접근할 수 없습니다."), { status: 422 });
  }
  return url;
}

async function fetchArticleHtml(value) {
  let url = await validatePublicUrl(value);
  for (let redirect = 0; redirect <= 4; redirect += 1) {
    const response = await fetch(url, {
      redirect: "manual",
      headers: { "User-Agent": "Mozilla/5.0 (compatible; KOSISNewsVerifier/1.0)", "Accept": "text/html,application/xhtml+xml" },
      signal: AbortSignal.timeout(20_000),
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      if (!location || redirect === 4) throw Object.assign(new Error("기사 URL의 리디렉션을 처리할 수 없습니다."), { status: 422 });
      url = await validatePublicUrl(new URL(location, url).href);
      continue;
    }
    if (!response.ok) throw Object.assign(new Error(`기사 페이지를 불러오지 못했습니다. (HTTP ${response.status})`), { status: 422 });
    if (!(response.headers.get("content-type") ?? "").toLowerCase().includes("text/html")) {
      throw Object.assign(new Error("HTML 기사 페이지만 검증할 수 있습니다."), { status: 422 });
    }
    const declared = Number(response.headers.get("content-length") ?? "0");
    if (declared > maxArticleBytes) throw Object.assign(new Error("기사 페이지가 너무 큽니다."), { status: 413 });
    const chunks = []; let size = 0;
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > maxArticleBytes) throw Object.assign(new Error("기사 페이지가 너무 큽니다."), { status: 413 });
      chunks.push(chunk);
    }
    return { html: Buffer.concat(chunks).toString("utf8"), finalUrl: url.href };
  }
  throw Object.assign(new Error("기사 페이지를 불러오지 못했습니다."), { status: 422 });
}

function decodeHtml(value = "") {
  const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  return value.replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&([a-z]+);/gi, (all, name) => named[name.toLowerCase()] ?? all)
    .replace(/\s+/g, " ").trim();
}

function metaContent(html, keys) {
  for (const key of keys) {
    const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const patterns = [
      new RegExp(`<meta[^>]+(?:property|name)=["']${escaped}["'][^>]+content=["']([^"']*)["'][^>]*>`, "i"),
      new RegExp(`<meta[^>]+content=["']([^"']*)["'][^>]+(?:property|name)=["']${escaped}["'][^>]*>`, "i"),
    ];
    for (const pattern of patterns) { const match = html.match(pattern); if (match) return decodeHtml(match[1]); }
  }
  return "";
}

function jsonLdArticles(html) {
  const values = [];
  for (const match of html.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    try {
      const parsed = JSON.parse(decodeHtml(match[1]).replace(/[\u0000-\u001f]+/g, " "));
      const queue = Array.isArray(parsed) ? parsed : [parsed];
      while (queue.length) {
        const value = queue.shift();
        if (!value || typeof value !== "object") continue;
        if (Array.isArray(value["@graph"])) queue.push(...value["@graph"]);
        const type = Array.isArray(value["@type"]) ? value["@type"] : [value["@type"]];
        if (type.some((item) => /Article|NewsArticle/i.test(String(item)))) values.push(value);
      }
    } catch { /* malformed publisher metadata: fall back to HTML */ }
  }
  return values;
}

function stripHtml(value) {
  return decodeHtml(value.replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]+>/g, " "));
}

function embeddedJsonTextBlocks(html) {
  const values = [];
  const seen = new Set();
  for (const match of html.matchAll(/"content"\s*:\s*"((?:\\.|[^"\\])*)"\s*,\s*"type"\s*:\s*"text"/g)) {
    let value = "";
    try { value = JSON.parse(`"${match[1]}"`); } catch { continue; }
    const text = stripHtml(String(value));
    if (text.length < 15 || seen.has(text)) continue;
    seen.add(text);
    values.push(text);
  }
  return values;
}

function statisticSentenceScore(text) {
  let score = 0;
  if (/통계청|국가통계|KOSIS|정부\s*(?:통계|조사)|조사에 따르면|자료에 따르면|집계됐|집계한|통계에 따르면/.test(text)) score += 5;
  if (/수출|수입|무역|인구|가구|출생|사망|고용|취업|실업|임금|물가|생산|판매|소비|소매|산업|종사자|사업체|농가|지역|전국|성별|연령/.test(text)) score += 3;
  if (/전년|전월|전분기|지난해|작년|올해|동기|대비|증가|감소|상승|하락|등락|증감|비중|규모|역대/.test(text)) score += 2;
  if (/%|퍼센트|%포인트|원|달러|명|가구|건|개사|대|톤|배|억|만|조|지수/.test(text)) score += 2;
  // Prefer an observed statistical level over a rate, forecast, or record-count
  // sentence.  A concrete "indicator + value" pair is directly queryable in
  // KOSIS and should survive the small Top-N article sentence budget.
  if (/(?:수출액|수입액|무역수지|취업자\s*수|실업자\s*수|인구|가구|출생아\s*수|사망자\s*수|임금|생산(?:량|액)?|판매(?:량|액)?|소매판매액|종사자\s*수|사업체\s*수)[^.!?。]{0,80}\d[\d,.]*(?:조|억|만|천)?(?:원|달러|명|가구|건|개사|개|대|톤)/.test(text)) score += 3;
  if (/(?:고용률|실업률|물가상승률|증가율|감소율|비중)[^.!?。]{0,50}\d[\d,.]*(?:%|퍼센트|%포인트|퍼센트포인트)/.test(text)) score += 2;
  if (/\b(?:19|20)\d{2}년|\d{1,2}월|\d분기/.test(text)) score += 1;
  if (/매출|영업이익|주가|시가총액|회사채|코인|토큰|나스닥|S&P|비트코인/.test(text) && !/통계청|국가통계|KOSIS/.test(text)) score -= 4;
  if (/선거|투표|취임식|기부|성금|감편|운항편/.test(text)) score -= 3;
  if (/^(?:\D*\b(?:19|20)\d{2}\D*)$/.test(text) && !/%|원|달러|명|건|개사|대|톤|억|만|조/.test(text)) score -= 4;
  return score;
}

function selectStatisticSentences(sentences, limit = maxArticleClaims) {
  const candidates = sentences.map((text, index) => ({ text, index, score: statisticSentenceScore(text) }))
    .filter(({ text }) => /\d/.test(text) && /(%|퍼센트|원|달러|명|가구|건|개|톤|배|억|만|조|지수|증가|감소|상승|하락|수출|수입|인구|고용|취업|실업|매출|생산|판매|소비|규모|비중|대비|집계|통계)/.test(text));
  return candidates.sort((left, right) => right.score - left.score || left.index - right.index)
    .slice(0, limit).sort((left, right) => left.index - right.index);
}

function extractArticle(html, finalUrl) {
  const structured = jsonLdArticles(html)[0] ?? {};
  const title = decodeHtml(structured.headline ?? metaContent(html, ["og:title", "twitter:title"]) ?? "") ||
    stripHtml(html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? "") || "제목을 확인할 수 없는 기사";
  const dateRaw = String(structured.datePublished ?? metaContent(html, ["article:published_time", "date", "datePublished", "pubdate"]) ?? "");
  const date = dateRaw.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? dateRaw.match(/\d{4}[./]\d{1,2}[./]\d{1,2}/)?.[0]?.replace(/[.]/g, "-").replace(/\//g, "-") ?? "";
  let body = typeof structured.articleBody === "string" ? decodeHtml(structured.articleBody) : "";
  if (body.length < 100) {
    const article = html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/i)?.[1] ?? html;
    body = [...article.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/gi)].map((match) => stripHtml(match[1])).filter((text) => text.length >= 15).join("\n");
  }
  const embeddedBody = embeddedJsonTextBlocks(html).join("\n");
  if (embeddedBody && !body.includes(embeddedBody)) body = `${body}\n${embeddedBody}`.trim();
  const description = decodeHtml(structured.description ?? metaContent(html, ["description", "og:description", "twitter:description"]) ?? "");
  if (description && !body.includes(description)) body = `${description}\n${body}`;
  const seen = new Set();
  const sentences = body.replace(/\s*\n+\s*/g, "\n").split(/(?<=[.!?。]|다\.)\s+|\n+/)
    .map((text) => text.trim()).filter((text) => text.length >= 12 && text.length <= 1200)
    .filter((text) => !seen.has(text) && seen.add(text));
  const selected = selectStatisticSentences(sentences);
  if (!selected.length) throw Object.assign(new Error("기사에서 검증할 수치 문장을 찾지 못했습니다."), { status: 422 });
  const articleId = `URL-${Date.now()}`;
  return {
    article: { title: title.slice(0, 500), date, url: finalUrl, extracted_claims: selected.length },
    sentenceCount: sentences.length,
    claims: selected.map(({ text, index }, offset) => ({
      claim_id: `${articleId}-${offset + 1}`, article_id: articleId, title: title.slice(0, 500),
      date: date || new Date().toISOString().slice(0, 10), url: finalUrl, claim_text: text,
      prev_sentence: sentences[index - 1] ?? "-", next_sentence: sentences[index + 1] ?? "-",
      article_context: body.slice(0, 20_000),
    })),
  };
}


function extractDirectArticle(payload) {
  const body = String(payload.body ?? "").trim();
  if (!body) throw Object.assign(new Error("기사 원문을 입력해 주세요."), { status: 422 });
  if (body.length > 200_000) throw Object.assign(new Error("기사 원문이 너무 깁니다."), { status: 413 });
  const seen = new Set();
  const sentences = body.replace(/\s*\n+\s*/g, "\n").split(/(?<=[.!?。]|다\.)\s+|\n+/)
    .map((text) => text.trim()).filter((text) => text.length >= 12 && text.length <= 1200)
    .filter((text) => !seen.has(text) && seen.add(text));
  const selected = selectStatisticSentences(sentences);
  if (!selected.length) throw Object.assign(new Error("기사에서 검증할 수치 문장을 찾지 못했습니다."), { status: 422 });
  const articleId = `TEXT-${Date.now()}`;
  const title = String(payload.title ?? "").trim().slice(0, 500) || "직접 입력 기사";
  const date = String(payload.date ?? "").trim() || new Date().toISOString().slice(0, 10);
  const url = String(payload.url ?? "").trim();
  return {
    article: { title, date, url, extracted_claims: selected.length },
    sentenceCount: sentences.length,
    claims: selected.map(({ text, index }, offset) => ({
      claim_id: `${articleId}-${offset + 1}`, article_id: articleId, title, date, url,
      claim_text: text, prev_sentence: sentences[index - 1] ?? "-",
      next_sentence: sentences[index + 1] ?? "-", article_context: body.slice(0, 20_000),
    })),
  };
}

function pruneClaimSessions(now = Date.now()) {
  for (const [sessionId, session] of claimSessions) {
    if (session.expiresAt <= now) claimSessions.delete(sessionId);
  }
  while (claimSessions.size >= maxClaimSessions) claimSessions.delete(claimSessions.keys().next().value);
}

function createClaimSession(extracted, options = {}) {
  pruneClaimSessions();
  const sessionId = randomUUID().replaceAll("-", "");
  const session = {
    ...extracted,
    kosisMode: String(options.kosis_mode ?? "verify"),
    retrievalMode: String(options.retrieval_mode ?? "auto"),
    expiresAt: Date.now() + claimSessionTtlMs,
  };
  claimSessions.set(sessionId, session);
  return {
    request_id: sessionId,
    session_id: sessionId,
    article_id: extracted.claims[0]?.article_id ?? "",
    title: extracted.article.title,
    date: extracted.article.date,
    url: extracted.article.url,
    kosis_mode: session.kosisMode,
    retrieval_mode: session.retrievalMode,
    sentence_count: extracted.sentenceCount,
    claim_count: extracted.claims.length,
    expires_in: Math.floor(claimSessionTtlMs / 1000),
    claims: extracted.claims.map((claim, index) => {
      const score = statisticSentenceScore(claim.claim_text);
      return {
        claim_id: claim.claim_id,
        claim_text: claim.claim_text,
        sentence_index: index,
        prev_sentence: claim.prev_sentence,
        next_sentence: claim.next_sentence,
        confidence: score >= 9 ? "높음" : score >= 6 ? "중간" : "낮음",
        reason: "수치·통계 표현을 포함한 KOSIS 검증 후보입니다.",
      };
    }),
    sentences: [],
  };
}

function selectedSessionClaims(payload) {
  pruneClaimSessions();
  const session = claimSessions.get(String(payload.session_id ?? ""));
  if (!session) throw Object.assign(new Error("검증 세션이 만료됐습니다. 기사를 다시 분석해 주세요."), { status: 404 });
  const requested = Array.isArray(payload.claim_ids) ? [...new Set(payload.claim_ids.map(String))] : [];
  if (!requested.length) throw Object.assign(new Error("검증할 문장을 한 개 이상 선택해 주세요."), { status: 422 });
  const requestedSet = new Set(requested);
  const claims = session.claims.filter((claim) => requestedSet.has(claim.claim_id));
  if (claims.length !== requestedSet.size) throw Object.assign(new Error("선택한 문장이 현재 세션에 없습니다."), { status: 422 });
  return { session, claims, requested };
}

async function submitClaims(claims) {
  const upstream = await fetch(`${apiBase}/v1/verifications`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
    body: JSON.stringify({ input_stage: "claims", claims }), signal: AbortSignal.timeout(65_000),
  });
  const text = await upstream.text();
  let payload; try { payload = JSON.parse(text); } catch { payload = { detail: text }; }
  if (!upstream.ok) throw Object.assign(new Error(typeof payload.detail === "string" ? payload.detail : "검증 작업을 등록하지 못했습니다."), { status: upstream.status });
  return payload;
}

async function proxyApi(request, response, pathname) {
  if (!apiKey) return sendJson(response, 503, { detail: "frontend backend is not configured" });
  const path = backendPath(pathname);
  if (!path) return sendJson(response, 404, { detail: "not found" });
  const allowedPost = pathname === "/api/verifications" && request.method === "POST";
  const allowedGet = pathname !== "/api/verifications" && request.method === "GET";
  if (!allowedPost && !allowedGet) return sendJson(response, 405, { detail: "method not allowed" });
  const body = allowedPost ? await readBody(request) : undefined;
  if (allowedPost) {
    let payload;
    try {
      payload = JSON.parse(body.toString("utf8"));
    } catch {
      return sendJson(response, 400, { detail: "invalid JSON" });
    }
    if (payload.input_stage !== "claims" || !Array.isArray(payload.claims) || payload.claims.length < 1) {
      return sendJson(response, 422, { detail: "at least one raw claim is required" });
    }
  }
  const upstream = await fetch(`${apiBase}${path}`, {
    method: request.method,
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
    body,
    signal: AbortSignal.timeout(65_000),
  });
  const text = await upstream.text();
  response.writeHead(upstream.status, commonHeaders(upstream.headers.get("content-type") ?? undefined));
  response.end(text);
}

async function serveStatic(response, pathname) {
  const relative = pathname === "/" ? "index.html" : pathname.slice(1);
  const safe = normalize(relative).replace(/^(\.\.[/\\])+/, "");
  const path = join(root, safe);
  if (!path.startsWith(root)) return sendJson(response, 404, { detail: "not found" });
  try {
    const body = await readFile(path);
    response.writeHead(200, commonHeaders(mime[extname(path)] ?? "application/octet-stream"));
    response.end(body);
  } catch {
    sendJson(response, 404, { detail: "not found" });
  }
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);
    if (url.pathname === "/healthz") {
      const upstream = await fetch(`${apiBase}/readyz`, { signal: AbortSignal.timeout(10_000) });
      return sendJson(response, upstream.ok ? 200 : 503, {
        status: upstream.ok ? "ready" : "degraded",
        frontend: "kosis-verification-ui-v1",
        api_connected: upstream.ok,
      });
    }

    if (url.pathname === "/api/articles/claims-url" && request.method === "POST") {
      const payload = await readJsonBody(request);
      const { html, finalUrl } = await fetchArticleHtml(String(payload.url ?? "").trim());
      return sendJson(response, 200, createClaimSession(extractArticle(html, finalUrl), payload));
    }
    if (url.pathname === "/api/articles/claims" && request.method === "POST") {
      const payload = await readJsonBody(request);
      return sendJson(response, 200, createClaimSession(extractDirectArticle(payload), payload));
    }
    if (url.pathname === "/api/articles/analyze-selection" && request.method === "POST") {
      if (!apiKey) return sendJson(response, 503, { detail: "frontend backend is not configured" });
      const payload = await readJsonBody(request);
      const { session, claims, requested } = selectedSessionClaims(payload);
      const job = await submitClaims(claims);
      return sendJson(response, 202, {
        ...job,
        session_id: String(payload.session_id),
        selected_claim_ids: requested,
        article: session.article,
      });
    }
    if (url.pathname === "/api/article-verifications" && request.method === "POST") {
      if (!apiKey) return sendJson(response, 503, { detail: "frontend backend is not configured" });
      const body = await readBody(request);
      let payload; try { payload = JSON.parse(body.toString("utf8")); } catch { return sendJson(response, 400, { detail: "invalid JSON" }); }
      const { html, finalUrl } = await fetchArticleHtml(String(payload.url ?? "").trim());
      const extracted = extractArticle(html, finalUrl);
      const job = await submitClaims(extracted.claims);
      return sendJson(response, 202, { ...job, article: extracted.article });
    }
    if (url.pathname.startsWith("/api/")) return await proxyApi(request, response, url.pathname);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return sendJson(response, 405, { detail: "method not allowed" });
    }
    return await serveStatic(response, url.pathname);
  } catch (error) {
    const status = Number(error.status) || 502;
    return sendJson(response, status, { detail: status === 502 ? "verification service unavailable" : error.message });
  }
});

if (process.env.KOSIS_EXTRACTOR_TEST_MODE !== "1") {
  server.listen(port, host, () => {
    console.log(`KOSIS frontend listening on http://${host}:${port}`);
  });
}

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000).unref();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

export { embeddedJsonTextBlocks, extractArticle, fetchArticleHtml, selectStatisticSentences, statisticSentenceScore };
