const state = {
  config: null,
};

const els = {
  loadingScreen: document.querySelector("#loadingScreen"),
  loadingTitle: document.querySelector("#loadingTitle"),
  loadingText: document.querySelector("#loadingText"),
  connectionStatus: document.querySelector("#connectionStatus"),
  form: document.querySelector("#bugForm"),
  project: document.querySelector("#issueProject"),
  issueType: document.querySelector("#issueType"),
  summary: document.querySelector("#bugSummary"),
  description: document.querySelector("#bugDescription"),
  priority: document.querySelector("#bugPriority"),
  assignee: document.querySelector("#bugAssignee"),
  testPhaseField: document.querySelector("#testPhaseField"),
  testPhase: document.querySelector("#testPhase"),
  labels: document.querySelector("#bugLabels"),
  createBug: document.querySelector("#createBug"),
  emptyState: document.querySelector("#bugEmptyState"),
  results: document.querySelector("#bugResults"),
  resultMeta: document.querySelector("#bugResultMeta"),
};

function showLoading(title, text = "") {
  els.loadingTitle.textContent = title;
  els.loadingText.textContent = text;
  els.loadingScreen.classList.add("visible");
}

function hideLoading() {
  els.loadingScreen.classList.remove("visible");
}

function setStatus(text, ok = false) {
  els.connectionStatus.innerHTML = `<span class="pulse ${ok ? "ok" : ""}"></span>${text}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function jiraLink(key) {
  const base = state.config?.base_url || "";
  if (!base || !key) return escapeHtml(key);
  const href = `${base.replace(/\/$/, "")}/browse/${encodeURIComponent(key)}`;
  return `<a href="${href}" target="_blank" rel="noreferrer">${escapeHtml(key)}</a>`;
}

async function loadConfig() {
  showLoading("Loading", "Checking saved Jira connection");
  try {
    const response = await fetch("/api/config");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load config");
    state.config = data;

    const mode = data.auth_mode || "auto";
    const user = data.user ? `, ${data.user}` : "";
    setStatus(`${data.base_url || "No Jira URL"} - ${mode}${user} - token ${data.token_set ? "ready" : "missing"}`, data.token_set);
  } finally {
    hideLoading();
  }
}

function renderResult(content) {
  els.emptyState.style.display = "none";
  els.results.innerHTML = content;
}

function renderError(error) {
  els.resultMeta.textContent = "Create failed";
  renderResult(`
    <article class="result-card status-error">
      <span class="badge error">Error</span>
      <p class="summary error-text">${escapeHtml(error)}</p>
    </article>
  `);
}

async function createBug(event) {
  event.preventDefault();
  els.createBug.disabled = true;
  showLoading("Creating bug", "Posting Bug issue to Jira");

  try {
    const issueType = els.issueType.value;
    const response = await fetch("/api/bug", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_key: els.project.value.trim() || "GLS4",
        issue_type: issueType,
        summary: els.summary.value.trim(),
        description: els.description.value.trim(),
        priority_id: els.priority.value,
        assignee: els.assignee.value.trim(),
        test_phase: issueType === "Bug" ? els.testPhase.value : "",
        labels: els.labels.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not create bug");

    els.resultMeta.textContent = `${data.key} created`;
    renderResult(`
      <article class="result-card status-created">
        <header class="result-top">
          <div class="key-line">
            <span class="badge created">${jiraLink(data.key)}</span>
            <span class="badge created">${escapeHtml(issueType)}</span>
          </div>
        </header>
        <div class="result-body">
          <p class="summary">${escapeHtml(els.summary.value.trim())}</p>
          <details class="payload-box">
            <summary>Payload</summary>
            <pre>${escapeHtml(JSON.stringify(data.payload, null, 2))}</pre>
          </details>
        </div>
      </article>
    `);
  } catch (error) {
    renderError(error.message);
  } finally {
    els.createBug.disabled = false;
    hideLoading();
  }
}

function syncIssueTypeFields() {
  const isBug = els.issueType.value === "Bug";
  els.testPhaseField.style.display = isBug ? "grid" : "none";
  if (!isBug) {
    els.testPhase.value = "";
  }
}

els.issueType.addEventListener("change", syncIssueTypeFields);
els.form.addEventListener("submit", createBug);
syncIssueTypeFields();
loadConfig().catch((error) => renderError(error.message));
