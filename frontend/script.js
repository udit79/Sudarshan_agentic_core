/* Dashboard controller: session, cases, transformation tasks, and safe output rendering. */
document.addEventListener("DOMContentLoaded", () => {
  const api = window.SudarshanAPI;
  if (!api) return;

  const elements = {
    sidebar: document.getElementById("sidebar"),
    collapseBtn: document.getElementById("collapseBtn"),
    mobileMenuBtn: document.getElementById("mobileMenuBtn"),
    promptInput: document.getElementById("promptInput"),
    charCount: document.getElementById("charCount"),
    submitBtn: document.getElementById("submitBtn"),
    newTransformBtn: document.getElementById("newTransformBtn"),
    caseSelect: document.getElementById("caseSelect"),
    newCaseBtn: document.getElementById("newCaseBtn"),
    resultPanel: document.getElementById("resultPanel"),
    resultTitle: document.getElementById("resultTitle"),
    resultMessage: document.getElementById("resultMessage"),
    resultOutput: document.getElementById("resultOutput"),
    cancelTaskBtn: document.getElementById("cancelTaskBtn"),
    recentGrid: document.getElementById("recentGrid"),
    userCard: document.getElementById("userCardBtn"),
    userName: document.querySelector(".user-name"),
    userPlan: document.querySelector(".user-plan"),
    userAvatar: document.querySelector(".user-avatar span"),
    topAvatar: document.querySelector(".top-user-avatar span"),
    greetingName: document.querySelector(".highlight-name"),
    toastContainer: document.getElementById("toastContainer"),
  };

  const outputCards = [...document.querySelectorAll(".output-card")];
  const selectedOutputTypes = new Set(["executive_summary"]);
  const terminalStates = new Set(["succeeded", "partial", "failed", "cancelled"]);
  let activeTaskId = null;
  let pollTimer = null;
  let currentUser = null;

  function showToast(message, isError = false) {
    if (!elements.toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast${isError ? " error" : ""}`;
    toast.textContent = message;
    elements.toastContainer.appendChild(toast);
    window.setTimeout(() => toast.remove(), 4500);
  }

  function showApiError(error) {
    const suffix = error.requestId ? ` (${error.requestId})` : "";
    showToast(`${error.message}${suffix}`, true);
  }

  function initials(user) {
    const source = user?.name || user?.email || "User";
    return source.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  }

  function formatTime(value) {
    if (!value) return "Just now";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Recently" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }

  function recentStorageKey() {
    return `sudarshan.recentTasks.${currentUser?.id || "anonymous"}`;
  }

  function readRecentTasks() {
    try {
      const value = JSON.parse(localStorage.getItem(recentStorageKey()) || "[]");
      return Array.isArray(value) ? value : [];
    } catch {
      return [];
    }
  }

  function setPromptBusy(isBusy) {
    elements.submitBtn.disabled = isBusy;
    elements.promptInput.disabled = isBusy;
    elements.caseSelect.disabled = isBusy;
    elements.newCaseBtn.disabled = isBusy;
    elements.submitBtn.classList.toggle("is-loading", isBusy);
  }

  function selectedLabels() {
    return outputCards.filter((card) => selectedOutputTypes.has(card.dataset.type))
      .map((card) => card.querySelector(".card-title")?.textContent.trim())
      .filter(Boolean);
  }

  function updateOutputSelection() {
    outputCards.forEach((card) => {
      const selected = selectedOutputTypes.has(card.dataset.type);
      card.classList.toggle("active", selected);
      card.setAttribute("aria-pressed", String(selected));
    });
    const labels = selectedLabels();
    elements.promptInput.placeholder = labels.length
      ? `Describe what you want to create for ${labels.join(" + ")}...`
      : "Select at least one output format, then describe what to create...";
  }

  function renderCases(cases) {
    elements.caseSelect.replaceChildren();
    if (!cases.length) {
      const empty = new Option("Create a case to begin", "");
      elements.caseSelect.add(empty);
      elements.promptInput.disabled = true;
      elements.submitBtn.disabled = true;
      return;
    }
    cases.forEach((item) => {
      const option = new Option(item.name, item.case_id);
      option.title = item.case_id;
      elements.caseSelect.add(option);
    });
    elements.promptInput.disabled = false;
    elements.submitBtn.disabled = false;
  }

  function renderResult(task) {
    if (!task) return;
    const status = task.status || "queued";
    elements.resultPanel.hidden = false;
    elements.resultTitle.textContent = status.replaceAll("_", " ");
    elements.resultMessage.textContent = task.error || `Task ${task.task_id || ""} · ${task.usage?.total_tokens ?? 0} total tokens`;
    elements.resultOutput.textContent = task.result ? JSON.stringify(task.result, null, 2) : "Waiting for transformed output…";
    elements.cancelTaskBtn.hidden = terminalStates.has(status);
    elements.cancelTaskBtn.disabled = status === "cancelled";
  }

  function saveRecentTask(task) {
    if (!task?.task_id) return;
    const saved = readRecentTasks()
      .filter((item) => item.task_id !== task.task_id);
    saved.unshift({ task_id: task.task_id, case_id: task.case_id, created_at: task.created_at });
    localStorage.setItem(recentStorageKey(), JSON.stringify(saved.slice(0, 8)));
  }

  function renderRecentTask(task) {
    if (!elements.recentGrid || !task?.task_id) return;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "recent-card recent-card-button";
    card.dataset.taskId = task.task_id;
    const title = document.createElement("h4");
    title.className = "recent-title";
    title.textContent = `${task.output_types?.join(" + ") || "Transformation"}`;
    const snippet = document.createElement("p");
    snippet.className = "recent-snippet";
    snippet.textContent = task.task_id;
    const timestamp = document.createElement("span");
    timestamp.className = "recent-timestamp";
    timestamp.textContent = formatTime(task.created_at);
    card.append(title, snippet, timestamp);
    elements.recentGrid.prepend(card);
    while (elements.recentGrid.children.length > 8) elements.recentGrid.lastElementChild.remove();
  }

  function renderRecentTasks() {
    if (!elements.recentGrid) return;
    elements.recentGrid.replaceChildren();
    const saved = readRecentTasks();
    if (!saved.length) {
      const empty = document.createElement("p");
      empty.className = "recent-empty";
      empty.textContent = "Your completed transformations will appear here.";
      elements.recentGrid.append(empty);
    }
  }

  async function pollTask(taskId) {
    try {
      const response = await api.getTask(taskId);
      const task = response.task || response;
      if (task.task_id !== activeTaskId) return;
      renderResult(task);
      if (terminalStates.has(task.status)) {
        setPromptBusy(false);
        saveRecentTask(task);
        renderRecentTask(task);
        activeTaskId = null;
        return;
      }
      pollTimer = window.setTimeout(() => pollTask(taskId), 1800);
    } catch (error) {
      setPromptBusy(false);
      showApiError(error);
    }
  }

  async function submitTransformation() {
    const input = elements.promptInput.value.trim();
    const caseId = elements.caseSelect.value;
    const outputTypes = [...selectedOutputTypes];
    if (!caseId) return showToast("Create or select a case first.", true);
    if (!input) return showToast("Enter a transformation request first.", true);
    if (!outputTypes.length) return showToast("Select at least one output type.", true);

    window.clearTimeout(pollTimer);
    setPromptBusy(true);
    elements.resultPanel.hidden = false;
    elements.resultTitle.textContent = "Submitting";
    elements.resultMessage.textContent = "The gateway is calculating input tokens and starting the task…";
    elements.resultOutput.textContent = "";
    try {
      const requestKey = `frontend-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const response = await api.createTransform({
        case_id: caseId,
        input,
        output_types: outputTypes,
        classification_level: "RESTRICTED",
        distribution: "Authorized NTRO personnel",
      }, requestKey);
      const task = response.task || response;
      activeTaskId = task.task_id;
      renderResult(task);
      saveRecentTask(task);
      renderRecentTask(task);
      elements.promptInput.value = "";
      elements.charCount.textContent = "0/50,000";
      elements.promptInput.style.height = "auto";
      pollTask(activeTaskId);
    } catch (error) {
      setPromptBusy(false);
      showApiError(error);
    }
  }

  async function createCase() {
    const name = window.prompt("Name this case");
    if (!name?.trim()) return;
    const caseId = `case-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    try {
      const created = await api.createCase({ case_id: caseId, name: name.trim() });
      const casesResponse = await api.listCases();
      renderCases(casesResponse.cases || []);
      elements.caseSelect.value = created.case_id;
      showToast("Case created.");
    } catch (error) {
      showApiError(error);
    }
  }

  async function cancelActiveTask() {
    if (!activeTaskId) return;
    try {
      const response = await api.cancelTask(activeTaskId);
      const task = response.task || response;
      renderResult(task);
      if (terminalStates.has(task.status)) {
        window.clearTimeout(pollTimer);
        setPromptBusy(false);
        activeTaskId = null;
      }
    } catch (error) {
      showApiError(error);
    }
  }

  function wireUi() {
    elements.collapseBtn?.addEventListener("click", () => elements.sidebar.classList.toggle("collapsed"));
    elements.mobileMenuBtn?.addEventListener("click", (event) => {
      event.stopPropagation();
      elements.sidebar.classList.toggle("mobile-open");
    });
    document.addEventListener("click", (event) => {
      if (elements.sidebar && !elements.sidebar.contains(event.target) && !elements.mobileMenuBtn?.contains(event.target)) {
        elements.sidebar.classList.remove("mobile-open");
      }
    });
    elements.promptInput?.addEventListener("input", () => {
      elements.charCount.textContent = `${elements.promptInput.value.length.toLocaleString()}/50,000`;
      elements.promptInput.style.height = "auto";
      elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 180)}px`;
    });
    elements.promptInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submitTransformation();
      }
    });
    elements.submitBtn?.addEventListener("click", submitTransformation);
    elements.newTransformBtn?.addEventListener("click", () => {
      elements.promptInput.value = "";
      elements.charCount.textContent = "0/50,000";
      elements.promptInput.focus();
    });
    elements.newCaseBtn?.addEventListener("click", createCase);
    elements.cancelTaskBtn?.addEventListener("click", cancelActiveTask);
    elements.userCard?.addEventListener("click", async () => {
      if (!window.confirm("Sign out of Sudarshan?")) return;
      try { await api.logout(); window.location.replace("login.html"); } catch (error) { showApiError(error); }
    });
    elements.recentGrid?.addEventListener("click", (event) => {
      const card = event.target.closest("[data-task-id]");
      if (!card) return;
      activeTaskId = card.dataset.taskId;
      pollTask(activeTaskId);
    });
    outputCards.forEach((card) => card.addEventListener("click", () => {
      const type = card.dataset.type;
      if (selectedOutputTypes.has(type) && selectedOutputTypes.size === 1) return;
      if (selectedOutputTypes.has(type)) selectedOutputTypes.delete(type);
      else selectedOutputTypes.add(type);
      updateOutputSelection();
    }));
  }

  async function initialize() {
    try {
      currentUser = (await api.getCurrentUser()).user;
      const name = currentUser.name || currentUser.email;
      elements.userName.textContent = name;
      elements.userPlan.textContent = currentUser.email;
      elements.userAvatar.textContent = initials(currentUser);
      elements.topAvatar.textContent = initials(currentUser);
      elements.greetingName.textContent = `${name.split(" ")[0]}.`;
      const casesResponse = await api.listCases();
      renderCases(casesResponse.cases || []);
      renderRecentTasks();
      updateOutputSelection();
    } catch (error) {
      if (error.status === 401) window.location.replace("login.html");
      else showApiError(error);
    }
  }

  wireUi();
  initialize();
});
