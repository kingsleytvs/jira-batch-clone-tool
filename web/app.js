const state = {
  config: null,
};

const els = {
  loadingScreen: document.querySelector("#loadingScreen"),
  loadingTitle: document.querySelector("#loadingTitle"),
  loadingText: document.querySelector("#loadingText"),
  connectionStatus: document.querySelector("#connectionStatus"),
  jiraBaseUrl: document.querySelector("#jiraBaseUrl"),
  jiraAuthMode: document.querySelector("#jiraAuthMode"),
  jiraUser: document.querySelector("#jiraUser"),
  jiraToken: document.querySelector("#jiraToken"),
  saveConnection: document.querySelector("#saveConnection"),
  form: document.querySelector("#cloneForm"),
  tickets: document.querySelector("#tickets"),
  dryRun: document.querySelector("#dryRun"),
  summaryPrefix: document.querySelector("#summaryPrefix"),
  targetProject: document.querySelector("#targetProject"),
  linkOriginal: document.querySelector("#linkOriginal"),
  linkType: document.querySelector("#linkType"),
  fieldChips: document.querySelector("#fieldChips"),
  runButton: document.querySelector("#runButton"),
  loadConfig: document.querySelector("#loadConfig"),
  clearResults: document.querySelector("#clearResults"),
  emptyState: document.querySelector("#emptyState"),
  results: document.querySelector("#results"),
  resultMeta: document.querySelector("#resultMeta"),
};

function showLoading(title, text = "") {
  els.loadingTitle.textContent = title;
  els.loadingText.textContent = text;
  els.loadingScreen.classList.add("visible");
}

function hideLoading() {
  els.loadingScreen.classList.remove("visible");
}

function selectedFields() {
  return Array.from(els.fieldChips.querySelectorAll("input:checked")).map((input) => input.value);
}

function setSelectedFields(fields) {
  const wanted = new Set(fields || []);
  for (const input of els.fieldChips.querySelectorAll("input")) {
    input.checked = wanted.has(input.value);
  }
}

function setBusy(isBusy) {
  els.runButton.disabled = isBusy;
  els.loadConfig.disabled = isBusy;
  els.runButton.textContent = isBusy
    ? "Running"
    : els.dryRun.checked
      ? "Run Preview"
      : "Create Clones";
}

function setStatus(text, ok = false) {
  els.connectionStatus.innerHTML = `<span class="pulse ${ok ? "ok" : ""}"></span>${text}`;
}

function jiraLink(key) {
  const base = state.config?.base_url || "";
  if (!base || !key) return key;
  const href = `${base.replace(/\/$/, "")}/browse/${encodeURIComponent(key)}`;
  return `<a href="${href}" target="_blank" rel="noreferrer">${key}</a>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadConfig() {
  showLoading("Loading", "Reading local Jira configuration");
  setStatus("Loading Jira profile");
  try {
    const response = await fetch("/api/config");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load config");

    state.config = data;
    els.jiraBaseUrl.value = data.base_url || "";
    els.jiraAuthMode.value = data.auth_mode === "basic" ? "basic" : "pat";
    els.jiraUser.value = data.user || "";
    els.jiraToken.value = "";
    els.jiraToken.placeholder = data.token_set ? "Token saved. Paste a new token to replace it." : "Paste current user's token";
    els.summaryPrefix.value = data.config.summary_prefix || "";
    els.targetProject.value = data.config.target_project || "";
    els.linkOriginal.checked = Boolean(data.config.link_to_original);
    els.linkType.value = data.config.link_type || "Cloners";
    setSelectedFields(data.config.clone_fields || []);

    const mode = data.auth_mode || "auto";
    const user = data.user ? `, ${data.user}` : "";
    setStatus(`${data.base_url || "No Jira URL"} - ${mode}${user} - token ${data.token_set ? "ready" : "missing"}`, data.token_set);
  } finally {
    hideLoading();
  }
}

async function saveConnection() {
  const token = els.jiraToken.value.trim();
  if (!token) {
    renderError("Please paste the current user's Jira token before saving.");
    return;
  }

  els.saveConnection.disabled = true;
  showLoading("Saving connection", "Updating local credential settings");
  try {
    const response = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_url: els.jiraBaseUrl.value.trim(),
        auth_mode: els.jiraAuthMode.value,
        user: els.jiraUser.value.trim(),
        token,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not save connection");
    els.jiraToken.value = "";
    await loadConfig();
    els.resultMeta.textContent = "Connection saved";
  } catch (error) {
    renderError(error.message);
  } finally {
    els.saveConnection.disabled = false;
    hideLoading();
  }
}

function renderError(error) {
  els.emptyState.style.display = "none";
  els.results.innerHTML = `
    <article class="result-card">
      <div class="result-top">
        <div class="key-line"><span class="badge error">Error</span></div>
      </div>
      <p class="summary">${escapeHtml(error)}</p>
    </article>
  `;
  els.resultMeta.textContent = "Run stopped";
}

function renderResults(items, dryRun) {
  els.emptyState.style.display = items.length ? "none" : "grid";
  els.resultMeta.textContent = `${items.length} ticket${items.length === 1 ? "" : "s"} - ${dryRun ? "preview" : "created"}`;

  els.results.innerHTML = items
    .map((item) => {
      const badgeClass = item.status === "created" ? "created" : "";
      const target = item.clone
        ? `<span class="badge created">${jiraLink(item.clone)}</span>`
        : `<span class="badge ${item.status === "error" ? "error" : ""}">${escapeHtml(item.status)}</span>`;
      const payload = item.payload
        ? `
          <details class="payload-box">
            <summary>Payload preview</summary>
            <pre>${escapeHtml(JSON.stringify(item.payload, null, 2))}</pre>
          </details>
        `
        : "";
      const linkNote = item.link_error
        ? `<p class="summary">Link warning: ${escapeHtml(item.link_error)}</p>`
        : "";
      const warning = item.warning
        ? `
          <div class="component-warning">
            <div>
              <strong>Origin component reminder</strong>
              <p>${escapeHtml(item.warning.message)}</p>
            </div>
            <button class="secondary update-origin-component" type="button" data-issue="${escapeHtml(item.source)}">
              Update origin
            </button>
          </div>
        `
        : "";
      const errorBlock = item.error
        ? `<p class="summary error-text">${escapeHtml(item.error)}</p>`
        : "";

      return `
        <article class="result-card status-${escapeHtml(item.status)}">
          <header class="result-top">
            <div class="key-line">
              <span class="badge ${badgeClass}">${jiraLink(item.source)}</span>
              ${target}
            </div>
          </header>
          <div class="result-body">
            ${item.summary ? `<p class="summary">${escapeHtml(item.summary)}</p>` : ""}
            ${errorBlock}
            ${warning}
            ${linkNote}
            ${payload}
          </div>
        </article>
      `;
    })
    .join("");
}

async function runClone(event) {
  event.preventDefault();
  setBusy(true);
  showLoading(
    els.dryRun.checked ? "Running preview" : "Creating cloned tickets",
    "Processing tickets one by one"
  );

  try {
    const dryRun = els.dryRun.checked;
    const response = await fetch("/api/clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tickets: els.tickets.value,
        dry_run: dryRun,
        target_project: els.targetProject.value.trim(),
        summary_prefix: els.summaryPrefix.value,
        clone_fields: selectedFields(),
        link_to_original: els.linkOriginal.checked,
        link_type: els.linkType.value.trim() || "Cloners",
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Run failed");
    renderResults(data.results || [], dryRun);
  } catch (error) {
    renderError(error.message);
  } finally {
    setBusy(false);
    hideLoading();
  }
}

els.form.addEventListener("submit", runClone);
els.saveConnection.addEventListener("click", saveConnection);
els.dryRun.addEventListener("change", () => setBusy(false));
els.loadConfig.addEventListener("click", () => loadConfig().catch((error) => renderError(error.message)));
els.clearResults.addEventListener("click", () => {
  els.results.innerHTML = "";
  els.emptyState.style.display = "grid";
  els.resultMeta.textContent = "No run yet";
});
els.results.addEventListener("click", async (event) => {
  const button = event.target.closest(".update-origin-component");
  if (!button) {
    return;
  }

  const issueKey = button.dataset.issue;
  button.disabled = true;
  button.textContent = "Updating";
  showLoading("Updating origin", `Setting component for ${issueKey}`);

  try {
    const response = await fetch("/api/component", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ issue_key: issueKey }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not update component");
    button.textContent = "Updated";
    button.classList.add("updated");
    els.resultMeta.textContent = `${issueKey} component updated to ${data.component}`;
  } catch (error) {
    button.disabled = false;
    button.textContent = "Update origin";
    renderError(error.message);
  } finally {
    hideLoading();
  }
});

loadConfig().catch((error) => renderError(error.message));
