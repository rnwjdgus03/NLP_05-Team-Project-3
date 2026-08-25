const form = document.querySelector("#analysisForm");
const bodyInput = document.querySelector("#articleBody");
const titleInput = document.querySelector("#articleTitle");
const dateInput = document.querySelector("#articleDate");
const urlInput = document.querySelector("#articleUrl");
const modeInput = document.querySelector("#kosisMode");
const retrievalInput = document.querySelector("#retrievalMode");
const submitButton = document.querySelector("#submitButton");
const formError = document.querySelector("#formError");
const charCount = document.querySelector("#charCount");
const chatStream = document.querySelector("#chatStream");
const flowItems = [...document.querySelectorAll("#flowList li")];
const inputTabs = [...document.querySelectorAll("[data-input-mode]")];
const directInputPane = document.querySelector("#directInputPane");
const urlInputPane = document.querySelector("#urlInputPane");
const newAnalysisButton = document.querySelector("#newAnalysisButton");
const mobileNewButton = document.querySelector("#mobileNewButton");
const recentList = document.querySelector("#recentList");
const navItems = [...document.querySelectorAll("[data-section]")];
let inputMode = "url";

const detectMessages = [
  ["기사 본문을 정리하고 있어요.", "문장 분리와 앞 문맥을 연결합니다."],
  ["검증 가능한 문장을 찾고 있어요.", "수치 주장을 담은 문장을 선별합니다."],
];

const verifyMessages = [
  ["수치와 기간을 구조화하고 있어요.", "선택한 문장의 지표·단위·시점을 확인합니다."],
  ["KOSIS 통계와 대조하고 있어요.", "공식 통계표 후보와 실제값을 조회합니다."],
];

const SELECTION_STEP_INDEX = 2;
const VERIFY_STEP_INDEX = 3;


function responseError(payload, fallback) {
  if (payload?.error?.message) return payload.error;
  if (typeof payload?.detail === "string") return { message: payload.detail };
  return { message: fallback };
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollVerification(jobId) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const stateResponse = await fetch(`/api/verifications/${jobId}`);
    const state = await stateResponse.json();
    if (!stateResponse.ok) throw responseError(state, "검증 상태를 확인하지 못했습니다.");
    if (state.status === "SUCCEEDED") {
      const resultResponse = await fetch(`/api/verifications/${jobId}/result`);
      const result = await resultResponse.json();
      if (!resultResponse.ok) throw responseError(result, "검증 결과를 가져오지 못했습니다.");
      return result;
    }
    if (state.status === "FAILED") throw { message: state.error_message || "검증 작업이 실패했습니다." };
    await sleep(3000);
  }
  throw { message: "검증 시간이 길어지고 있습니다. 잠시 후 다시 시도해 주세요." };
}

function normalizeVerificationResult(result, detection, selectedClaimIds) {
  const claims = result.claims || [];
  const measurements = claims.map((item) => {
    const claim = item.claim || {};
    const evidence = item.selected_evidence
      || (item.candidates || []).find((candidate) => candidate?.kosis_value !== null && candidate?.kosis_value !== "")
      || null;
    const candidates = (item.candidates || []).slice(0, 5).map((candidate, index) => ({
      rank: index + 1,
      tbl_id: candidate.table?.tbl_id || "",
      tbl_name: candidate.table?.name || "",
      org_id: candidate.table?.org_id || "",
    }));
    const status = item.verdict === "MATCH"
      ? "일치"
      : item.verdict === "MISMATCH_REVIEW_REQUIRED" ? "불일치 검토 필요" : "판단 보류";
    return {
      claim_measurement_id: item.claim_measurement_id,
      claim_text: claim.text || "",
      indicator: claim.indicator || "",
      item: claim.item || "",
      period: claim.period || "",
      value: claim.value || "",
      unit: claim.unit || "",
      stage: "verification",
      status,
      status_code: item.verdict || "UNRESOLVED",
      status_reason: item.explanation?.detail || "세부 근거가 없습니다.",
      final_status: item.verdict || "UNRESOLVED",
      review_reason: item.review_required ? item.explanation?.detail || "검토가 필요합니다." : "",
      candidates,
      kosis_actual_value: evidence?.kosis_value ?? "",
      kosis_unit: evidence?.item?.unit || "",
      kosis_period_used: evidence?.period || "",
      kosis_table_name: evidence?.table?.name || "",
      kosis_item_name: evidence?.item?.name || "",
      kosis_object_names: (evidence?.objects || []).map((object) => object.value_name).filter(Boolean),
      needs_review: item.verdict !== "MATCH",
    };
  });
  const verifiedCount = claims.filter((item) => item.verdict !== "UNRESOLVED").length;
  return {
    request_id: result.job_id || detection.request_id,
    processing_status: "completed",
    article_id: detection.article_id,
    title: detection.title,
    date: detection.date,
    url: detection.url,
    kosis_mode: detection.kosis_mode,
    retrieval_mode: detection.retrieval_mode,
    session_id: detection.session_id,
    selected_claim_ids: selectedClaimIds,
    summary: {
      sentence_count: detection.sentence_count,
      claim_count: detection.claim_count,
      selected_claim_count: selectedClaimIds.length,
      measurement_count: result.summary?.extracted_measurement_count ?? claims.length,
      eligible_count: result.summary?.ready_measurement_count ?? claims.length,
      enrich_count: 0,
      rejected_count: 0,
      candidate_count: claims.reduce((total, item) => total + Number(item.candidate_count || 0), 0),
      mapping_count: claims.filter((item) => item.selected_evidence).length,
      verified_count: verifiedCount,
      review_count: claims.length - verifiedCount,
      not_kosis_count: 0,
    },
    measurements,
  };
}

function hasValue(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function formatKoreanNumber(value) {
  const number = Number(String(value).replaceAll(",", ""));
  if (!Number.isFinite(number)) return String(value);
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 3 }).format(number);
}

function safeConvertedValue(item) {
  const rawValue = Number(String(item.kosis_actual_value).replaceAll(",", ""));
  if (!Number.isFinite(rawValue)) return "";

  const sourceUnit = String(item.kosis_unit || "").replaceAll(" ", "");
  const claimText = String(item.claim_text || "").replaceAll(" ", "");
  const supportedUnits = [
    "백만달러", "천달러", "만달러", "억달러", "달러",
    "백만원", "천원", "만원", "억원", "조원", "원",
    "천명", "만명", "명",
  ];
  const claimUnit = supportedUnits.find((unit) => claimText.includes(unit))
    || String(item.unit || "").replaceAll(" ", "");
  const scale = {
    명: 1, 천명: 1e3, 만명: 1e4,
    원: 1, 천원: 1e3, 만원: 1e4, 백만원: 1e6, 억원: 1e8, 조원: 1e12,
    달러: 1, 천달러: 1e3, 만달러: 1e4, 백만달러: 1e6, 억달러: 1e8,
  };
  if (!(sourceUnit in scale) || !(claimUnit in scale)) return "";

  const sourceFamily = sourceUnit.includes("달러") ? "달러" : sourceUnit.includes("원") ? "원" : "명";
  const claimFamily = claimUnit.includes("달러") ? "달러" : claimUnit.includes("원") ? "원" : "명";
  if (sourceFamily !== claimFamily) return "";

  const converted = rawValue * scale[sourceUnit] / scale[claimUnit];
  const displayUnit = claimUnit.replace("달러", " 달러").trim();
  return `약 ${formatKoreanNumber(converted)}${displayUnit}`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
}

function showConversation() {
  document.body.classList.remove("guide-focus");
  document.body.classList.add("conversation-active");
  navItems.forEach((item) => item.classList.toggle("active", item.dataset.section === "chat"));
}

function resetConversation({ focus = false } = {}) {
  document.body.classList.remove("conversation-active", "guide-focus");
  chatStream.replaceChildren();
  form.reset();
  inputMode = "url";
  directInputPane.hidden = true;
  urlInputPane.hidden = false;
  inputTabs.forEach((tab) => {
    const selected = tab.dataset.inputMode === "url";
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  charCount.textContent = "0 / 200,000";
  formError.textContent = "";
  resetFlow();
  navItems.forEach((item) => item.classList.toggle("active", item.dataset.section === "chat"));
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (focus) window.setTimeout(() => urlInput.focus(), 250);
}

function setFlowStep(activeIndex) {
  flowItems.forEach((item, index) => {
    item.classList.toggle("active", index === activeIndex);
    item.classList.toggle("done", index < activeIndex || activeIndex >= flowItems.length);
  });
}

function resetFlow() {
  flowItems.forEach((item) => item.classList.remove("active", "done"));
}

function setInputMode(mode) {
  inputMode = mode;
  const isDirect = mode === "direct";
  directInputPane.hidden = !isDirect;
  urlInputPane.hidden = isDirect;
  inputTabs.forEach((tab) => {
    const selected = tab.dataset.inputMode === mode;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  formError.textContent = "";
  (isDirect ? bodyInput : urlInput).focus();
}

function appendUserMessage(payload) {
  const article = element("article", "message user-message");
  const box = element("div", "message-body");
  const meta = element(
    "div",
    "user-meta",
    payload.input_mode === "url"
      ? "URL 자동 수집"
      : [payload.title || "제목 없음", payload.date].filter(Boolean).join(" · "),
  );
  const sourceText = payload.input_mode === "url" ? payload.url : payload.body;
  const preview = sourceText.length > 360 ? `${sourceText.slice(0, 360).trim()}…` : sourceText;
  const copy = element("p", "", preview);
  box.append(meta, copy);
  if (payload.input_mode === "direct" && sourceText.length > 360) {
    const details = element("details");
    details.append(element("summary", "", "기사 원문 전체 보기"), element("p", "", sourceText));
    box.append(details);
  }
  article.append(box);
  chatStream.append(article);
}

function appendLoadingMessage(messages = detectMessages) {
  const article = element("article", "message assistant-message loading-message");
  const avatar = element("div", "avatar", "FL");
  const box = element("div", "message-body");
  const row = element("div", "loading-row");
  const dots = element("div", "loading-dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(element("i"), element("i"), element("i"));
  const copy = element("div", "loading-copy");
  const strong = element("strong", "", messages[0][0]);
  const small = element("small", "", messages[0][1]);
  copy.append(strong, small);
  row.append(dots, copy);
  box.append(row);
  article.append(avatar, box);
  chatStream.append(article);
  return { article, strong, small };
}

function appendClaimSelectionMessage(detection) {
  const article = element("article", "message assistant-message selection-message");
  const avatar = element("div", "avatar", "FL");
  const box = element("div", "message-body");
  const heading = element("div", "selection-heading");
  heading.append(
    element("p", "eyebrow", "STEP 1 · 검증 문장 선택"),
    element("h2", "", `검증 가능한 문장을 ${detection.claim_count}개 찾았어요.`),
    element(
      "p",
      "selection-lead",
      `전체 ${detection.sentence_count}개 문장 중 수치 주장이 담긴 문장입니다. 검증할 문장을 선택해 주세요.`,
    ),
  );
  box.append(heading);

  if (!detection.claims?.length) {
    box.append(
      element(
        "div",
        "empty-result",
        "검증 가능한 수치 주장을 찾지 못했습니다.\n기사의 수치·단위·기간 표현을 확인하거나 다른 기사를 입력해 보세요.",
      ),
    );
    article.append(avatar, box);
    chatStream.append(article);
    resetFlow();
    return;
  }

  const toolbar = element("div", "selection-toolbar");
  const counter = element("span", "selection-counter");
  const selectAll = element("button", "selection-link", "전체 선택");
  const clearAll = element("button", "selection-link", "전체 해제");
  selectAll.type = "button";
  clearAll.type = "button";
  toolbar.append(counter, element("span", "selection-toolbar-spacer"), selectAll, clearAll);
  box.append(toolbar);

  const list = element("div", "claim-select-list");
  const checkboxes = detection.claims.map((claim, index) => {
    const row = element("label", "claim-select-item");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = claim.claim_id;
    input.checked = true;
    const copy = element("div", "claim-select-copy");
    const head = element("div", "claim-select-head");
    head.append(element("span", "claim-select-index", String(index + 1).padStart(2, "0")));
    if (claim.confidence) {
      head.append(element("span", "claim-confidence", `확신도 ${claim.confidence}`));
    }
    copy.append(head, element("p", "claim-select-text", claim.claim_text));
    if (claim.reason) copy.append(element("small", "claim-select-reason", claim.reason));
    row.append(input, copy);
    list.append(row);
    return input;
  });
  box.append(list);

  const actions = element("div", "selection-actions");
  const confirm = element("button", "analyze-button selection-confirm");
  confirm.type = "button";
  const confirmLabel = element("span", "", "선택한 문장 검증하기");
  confirm.append(confirmLabel);
  const note = element("p", "selection-note", "선택한 문장만 KOSIS 통계와 대조합니다.");
  actions.append(note, confirm);
  box.append(actions);

  const selectedIds = () => checkboxes.filter((input) => input.checked).map((input) => input.value);

  function syncState() {
    const count = selectedIds().length;
    counter.textContent = `${count} / ${checkboxes.length}개 선택`;
    confirmLabel.textContent = count
      ? `선택한 ${count}개 문장 검증하기`
      : "검증할 문장을 선택하세요";
    confirm.disabled = count === 0;
  }

  checkboxes.forEach((input) => input.addEventListener("change", syncState));
  selectAll.addEventListener("click", () => {
    checkboxes.forEach((input) => (input.checked = true));
    syncState();
  });
  clearAll.addEventListener("click", () => {
    checkboxes.forEach((input) => (input.checked = false));
    syncState();
  });
  confirm.addEventListener("click", () => {
    const claimIds = selectedIds();
    if (!claimIds.length) return;
    lockSelectionCard(article, checkboxes, [selectAll, clearAll, confirm], claimIds.length);
    verifySelectedClaims(detection, claimIds);
  });

  syncState();
  article.append(avatar, box);
  chatStream.append(article);
  setFlowStep(SELECTION_STEP_INDEX);
}

function lockSelectionCard(article, checkboxes, buttons, count) {
  checkboxes.forEach((input) => (input.disabled = true));
  buttons.forEach((button) => (button.disabled = true));
  article.classList.add("selection-locked");
  const badge = element("span", "selection-submitted", `${count}개 문장 검증 요청됨`);
  article.querySelector(".selection-actions")?.replaceChildren(badge);
}

async function verifySelectedClaims(detection, claimIds) {
  const loading = appendLoadingMessage(verifyMessages);
  const progressTimer = startProgress(loading, verifyMessages, VERIFY_STEP_INDEX);
  scrollToLatest();

  try {
    const response = await fetch("/api/articles/analyze-selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: detection.session_id,
        claim_ids: claimIds,
        kosis_mode: detection.kosis_mode,
        retrieval_mode: detection.retrieval_mode,
      }),
    });
    const job = await response.json();
    if (!response.ok) throw responseError(job, "검증 요청에 실패했습니다.");
    const rawResult = await pollVerification(job.job_id);
    const result = normalizeVerificationResult(rawResult, detection, claimIds);
    loading.article.remove();
    appendResultMessage(result);
    setFlowStep(flowItems.length);
  } catch (error) {
    loading.article.remove();
    appendErrorMessage(error);
    resetFlow();
  } finally {
    window.clearInterval(progressTimer);
    scrollToLatest();
  }
}

function verdictClass(item) {
  if (item.status_code === "MATCH" || item.status === "일치") return "match";
  if (item.status_code === "VALUE_MISMATCH" || item.status === "불일치") return "mismatch";
  if (item.final_status === "NOT_KOSIS" || item.status === "검증대상 아님") return "not-kosis";
  if (item.stage === "enrich" || item.status === "보강 필요") return "enrich";
  return "review";
}

function appendSummaryGrid(container, summary) {
  const grid = element("div", "summary-grid");
  const items = [
    [summary.sentence_count, "분석 문장"],
    [summary.claim_count, "검증 가능 문장"],
    [summary.selected_claim_count ?? summary.claim_count, "선택한 문장"],
    [summary.measurement_count, "추출 측정값"],
    [summary.eligible_count, "매핑 대상"],
    [summary.enrich_count, "보강 필요"],
    [summary.not_kosis_count || summary.rejected_count, "검증대상 아님"],
    [summary.verified_count, "실제값 검증"],
  ];
  items.forEach(([value, label]) => {
    const item = element("div", "summary-item");
    item.append(element("strong", "", value ?? 0), element("span", "", label));
    grid.append(item);
  });
  container.append(grid);
}

function appendCandidates(container, candidates) {
  if (!candidates?.length) return;
  const details = element("details", "candidate-details");
  const summary = element("summary", "", `KOSIS 통계표 후보 ${candidates.length}개`);
  const list = element("div", "candidate-list");
  candidates.forEach((candidate) => {
    const row = element("div", "candidate-item");
    const rank = element("span", "candidate-rank", candidate.rank);
    const name = element("span", "", candidate.tbl_name || "통계표 이름 없음");
    const id = element("span", "candidate-id", candidate.tbl_id || "-");
    row.append(rank, name, id);
    list.append(row);
  });
  details.append(summary, list);
  container.append(details);
}

function appendMeasurement(container, item, index) {
  const card = element("section", "measurement-card");
  const head = element("div", "measurement-head");
  const label = element("span", "measurement-label", `MEASUREMENT ${String(index + 1).padStart(2, "0")}`);
  const verdict = element("span", `verdict ${verdictClass(item)}`, item.status || "판단 보류");
  head.append(label, verdict);

  if (item.status_code === "UNRESOLVED") {
    const hasEvidence = hasValue(item.kosis_actual_value);
    const intro = element(
      "p",
      "hold-intro",
      hasEvidence
        ? "공식 통계 후보는 찾았지만, 기준 일치 확인이 필요합니다."
        : "대조할 공식 통계값을 확정하지 못했습니다.",
    );
    const claimBlock = element("div", "evidence-block");
    claimBlock.append(
      element("strong", "evidence-title", "뉴스 주장"),
      element("p", "evidence-claim", item.claim_text || "원문 문장 없음"),
    );

    const evidenceBlock = element("div", "evidence-block kosis-evidence");
    evidenceBlock.append(element("strong", "evidence-title", "KOSIS 근거 후보"));
    if (hasEvidence) {
      const path = [
        item.kosis_table_name,
        item.kosis_item_name,
        ...(item.kosis_object_names || []),
      ].filter(Boolean).join(" > ") || "KOSIS 공식 통계 후보";
      const period = item.kosis_period_used ? `${item.kosis_period_used} 공식값` : "공식값";
      const actual = `${formatKoreanNumber(item.kosis_actual_value)}${item.kosis_unit || ""}`;
      evidenceBlock.append(
        element("p", "evidence-path", path),
        element("p", "evidence-value", `${period}: ${actual}`),
      );
      const converted = safeConvertedValue(item);
      if (converted) {
        evidenceBlock.append(element("p", "evidence-converted", `환산값: ${converted}`));
      }
    } else {
      evidenceBlock.append(element("p", "evidence-path", "확정된 후보 없음"));
    }
    card.append(head, intro, claimBlock, evidenceBlock);
    container.append(card);
    return;
  }

  const quote = element("p", "claim-quote", item.claim_text || "원문 문장 없음");
  const valueRow = element("div", "value-row");
  const valueText = [item.value, item.unit].filter(Boolean).join(" ") || item.measurement_text || "수치 없음";
  valueRow.append(element("span", "value-chip", valueText));
  if (item.indicator) valueRow.append(element("span", "value-chip", item.indicator));
  if (item.period) valueRow.append(element("span", "value-chip", item.period));
  if (item.kosis_actual_value) {
    const actual = [item.kosis_actual_value, item.kosis_unit].filter(Boolean).join(" ");
    valueRow.append(element("span", "value-chip", `KOSIS ${actual}`));
  }
  const reason = element("p", "reason-copy", item.status_reason || "세부 사유가 없습니다.");
  card.append(head, quote, valueRow, reason);
  if (item.enrichment_actions) {
    card.append(element("p", "action-copy", `권장 보강 · ${item.enrichment_actions}`));
  }
  appendCandidates(card, item.candidates);
  container.append(card);
}

function appendResultMessage(payload) {
  const article = element("article", "message assistant-message result-message");
  const avatar = element("div", "avatar", "FL");
  const box = element("div", "message-body");
  const heading = element("div", "result-heading");
  const titleWrap = element("div");
  titleWrap.append(
    element("p", "eyebrow", "STEP 2 · ANALYSIS COMPLETE"),
    element(
      "h2",
      "",
      payload.selected_claim_ids?.length
        ? `선택한 ${payload.selected_claim_ids.length}개 문장의 검증 결과입니다.`
        : "기사 수치 검증 결과입니다.",
    ),
    element(
      "p",
      "",
      [payload.title, payload.date, `요청 ID · ${payload.request_id}`].filter(Boolean).join(" · "),
    ),
  );
  heading.append(titleWrap);
  box.append(heading);
  appendSummaryGrid(box, payload.summary);

  const list = element("div", "measurement-list");
  if (payload.measurements?.length) {
    payload.measurements.forEach((item, index) => appendMeasurement(list, item, index));
  } else {
    list.append(
      element(
        "div",
        "empty-result",
        "KOSIS와 대조할 수 있는 수치 주장을 찾지 못했습니다.\n기사의 수치·단위·기간 표현을 확인해 보세요.",
      ),
    );
  }
  box.append(list);
  article.append(avatar, box);
  chatStream.append(article);
  addRecentItem(payload);
}

function addRecentItem(payload) {
  recentList.querySelector(".recent-empty")?.remove();
  const button = element("button", "recent-item");
  button.type = "button";
  const title = payload.title || payload.measurements?.[0]?.claim_text || "기사 수치 검증";
  const matchCount = (payload.measurements || []).filter((item) => verdictClass(item) === "match").length;
  const status = payload.measurements?.length
    ? `${payload.measurements.length}개 측정값 · ${matchCount}개 일치`
    : "검증 대상 없음";
  button.append(element("strong", "", title), element("small", "", status));
  button.addEventListener("click", () => {
    showConversation();
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
  recentList.prepend(button);
  while (recentList.children.length > 5) recentList.lastElementChild.remove();
}

function appendErrorMessage(error) {
  const article = element("article", "message assistant-message error-message");
  const avatar = element("div", "avatar", "FL");
  const box = element("div", "message-body");
  box.append(
    element("h2", "", "분석을 완료하지 못했어요."),
    element("p", "", error.message || "잠시 후 다시 시도해 주세요."),
  );
  article.append(avatar, box);
  chatStream.append(article);
}

function startProgress(loading, messages, firstStepIndex) {
  let step = 0;
  if (firstStepIndex === 0 && inputMode === "url") {
    loading.strong.textContent = "기사 페이지를 가져오고 있어요.";
    loading.small.textContent = "제목·작성일·본문을 자동으로 추출합니다.";
  }
  setFlowStep(firstStepIndex);
  return window.setInterval(() => {
    step = Math.min(step + 1, messages.length - 1);
    loading.strong.textContent = messages[step][0];
    loading.small.textContent = messages[step][1];
    setFlowStep(firstStepIndex + step);
  }, 2300);
}

bodyInput.addEventListener("input", () => {
  charCount.textContent = `${bodyInput.value.length.toLocaleString()} / 200,000`;
  if (bodyInput.value.trim()) formError.textContent = "";
});

inputTabs.forEach((tab) => {
  tab.addEventListener("click", () => setInputMode(tab.dataset.inputMode));
});

bodyInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    form.requestSubmit();
  }
});

newAnalysisButton.addEventListener("click", () => resetConversation({ focus: true }));
mobileNewButton.addEventListener("click", () => resetConversation({ focus: true }));

navItems.forEach((item) => {
  item.addEventListener("click", () => {
    if (item.dataset.section === "chat") {
      if (chatStream.children.length) showConversation();
      else resetConversation();
      return;
    }
    document.body.classList.remove("conversation-active");
    document.body.classList.add("guide-focus");
    navItems.forEach((navItem) => navItem.classList.toggle("active", navItem === item));
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  let endpoint;
  let payload;
  if (inputMode === "direct") {
    const body = bodyInput.value.trim();
    if (!body) {
      formError.textContent = "기사 원문을 입력해 주세요.";
      bodyInput.focus();
      return;
    }
    if (!dateInput.value) {
      formError.textContent = "기사 날짜를 입력해 주세요.";
      dateInput.focus();
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) {
      formError.textContent = "기사 연도는 4자리로 입력해 주세요.";
      dateInput.focus();
      return;
    }
    endpoint = "/api/articles/claims";
    payload = {
      input_mode: "direct",
      body,
      title: titleInput.value.trim(),
      date: dateInput.value,
      splitter: "auto",
      kosis_mode: modeInput.value,
      retrieval_mode: retrievalInput.value,
      contextual: true,
    };
  } else {
    let articleUrl = urlInput.value.trim();
    if (!articleUrl) {
      formError.textContent = "기사 URL을 입력해 주세요.";
      urlInput.focus();
      return;
    }
    if (!/^https?:\/\//i.test(articleUrl)) articleUrl = `https://${articleUrl}`;
    try {
      const parsed = new URL(articleUrl);
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error();
    } catch {
      formError.textContent = "올바른 http 또는 https 기사 URL을 입력해 주세요.";
      urlInput.focus();
      return;
    }
    endpoint = "/api/articles/claims-url";
    payload = {
      input_mode: "url",
      url: articleUrl,
      splitter: "auto",
      kosis_mode: modeInput.value,
      retrieval_mode: retrievalInput.value,
      contextual: true,
    };
  }

  formError.textContent = "";
  submitButton.disabled = true;
  showConversation();
  appendUserMessage(payload);
  const loading = appendLoadingMessage(detectMessages);
  const progressTimer = startProgress(loading, detectMessages, 0);
  scrollToLatest();

  try {
    const requestPayload = { ...payload };
    delete requestPayload.input_mode;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw responseError(result, "분석 요청에 실패했습니다.");
    }
    loading.article.remove();
    appendClaimSelectionMessage(result);
    bodyInput.value = "";
    urlInput.value = "";
    charCount.textContent = "0 / 200,000";
  } catch (error) {
    loading.article.remove();
    appendErrorMessage(error);
    resetFlow();
  } finally {
    window.clearInterval(progressTimer);
    submitButton.disabled = false;
    scrollToLatest();
  }
});
