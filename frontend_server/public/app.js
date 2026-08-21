const form = document.querySelector("#verify-form");
const submitButton = document.querySelector("#submit-button");
const serverState = document.querySelector("#server-state");
const jobState = document.querySelector("#job-state");
const emptyState = document.querySelector("#empty-state");
const progress = document.querySelector("#progress");
const resultBox = document.querySelector("#result");
const errorBox = document.querySelector("#error");

const steps = [
  ["article_fetch", "기사 본문과 수치 주장 수집"],
  ["hcx_extraction", "HCX 측정값 추출"], ["prepare", "KOSIS 검증 가능성 게이트"],
  ["stage_a_legacy", "관련 통계표 의미 검색"], ["stage_a_balanced", "통계표 균형 재순위"],
  ["stage_a_merge", "Top-10 표 후보 병합"], ["stage_b", "ITEM·OBJ 좌표 생성"],
  ["stage_c", "좌표 Top-5 재순위"], ["kosis_verification", "KOSIS 공식값 조회"],
  ["result_serialization", "판정과 근거 정리"], ["complete", "검증 완료"],
];

function setBadge(element, text, type = "neutral") { element.textContent = text; element.className = `status-badge ${type}`; }
function escapeHtml(value) { const node = document.createElement("span"); node.textContent = value ?? ""; return node.innerHTML; }

async function api(path, options) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `요청 실패 (${response.status})`);
  return payload;
}

function renderProgress(current) {
  const index = steps.findIndex(([key]) => key === current);
  progress.innerHTML = steps.map(([key, label], i) => `<li class="${i < index ? "done" : i === index ? "active" : ""}">${escapeHtml(label)}</li>`).join("");
  progress.classList.remove("hidden");
}

function renderResult(data) {
  const counts = data.summary?.verdict_counts ?? {};
  const cards = (data.claims ?? []).map((claim) => {
    const evidence = claim.selected_evidence;
    const table = evidence?.table;
    const item = evidence?.item;
    const reason = evidence?.verdict_reason ?? (Object.keys(claim.candidate_verdict_counts ?? {}).join(", ") || "확정 가능한 KOSIS 좌표가 없습니다.");
    return `<article class="result-card">
      <header><span class="verdict ${escapeHtml(claim.verdict)}">${escapeHtml(claim.verdict)}</span><span class="claim-id">${escapeHtml(claim.claim_measurement_id)}</span></header>
      ${evidence ? `<div class="evidence-grid">
        <div><small>KOSIS 통계표</small><strong>${escapeHtml(table?.name || "-")}<br>${escapeHtml(table?.tbl_id || "")}</strong></div>
        <div><small>항목 / 단위</small><strong>${escapeHtml(item?.name || "-")} · ${escapeHtml(item?.unit || "-")}</strong></div>
        <div><small>기사 수치</small><strong>${escapeHtml(String(evidence.claim_value ?? "-"))}</strong></div>
        <div><small>KOSIS 수치</small><strong>${escapeHtml(String(evidence.kosis_value ?? "-"))}</strong></div>
      </div>` : ""}
      <p class="reason">${escapeHtml(reason)}</p>
    </article>`;
  }).join("");
  resultBox.innerHTML = `<div class="summary"><span>측정값 ${data.summary?.measurement_count ?? 0}</span><span>MATCH ${counts.MATCH ?? 0}</span><span>UNRESOLVED ${counts.UNRESOLVED ?? 0}</span></div>${cards}`;
  resultBox.classList.remove("hidden");
}

async function poll(jobId) {
  while (true) {
    const state = await api(`/api/verifications/${jobId}`);
    setBadge(jobState, state.progress_step || state.status, state.status === "FAILED" ? "error" : state.status === "SUCCEEDED" ? "success" : "running");
    renderProgress(state.progress_step);
    if (state.status === "FAILED") throw new Error(state.error || "검증 작업이 실패했습니다.");
    if (state.status === "SUCCEEDED") return api(`/api/verifications/${jobId}/result`);
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitButton.disabled = true;
  emptyState.classList.add("hidden"); resultBox.classList.add("hidden"); errorBox.classList.add("hidden");
  setBadge(jobState, "작업 등록", "running"); renderProgress("hcx_extraction");
  renderProgress("article_fetch");
  try {
    const job = await api("/api/article-verifications", {
      method: "POST",
      body: JSON.stringify({ url: document.querySelector("#url").value.trim() }),
    });
    renderResult(await poll(job.job_id));
    setBadge(jobState, "완료", "success");
  } catch (error) {
    errorBox.textContent = error.message; errorBox.classList.remove("hidden"); setBadge(jobState, "오류", "error");
  } finally { submitButton.disabled = false; }
});

api("/healthz").then(() => setBadge(serverState, "서버 연결됨", "success")).catch(() => setBadge(serverState, "연결 오류", "error"));
