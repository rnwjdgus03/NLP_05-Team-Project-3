import assert from "node:assert/strict";
import http from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { existsSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const stage = process.env.FRONTEND_STAGE ?? (existsSync(join(here, "server.mjs")) ? here : join(here, "frontend-v60-integration-stage"));
const jobId = "0123456789abcdef0123456789abcdef";
let submitted;

function json(response, status, payload) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(payload));
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const backend = http.createServer(async (request, response) => {
  if (request.url === "/readyz") return json(response, 200, { status: "ready" });
  if (request.url === "/v1/verifications" && request.method === "POST") {
    submitted = await readJson(request);
    assert.equal(request.headers["x-api-key"], "contract-test-key");
    return json(response, 202, { job_id: jobId, status: "QUEUED" });
  }
  if (request.url === `/v1/verifications/${jobId}`) {
    return json(response, 200, { job_id: jobId, status: "SUCCEEDED" });
  }
  if (request.url === `/v1/verifications/${jobId}/result`) {
    return json(response, 200, {
      schema_version: "kosis-service-result-v3",
      job_id: jobId,
      summary: { measurement_count: 1, ready_measurement_count: 1, extracted_measurement_count: 1 },
      claims: [{
        claim_measurement_id: "TEST-1-m1",
        claim: { text: "지난해 수출액은 6838억 달러였다.", indicator: "수출액", item: "-", period: "2024", value: "6838", unit: "억 달러" },
        verdict: "MATCH",
        decision_status: "VERIFIED_MATCH",
        selected_evidence: {
          table: { org_id: "101", tbl_id: "DT_TEST", name: "수출입 통계" },
          item: { id: "T001", name: "수출액", unit: "천달러" },
          objects: [], period: "2024", kosis_value: "683800000",
        },
        candidate_count: 1,
        candidates: [],
        explanation: { title: "일치", detail: "공식 통계와 일치합니다." },
        review_required: false,
      }],
    });
  }
  json(response, 404, { detail: "not found" });
});

backend.listen(0, "127.0.0.1");
await once(backend, "listening");
const backendPort = backend.address().port;

const probe = http.createServer();
probe.listen(0, "127.0.0.1");
await once(probe, "listening");
const frontendPort = probe.address().port;
await new Promise((resolve) => probe.close(resolve));

const frontend = spawn(process.execPath, [join(stage, "server.mjs")], {
  cwd: stage,
  env: {
    ...process.env,
    KOSIS_FRONTEND_HOST: "127.0.0.1",
    KOSIS_FRONTEND_PORT: String(frontendPort),
    KOSIS_API_BASE_URL: `http://127.0.0.1:${backendPort}`,
    KOSIS_SERVICE_API_KEY: "contract-test-key",
  },
  stdio: ["ignore", "pipe", "pipe"],
});

const logs = [];
frontend.stdout.on("data", (chunk) => logs.push(chunk.toString()));
frontend.stderr.on("data", (chunk) => logs.push(chunk.toString()));
const base = `http://127.0.0.1:${frontendPort}`;

try {
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const response = await fetch(`${base}/healthz`);
      if (response.ok) { ready = true; break; }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(ready, true, `frontend did not become ready: ${logs.join("")}`);

  const detectionResponse = await fetch(`${base}/api/articles/claims`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: "수출 통계 기사",
      date: "2025-01-01",
      body: "지난해 우리나라 전체 수출액은 6838억 달러를 기록했다. 정부는 관련 대책을 논의했다.",
      kosis_mode: "verify",
      retrieval_mode: "auto",
    }),
  });
  assert.equal(detectionResponse.status, 200);
  const detection = await detectionResponse.json();
  assert.ok(detection.session_id);
  assert.equal(detection.claim_count, 1);
  assert.match(detection.claims[0].claim_text, /6838/);

  const invalidResponse = await fetch(`${base}/api/articles/analyze-selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: detection.session_id, claim_ids: ["missing-claim"] }),
  });
  assert.equal(invalidResponse.status, 422);

  const submitResponse = await fetch(`${base}/api/articles/analyze-selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: detection.session_id, claim_ids: [detection.claims[0].claim_id] }),
  });
  assert.equal(submitResponse.status, 202);
  const job = await submitResponse.json();
  assert.equal(job.job_id, jobId);
  assert.equal(submitted.input_stage, "claims");
  assert.equal(submitted.claims.length, 1);
  assert.equal(submitted.claims[0].claim_id, detection.claims[0].claim_id);

  const stateResponse = await fetch(`${base}/api/verifications/${jobId}`);
  assert.equal(stateResponse.status, 200);
  assert.equal((await stateResponse.json()).status, "SUCCEEDED");

  const resultResponse = await fetch(`${base}/api/verifications/${jobId}/result`);
  assert.equal(resultResponse.status, 200);
  const result = await resultResponse.json();
  assert.equal(result.claims[0].selected_evidence.table.tbl_id, "DT_TEST");

  const indexResponse = await fetch(`${base}/`);
  assert.equal(indexResponse.status, 200);
  assert.match(await indexResponse.text(), /KOSIS/);
  console.log("frontend_v60_adapter_contract=PASS");
} finally {
  frontend.kill("SIGTERM");
  backend.close();
  await Promise.race([once(frontend, "exit"), new Promise((resolve) => setTimeout(resolve, 3000))]);
}
