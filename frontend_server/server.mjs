import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

const root = fileURLToPath(new URL("./public/", import.meta.url));
const host = process.env.KOSIS_FRONTEND_HOST ?? "127.0.0.1";
const port = Number(process.env.KOSIS_FRONTEND_PORT ?? "3000");
const apiBase = process.env.KOSIS_API_BASE_URL ?? "http://127.0.0.1:8000";
const apiKey = process.env.KOSIS_SERVICE_API_KEY ?? "";
const maxBodyBytes = 1_000_000;
const maxArticleBytes = 5_000_000;
const maxArticleClaims = 8;

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
  const description = decodeHtml(structured.description ?? metaContent(html, ["description", "og:description", "twitter:description"]) ?? "");
  if (description && !body.includes(description)) body = `${description}\n${body}`;
  const seen = new Set();
  const sentences = body.replace(/\s*\n+\s*/g, "\n").split(/(?<=[.!?。]|다\.)\s+|\n+/)
    .map((text) => text.trim()).filter((text) => text.length >= 12 && text.length <= 1200)
    .filter((text) => !seen.has(text) && seen.add(text));
  const candidates = sentences.map((text, index) => ({ text, index })).filter(({ text }) =>
    /\d/.test(text) && /(%|퍼센트|원|달러|명|건|개|톤|배|억|만|조|지수|증가|감소|상승|하락|수출|수입|인구|고용|실업|매출|생산)/.test(text));
  const selected = candidates.slice(0, maxArticleClaims);
  if (!selected.length) throw Object.assign(new Error("기사에서 검증할 수치 문장을 찾지 못했습니다."), { status: 422 });
  const articleId = `URL-${Date.now()}`;
  return {
    article: { title: title.slice(0, 500), date, url: finalUrl, extracted_claims: selected.length },
    claims: selected.map(({ text, index }, offset) => ({
      claim_id: `${articleId}-${offset + 1}`, article_id: articleId, title: title.slice(0, 500),
      date: date || new Date().toISOString().slice(0, 10), url: finalUrl, claim_text: text,
      prev_sentence: sentences[index - 1] ?? "-", next_sentence: sentences[index + 1] ?? "-",
      article_context: body.slice(0, 20_000),
    })),
  };
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

server.listen(port, host, () => {
  console.log(`KOSIS frontend listening on http://${host}:${port}`);
});

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000).unref();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
