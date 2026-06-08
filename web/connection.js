const els = {
  loadingScreen: document.querySelector("#loadingScreen"),
  loadingTitle: document.querySelector("#loadingTitle"),
  loadingText: document.querySelector("#loadingText"),
  connectionStatus: document.querySelector("#connectionStatus"),
  form: document.querySelector("#connectionForm"),
  jiraBaseUrl: document.querySelector("#jiraBaseUrl"),
  jiraAuthMode: document.querySelector("#jiraAuthMode"),
  jiraUser: document.querySelector("#jiraUser"),
  jiraToken: document.querySelector("#jiraToken"),
  saveConnection: document.querySelector("#saveConnection"),
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

function showMessage(message, isError = false) {
  setStatus(message, !isError);
}

async function loadConnection() {
  showLoading("Loading connection", "Reading local credential settings");
  try {
    const response = await fetch("/api/config");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load config");

    els.jiraBaseUrl.value = data.base_url || "";
    els.jiraAuthMode.value = data.auth_mode === "basic" ? "basic" : "pat";
    els.jiraUser.value = data.user || "";
    els.jiraToken.value = "";
    els.jiraToken.placeholder = data.token_set
      ? "Token saved. Paste a new token to replace it."
      : "Paste current user's token";

    const mode = data.auth_mode || "auto";
    const user = data.user ? `, ${data.user}` : "";
    setStatus(`${data.base_url || "No Jira URL"} - ${mode}${user} - token ${data.token_set ? "ready" : "missing"}`, data.token_set);
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    hideLoading();
  }
}

async function saveConnection(event) {
  event.preventDefault();
  const token = els.jiraToken.value.trim();
  if (!token) {
    showMessage("Please paste the current user's Jira token before saving.", true);
    return;
  }

  els.saveConnection.disabled = true;
  showLoading("Saving connection", "Updating local .env credential");

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
    setStatus(`${data.base_url} - ${data.auth_mode} - token ready`, true);
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    els.saveConnection.disabled = false;
    hideLoading();
  }
}

els.form.addEventListener("submit", saveConnection);
loadConnection();
