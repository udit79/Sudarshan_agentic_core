/* Dashboard controller: session, cases, chats, transformation tasks, and rich output rendering. */
document.addEventListener("DOMContentLoaded", () => {
  const api = window.SudarshanAPI;
  if (!api) return;

  const elements = {
    sidebar: document.getElementById("sidebar"),
    collapseBtn: document.getElementById("collapseBtn"),
    mobileMenuBtn: document.getElementById("mobileMenuBtn"),
    sidebarChatList: document.getElementById("sidebarChatList"),
    sidebarHistoryList: document.getElementById("sidebarHistoryList"),
    sidebarHistoryCount: document.getElementById("sidebarHistoryCount"),
    sidebarNewChatBtn: document.getElementById("sidebarNewChatBtn"),
    promptInput: document.getElementById("promptInput"),
    charCount: document.getElementById("charCount"),
    submitBtn: document.getElementById("submitBtn"),
    fileInput: document.getElementById("fileInput"),
    attachFilesBtn: document.getElementById("attachFilesBtn"),
    attachmentList: document.getElementById("attachmentList"),
    newTransformBtn: document.getElementById("newTransformBtn"),
    caseSelect: document.getElementById("caseSelect"),
    newCaseBtn: document.getElementById("newCaseBtn"),
    resultPanel: document.getElementById("resultPanel"),
    resultTitle: document.getElementById("resultTitle"),
    resultMessage: document.getElementById("resultMessage"),
    resultOutput: document.getElementById("resultOutput"),
    outputTabsContainer: document.getElementById("outputTabsContainer"),
    outputTabsList: document.getElementById("outputTabsList"),
    richOutputContainer: document.getElementById("richOutputContainer"),
    exportOutputBtn: document.getElementById("exportOutputBtn"),
    exportBtnLabel: document.getElementById("exportBtnLabel"),
    stopTaskBtn: document.getElementById("stopTaskBtn"),
    taskProgress: document.getElementById("taskProgress"),
    taskProgressBar: document.getElementById("taskProgressBar"),
    taskProgressValue: document.getElementById("taskProgressValue"),
    taskProgressLabel: document.getElementById("taskProgressLabel"),
    runObservability: document.getElementById("runObservability"),
    runStageValue: document.getElementById("runStageValue"),
    runChildrenValue: document.getElementById("runChildrenValue"),
    runQualityValue: document.getElementById("runQualityValue"),
    runCursorValue: document.getElementById("runCursorValue"),
    runTokensValue: document.getElementById("runTokensValue"),
    runLatencyValue: document.getElementById("runLatencyValue"),
    runCacheValue: document.getElementById("runCacheValue"),
    runWaitsValue: document.getElementById("runWaitsValue"),
    runWaitingNotice: document.getElementById("runWaitingNotice"),
    runWaitingReason: document.getElementById("runWaitingReason"),
    toggleAllOutputsBtn: document.getElementById("toggleAllOutputsBtn"),
    viewAllLabel: document.getElementById("viewAllLabel"),
    recentFilterBar: document.getElementById("recentFilterBar"),
    recentGrid: document.getElementById("recentGrid"),
    userCard: document.getElementById("userCardBtn"),
    userName: document.querySelector(".user-name"),
    userPlan: document.querySelector(".user-plan"),
    userAvatar: document.querySelector(".user-avatar span"),
    topAvatar: document.querySelector(".top-user-avatar span"),
    greetingName: document.querySelector(".highlight-name"),
    backendStatusBadge: document.getElementById("backendStatusBadge"),
    backendStatusDot: document.getElementById("backendStatusDot"),
    backendStatusText: document.getElementById("backendStatusText"),
    configModal: document.getElementById("configModal"),
    configForm: document.getElementById("configForm"),
    configInput: document.getElementById("openaiApiKey"),
    configError: document.getElementById("configModalError"),
    configSkipBtn: document.getElementById("configSkipBtn"),
  };

  const outputCards = [...document.querySelectorAll(".output-card")];
  const allOutputTypes = ["executive_summary", "presentation", "advisory", "infographic", "video", "linkedin_post"];
  const selectedOutputTypes = new Set(["executive_summary"]);
  const terminalStates = new Set(["succeeded", "partial", "failed", "cancelled", "completed"]);

  let activeTaskId = null;
  let activeChatId = null;
  let currentTaskData = null;
  let activeTabType = null;
  let currentSlideIndex = 0;
  let activeRecentFilter = "all";
  let pollTimer = null;
  let closeProgressStream = null;
  const selectedFiles = [];
  const supportedUploadExtensions = new Set([
    "txt", "pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp",
    "pptx", "pptm", "ppsx", "ppsm", "potx", "potm", "mp4", "mov", "avi", "mkv", "webm",
  ]);
  const sudarshanDisplayName = "Sudarshan Operator";
  const sudarshanFriendlyLine = "“From context to clarity.”";
  let currentUser = { id: "operator-default", name: sudarshanDisplayName, email: "" };

  // Toast notifications
  function showToast(message, isError = false) {
    if (!elements.toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast${isError ? " error" : ""}`;
    toast.textContent = message;
    elements.toastContainer.appendChild(toast);
    window.setTimeout(() => toast.remove(), 4000);
  }

  function showApiError(error) {
    const suffix = error.requestId ? ` (${error.requestId})` : "";
    showToast(`${error.message}${suffix}`, true);
  }

  function updateTaskProgress(progress, message = "", stage = "") {
    if (!elements.taskProgress) return;

    const numericProgress = Number(progress);
    const hasProgress = Number.isFinite(numericProgress);
    const boundedProgress = hasProgress
      ? Math.min(100, Math.max(0, numericProgress))
      : null;
    const readableStage = stage ? String(stage).replaceAll("_", " ") : "";
    const label = message || (readableStage ? `Stage: ${readableStage}` : "Agent progress");

    elements.taskProgress.hidden = false;
    if (elements.taskProgressLabel) elements.taskProgressLabel.textContent = label;
    if (boundedProgress !== null) {
      if (elements.taskProgressBar) elements.taskProgressBar.style.width = `${boundedProgress}%`;
      if (elements.taskProgressValue) elements.taskProgressValue.textContent = `${Math.round(boundedProgress)}%`;
      const track = elements.taskProgress.querySelector('[role="progressbar"]');
      track?.setAttribute("aria-valuenow", String(Math.round(boundedProgress)));
    }
    if (elements.resultMessage && (hasProgress || message || readableStage)) {
      const progressText = boundedProgress === null ? "Progress" : `Progress ${Math.round(boundedProgress)}%`;
      elements.resultMessage.textContent = `${progressText}${readableStage ? ` · ${readableStage}` : ""}`;
    }
  }

  function resetTaskProgress() {
    if (!elements.taskProgress) return;
    elements.taskProgress.hidden = true;
    if (elements.taskProgressBar) elements.taskProgressBar.style.width = "0%";
    if (elements.taskProgressValue) elements.taskProgressValue.textContent = "0%";
    const track = elements.taskProgress.querySelector('[role="progressbar"]');
    track?.setAttribute("aria-valuenow", "0");
  }

  function renderRunProjectionMeta(task) {
    if (!task) return;
    if (elements.runObservability) elements.runObservability.hidden = false;
    if (elements.runStageValue) elements.runStageValue.textContent = task.stage || "—";
    if (elements.runChildrenValue) {
      const childCount = Number.isFinite(Number(task.child_count))
        ? Number(task.child_count)
        : (Array.isArray(task.children) ? task.children.length : 0);
      elements.runChildrenValue.textContent = String(childCount);
    }
    if (elements.runQualityValue) {
      elements.runQualityValue.textContent = task.quality_status || "pending";
    }
    if (elements.runCursorValue) {
      elements.runCursorValue.textContent = String(Number(task.event_cursor || 0));
    }
    const telemetry = task.telemetry || {};
    const totalTokens = Number(telemetry.total_tokens ?? (
      Number(telemetry.input_tokens || 0)
      + Number(telemetry.output_tokens || 0)
      + Number(telemetry.reasoning_tokens || 0)
    ));
    if (elements.runTokensValue) elements.runTokensValue.textContent = String(Number.isFinite(totalTokens) ? totalTokens : 0);
    if (elements.runLatencyValue) elements.runLatencyValue.textContent = `${Number(telemetry.latency_ms || 0)} ms`;
    if (elements.runCacheValue) elements.runCacheValue.textContent = `${Number(telemetry.cache_hits || 0)} hits`;
    if (elements.runWaitsValue) elements.runWaitsValue.textContent = String(Number(telemetry.wait_count || 0));

    const status = String(task.status || "").toLowerCase();
    const waiting = ["waiting", "waiting_for_input", "paused"].includes(status) || task.requires_action;
    if (elements.runWaitingNotice) elements.runWaitingNotice.hidden = !waiting;
    if (waiting && elements.runWaitingReason) {
      elements.runWaitingReason.textContent = task.wait_reason || task.message || "The agent is waiting for the next permitted action.";
    }
  }

  function handleProgressEvent(event) {
    const payload = event && typeof event === "object" ? event : {};
    if (currentTaskData && payload.sequence != null) {
      currentTaskData.event_cursor = Math.max(
        Number(currentTaskData.event_cursor || 0),
        Number(payload.sequence || 0),
      );
      currentTaskData.status = payload.status || currentTaskData.status;
      currentTaskData.stage = payload.stage || currentTaskData.stage;
      currentTaskData.progress = Number(payload.progress ?? currentTaskData.progress ?? 0);
      currentTaskData.child_count = Number(payload.child_count ?? currentTaskData.child_count ?? 0);
      currentTaskData.quality_status = payload.quality_status || currentTaskData.quality_status;
      currentTaskData.requires_action = Boolean(payload.requires_action ?? currentTaskData.requires_action ?? false);
      currentTaskData.wait_reason = payload.wait_reason || currentTaskData.wait_reason || "";
      currentTaskData.telemetry = payload.telemetry || currentTaskData.telemetry || {};
      renderRunProjectionMeta(currentTaskData);
    }
    const message = payload.message || "";
    const stepEl = document.getElementById("liveStepIndicator");
    if (stepEl && message) stepEl.textContent = message;
    updateTaskProgress(payload.progress, message, payload.stage || "");
  }

  function showConfigurationPrompt() {
    if (!elements.configModal || !elements.configForm) return;
    elements.configModal.hidden = false;
    elements.configInput?.focus();
  }

  function hideConfigurationPrompt() {
    if (elements.configModal) elements.configModal.hidden = true;
    if (elements.configInput) elements.configInput.value = "";
  }

  async function submitConfiguration(event) {
    event.preventDefault();
    const apiKey = elements.configInput?.value.trim() || "";
    if (!apiKey) return;
    const submit = elements.configForm.querySelector("button[type=submit]");
    if (submit) submit.disabled = true;
    if (elements.configError) elements.configError.hidden = true;
    try {
      await api.configureSession(apiKey);
      hideConfigurationPrompt();
      showToast("OpenAI configured for this running session.");
    } catch (error) {
      if (elements.configError) {
        elements.configError.textContent = error.message || "The API key could not be configured.";
        elements.configError.hidden = false;
      }
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 1024) return `${bytes || 0} B`;
    const units = ["KB", "MB", "GB"];
    let value = bytes;
    let unit = "B";
    for (const nextUnit of units) {
      value /= 1024;
      unit = nextUnit;
      if (value < 1024 || nextUnit === units.at(-1)) break;
    }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${unit}`;
  }

  function renderAttachments() {
    if (!elements.attachmentList) return;
    elements.attachmentList.replaceChildren();
    elements.attachmentList.hidden = selectedFiles.length === 0;
    selectedFiles.forEach((file, index) => {
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      const icon = document.createElement("span");
      icon.textContent = "📎";
      const name = document.createElement("span");
      name.className = "attachment-chip-name";
      name.textContent = file.name;
      name.title = file.name;
      const size = document.createElement("span");
      size.className = "attachment-chip-status";
      size.textContent = formatBytes(file.size);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "attachment-remove";
      remove.title = `Remove ${file.name}`;
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        selectedFiles.splice(index, 1);
        renderAttachments();
      });
      chip.append(icon, name, size, remove);
      elements.attachmentList.appendChild(chip);
    });
  }

  function addSelectedFiles(fileList) {
    const files = [...(fileList || [])];
    const rejected = [];
    for (const file of files) {
      const extension = file.name.split(".").pop()?.toLowerCase() || "";
      if (!supportedUploadExtensions.has(extension)) {
        rejected.push(file.name);
        continue;
      }
      if (!selectedFiles.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) {
        selectedFiles.push(file);
      }
    }
    renderAttachments();
    if (rejected.length) {
      showToast(`Unsupported file type: ${rejected.join(", ")}`, true);
    }
    if (selectedFiles.length) {
      showToast(`${selectedFiles.length} source file${selectedFiles.length === 1 ? "" : "s"} ready to add.`);
    }
  }

  async function ingestSelectedFiles(caseId) {
    if (!selectedFiles.length) return;
    if (elements.attachFilesBtn) elements.attachFilesBtn.disabled = true;
    try {
      let index = 0;
      while (index < selectedFiles.length) {
        const file = selectedFiles[index];
        const ingestionProgress = Math.min(20, 5 + Math.round((index / selectedFiles.length) * 15));
        updateTaskProgress(
          ingestionProgress,
          `Adding source ${index + 1} of ${selectedFiles.length}: ${file.name}`,
          "source_ingestion",
        );
        elements.resultMessage.textContent = `Adding source ${index + 1} of ${selectedFiles.length}: ${file.name}`;
        await api.ingestFile(file, {
          caseId,
          taskId: `ingest-${Date.now()}-${index}`,
          classificationLevel: "RESTRICTED",
        });
        selectedFiles.splice(index, 1);
        renderAttachments();
      }
      updateTaskProgress(20, "Source files indexed; preparing the agentic run...", "source_ingestion");
      showToast("Source files added to case memory.");
    } finally {
      if (elements.attachFilesBtn) elements.attachFilesBtn.disabled = false;
    }
  }

  function initials(user) {
    const source = user?.name || user?.email || "User";
    return source.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  }

  function formatTime(value) {
    if (!value) return "Just now";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Recently";
    const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diffSec < 60) return "Just now";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // Local Storage Keys
  function recentStorageKey() {
    return `sudarshan.recentTasks.${currentUser?.id || "default"}`;
  }

  function chatsStorageKey() {
    return `sudarshan.chats.${currentUser?.id || "default"}`;
  }

  function adoptCurrentUser(user) {
    if (!user || typeof user !== "object") return;
    const previousId = currentUser?.id || "operator-default";
    const nextId = user.id || user.user_id || previousId;
    if (previousId !== nextId) {
      for (const prefix of ["sudarshan.chats.", "sudarshan.recentTasks."]) {
        const previousKey = `${prefix}${previousId}`;
        const nextKey = `${prefix}${nextId}`;
        const previousValue = localStorage.getItem(previousKey);
        if (previousValue && !localStorage.getItem(nextKey)) {
          localStorage.setItem(nextKey, previousValue);
        }
      }
    }
    currentUser = { ...currentUser, ...user, id: nextId };
    cachedRecentTasks = null;
  }

  // Dynamic Chat Naming derived from user query/question
  function generateChatTitle(prompt) {
    if (!prompt || typeof prompt !== "string") return "Intelligence Query";
    let clean = prompt.replace(/\r?\n+/g, " ").replace(/\s+/g, " ").trim();
    clean = clean.replace(/^["'“`]+|["'”`]+$/g, "");
    clean = clean.replace(/^(can you please |could you please |please |can you |could you |i want you to |tell me about |give me a |give me an |generate a |generate an |create a |create an |write a |write an |draft a |draft an |provide a |provide an |show me )/i, "").trim();

    if (!clean) return "Intelligence Query";
    clean = clean.charAt(0).toUpperCase() + clean.slice(1);

    const maxLen = 34;
    if (clean.length <= maxLen) return clean;

    const truncated = clean.slice(0, maxLen);
    const lastSpace = truncated.lastIndexOf(" ");
    if (lastSpace > 16) {
      return `${truncated.slice(0, lastSpace)}…`;
    }
    return `${truncated}…`;
  }

  // Chats Storage (Real User Chats)
  function getChats() {
    try {
      let data = JSON.parse(localStorage.getItem(chatsStorageKey()));
      if (Array.isArray(data) && data.length > 0) {
        let seenEmpty = false;
        data = data.filter((c) => {
          if (c.title === "New Chat" || c.isNew) {
            if (seenEmpty) return false;
            seenEmpty = true;
            return true;
          }
          return true;
        });
        return data;
      }
    } catch { /* fallback */ }

    const defaults = [
      { id: "chat-main", title: "New Chat", case_id: "case-main", created_at: Date.now(), isNew: true }
    ];
    localStorage.setItem(chatsStorageKey(), JSON.stringify(defaults));
    return defaults;
  }

  function saveChats(chats) {
    localStorage.setItem(chatsStorageKey(), JSON.stringify(chats));
    renderSidebarChats();
    syncCaseSelect();
  }

  // Real User Recent Tasks (No fake placeholder data)
  let cachedRecentTasks = null;

  function readRecentTasks() {
    if (cachedRecentTasks !== null) {
      return cachedRecentTasks;
    }
    try {
      const data = JSON.parse(localStorage.getItem(recentStorageKey()));
      if (Array.isArray(data)) {
        cachedRecentTasks = data;
        return data;
      }
    } catch { /* fallback */ }

    cachedRecentTasks = [];
    return [];
  }

  function saveRecentTask(task) {
    if (!task?.task_id) return;
    const current = readRecentTasks().filter((t) => t.task_id !== task.task_id);
    current.unshift(task);
    cachedRecentTasks = current.slice(0, 30);
    localStorage.setItem(recentStorageKey(), JSON.stringify(cachedRecentTasks));
    renderSidebarHistory();
    renderRecentTasks();
  }

  async function syncRemoteHistory() {
    if (!api.listTasks) return;
    try {
      const response = await api.listTasks();
      const remoteTasks = response?.tasks || [];
      if (!Array.isArray(remoteTasks) || remoteTasks.length === 0) return;

      const merged = new Map(remoteTasks.filter((task) => task?.task_id).map((task) => [task.task_id, task]));
      for (const localTask of readRecentTasks()) {
        if (!localTask?.task_id) continue;
        const remoteTask = merged.get(localTask.task_id);
        // Preserve the richer browser copy when it contains rendered output.
        if (!remoteTask || localTask.result || new Date(localTask.updated_at || 0) > new Date(remoteTask.updated_at || 0)) {
          merged.set(localTask.task_id, localTask);
        }
      }
      cachedRecentTasks = [...merged.values()]
        .sort((left, right) => new Date(right.updated_at || right.created_at || 0) - new Date(left.updated_at || left.created_at || 0))
        .slice(0, 30);
      localStorage.setItem(recentStorageKey(), JSON.stringify(cachedRecentTasks));
      renderSidebarHistory();
      renderRecentTasks();
    } catch {
      // Local history remains usable when the gateway history endpoint is unavailable.
    }
  }

  // Format Helper
  function formatName(type) {
    const map = {
      executive_summary: "Intelligence Brief",
      presentation: "Presentation",
      advisory: "Report",
      infographic: "Infographic",
      video: "Video Package",
      linkedin_post: "LinkedIn Post"
    };
    return map[type] || type;
  }

  function badgeClass(type) {
    const map = {
      executive_summary: "badge-brief",
      presentation: "badge-presentation",
      advisory: "badge-report",
      infographic: "badge-infographic",
      video: "badge-video",
      linkedin_post: "badge-social"
    };
    return map[type] || "badge-brief";
  }

  function formatShort(type) {
    const map = {
      executive_summary: "Brief",
      presentation: "PPT",
      advisory: "Report",
      infographic: "Infographic",
      video: "Video",
      linkedin_post: "LinkedIn"
    };
    return map[type] || "Brief";
  }

  // Left Sidebar: Render Chats
  function renderSidebarChats() {
    if (!elements.sidebarChatList) return;
    elements.sidebarChatList.replaceChildren();
    const chats = getChats();

    if (!activeChatId && chats.length > 0) {
      activeChatId = chats[0].id;
    }

    chats.forEach((chat) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `chat-item-btn${chat.id === activeChatId ? " active" : ""}`;
      btn.dataset.chatId = chat.id;

      const content = document.createElement("div");
      content.className = "chat-item-content";

      const icon = document.createElement("span");
      icon.className = "chat-item-icon";
      icon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;

      const title = document.createElement("span");
      title.className = "chat-item-title";
      title.textContent = chat.title;
      title.title = chat.prompt || chat.title;

      content.append(icon, title);

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "chat-delete-btn";
      delBtn.title = "Delete chat";
      delBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteChat(chat.id);
      });

      btn.append(content, delBtn);

      btn.addEventListener("click", () => {
        selectChat(chat.id);
      });

      elements.sidebarChatList.appendChild(btn);
    });
  }

  function selectChat(chatId) {
    activeChatId = chatId;
    renderSidebarChats();
    const chats = getChats();
    const chat = chats.find((c) => c.id === chatId);
    if (chat && elements.caseSelect) {
      elements.caseSelect.value = chat.case_id;
    }

    // Retrieve full task payload from chat or recentTasks
    let taskForChat = chat?.task || null;
    if (!taskForChat || !taskForChat.result) {
      const tasks = readRecentTasks();
      taskForChat = tasks.find((t) => 
        (chat?.task_id && t.task_id === chat.task_id) ||
        (chat?.id && t.chat_id === chat.id) ||
        (chat?.case_id && t.case_id === chat.case_id)
      ) || taskForChat;
    }

    if (taskForChat && (taskForChat.result || taskForChat.status === "succeeded")) {
      if (elements.promptInput) {
        elements.promptInput.value = taskForChat.prompt || chat?.prompt || "";
        elements.charCount.textContent = `${elements.promptInput.value.length.toLocaleString()}/50,000`;
        elements.promptInput.style.height = "auto";
        elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 180)}px`;
      }
      loadTaskIntoView(taskForChat);
    } else {
      if (elements.resultPanel) elements.resultPanel.hidden = true;
      if (elements.promptInput) {
        elements.promptInput.value = chat?.prompt || "";
        elements.charCount.textContent = `${elements.promptInput.value.length.toLocaleString()}/50,000`;
        elements.promptInput.style.height = "auto";
        elements.promptInput.focus();
      }
    }
    showToast(`Switched to: ${chat?.title || "Chat"}`);
  }

  function createNewChat() {
    selectedFiles.splice(0);
    renderAttachments();
    const chats = getChats();
    // Check if the current chat is already fresh and unused
    const currentChat = chats.find((c) => c.id === activeChatId);
    if (currentChat && (currentChat.isNew || currentChat.title === "New Chat") && !currentChat.task && !currentChat.prompt) {
      if (elements.promptInput) {
        elements.promptInput.value = "";
        elements.charCount.textContent = "0/50,000";
        elements.promptInput.style.height = "auto";
        elements.promptInput.focus();
      }
      if (elements.resultPanel) elements.resultPanel.hidden = true;
      showToast("Ready for your new chat.");
      return;
    }

    // Check if another empty unused chat exists
    const existingEmpty = chats.find((c) => (c.isNew || c.title === "New Chat") && !c.task && !c.prompt);
    if (existingEmpty) {
      selectChat(existingEmpty.id);
      return;
    }

    const newId = `chat-${Date.now()}`;
    const newCaseId = `case-${Date.now()}`;
    chats.unshift({
      id: newId,
      title: "New Chat",
      case_id: newCaseId,
      created_at: Date.now(),
      isNew: true
    });
    activeChatId = newId;
    saveChats(chats);
    if (elements.promptInput) {
      elements.promptInput.value = "";
      elements.charCount.textContent = "0/50,000";
      elements.promptInput.style.height = "auto";
      elements.promptInput.focus();
    }
    if (elements.resultPanel) {
      elements.resultPanel.hidden = true;
    }
    showToast("Started new chat.");
  }

  function deleteChat(chatId) {
    let chats = getChats().filter((c) => c.id !== chatId);
    if (chats.length === 0) {
      chats = [{
        id: `chat-${Date.now()}`,
        title: "New Chat",
        case_id: `case-${Date.now()}`,
        created_at: Date.now(),
        isNew: true
      }];
    }
    if (activeChatId === chatId) {
      activeChatId = chats[0].id;
    }
    saveChats(chats);
    selectChat(activeChatId);
    showToast("Chat removed.");
  }

  function syncCaseSelect() {
    if (!elements.caseSelect) return;
    elements.caseSelect.replaceChildren();
    const chats = getChats();
    chats.forEach((chat) => {
      const opt = new Option(chat.title, chat.case_id);
      elements.caseSelect.add(opt);
    });
    const active = chats.find((c) => c.id === activeChatId);
    if (active) elements.caseSelect.value = active.case_id;
  }

  function getActiveCaseId() {
    const chats = getChats();
    const activeChat = chats.find((c) => c.id === activeChatId);
    return activeChat?.case_id || "case-default";
  }

  // Left Sidebar: Render History
  function renderSidebarHistory() {
    if (!elements.sidebarHistoryList) return;
    elements.sidebarHistoryList.replaceChildren();
    const tasks = readRecentTasks();

    if (elements.sidebarHistoryCount) {
      elements.sidebarHistoryCount.textContent = tasks.length;
    }

    if (!tasks.length) {
      const hint = document.createElement("div");
      hint.className = "sidebar-empty-hint";
      hint.textContent = "No history logged yet.";
      elements.sidebarHistoryList.appendChild(hint);
      return;
    }

    tasks.slice(0, 8).forEach((task) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "history-item-btn";
      btn.dataset.taskId = task.task_id;

      const top = document.createElement("div");
      top.className = "history-item-top";

      const firstType = task.output_types?.[0] || "executive_summary";
      const badge = document.createElement("span");
      badge.className = `history-badge ${badgeClass(firstType)}`;
      badge.textContent = formatShort(firstType);

      const time = document.createElement("span");
      time.className = "history-item-time";
      time.textContent = formatTime(task.created_at);

      top.append(badge, time);

      const snippet = document.createElement("div");
      snippet.className = "history-item-snippet";
      snippet.textContent = task.prompt || task.task_id;

      btn.append(top, snippet);

      btn.addEventListener("click", () => {
        loadTaskIntoView(task);
      });

      elements.sidebarHistoryList.appendChild(btn);
    });
  }

  // Output Selection Cards Logic
  function selectedLabels() {
    return outputCards
      .filter((card) => selectedOutputTypes.has(card.dataset.type))
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
    if (elements.promptInput) {
      elements.promptInput.placeholder = labels.length
        ? `Describe what you want to create for ${labels.join(" + ")}...`
        : "Select at least one output format, then describe what to create...";
    }

    if (elements.viewAllLabel) {
      elements.viewAllLabel.textContent = selectedOutputTypes.size === allOutputTypes.length ? "Reset selection" : "View all";
    }
  }

  // Toggle All Output Types ("View all" button)
  function toggleAllOutputs() {
    if (selectedOutputTypes.size === allOutputTypes.length) {
      selectedOutputTypes.clear();
      selectedOutputTypes.add("executive_summary");
    } else {
      allOutputTypes.forEach((type) => selectedOutputTypes.add(type));
    }
    updateOutputSelection();
    showToast(selectedOutputTypes.size === allOutputTypes.length ? "All 6 output formats selected." : "Reset to Intelligence Brief.");
  }

  // Extract structured pipeline output from real backend responses
  function extractOutputForType(result, type) {
    if (!result) return null;
    let candidate = result[type];
    // The Python status projection uses `responses`, while the gateway's
    // persisted task normally flattens that map. Accept both shapes so a
    // terminal failed run can still display its retained structured draft.
    if (!candidate && result.responses && typeof result.responses === "object") {
      candidate = result.responses[type];
    }
    if (!candidate && result.response && typeof result.response === "object") {
      candidate = result.response;
    }
    if (!candidate && type === "linkedin_post") candidate = result.linkedin || result.linkedin_post;
    if (!candidate && type === "presentation") candidate = result.ppt || result.presentation;
    if (!candidate && type === "executive_summary") candidate = result.brief || result.executive_summary;
    if (!candidate && result.pipeline === type) candidate = result;
    if (!candidate && (result.title || result.executive_summary || result.slides || result.storyboard || result.post_text || result.syntax)) {
      candidate = result;
    }
    if (!candidate) return null;
    if (candidate && typeof candidate === "object" && candidate.output && typeof candidate.output === "object") {
      return candidate.output;
    }
    return candidate;
  }

  // Render the Transformation Viewer
  function renderTaskOutput(task) {
    if (!task) return;
    task = api.normalizeRunProjection ? api.normalizeRunProjection(task) : task;
    currentTaskData = task;
    renderRunProjectionMeta(task);
    elements.resultPanel.hidden = false;
    elements.resultTitle.textContent = (task.status || "succeeded").replaceAll("_", " ");
    elements.resultMessage.textContent = `Task ${task.task_id || "Active"} · ${task.output_types?.map(formatName).join(" + ") || "Output"} · ${formatTime(task.created_at)}`;

    // Fallback JSON in details
    if (elements.resultOutput) {
      elements.resultOutput.textContent = JSON.stringify(task.result || task, null, 2);
    }

    const availableTypes = task.output_types || Object.keys(task.result || {});
    if (!availableTypes.length) {
      elements.richOutputContainer.innerHTML = `<p class="result-message">Waiting for transformed output data...</p>`;
      return;
    }

    // Set active tab
    if (!activeTabType || !availableTypes.includes(activeTabType)) {
      activeTabType = availableTypes[0];
    }

    // Render Tabs if more than 1 output type
    if (availableTypes.length > 1) {
      elements.outputTabsContainer.hidden = false;
      elements.outputTabsList.replaceChildren();
      availableTypes.forEach((type) => {
        const tabBtn = document.createElement("button");
        tabBtn.type = "button";
        tabBtn.className = `output-tab${type === activeTabType ? " active" : ""}`;
        tabBtn.textContent = formatName(type);
        tabBtn.addEventListener("click", () => {
          activeTabType = type;
          currentSlideIndex = 0;
          renderTaskOutput(currentTaskData);
        });
        elements.outputTabsList.appendChild(tabBtn);
      });
    } else {
      elements.outputTabsContainer.hidden = true;
    }

    // Update Export button label
    if (elements.exportBtnLabel) {
      elements.exportBtnLabel.textContent = `Export ${formatShort(activeTabType)}`;
    }

    // Render Active Format Viewer
    const payload = extractOutputForType(task.result, activeTabType) || task.result;
    renderFormatView(activeTabType, payload);
    renderArtifactPreview(activeTabType, payload);
    renderFailureNotice(task, activeTabType);
  }

  function renderFailureNotice(task, type) {
    if (task?.status !== "failed" || !elements.richOutputContainer) return;
    const response = extractResponseForType(task.result, type);
    const quality = response?.metadata?.quality_review || {};
    const issues = [
      ...(Array.isArray(quality.issues) ? quality.issues : []),
      ...(Array.isArray(quality.required_revisions) ? quality.required_revisions : []),
    ];
    const notice = document.createElement("div");
    notice.className = "result-error-box pipeline-failure-notice";

    const heading = document.createElement("strong");
    heading.textContent = `${formatName(type)} was retained as a failed draft`;
    notice.appendChild(heading);

    const failure = document.createElement("p");
    failure.textContent = response?.failure || task.error || "The pipeline did not pass its quality gate.";
    notice.appendChild(failure);

    const usage = response?.metadata?.failed_state || {};
    const tokenUsage = task.usage || {};
    const usageText = Number.isFinite(Number(tokenUsage.total_tokens))
      ? ` · Usage ${Number(tokenUsage.total_tokens).toLocaleString()} tokens`
      : "";
    const details = document.createElement("small");
    details.textContent = `Attempt ${usage.attempt || response?.attempts || "?"}/${usage.max_attempts || "?"} · Token budget ${usage.token_budget || "not reported"}${usageText}`;
    notice.appendChild(details);

    if (issues.length) {
      const list = document.createElement("ul");
      issues.slice(0, 8).forEach((issue) => {
        const item = document.createElement("li");
        item.textContent = String(issue);
        list.appendChild(item);
      });
      notice.appendChild(list);
    }
    elements.richOutputContainer.prepend(notice);
  }

  function renderArtifactPreview(type, data) {
    if (!currentTaskData?.task_id || !elements.richOutputContainer || !api.artifactUrl) return;
    const artifactTypes = new Set(["presentation", "infographic", "video", "linkedin_post", "advisory"]);
    if (!artifactTypes.has(type)) return;
    const response = extractResponseForType(currentTaskData.result, type);
    const artifact = response?.artifact && typeof response.artifact === "object" ? response.artifact : {};
    const manifest = (currentTaskData.artifact_manifests || []).find((candidate) => {
      const kind = String(candidate?.kind || "").toLowerCase();
      return kind === (type === "presentation" ? "presentation" : type);
    });
    const output = response?.output && typeof response.output === "object" ? response.output : data;
    const artifactPath = type === "video"
      ? (artifact.video_path || artifact.path)
      : type === "infographic"
        ? (output?.artifact_path || artifact.path)
        : type === "presentation"
          ? artifact.path
          : (output?.image?.asset_uri || artifact.path || output?.artifact_path);
    const hasLocalInfographicSyntax = type === "infographic"
      && typeof output?.syntax === "string"
      && output.syntax.trim().startsWith("infographic");
    const artifactId = api.activeMode === "fastapi"
      ? (currentTaskData.run_id || currentTaskData.task_id)
      : currentTaskData.task_id;
    const url = api.artifactUrl(artifactId, type);
    const panel = document.createElement("div");
    panel.className = "artifact-preview-panel";
    const heading = document.createElement("div");
    heading.className = "artifact-preview-heading";
    heading.textContent = `${formatName(type)} artifact`;
    panel.appendChild(heading);
    if (manifest) {
      const metadata = document.createElement("small");
      metadata.className = "artifact-manifest-summary";
      metadata.textContent = `${manifest.name || formatName(type)} · ${manifest.quality_status || "pending"} · ${formatBytes(Number(manifest.size_bytes || 0))}`;
      panel.appendChild(metadata);
    }

    // Failed or syntax-only pipelines must not render a broken image/video URL.
    // Keep the pipeline failure visible instead of presenting a misleading 404.
    // A syntax-only infographic is rendered lazily by the gateway's local
    // renderer. Keep requesting the artifact URL instead of stopping here.
    if (!artifactPath && !hasLocalInfographicSyntax) {
      const message = document.createElement("p");
      message.className = "result-message";
      message.textContent = response?.failure
        ? `${formatName(type)} was not rendered: ${response.failure}`
        : `${formatName(type)} has no rendered artifact yet.`;
      panel.appendChild(message);
      elements.richOutputContainer.appendChild(panel);
      return;
    }

    if (type === "video") {
      const video = document.createElement("video");
      video.className = "artifact-video-player";
      video.controls = true;
      video.preload = "metadata";
      video.src = url;
      video.setAttribute("aria-label", "Generated video artifact");
      panel.appendChild(video);
    } else if (type === "infographic" || type === "linkedin_post") {
      const imageUri = data?.image?.asset_uri;
      const image = document.createElement("img");
      image.className = "artifact-image-preview";
      image.alt = data?.alt_text || data?.image?.alt_text || `${formatName(type)} artifact`;
      image.src = imageUri && /^https?:\/\//i.test(imageUri) ? imageUri : url;
      panel.appendChild(image);
    }

    const link = document.createElement("a");
    link.className = "result-action-btn artifact-download-link";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = type === "video" ? "Open video" : `Open ${formatShort(type)} artifact`;
    panel.appendChild(link);
    elements.richOutputContainer.appendChild(panel);
  }

  function extractResponseForType(result, type) {
    if (!result || typeof result !== "object") return null;
    let candidate = result[type];
    if (!candidate && result.responses && typeof result.responses === "object") {
      candidate = result.responses[type];
    }
    if (!candidate && result.response && typeof result.response === "object") {
      candidate = result.response;
    }
    if (!candidate && type === "linkedin_post") candidate = result.linkedin || result.linkedin_post;
    if (!candidate && type === "presentation") candidate = result.ppt || result.presentation;
    if (!candidate && result.pipeline === type) candidate = result;
    return candidate && typeof candidate === "object" ? candidate : null;
  }

  // Specialized Rich Format Viewers
  function renderFormatView(type, data) {
    if (!elements.richOutputContainer) return;
    elements.richOutputContainer.replaceChildren();

    if (!data) {
      const terminalMessage = currentTaskData?.status === "failed"
        ? `${formatName(type)} finished with a terminal failure, but the gateway returned no structured draft. Check the backend logs for task ${currentTaskData.task_id || "unknown"}.`
        : `No rendered payload available for ${formatName(type)} yet.`;
      elements.richOutputContainer.innerHTML = `<p class="result-message">${terminalMessage}</p>`;
      return;
    }

    if (type === "executive_summary") {
      renderBriefView(data);
    } else if (type === "presentation") {
      renderPresentationView(data);
    } else if (type === "advisory") {
      renderReportView(data);
    } else if (type === "infographic") {
      renderInfographicView(data);
    } else if (type === "video") {
      renderVideoPackageView(data);
    } else if (type === "linkedin_post") {
      renderSocialPostView(data);
    } else {
      const generic = document.createElement("div");
      generic.className = "brief-summary-box";
      generic.innerHTML = `<h4 class="brief-heading">${formatName(type)}</h4><pre class="result-output">${JSON.stringify(data, null, 2)}</pre>`;
      elements.richOutputContainer.appendChild(generic);
    }
  }

  // 1. Intelligence Brief View (Executive Summary Pipeline)
  function renderBriefView(data) {
    const wrap = document.createElement("div");
    wrap.className = "brief-viewer";

    const meta = document.createElement("div");
    meta.className = "brief-meta-bar";
    meta.innerHTML = `
      <span class="brief-tag">${data.classification || "SUDARSHAN // INTELLIGENCE BRIEF"}</span>
      <span class="brief-date">${new Date().toLocaleDateString("en-US", { dateStyle: "medium" })}</span>
    `;

    const summaryBox = document.createElement("div");
    summaryBox.className = "brief-summary-box";
    summaryBox.innerHTML = `
      <h4 class="brief-heading">${data.title || "Executive Intelligence Brief"}</h4>
      <p class="brief-text">${data.executive_summary || data.summary || "Summary data generated."}</p>
    `;

    // Key findings
    const findings = data.key_findings || data.findings || [];
    const findingsGrid = document.createElement("div");
    findingsGrid.className = "brief-findings-grid";
    findings.forEach((f, idx) => {
      const card = document.createElement("div");
      card.className = "brief-finding-card";
      if (typeof f === "string") {
        card.innerHTML = `<h5 class="finding-title">Finding #${idx + 1}</h5><p class="finding-desc">${f}</p>`;
      } else {
        card.innerHTML = `<h5 class="finding-title">${f.title || `Finding #${idx + 1}`}</h5><p class="finding-desc">${f.desc || f.text || JSON.stringify(f)}</p>`;
      }
      findingsGrid.appendChild(card);
    });

    // Strategic Implications (if present in real ExecutiveSummaryOutput)
    let implicationsBox = null;
    if (Array.isArray(data.implications) && data.implications.length > 0) {
      implicationsBox = document.createElement("div");
      implicationsBox.className = "brief-summary-box";
      implicationsBox.style.marginTop = "14px";
      const impList = data.implications.map((imp) => `<li class="rec-item"><span class="rec-bullet" style="color: #f59e0b;">⚡</span><span>${imp}</span></li>`).join("");
      implicationsBox.innerHTML = `<h5 class="finding-title" style="color: #fbbf24;">Operational & Strategic Implications</h5><ul class="rec-list">${impList}</ul>`;
    }

    // Recommendations
    const recs = data.recommended_actions || data.recommendations || [];
    const recBox = document.createElement("div");
    recBox.className = "brief-recommendations";
    const recList = recs.map((r) => {
      const text = typeof r === "string" ? r : (r.action || JSON.stringify(r));
      return `<li class="rec-item"><span class="rec-bullet">▸</span><span>${text}</span></li>`;
    }).join("");
    recBox.innerHTML = `<h5 class="finding-title">Actionable Recommendations</h5><ul class="rec-list">${recList || '<li class="rec-item">No specific recommendations logged.</li>'}</ul>`;

    // Confidence statement
    let confBox = null;
    if (data.confidence_statement) {
      confBox = document.createElement("div");
      confBox.style.cssText = "font-size: 0.8rem; color: var(--text-secondary); margin-top: 12px; padding: 8px 12px; background: rgba(99, 102, 241, 0.08); border-radius: 8px; border-left: 3px solid #6366f1;";
      confBox.innerHTML = `<strong>Confidence Assessment:</strong> ${data.confidence_statement}`;
    }

    wrap.append(meta, summaryBox, findingsGrid);
    if (implicationsBox) wrap.appendChild(implicationsBox);
    wrap.appendChild(recBox);
    if (confBox) wrap.appendChild(confBox);
    elements.richOutputContainer.appendChild(wrap);
  }

  // 2. Presentation Slide Deck View (Interactive Carousel)
  function renderPresentationView(data) {
    const slides = data.slides || [];
    if (!slides.length) {
      elements.richOutputContainer.innerHTML = `<p class="result-message">No slide deck data found in presentation payload.</p>`;
      return;
    }

    if (currentSlideIndex >= slides.length) currentSlideIndex = 0;
    const currentSlide = slides[currentSlideIndex];

    const wrap = document.createElement("div");
    wrap.className = "presentation-viewer";

    // Controls bar
    const controls = document.createElement("div");
    controls.className = "slide-controls-bar";

    const nav = document.createElement("div");
    nav.className = "slide-nav-group";

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "slide-arrow-btn";
    prevBtn.innerHTML = "❮";
    prevBtn.disabled = currentSlideIndex === 0;
    prevBtn.addEventListener("click", () => {
      if (currentSlideIndex > 0) {
        currentSlideIndex--;
        renderPresentationView(data);
      }
    });

    const counter = document.createElement("span");
    counter.className = "slide-counter";
    counter.textContent = `Slide ${currentSlideIndex + 1} of ${slides.length}`;

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "slide-arrow-btn";
    nextBtn.innerHTML = "❯";
    nextBtn.disabled = currentSlideIndex === slides.length - 1;
    nextBtn.addEventListener("click", () => {
      if (currentSlideIndex < slides.length - 1) {
        currentSlideIndex++;
        renderPresentationView(data);
      }
    });

    nav.append(prevBtn, counter, nextBtn);

    const titleEl = document.createElement("span");
    titleEl.style.fontSize = "0.78rem";
    titleEl.style.color = "var(--text-secondary)";
    titleEl.textContent = data.title || "Presentation Deck";

    controls.append(nav, titleEl);

    // Slide Canvas
    const canvas = document.createElement("div");
    canvas.className = "slide-canvas";

    const slideNum = currentSlide.slide_number || currentSlide.number || (currentSlideIndex + 1);
    const badge = document.createElement("span");
    badge.className = "slide-header-badge";
    badge.textContent = `SLIDE ${slideNum} // ${currentSlide.layout?.toUpperCase() || "CONTENT"}`;

    const slideTitle = document.createElement("h3");
    slideTitle.className = "slide-title";
    slideTitle.textContent = currentSlide.title || `Slide ${slideNum}`;

    const bulletsList = document.createElement("ul");
    bulletsList.className = "slide-bullets";
    const bullets = currentSlide.bullets || [];
    bullets.forEach((b) => {
      const li = document.createElement("li");
      li.className = "slide-bullet-item";
      li.innerHTML = `<span class="slide-bullet-dot"></span><span>${b}</span>`;
      bulletsList.appendChild(li);
    });

    const notes = document.createElement("div");
    notes.className = "slide-footer-notes";
    notes.textContent = `Speaker Notes: ${currentSlide.speaker_notes || currentSlide.notes || "No notes recorded for this slide."}`;

    canvas.append(badge, slideTitle, bulletsList, notes);
    wrap.append(controls, canvas);

    // Conclusion / Takeaways banner (if on conclusion slide or available)
    if (data.conclusion_summary && currentSlideIndex === slides.length - 1) {
      const concBox = document.createElement("div");
      concBox.style.cssText = "margin-top: 14px; padding: 12px 16px; background: rgba(34, 197, 94, 0.08); border-radius: 8px; border: 1px solid rgba(34, 197, 94, 0.2);";
      concBox.innerHTML = `
        <h5 style="color: #4ade80; font-size: 0.85rem; font-weight: 600; margin-bottom: 4px;">Executive Conclusion</h5>
        <p style="font-size: 0.82rem; color: #cbd5e1; margin: 0;">${data.conclusion_summary}</p>
      `;
      wrap.appendChild(concBox);
    }

    elements.richOutputContainer.appendChild(wrap);
  }

  // 3. Report Document View (Advisory Report Pipeline)
  function renderReportView(data) {
    const wrap = document.createElement("div");
    wrap.className = "report-viewer";

    const header = document.createElement("div");
    header.className = "report-title-header";
    const severity = data.severity_rating || "moderate";
    const sevColor = severity === "critical" ? "#ef4444" : severity === "high" ? "#f97316" : "#3b82f6";
    header.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">
        <h3 class="report-main-title" style="margin: 0;">${data.title || "Technical Advisory Report"}</h3>
        <span style="font-size: 0.72rem; font-weight: 700; text-transform: uppercase; padding: 3px 8px; border-radius: 6px; background: ${sevColor}22; color: ${sevColor}; border: 1px solid ${sevColor}55;">
          ${severity} Severity
        </span>
      </div>
      <div class="report-meta">${data.classification_level || data.classification || "RESTRICTED"} · ${data.distribution || "Authorized Command"} · ${data.subject || "Strategic Operation"}</div>
    `;
    wrap.appendChild(header);

    // If structured AdvisoryOutput fields exist:
    const sectionsToRender = [];
    if (data.executive_summary) sectionsToRender.push({ heading: "Executive Summary", content: data.executive_summary });
    if (data.overview) sectionsToRender.push({ heading: "Strategic Overview", content: data.overview });
    if (data.situation) sectionsToRender.push({ heading: "Situational Background", content: data.situation });
    if (data.assessment) sectionsToRender.push({ heading: "Technical Assessment", content: data.assessment });
    if (data.impact_analysis) sectionsToRender.push({ heading: "Operational Impact Analysis", content: data.impact_analysis });

    if (sectionsToRender.length > 0) {
      sectionsToRender.forEach((sec) => {
        const s = document.createElement("div");
        s.className = "report-section";
        s.innerHTML = `
          <h4 class="report-section-title">${sec.heading}</h4>
          <p class="report-paragraph">${sec.content}</p>
        `;
        wrap.appendChild(s);
      });
    } else if (Array.isArray(data.sections)) {
      data.sections.forEach((sec) => {
        const s = document.createElement("div");
        s.className = "report-section";
        s.innerHTML = `
          <h4 class="report-section-title">${sec.heading || "Section"}</h4>
          <p class="report-paragraph">${sec.content || ""}</p>
        `;
        wrap.appendChild(s);
      });
    }

    // Observed Patterns
    if (Array.isArray(data.observed_patterns) && data.observed_patterns.length > 0) {
      const patDiv = document.createElement("div");
      patDiv.className = "report-section";
      const patList = data.observed_patterns.map((p) => `<li style="margin-bottom: 4px;">▸ ${p}</li>`).join("");
      patDiv.innerHTML = `<h4 class="report-section-title">Observed Threat & Intelligence Patterns</h4><ul style="list-style: none; padding-left: 0; color: #cbd5e1; font-size: 0.85rem;">${patList}</ul>`;
      wrap.appendChild(patDiv);
    }

    // Prioritized Recommendations
    if (Array.isArray(data.recommendations) && data.recommendations.length > 0) {
      const recDiv = document.createElement("div");
      recDiv.className = "report-section";
      let recsHtml = "";
      data.recommendations.forEach((rec) => {
        if (typeof rec === "string") {
          recsHtml += `<div style="padding: 8px 12px; margin-bottom: 6px; background: rgba(255,255,255,0.03); border-radius: 6px; font-size: 0.84rem;">▸ ${rec}</div>`;
        } else {
          recsHtml += `
            <div style="padding: 10px 14px; margin-bottom: 8px; background: rgba(99, 102, 241, 0.05); border-left: 3px solid #6366f1; border-radius: 4px;">
              <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 4px;">
                <span style="font-size: 0.72rem; font-weight: 700; background: #6366f1; color: white; padding: 1px 6px; border-radius: 4px;">${rec.priority || "P1"}</span>
                <strong style="font-size: 0.88rem; color: #e2e8f0;">${rec.action}</strong>
              </div>
              <div style="font-size: 0.78rem; color: var(--text-secondary);">
                <span>Owner: ${rec.responsible_party || "Command"}</span> · <span>Timeline: ${rec.timeline || "Immediate"}</span>
              </div>
              ${rec.rationale ? `<p style="font-size: 0.8rem; color: #94a3b8; margin: 4px 0 0;">${rec.rationale}</p>` : ""}
            </div>
          `;
        }
      });
      recDiv.innerHTML = `<h4 class="report-section-title">Operational Recommendations</h4>${recsHtml}`;
      wrap.appendChild(recDiv);
    }

    elements.richOutputContainer.appendChild(wrap);
  }

  // 4. Infographic View (AntV Infographic Pipeline)
  function renderInfographicView(data) {
    const wrap = document.createElement("div");
    wrap.className = "infographic-viewer";

    const header = document.createElement("div");
    header.className = "brief-meta-bar";
    header.innerHTML = `
      <span class="brief-tag" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border-color: rgba(16, 185, 129, 0.35);">
        ANTV INFOGRAPHIC // ${data.visual_type?.toUpperCase() || "VISUAL SYNTAX"}
      </span>
      <button class="result-action-btn" id="copyAntvBtn" style="padding: 4px 10px; font-size: 0.75rem;">Copy AntV Code</button>
    `;
    wrap.appendChild(header);

    const titleBox = document.createElement("div");
    titleBox.className = "brief-summary-box";
    titleBox.style.marginBottom = "14px";
    titleBox.innerHTML = `
      <h4 class="brief-heading">${data.title || "Infographic Visual Architecture"}</h4>
      <p class="brief-text">${data.alt_text || "Visual syntax generated for AntV engine rendering."}</p>
    `;
    wrap.appendChild(titleBox);

    // If AntV syntax exists, display formatted syntax preview
    if (data.syntax) {
      const syntaxContainer = document.createElement("div");
      syntaxContainer.style.cssText = "background: #090d16; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 14px; margin-bottom: 14px; position: relative;";
      syntaxContainer.innerHTML = `
        <div style="font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 8px; font-family: monospace;">ANTV DIRECTIVE SPECIFICATION:</div>
        <pre style="margin: 0; color: #38bdf8; font-family: monospace; font-size: 0.8rem; line-height: 1.4; white-space: pre-wrap; word-break: break-word; max-height: 280px; overflow-y: auto;">${data.syntax}</pre>
      `;
      wrap.appendChild(syntaxContainer);
    }

    // KPI grid if KPIs available
    if (Array.isArray(data.kpis) && data.kpis.length > 0) {
      const kpiGrid = document.createElement("div");
      kpiGrid.className = "infographic-kpi-grid";
      data.kpis.forEach((k) => {
        const card = document.createElement("div");
        card.className = "infographic-kpi-card";
        card.innerHTML = `<div class="kpi-metric-number">${k.number || k.value}</div><div class="kpi-metric-label">${k.label || k.name}</div>`;
        kpiGrid.appendChild(card);
      });
      wrap.appendChild(kpiGrid);
    }

    elements.richOutputContainer.appendChild(wrap);

    document.getElementById("copyAntvBtn")?.addEventListener("click", () => {
      navigator.clipboard?.writeText(data.syntax || JSON.stringify(data, null, 2));
      showToast("AntV syntax copied to clipboard.");
    });
  }

  // 5. Complete Video Package View (native video pipeline)
  function renderVideoPackageView(data) {
    const wrap = document.createElement("div");
    wrap.className = "video-script-viewer";

    const header = document.createElement("div");
    header.className = "brief-meta-bar";
    header.innerHTML = `
      <span class="brief-tag" style="background: rgba(139, 92, 246, 0.15); color: #c4b5fd; border-color: rgba(139, 92, 246, 0.35);">
        ${data.title || data.subject || "NATIVE VIDEO PACKAGE"}
      </span>
      <button class="result-action-btn" id="copyScriptBtn" style="padding: 4px 10px; font-size: 0.75rem;">Copy narration</button>
    `;

    const scenes = data.storyboard || data.scenes || [];
    if (scenes.length > 0) {
      const table = document.createElement("table");
      table.className = "script-table";

      let cumulativeTime = 0;
      scenes.forEach((sc, idx) => {
        const tr = document.createElement("tr");
        tr.className = "script-row";
        const duration = sc.duration_seconds || 5;
        const timeLabel = sc.time || `${cumulativeTime}s - ${cumulativeTime + duration}s`;
        cumulativeTime += duration;

        const visualCue = sc.visual_description || sc.cue || (sc.on_screen_text ? `On-screen: "${sc.on_screen_text}"` : `Scene ${idx + 1}`);
        const voiceText = sc.narration || sc.voice || "";

        tr.innerHTML = `
          <td class="script-col-cue">
            <span class="cue-timestamp">${timeLabel}</span>
            ${visualCue}
          </td>
          <td class="script-col-voice">${voiceText}</td>
        `;
        table.appendChild(tr);
      });
      wrap.append(header, table);
    } else {
      const scriptBox = document.createElement("div");
      scriptBox.className = "brief-summary-box";
      scriptBox.innerHTML = `
        <h4 class="brief-heading">${data.title || "Video Narration Script"}</h4>
        <p class="brief-text" style="white-space: pre-wrap;">${data.script || data.transcript || "No narration script available."}</p>
      `;
      wrap.append(header, scriptBox);
    }

    elements.richOutputContainer.appendChild(wrap);

    document.getElementById("copyScriptBtn")?.addEventListener("click", () => {
      let scriptText = "";
      if (scenes.length > 0) {
        scriptText = scenes.map((s) => `VOICE: ${s.narration || s.voice || ""}\n[VISUAL: ${s.visual_description || s.cue || ""}]\n`).join("\n");
      } else {
        scriptText = data.script || data.transcript || "";
      }
      navigator.clipboard?.writeText(scriptText);
      showToast("Video narration copied to clipboard.");
    });
  }

  // 6. LinkedIn Post View
  function renderSocialPostView(data) {
    const wrap = document.createElement("div");
    wrap.className = "social-post-viewer";

    const card = document.createElement("div");
    card.className = "social-card-mock";

    const author = document.createElement("div");
    author.className = "social-author-row";
    const authorName = data.author || (currentUser?.name ? `${currentUser.name} (Sudarshan AI)` : "Sudarshan AI Intelligence");
    author.innerHTML = `
      <div class="social-avatar">S</div>
      <div class="social-author-info">
        <span class="social-author-name">${authorName}</span>
        <span class="social-time">${data.audience ? `Audience: ${data.audience}` : "🌐 Public"}</span>
      </div>
      <button class="result-action-btn" id="copyPostBtn" style="margin-left: auto; padding: 4px 10px; font-size: 0.75rem;">Copy Post</button>
    `;

    const bodyText = data.post_text || data.body || "";
    const body = document.createElement("div");
    body.className = "social-body-text";
    body.style.whiteSpace = "pre-wrap";
    body.textContent = bodyText;

    const tags = document.createElement("div");
    tags.className = "social-hashtags";
    (data.hashtags || []).forEach((tag) => {
      const span = document.createElement("span");
      span.className = "hashtag-pill";
      span.textContent = tag.startsWith("#") ? tag : `#${tag}`;
      tags.appendChild(span);
    });

    card.append(author, body, tags);

    // Call to Action card (if present in real LinkedInPostOutput)
    if (data.call_to_action) {
      const ctaBox = document.createElement("div");
      ctaBox.style.cssText = "margin-top: 12px; padding: 8px 12px; background: rgba(99, 102, 241, 0.08); border-radius: 6px; font-size: 0.82rem; color: #a5b4fc;";
      ctaBox.innerHTML = `<strong>Call to Action:</strong> ${data.call_to_action}`;
      card.appendChild(ctaBox);
    }

    wrap.appendChild(card);
    elements.richOutputContainer.appendChild(wrap);

    document.getElementById("copyPostBtn")?.addEventListener("click", () => {
      const tagsStr = (data.hashtags || []).map((t) => (t.startsWith("#") ? t : `#${t}`)).join(" ");
      const text = `${bodyText}\n\n${tagsStr}`;
      navigator.clipboard?.writeText(text);
      showToast("Social post copied to clipboard.");
    });
  }

  // Load any clicked task directly into viewer
  function loadTaskIntoView(task, shouldScroll = false) {
    if (!task) return;
    renderTaskOutput(task);
    if (elements.promptInput && task.prompt) {
      elements.promptInput.value = task.prompt;
      elements.charCount.textContent = `${task.prompt.length.toLocaleString()}/50,000`;
      elements.promptInput.style.height = "auto";
      elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 180)}px`;
    }
    if (elements.resultPanel) {
      elements.resultPanel.hidden = false;
      if (shouldScroll) {
        const rect = elements.resultPanel.getBoundingClientRect();
        const inView = rect.top >= 0 && rect.bottom <= (window.innerHeight || document.documentElement.clientHeight);
        if (!inView) {
          elements.resultPanel.scrollIntoView({ behavior: "auto", block: "nearest" });
        }
      }
    }
  }

  // Export Active Format Data
  function exportActiveOutput() {
    if (!currentTaskData || !activeTabType) return;
    const format = formatName(activeTabType);
    const content = JSON.stringify(currentTaskData.result?.[activeTabType] || currentTaskData.result, null, 2);
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sudarshan-${activeTabType}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Exported ${format} payload.`);
  }

  // Render Recent Tasks with Filter Support
  function renderRecentTasks() {
    if (!elements.recentGrid) return;
    elements.recentGrid.replaceChildren();
    const tasks = readRecentTasks();

    const filtered = activeRecentFilter === "all"
      ? tasks
      : tasks.filter((t) => (t.output_types || []).includes(activeRecentFilter));

    if (!filtered.length) {
      const empty = document.createElement("p");
      empty.className = "recent-empty";
      empty.textContent = activeRecentFilter === "all"
        ? "Your completed transformations will appear here."
        : `No recent transformations found for ${formatName(activeRecentFilter)}.`;
      elements.recentGrid.appendChild(empty);
      return;
    }

    filtered.forEach((task) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "recent-card recent-card-button";
      card.dataset.taskId = task.task_id;

      const title = document.createElement("h4");
      title.className = "recent-title";
      const names = (task.output_types || []).map(formatName).join(" + ");
      title.textContent = names || "Transformation";

      const snippet = document.createElement("p");
      snippet.className = "recent-snippet";
      snippet.textContent = task.prompt || task.task_id;

      const timestamp = document.createElement("span");
      timestamp.className = "recent-timestamp";
      timestamp.textContent = formatTime(task.created_at);

      card.append(title, snippet, timestamp);

      card.addEventListener("click", () => {
        loadTaskIntoView(task);
      });

      elements.recentGrid.appendChild(card);
    });
  }

  // Finish transformation and restore input UI
  function finishSubmissionSuccess(task) {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    closeProgressStream?.();
    closeProgressStream = null;
    elements.submitBtn.disabled = false;
    elements.promptInput.disabled = false;
    elements.submitBtn.classList.remove("is-loading");
    if (elements.stopTaskBtn) {
      elements.stopTaskBtn.hidden = true;
      elements.stopTaskBtn.disabled = false;
    }
    resetTaskProgress();

    const question = task.prompt || elements.promptInput?.value.trim() || "";

    // 1. Update and persist Chat in Left Panel with name based on user's question
    const chats = getChats();
    const targetChatId = task.chat_id || activeChatId;
    let currentChat = chats.find((c) => c.id === targetChatId);
    if (!currentChat) {
      currentChat = {
        id: targetChatId || `chat-${Date.now()}`,
        case_id: task.case_id || `case-${Date.now()}`,
        created_at: Date.now()
      };
      chats.unshift(currentChat);
    }

    // Set chat title according to the question asked
    if (question) {
      currentChat.title = generateChatTitle(question);
      currentChat.prompt = question;
    }
    currentChat.task_id = task.task_id;
    currentChat.case_id = task.case_id || currentChat.case_id;
    currentChat.status = task.status;
    currentChat.output_types = task.output_types;
    currentChat.task = task;
    currentChat.result = task.result;
    currentChat.updated_at = Date.now();
    delete currentChat.isNew;

    activeChatId = currentChat.id;
    saveChats(chats);

    // 2. Save Recent Task for history & recent tasks grid
    task.chat_id = currentChat.id;
    task.case_id = currentChat.case_id;
    saveRecentTask(task);

    // 3. Render Output
    renderTaskOutput(task);
    const isSuccess = task.status === "succeeded";
    showToast(isSuccess ? `Saved chat: "${currentChat.title}"` : `Task finished with status: ${task.status}`, !isSuccess);
  }

  // Submit Transformation Engine (Real Backend Synchronization)
  async function submitTransformation() {
    const input = elements.promptInput.value.trim();
    const caseId = elements.caseSelect?.value || getActiveCaseId();
    const outputTypes = [...selectedOutputTypes];

    if (!input) return showToast("Enter a transformation request first.", true);
    if (!outputTypes.length) return showToast("Select at least one output format.", true);

    // Name the chat with respect to the user's question immediately
    const chats = getChats();
    let currentChat = chats.find((c) => c.id === activeChatId);
    if (!currentChat) {
      currentChat = {
        id: activeChatId || `chat-${Date.now()}`,
        title: generateChatTitle(input),
        case_id: caseId,
        created_at: Date.now(),
        prompt: input,
        output_types: outputTypes
      };
      chats.unshift(currentChat);
      activeChatId = currentChat.id;
    } else {
      currentChat.title = generateChatTitle(input);
      currentChat.prompt = input;
      currentChat.case_id = caseId;
      currentChat.output_types = outputTypes;
      delete currentChat.isNew;
    }
    saveChats(chats);

    elements.submitBtn.disabled = true;
    elements.promptInput.disabled = true;
    elements.submitBtn.classList.add("is-loading");
    if (elements.stopTaskBtn) {
      elements.stopTaskBtn.hidden = false;
      elements.stopTaskBtn.disabled = false;
    }

    elements.resultPanel.hidden = false;
    elements.resultTitle.textContent = "Synthesizing";
    elements.resultMessage.textContent = `Dispatching multi-agent transformation for: ${outputTypes.map(formatName).join(" + ")}...`;
    elements.richOutputContainer.innerHTML = `
      <div class="processing-status-card" style="padding: 36px 20px; text-align: center;">
        <div class="processing-spinner" style="width: 38px; height: 38px; border: 3px solid rgba(99, 102, 241, 0.2); border-top-color: #6366f1; border-radius: 50%; margin: 0 auto 16px; animation: spin 0.8s linear infinite;"></div>
        <div style="font-size: 1.05rem; font-weight: 600; color: #e2e8f0; margin-bottom: 6px;">Synthesizing Multi-Agent Pipelines...</div>
        <div id="liveStepIndicator" style="font-size: 0.85rem; color: #a5b4fc; margin-bottom: 8px;">Connecting to Sudarshan Core orchestrator...</div>
        <div style="font-size: 0.78rem; color: var(--text-secondary);">Formats: ${outputTypes.map(formatName).join(", ")}</div>
      </div>
    `;
    updateTaskProgress(0, "Connecting to Sudarshan Core orchestrator...", "queued");

    try {
      await api.ensureCase?.(caseId, currentChat.title || "Untitled case");
      await ingestSelectedFiles(caseId);
      const response = await api.createTransform({
        case_id: caseId,
        input,
        output_types: outputTypes,
        classification_level: "RESTRICTED",
        distribution: "Authorized NTRO personnel"
      });

      const task = response.task || response;
      task.prompt = input;
      task.case_id = caseId;
      task.chat_id = currentChat.id;
      task.output_types = outputTypes;
      task.created_at = task.created_at || Date.now();
      activeTaskId = task.task_id;
      const targetRunId = task.run_id || task.runId || task.task_id;
      const progressSubscriptionId = api.activeMode === "fastapi" ? targetRunId : activeTaskId;
      updateTaskProgress(0, "Run accepted; waiting for the orchestrator...", "queued");

      // Connect live SSE streaming progress listener for real-time agent updates
      if (api.subscribeToTask && progressSubscriptionId) {
        closeProgressStream?.();
        closeProgressStream = api.subscribeToTask(progressSubscriptionId, handleProgressEvent, () => {
          // Polling remains the source of truth if the optional event stream closes.
        });
      }

      // If task has immediate completed result
      if (task.result && (task.status === "succeeded" || task.status === "partial")) {
        finishSubmissionSuccess(task);
      } else {
        // Poll remote task
        pollRemoteTask(activeTaskId, input, targetRunId, caseId, currentChat.id, outputTypes);
      }
    } catch (err) {
      elements.submitBtn.disabled = false;
      elements.promptInput.disabled = false;
      elements.submitBtn.classList.remove("is-loading");
      closeProgressStream?.();
      closeProgressStream = null;
      if (elements.stopTaskBtn) {
        elements.stopTaskBtn.hidden = true;
        elements.stopTaskBtn.disabled = false;
      }
      resetTaskProgress();
      const isNetworkError = !err.status && (
        !window.navigator.onLine ||
        err.message?.includes("fetch") ||
        err.message?.includes("Failed to fetch") ||
        err.message?.includes("NetworkError")
      );
      elements.resultTitle.textContent = isNetworkError ? "Backend Service Unreachable" : "Execution Notice";
      elements.resultMessage.textContent = err.message || "An error occurred during pipeline request";
      elements.richOutputContainer.innerHTML = `
        <div class="result-error-box" style="padding: 28px 20px; text-align: center; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 12px; background: rgba(239, 68, 68, 0.06); max-width: 540px; margin: 0 auto;">
          <div style="font-size: 1.8rem; margin-bottom: 8px;">${isNetworkError ? "🔌" : "⚠️"}</div>
          <h4 style="color: #f87171; margin-bottom: 6px; font-weight: 600; font-size: 1rem;">
            ${isNetworkError ? "Backend Service Unreachable" : "Pipeline Execution Notice"}
          </h4>
          <p style="color: var(--text-secondary); font-size: 0.85rem; line-height: 1.5; margin: 0 0 16px;">
            ${err.message || "An error occurred while connecting to the core server."}
            ${isNetworkError ? "<br>Please make sure the backend server is running:" : ""}
          </p>
          ${isNetworkError ? `
          <div style="background: rgba(0, 0, 0, 0.4); padding: 10px 14px; border-radius: 8px; font-family: monospace; font-size: 0.78rem; color: #38bdf8; text-align: left; margin-bottom: 16px; border: 1px solid rgba(255, 255, 255, 0.08);">
            # Start Python FastAPI:<br>
            uvicorn api.server:app --port 8000<br><br>
            # Or start Node Gateway:<br>
            npm --prefix backend-node start
          </div>` : ""}
          <button type="button" class="btn btn-primary" id="retrySubmitBtn" style="font-size: 0.82rem; padding: 6px 16px;">
            Try Again
          </button>
        </div>
      `;
      document.getElementById("retrySubmitBtn")?.addEventListener("click", submitTransformation);
      showApiError(err);
    }
  }

  // Poll Remote Task until terminal state
  async function pollRemoteTask(taskId, originalPrompt, runId, caseId, chatId, outputTypes) {
    try {
      const response = await api.getTask(taskId);
      const task = api.normalizeRunProjection
        ? api.normalizeRunProjection(response.task || response)
        : (response.task || response);
      task.prompt = originalPrompt;
      task.case_id = caseId || task.case_id;
      task.chat_id = chatId || task.chat_id;
      task.output_types = outputTypes || task.output_types || [];
      task.created_at = task.created_at || Date.now();

      if (terminalStates.has(task.status)) {
        finishSubmissionSuccess(task);
        return;
      }

      // Update stage indicator while waiting
      updateTaskProgress(task.progress, task.message || "", task.stage || "");
      renderRunProjectionMeta(task);
      if (task.stage && !task.message) {
        const stepEl = document.getElementById("liveStepIndicator");
        if (stepEl) stepEl.textContent = `Stage: ${task.stage.replaceAll("_", " ")}...`;
      }

      pollTimer = window.setTimeout(() => pollRemoteTask(taskId, originalPrompt, runId, caseId, chatId, outputTypes), 1500);
    } catch (error) {
      elements.submitBtn.disabled = false;
      elements.promptInput.disabled = false;
      elements.submitBtn.classList.remove("is-loading");
      closeProgressStream?.();
      closeProgressStream = null;
      if (elements.stopTaskBtn) {
        elements.stopTaskBtn.hidden = true;
        elements.stopTaskBtn.disabled = false;
      }
      resetTaskProgress();
      showApiError(error);
    }
  }

  // Wire Event Listeners
  function wireEvents() {
    // Sidebar collapse & mobile toggle
    elements.collapseBtn?.addEventListener("click", () => {
      const collapsed = elements.sidebar.classList.toggle("collapsed");
      elements.collapseBtn.setAttribute("aria-expanded", String(!collapsed));
      elements.collapseBtn.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
    });
    elements.mobileMenuBtn?.addEventListener("click", (e) => {
      e.stopPropagation();
      elements.sidebar.classList.toggle("mobile-open");
    });
    document.addEventListener("click", (e) => {
      if (elements.sidebar && !elements.sidebar.contains(e.target) && !elements.mobileMenuBtn?.contains(e.target)) {
        elements.sidebar.classList.remove("mobile-open");
      }
    });

    // Sidebar new chat & new transformation button
    elements.sidebarNewChatBtn?.addEventListener("click", createNewChat);
    elements.newTransformBtn?.addEventListener("click", () => {
      createNewChat();
    });

    // Prompt input auto-expand & counter
    elements.promptInput?.addEventListener("input", () => {
      elements.charCount.textContent = `${elements.promptInput.value.length.toLocaleString()}/50,000`;
      elements.promptInput.style.height = "auto";
      elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 180)}px`;
    });

    elements.promptInput?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        submitTransformation();
      }
    });

    elements.submitBtn?.addEventListener("click", submitTransformation);
    elements.newCaseBtn?.addEventListener("click", createNewChat);
    elements.exportOutputBtn?.addEventListener("click", exportActiveOutput);
    elements.toggleAllOutputsBtn?.addEventListener("click", toggleAllOutputs);

    // Stop Active Task. Cancellation is cooperative at safe graph boundaries;
    // it is not a resumable provider-level pause.
    elements.stopTaskBtn?.addEventListener("click", async () => {
      if (!activeTaskId) return;
      elements.stopTaskBtn.disabled = true;
      try {
        await api.cancelTask(activeTaskId);
        showToast("Stop requested; the run will halt at the next safe boundary.");
        if (pollTimer) clearTimeout(pollTimer);
        pollTimer = null;
        closeProgressStream?.();
        closeProgressStream = null;
        elements.submitBtn.disabled = false;
        elements.promptInput.disabled = false;
        elements.submitBtn.classList.remove("is-loading");
        elements.stopTaskBtn.hidden = true;
        elements.stopTaskBtn.disabled = false;
        elements.resultTitle.textContent = "Stopped";
        updateTaskProgress(undefined, "Stop requested. Waiting for the safe cancellation boundary...", "cancellation");
        elements.resultMessage.textContent = "Stop requested. The agentic run will halt at the next safe graph boundary.";
      } catch (err) {
        elements.stopTaskBtn.disabled = false;
        showApiError(err);
      }
    });

    elements.attachFilesBtn?.addEventListener("click", () => elements.fileInput?.click());
    elements.fileInput?.addEventListener("change", () => {
      addSelectedFiles(elements.fileInput.files);
      elements.fileInput.value = "";
    });

    // Output Cards Click Handlers
    outputCards.forEach((card) => {
      card.addEventListener("click", () => {
        const type = card.dataset.type;
        if (selectedOutputTypes.has(type) && selectedOutputTypes.size === 1) {
          showToast("At least one output format must remain selected.");
          return;
        }
        if (selectedOutputTypes.has(type)) {
          selectedOutputTypes.delete(type);
        } else {
          selectedOutputTypes.add(type);
        }
        updateOutputSelection();
      });
    });

    // Recent Transformations Filter Pills (Instant 0ms Pointer & Click Response)
    let lastFilterTime = 0;
    const handleFilterChange = (pill) => {
      if (!pill) return;
      const now = performance.now();
      if (now - lastFilterTime < 60 && pill.classList.contains("active")) return;
      lastFilterTime = now;

      elements.recentFilterBar.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      activeRecentFilter = pill.dataset.filter || "all";
      renderRecentTasks();

      // Immediately synchronize and display the chosen transformation in the viewer
      const tasks = readRecentTasks();
      const match = activeRecentFilter === "all"
        ? tasks[0]
        : tasks.find((t) => (t.output_types || []).includes(activeRecentFilter));
      if (match) {
        loadTaskIntoView(match, false);
      }
    };

    elements.recentFilterBar?.querySelectorAll(".filter-pill").forEach((pill) => {
      pill.addEventListener("pointerdown", () => handleFilterChange(pill));
      pill.addEventListener("click", (e) => {
        e.preventDefault();
        handleFilterChange(pill);
      });
    });

    // User Card logout prompt
    elements.userCard?.addEventListener("click", () => {
      if (window.confirm("Sign out of Sudarshan AI?")) {
        window.location.replace("login.html");
      }
    });
    elements.configForm?.addEventListener("submit", submitConfiguration);
    elements.configSkipBtn?.addEventListener("click", hideConfigurationPrompt);
  }

  // Initialize Dashboard State with Live Backend Sync
  async function init() {
    try {
      const identity = await api.getCurrentUser?.();
      if (identity?.user) {
        adoptCurrentUser(identity.user);
        if (elements.userName) elements.userName.textContent = sudarshanDisplayName;
        if (elements.userPlan) elements.userPlan.textContent = sudarshanFriendlyLine;
        if (elements.userAvatar) elements.userAvatar.textContent = "SO";
        if (elements.topAvatar) elements.topAvatar.textContent = "SO";
        if (elements.greetingName) elements.greetingName.textContent = "Operator.";
      }
    } catch {
      // Use the anonymous development scope when no authenticated gateway user exists.
    }

    renderSidebarChats();
    syncCaseSelect();
    renderSidebarHistory();
    renderRecentTasks();
    updateOutputSelection();
    wireEvents();

    // Check backend health & update status badge
    async function updateHealth() {
      try {
        const health = await api.checkHealth();
        if (health && (health.ok || health.healthy)) {
          elements.backendStatusBadge?.classList.add("connected");
          elements.backendStatusBadge?.classList.remove("offline");
          if (elements.backendStatusText) {
            elements.backendStatusText.textContent = health.mode === "gateway" ? "Live :8080" : "Core :8000";
          }
        } else {
          elements.backendStatusBadge?.classList.remove("connected");
          elements.backendStatusBadge?.classList.add("offline");
          if (elements.backendStatusText) {
            elements.backendStatusText.textContent = "Offline";
          }
        }
      } catch {
        elements.backendStatusBadge?.classList.remove("connected");
        elements.backendStatusBadge?.classList.add("offline");
        if (elements.backendStatusText) {
          elements.backendStatusText.textContent = "Offline";
        }
      }
    }

    const initialHealth = await api.checkHealth();
    await updateHealth();
    if (initialHealth?.ok && initialHealth.data?.configuration && initialHealth.data.configuration.openai_api_key === false) {
      showConfigurationPrompt();
    }
    // Re-check health every 20 seconds
    setInterval(updateHealth, 20000);

    // Sync remote cases from backend if available
    try {
      const casesRes = await api.getCases();
      const backendCases = casesRes?.cases || (Array.isArray(casesRes) ? casesRes : []);
      if (backendCases.length > 0) {
        backendCases.forEach((bc) => {
          const cid = bc.caseId || bc.case_id || bc._id;
          const cname = bc.title || bc.name || cid;
          if (cid && elements.caseSelect && !elements.caseSelect.querySelector(`option[value="${cid}"]`)) {
            const opt = document.createElement("option");
            opt.value = cid;
            opt.textContent = cname;
            elements.caseSelect.appendChild(opt);
          }
        });
      }
    } catch { /* offline case handling */ }

    // Load initial task into view if available
    const tasks = readRecentTasks();
    if (tasks.length > 0) {
      loadTaskIntoView(tasks[0]);
    }
    await syncRemoteHistory();
  }

  init();
});
