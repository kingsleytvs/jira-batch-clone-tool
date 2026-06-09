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
  testPhaseField: document.querySelector("#testPhaseField"),
  testPhase: document.querySelector("#testPhase"),
  components: document.querySelector("#bugComponents"),
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

function renderTransitions(issueKey, workflow) {
  const transitions = workflow.transitions || [];
  const currentStatus = workflow.current_status || "Unknown";
  if (!transitions.length) {
    return `
      <div class="transition-box">
        <div class="transition-head">
          <div>
            <strong>Workflow</strong>
            <p>No available workflow transition for ${escapeHtml(issueKey)}.</p>
          </div>
          <span class="status-pill">${escapeHtml(currentStatus)}</span>
        </div>
      </div>
    `;
  }

  const options = transitions
    .map((transition) => {
      const label = transition.to_status
        ? `${transition.name} -> ${transition.to_status}`
        : transition.name;
      return `<option value="${escapeHtml(transition.id)}">${escapeHtml(label)}</option>`;
    })
    .join("");

  return `
    <div class="transition-box" data-issue="${escapeHtml(issueKey)}">
      <div class="transition-head">
        <div>
          <strong>Workflow</strong>
          <p>Current status and available next actions from Jira.</p>
        </div>
        <span class="status-pill">${escapeHtml(currentStatus)}</span>
      </div>
      <div class="transition-actions">
        <label class="transition-field">
          <span>Next Status</span>
          <select class="transition-select">${options}</select>
        </label>
        <label class="transition-field bug-category-field" hidden>
          <span>Bug Category</span>
          <select class="bug-category-select">
            <option value="">None</option>
            <option value="Authorization">Authorization</option>
            <option value="Biz Design Issue">Biz Design Issue</option>
            <option value="IT Design Issue">IT Design Issue</option>
            <option value="Configuration">Configuration</option>
            <option value="Code Bug">Code Bug</option>
            <option value="Previous Release Issue">Previous Release Issue</option>
            <option value="Partner Issue">Partner Issue</option>
            <option value="Product Issue">Product Issue</option>
            <option value="Data Issue">Data Issue</option>
            <option value="Data Migration">Data Migration</option>
            <option value="Integration">Integration</option>
            <option value="IT Transport">IT Transport</option>
            <option value="Network / Infrastructure Issue">Network / Infrastructure Issue</option>
            <option value="System Performance Issue">System Performance Issue</option>
            <option value="Environment Readiness">Environment Readiness</option>
            <option value="Other">Other</option>
          </select>
        </label>
        <button class="secondary transition-button" type="button">Update Status</button>
      </div>
    </div>
  `;
}

async function fetchTransitions(issueKey) {
  const response = await fetch("/api/transitions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_key: issueKey }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not load transitions");
  return {
    current_status: data.current_status,
    transitions: data.transitions || [],
  };
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
        test_phase: issueType === "Bug" ? els.testPhase.value : "",
        components: els.components.value,
        labels: els.labels.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not create bug");

    const workflow = await fetchTransitions(data.key);
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
          ${renderTransitions(data.key, workflow)}
          <details class="payload-box">
            <summary>Payload</summary>
            <pre>${escapeHtml(JSON.stringify(data.payload, null, 2))}</pre>
          </details>
        </div>
      </article>
    `);
    document.querySelectorAll(".transition-box").forEach(syncBugCategoryVisibility);
  } catch (error) {
    renderError(error.message);
  } finally {
    els.createBug.disabled = false;
    hideLoading();
  }
}

async function updateTransition(event) {
  const button = event.target.closest(".transition-button");
  if (!button) {
    return;
  }

  const box = button.closest(".transition-box");
  const issueKey = box.dataset.issue;
  const transitionId = box.querySelector(".transition-select").value;
  const bugCategorySelect = box.querySelector(".bug-category-select");
  const bugCategoryField = box.querySelector(".bug-category-field");
  const bugCategory = bugCategoryField.hidden ? "" : bugCategorySelect.value;

  button.disabled = true;
  showLoading("Updating status", `Applying workflow transition to ${issueKey}`);

  try {
    const response = await fetch("/api/transitions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        issue_key: issueKey,
        transition_id: transitionId,
        bug_category: bugCategory,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not update status");

    box.outerHTML = renderTransitions(issueKey, {
      current_status: data.current_status,
      transitions: data.transitions || [],
    });
    document.querySelectorAll(".transition-box").forEach(syncBugCategoryVisibility);
    els.resultMeta.textContent = `${issueKey} status updated`;
  } catch (error) {
    renderError(error.message);
  } finally {
    button.disabled = false;
    hideLoading();
  }
}

function syncBugCategoryVisibility(box) {
  const transitionSelect = box.querySelector(".transition-select");
  const bugCategoryField = box.querySelector(".bug-category-field");
  const bugCategorySelect = box.querySelector(".bug-category-select");
  if (!transitionSelect || !bugCategoryField || !bugCategorySelect) {
    return;
  }

  const selectedText = transitionSelect.options[transitionSelect.selectedIndex]?.text || "";
  const needsBugCategory = selectedText.toLowerCase().includes("ready for testing");
  bugCategoryField.hidden = !needsBugCategory;
  if (!needsBugCategory) {
    bugCategorySelect.value = "";
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
els.results.addEventListener("click", updateTransition);
els.results.addEventListener("change", (event) => {
  if (event.target.classList.contains("transition-select")) {
    syncBugCategoryVisibility(event.target.closest(".transition-box"));
  }
});
syncIssueTypeFields();
loadConfig().catch((error) => renderError(error.message));
