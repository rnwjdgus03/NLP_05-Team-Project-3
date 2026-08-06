const form = document.querySelector("#analysisForm");
const bodyInput = document.querySelector("#articleBody");
const titleInput = document.querySelector("#articleTitle");
const dateInput = document.querySelector("#articleDate");
const urlInput = document.querySelector("#articleUrl");
const modeInput = document.querySelector("#kosisMode");
const submitButton = document.querySelector("#submitButton");
const formError = document.querySelector("#formError");
const charCount = document.querySelector("#charCount");
const chatStream = document.querySelector("#chatStream");
const flowItems = [...document.querySelectorAll("#flowList li")];
const inputTabs = [...document.querySelectorAll("[data-input-mode]")];
const directInputPane = document.querySelector("#directInputPane");
const urlInputPane = document.querySelector("#urlInputPane");
let inputMode = "direct";

const progressMessages = [
  ["기사 본문을 정리하고 있어요.", "문장 분리와 앞 문맥을 연결합니다."],
  ["통계 주장을 찾고 있어요.", "검증할 수 있는 수치 주장을 선별합니다."],
  ["수치와 기간을 구조화하고 있어요.", "각 measurement의 지표·단위·시점을 확인합니다."],
  ["KOSIS 통계와 대조하고 있어요.", "공식 통계표 후보와 실제값을 조회합니다."],
];

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
  const copy = element(
    "p",
    "",
    payload.input_mode === "url" ? payload.url : payload.body,
  );
  box.append(meta, copy);
  article.append(box);
  chatStream.append(article);
}

function appendLoadingMessage() {
  const article = element("article", "message assistant-message loading-message");
  const avatar = element("div", "avatar", "FL");
  const box = element("div", "message-body");
  const row = element("div", "loading-row");
  const dots = element("div", "loading-dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(element("i"), element("i"), element("i"));
  const copy = element("div", "loading-copy");
  const strong = element("strong", "", progressMessages[0][0]);
  const small = element("small", "", progressMessages[0][1]);
  copy.append(strong, small);
  row.append(dots, copy);
  box.append(row);
  article.append(avatar, box);
  chatStream.append(article);
  return { article, strong, small };
}

function verdictClass(item) {
  if (item.status_code === "MATCH" || item.status === "일치") return "match";
  if (item.status_code === "VALUE_MISMATCH" || item.status === "불일치") return "mismatch";
  return "review";
}

function appendSummaryGrid(container, summary) {
  const grid = element("div", "summary-grid");
  const items = [
    [summary.sentence_count, "분석 문장"],
    [summary.claim_count, "통계 주장"],
    [summary.measurement_count, "추출 측정값"],
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
  const verdict = element("span", `verdict ${verdictClass(item)}`, item.status || "판단불가");
  head.append(label, verdict);

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
    element("p", "eyebrow", "ANALYSIS COMPLETE"),
    element("h2", "", "기사 수치 검증 결과입니다."),
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

function startProgress(loading) {
  let step = 0;
  if (inputMode === "url") {
    loading.strong.textContent = "기사 페이지를 가져오고 있어요.";
    loading.small.textContent = "제목·작성일·본문을 자동으로 추출합니다.";
  }
  setFlowStep(0);
  return window.setInterval(() => {
    step = Math.min(step + 1, progressMessages.length - 1);
    loading.strong.textContent = progressMessages[step][0];
    loading.small.textContent = progressMessages[step][1];
    setFlowStep(step);
  }, 2300);
}

bodyInput.addEventListener("input", () => {
  charCount.textContent = `${bodyInput.value.length.toLocaleString()} / 200,000`;
  if (bodyInput.value.trim()) formError.textContent = "";
});

inputTabs.forEach((tab) => {
  tab.addEventListener("click", () => setInputMode(tab.dataset.inputMode));
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
    endpoint = "/api/articles/analyze";
    payload = {
      input_mode: "direct",
      body,
      title: titleInput.value.trim(),
      date: dateInput.value,
      splitter: "auto",
      kosis_mode: modeInput.value,
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
    endpoint = "/api/articles/analyze-url";
    payload = {
      input_mode: "url",
      url: articleUrl,
      splitter: "auto",
      kosis_mode: modeInput.value,
    };
  }

  formError.textContent = "";
  submitButton.disabled = true;
  appendUserMessage(payload);
  const loading = appendLoadingMessage();
  const progressTimer = startProgress(loading);
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
      throw result.error || { message: "분석 요청에 실패했습니다." };
    }
    loading.article.remove();
    appendResultMessage(result);
    setFlowStep(progressMessages.length);
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
