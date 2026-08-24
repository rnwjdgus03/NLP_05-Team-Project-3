const form = document.querySelector("#verify-form");
const submitButton = document.querySelector("#submit-button");
const serverState = document.querySelector("#server-state");
const jobState = document.querySelector("#job-state");
const emptyState = document.querySelector("#empty-state");
const progress = document.querySelector("#progress");
const resultBox = document.querySelector("#result");
const errorBox = document.querySelector("#error");

const steps = [
  ["article_fetch", "기사 본문 수집 및 수치 문장 선별"],
  ["hcx_extraction", "AI 수치 주장 구조화"], ["prepare", "KOSIS 검증 가능성 판별"],
  ["stage_a_legacy", "관련 KOSIS 통계표 의미 검색"], ["stage_a_balanced", "조사·기관·통계표 계열 재순위"],
  ["stage_a_merge", "통계표 Top-10 후보 병합"], ["stage_b", "ITEM·OBJ 좌표 정합성 확인"],
  ["stage_c", "좌표 Top-5 최종 재순위"], ["kosis_verification", "KOSIS Open API 공식값 조회"],
  ["result_serialization", "비교 판정과 근거 설명 생성"], ["complete", "검증 완료"],
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
    const extracted = claim.claim ?? {};
    const table = evidence?.table;
    const item = evidence?.item;
    const explanation = claim.explanation ?? {};
    const reason = explanation.detail ?? evidence?.verdict_reason ?? (Object.keys(claim.candidate_verdict_counts ?? {}).join(", ") || "확정 가능한 KOSIS 좌표가 없습니다.");
    return `<article class="result-card">
      <header><span class="verdict ${escapeHtml(claim.verdict)}">${escapeHtml(claim.verdict)}</span><span class="claim-id">${escapeHtml(claim.claim_measurement_id)}</span></header>
      ${extracted.text ? `<div class="claim-summary"><small>AI가 추출한 수치 주장</small><blockquote>${escapeHtml(extracted.text)}</blockquote><div><span>${escapeHtml(extracted.indicator || "지표 미확정")}</span><span>${escapeHtml(extracted.period || "기간 미확정")}</span><span>${escapeHtml(`${extracted.value || "-"}${extracted.unit || ""}`)}</span></div></div>` : ""}
      ${evidence ? `<div class="evidence-grid">
        <div><small>KOSIS 통계표</small><strong>${escapeHtml(table?.name || "-")}<br>${escapeHtml(table?.tbl_id || "")}</strong></div>
        <div><small>항목 / 단위</small><strong>${escapeHtml(item?.name || "-")} · ${escapeHtml(item?.unit || "-")}</strong></div>
        <div><small>기사 수치</small><strong>${escapeHtml(String(evidence.claim_value ?? "-"))}</strong></div>
        <div><small>KOSIS 공식 수치 / 기간</small><strong>${escapeHtml(String(evidence.kosis_value ?? "-"))} · ${escapeHtml(String(evidence.period ?? "-"))}</strong></div>
      </div>` : ""}
      <p class="reason"><strong>${escapeHtml(explanation.title || "판정 근거")}</strong>${escapeHtml(reason)}</p>
    </article>`;
  }).join("");
  resultBox.innerHTML = `<div class="summary"><span>검증 수치 ${data.summary?.measurement_count ?? 0}</span><span>MATCH ${counts.MATCH ?? 0}</span><span>REVIEW ${counts.MISMATCH_REVIEW_REQUIRED ?? 0}</span><span>UNRESOLVED ${counts.UNRESOLVED ?? 0}</span></div>${cards}`;
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
