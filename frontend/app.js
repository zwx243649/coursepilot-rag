const ICONS = {
  activity:
    '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>',
  chart:
    '<path d="M3 3v18h18"></path><path d="M7 16v-4"></path><path d="M12 16V8"></path><path d="M17 16v-7"></path>',
  check:
    '<path d="M20 6 9 17l-5-5"></path>',
  close:
    '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>',
  database:
    '<ellipse cx="12" cy="5" rx="8" ry="3"></ellipse><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"></path><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"></path>',
  file:
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M8 13h8"></path><path d="M8 17h6"></path>',
  message:
    '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"></path>',
  play:
    '<polygon points="6 3 20 12 6 21 6 3"></polygon>',
  plus:
    '<path d="M5 12h14"></path><path d="M12 5v14"></path>',
  refresh:
    '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"></path><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"></path><path d="M3 16v-4h4"></path><path d="M21 8v4h-4"></path>',
  search:
    '<circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path>',
  send:
    '<path d="m22 2-7 20-4-9-9-4z"></path><path d="M22 2 11 13"></path>',
  trash:
    '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path>',
  upload:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><path d="M12 3v12"></path>',
  warning:
    '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path>',
};

const STATUS_LABELS = {
  queued: "等待处理",
  processing: "解析中",
  ready: "可检索",
  failed: "处理失败",
};

const NODE_LABELS = {
  analyze: "问题分析",
  retrieve: "向量检索",
  grade: "相关性判断",
  generate: "生成回答",
  refuse: "安全拒绝",
};

const state = {
  courses: [],
  selectedCourseId: null,
  documents: [],
  messages: [],
  conversationId: null,
  activeView: "chat",
  health: null,
  uploadQueue: [],
  selectedColor: "#0F766E",
  lastTrace: null,
  evaluation: null,
  isAsking: false,
  pollTimer: null,
  importPollTimer: null,
};

function icon(name, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((element) => {
    element.innerHTML = icon(element.dataset.icon);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function selectedCourse() {
  return state.courses.find((course) => course.id === state.selectedCourseId) || null;
}

async function api(path, options = {}) {
  const request = { ...options, headers: { ...(options.headers || {}) } };
  if (request.body && !(request.body instanceof FormData)) {
    request.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`/api${path}`, request);
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item.msg).join("；");
      }
    } catch {
      // Keep the HTTP status fallback.
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function toast(message, type = "info") {
  const region = document.getElementById("toastRegion");
  const item = document.createElement("div");
  item.className = `toast ${type === "error" ? "error" : ""}`;
  item.textContent = message;
  region.appendChild(item);
  window.setTimeout(() => item.remove(), 3600);
}

function formatDate(value) {
  if (!value) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

async function loadHealth() {
  const button = document.getElementById("healthButton");
  const label = document.getElementById("healthLabel");
  try {
    state.health = await api("/system/health");
    const healthy = state.health.status === "ok";
    button.classList.toggle("ok", healthy);
    button.classList.toggle("degraded", !healthy);
    label.textContent = healthy ? "服务正常" : "部分服务可用";
    button.title = JSON.stringify(state.health);
  } catch (error) {
    button.classList.remove("ok");
    button.classList.add("degraded");
    label.textContent = "连接异常";
    button.title = error.message;
  }
}

async function loadCourses() {
  state.courses = await api("/courses");
  if (!state.courses.some((course) => course.id === state.selectedCourseId)) {
    state.selectedCourseId = state.courses[0]?.id || null;
  }
  renderCourses();
  renderHeader();
  if (state.selectedCourseId) {
    await selectCourse(state.selectedCourseId, { preserveMessages: false });
  } else {
    renderDocuments();
    renderMessages();
  }
}

async function selectCourse(courseId, options = {}) {
  if (!courseId) {
    state.selectedCourseId = null;
  } else {
    state.selectedCourseId = courseId;
  }
  if (!options.preserveMessages) {
    state.messages = [];
    state.conversationId = null;
    state.lastTrace = null;
  }
  renderCourses();
  renderHeader();
  renderMessages();
  renderEvidence();
  await loadDocuments();
}

function renderCourses() {
  const container = document.getElementById("courseList");
  if (!state.courses.length) {
    container.innerHTML = `
      <div class="empty-compact">
        <span>${icon("plus", 18)}</span>
        <p>还没有课程</p>
      </div>
    `;
    return;
  }

  container.innerHTML = state.courses
    .map(
      (course) => `
        <button
          class="course-item ${course.id === state.selectedCourseId ? "active" : ""}"
          type="button"
          data-course-id="${escapeHtml(course.id)}"
          style="--course-color:${escapeHtml(course.color)}"
        >
          <span class="course-dot"></span>
          <span class="course-name">${escapeHtml(course.name)}</span>
          <span class="course-meta">${course.document_count || 0}</span>
        </button>
      `,
    )
    .join("");
}

function renderHeader() {
  const course = selectedCourse();
  document.getElementById("courseTitle").textContent = course?.name || "CoursePilot";
  document.getElementById("courseDescription").textContent =
    course?.description || "从课程资料中检索、引用并回答问题";
  document.getElementById("headerDocumentCount").textContent =
    course?.document_count || state.documents.length || 0;
  document.getElementById("headerChunkCount").textContent = course?.chunk_count || 0;
}

async function loadDocuments() {
  window.clearTimeout(state.pollTimer);
  if (!state.selectedCourseId) {
    state.documents = [];
    renderDocuments();
    return;
  }

  const courseId = state.selectedCourseId;
  try {
    const documents = await api(`/courses/${courseId}/documents`);
    if (state.selectedCourseId !== courseId) return;
    state.documents = documents;
    renderDocuments();
    if (documents.some((item) => ["queued", "processing"].includes(item.status))) {
      state.pollTimer = window.setTimeout(loadDocuments, 2500);
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderDocuments() {
  const container = document.getElementById("documentList");
  const libraryBody = document.getElementById("libraryBody");
  document.getElementById("documentCount").textContent = state.documents.length;
  document.getElementById("librarySummary").textContent = state.documents.length
    ? `${state.documents.length} 个文件，可检索 ${state.documents.filter((item) => item.status === "ready").length} 个`
    : "暂无资料";

  if (!state.documents.length) {
    container.innerHTML = `
      <div class="empty-compact">
        <span>${icon("file", 18)}</span>
        <p>当前课程暂无资料</p>
      </div>
    `;
    libraryBody.innerHTML =
      '<tr><td colspan="5"><div class="empty-compact"><p>暂无资料</p></div></td></tr>';
    renderHeader();
    return;
  }

  container.innerHTML = state.documents
    .map(
      (documentItem) => `
        <div class="document-item">
          <span class="document-icon">${icon("file")}</span>
          <div class="document-copy">
            <div class="document-name" title="${escapeHtml(documentItem.original_name)}">
              ${escapeHtml(documentItem.original_name)}
            </div>
            <div class="document-meta">
              <span class="status-text ${escapeHtml(documentItem.status)}">
                ${STATUS_LABELS[documentItem.status] || escapeHtml(documentItem.status)}
              </span>
              <span>${documentItem.chunk_count} 切片</span>
            </div>
          </div>
        </div>
      `,
    )
    .join("");

  libraryBody.innerHTML = state.documents
    .map(
      (documentItem) => `
        <tr>
          <td>
            <div class="file-cell">
              <span class="document-icon">${icon("file")}</span>
              <div>
                <strong title="${escapeHtml(documentItem.original_name)}">${escapeHtml(documentItem.original_name)}</strong>
                <small>${escapeHtml(documentItem.mime_type || "text/plain")}</small>
              </div>
            </div>
          </td>
          <td>
            <span class="status-text ${escapeHtml(documentItem.status)}">
              ${STATUS_LABELS[documentItem.status] || escapeHtml(documentItem.status)}
            </span>
            ${
              documentItem.error_message
                ? `<div class="document-meta">${escapeHtml(documentItem.error_message)}</div>`
                : ""
            }
          </td>
          <td>${documentItem.chunk_count}</td>
          <td>${formatDate(documentItem.updated_at)}</td>
          <td>
            <div class="table-actions">
              <button class="icon-button" type="button" data-preview-id="${escapeHtml(documentItem.id)}" aria-label="预览" title="预览">
                ${icon("search")}
              </button>
              <button class="icon-button" type="button" data-delete-id="${escapeHtml(documentItem.id)}" aria-label="删除" title="删除">
                ${icon("trash")}
              </button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
  renderHeader();
}

function formatAnswer(content) {
  const lines = escapeHtml(content).split("\n");
  const blocks = [];
  let listItems = [];

  const flushList = () => {
    if (listItems.length) {
      blocks.push(`<ul>${listItems.join("")}</ul>`);
      listItems = [];
    }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ")) {
      listItems.push(`<li>${trimmed.slice(2)}</li>`);
      return;
    }
    flushList();
    if (trimmed) {
      blocks.push(`<p>${trimmed}</p>`);
    }
  });
  flushList();
  return blocks.join("") || "<p></p>";
}

function renderCitations(citations = []) {
  if (!citations.length) return "";
  return `
    <div class="citations">
      ${citations
        .map(
          (citation) => `
            <div class="citation">
              <span class="citation-index">${citation.index}</span>
              <div class="citation-copy">
                <div class="citation-source">
                  ${escapeHtml(citation.document_name)}
                  ${citation.page_number ? `· 第 ${citation.page_number} 页` : ""}
                </div>
                <div class="citation-excerpt">${escapeHtml(citation.excerpt)}</div>
              </div>
              <span class="citation-score">${Number(citation.score || 0).toFixed(2)}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderMessages() {
  const container = document.getElementById("messages");
  const course = selectedCourse();

  if (!state.messages.length && !state.isAsking) {
    container.innerHTML = `
      <div class="empty-chat">
        <span class="empty-chat-mark">${icon("message", 24)}</span>
        <h2>${escapeHtml(course?.name || "CoursePilot")}</h2>
        <p>基于当前课程资料回答，并给出可追溯的原文依据。</p>
        <div class="prompt-grid">
          <button class="prompt-button" type="button" data-prompt="提炼这门课程的核心知识点，并按主题说明。">
            提炼核心知识点
          </button>
          <button class="prompt-button" type="button" data-prompt="解释检索增强生成的基本流程，以及它解决了什么问题。">
            解释关键概念
          </button>
          <button class="prompt-button" type="button" data-prompt="根据资料生成一份复习提纲，包含重点和常见误区。">
            生成复习提纲
          </button>
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = state.messages
    .map((message) => {
      if (message.role === "user") {
        return `
          <article class="message user">
            <div class="message-body">${escapeHtml(message.content)}</div>
          </article>
        `;
      }
      return `
        <article class="message assistant">
          <div class="message-label">${icon("activity")} CoursePilot</div>
          <div class="message-body">
            <div class="assistant-answer">${formatAnswer(message.content)}</div>
            ${renderCitations(message.citations || [])}
          </div>
        </article>
      `;
    })
    .join("");

  if (state.isAsking) {
    container.insertAdjacentHTML(
      "beforeend",
      `
        <article class="message assistant">
          <div class="message-label">${icon("activity")} CoursePilot</div>
          <div class="message-body">
            正在检索课程资料
            <div class="loading-line"></div>
          </div>
        </article>
      `,
    );
  }

  window.requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight;
  });
}

function renderEvidence() {
  const container = document.getElementById("evidenceContent");
  const trace = state.lastTrace;
  if (!trace) {
    container.innerHTML = `
      <div class="empty-compact">
        <span>${icon("activity", 20)}</span>
        <p>提问后显示检索节点与引用来源</p>
      </div>
    `;
    return;
  }

  const nodes = (trace.nodes || [])
    .map(
      (node) => `
        <span class="trace-node">
          ${icon("check", 12)}
          ${NODE_LABELS[node] || escapeHtml(node)}
        </span>
      `,
    )
    .join("");
  const citations = trace.citations || [];
  const decision = trace.decision === "generate" ? "已生成" : "资料不足";

  container.innerHTML = `
    <section class="trace-section">
      <div class="trace-title">工作流节点</div>
      <div class="trace-flow">${nodes}</div>
    </section>
    <section class="trace-section">
      <div class="trace-title">本次运行</div>
      <div class="trace-metrics">
        <div class="trace-metric">
          <strong>${trace.retrieval_count}</strong>
          <span>召回切片</span>
        </div>
        <div class="trace-metric">
          <strong>${trace.latency_ms} ms</strong>
          <span>处理耗时</span>
        </div>
        <div class="trace-metric">
          <strong>${decision}</strong>
          <span>结果状态</span>
        </div>
        <div class="trace-metric">
          <strong>${citations.length}</strong>
          <span>引用来源</span>
        </div>
      </div>
    </section>
    <section class="trace-section">
      <div class="trace-title">引用来源</div>
      ${
        citations.length
          ? `<div class="evidence-list">${citations
              .slice(0, 4)
              .map(
                (citation) => `
                  <div class="evidence-source">
                    <div class="evidence-source-head">
                      <span>${escapeHtml(citation.document_name)}</span>
                      <span>${Number(citation.score || 0).toFixed(2)}</span>
                    </div>
                    <p>${escapeHtml(citation.excerpt)}</p>
                  </div>
                `,
              )
              .join("")}</div>`
          : '<div class="empty-compact"><p>没有达到阈值的引用来源</p></div>'
      }
    </section>
  `;
}

async function sendQuestion(question) {
  const cleaned = question.trim();
  if (!cleaned || state.isAsking) return;
  if (!state.selectedCourseId) {
    toast("请先创建或选择课程", "error");
    return;
  }

  state.messages.push({ role: "user", content: cleaned });
  state.isAsking = true;
  renderMessages();
  document.getElementById("questionInput").value = "";
  resizeComposer();

  try {
    const response = await api("/chat", {
      method: "POST",
      body: JSON.stringify({
        course_id: state.selectedCourseId,
        question: cleaned,
        conversation_id: state.conversationId,
      }),
    });
    state.conversationId = response.conversation_id;
    state.messages.push({
      role: "assistant",
      content: response.answer,
      citations: response.citations,
    });
    state.lastTrace = { ...response.trace, citations: response.citations };
  } catch (error) {
    state.messages.push({
      role: "assistant",
      content: `请求失败：${error.message}`,
      citations: [],
    });
    toast(error.message, "error");
  } finally {
    state.isAsking = false;
    renderMessages();
    renderEvidence();
  }
}

function resizeComposer() {
  const input = document.getElementById("questionInput");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

function openUploadDialog() {
  if (!state.selectedCourseId) {
    toast("请先创建课程", "error");
    return;
  }
  state.uploadQueue = [];
  renderSelectedFiles();
  document.getElementById("fileInput").value = "";
  switchSourceTab("file");
  document.getElementById("uploadDialog").showModal();
}

function switchSourceTab(tabName) {
  document.querySelectorAll(".source-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.sourceTab === tabName);
  });
  const filePanel = document.getElementById("fileSourcePanel");
  const webPanel = document.getElementById("webSourcePanel");
  filePanel.hidden = tabName !== "file";
  webPanel.hidden = tabName !== "web";
  filePanel.classList.toggle("active", tabName === "file");
  webPanel.classList.toggle("active", tabName === "web");
  document.getElementById("confirmUploadButton").hidden = tabName !== "file";
  document.getElementById("confirmWebImportButton").hidden = tabName !== "web";
}

function addFiles(files) {
  const allowed = [".pdf", ".md", ".markdown", ".txt"];
  for (const file of files) {
    const suffix = `.${file.name.split(".").pop().toLowerCase()}`;
    if (!allowed.includes(suffix)) {
      toast(`${file.name} 的格式不受支持`, "error");
      continue;
    }
    if (file.size > 25 * 1024 * 1024) {
      toast(`${file.name} 超过 25 MB`, "error");
      continue;
    }
    if (!state.uploadQueue.some((item) => item.file.name === file.name && item.file.size === file.size)) {
      state.uploadQueue.push({ file, status: "waiting" });
    }
  }
  renderSelectedFiles();
}

function renderSelectedFiles() {
  const container = document.getElementById("selectedFiles");
  container.innerHTML = state.uploadQueue
    .map(
      (item, index) => `
        <div class="selected-file">
          <span>${escapeHtml(item.file.name)}</span>
          <small data-file-status="${index}">
            ${
              item.status === "uploading"
                ? "上传中"
                : item.status === "done"
                  ? "已完成"
                  : item.status === "failed"
                    ? "失败"
                    : formatBytes(item.file.size)
            }
          </small>
        </div>
      `,
    )
    .join("");
}

async function uploadFiles() {
  if (!state.uploadQueue.length) {
    toast("请选择文件", "error");
    return;
  }
  const button = document.getElementById("confirmUploadButton");
  button.disabled = true;
  let successCount = 0;

  for (const item of state.uploadQueue) {
    item.status = "uploading";
    renderSelectedFiles();
    const form = new FormData();
    form.append("file", item.file, item.file.name);
    try {
      await api(`/courses/${state.selectedCourseId}/documents`, {
        method: "POST",
        body: form,
      });
      item.status = "done";
      successCount += 1;
    } catch (error) {
      item.status = "failed";
      toast(`${item.file.name}: ${error.message}`, "error");
    }
    renderSelectedFiles();
  }

  button.disabled = false;
  if (successCount) {
    toast(`已上传 ${successCount} 个文件`);
    document.getElementById("uploadDialog").close();
    state.uploadQueue = [];
    await loadDocuments();
    await refreshCourseStats();
  }
}

async function startWebImport() {
  if (!state.selectedCourseId) {
    toast("请先创建课程", "error");
    return;
  }
  const url = document.getElementById("docsUrlInput").value.trim();
  if (!url) {
    toast("请输入官方文档网址", "error");
    return;
  }

  const button = document.getElementById("confirmWebImportButton");
  button.disabled = true;
  try {
    const job = await api(`/courses/${state.selectedCourseId}/imports/web`, {
      method: "POST",
      body: JSON.stringify({
        url,
        max_pages: Number(document.getElementById("maxPagesInput").value || 12),
        same_path_only: document.getElementById("samePathInput").checked,
      }),
    });
    document.getElementById("uploadDialog").close();
    document.getElementById("docsUrlInput").value = "";
    toast("官方文档已加入导入队列");
    pollImportJob(job.id);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function pollImportJob(jobId) {
  window.clearTimeout(state.importPollTimer);
  try {
    const job = await api(`/imports/${jobId}`);
    await loadDocuments();
    await refreshCourseStats();
    if (["queued", "processing"].includes(job.status)) {
      state.importPollTimer = window.setTimeout(() => pollImportJob(jobId), 2500);
      return;
    }
    if (job.status === "ready") {
      toast(`官方文档导入完成，共索引 ${job.imported_count} 个页面`);
    } else {
      toast(job.error_message || "官方文档导入失败", "error");
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

async function refreshCourseStats() {
  try {
    state.courses = await api("/courses");
    renderCourses();
    renderHeader();
  } catch {
    // The document list is still usable if the aggregate refresh fails.
  }
}

async function deleteDocument(documentId) {
  const documentItem = state.documents.find((item) => item.id === documentId);
  if (!documentItem || !window.confirm(`删除“${documentItem.original_name}”？`)) return;
  try {
    await api(`/documents/${documentId}`, { method: "DELETE" });
    toast("资料已删除");
    await loadDocuments();
    await refreshCourseStats();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function previewDocument(documentId) {
  const documentItem = state.documents.find((item) => item.id === documentId);
  if (!documentItem) return;
  try {
    const chunks = await api(`/documents/${documentId}/chunks?limit=20`);
    document.getElementById("previewTitle").textContent = documentItem.original_name;
    document.getElementById("chunkPreview").innerHTML = chunks.length
      ? chunks
          .map(
            (chunk) => `
              <div class="chunk-block">
                <small>切片 ${chunk.chunk_index + 1}${chunk.page_number ? ` · 第 ${chunk.page_number} 页` : ""}</small>
                ${escapeHtml(chunk.content)}
              </div>
            `,
          )
          .join("")
      : '<div class="empty-compact"><p>文档尚未生成切片</p></div>';
    document.getElementById("previewDialog").showModal();
  } catch (error) {
    toast(error.message, "error");
  }
}

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });

  document.querySelectorAll(".source-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchSourceTab(tab.dataset.sourceTab));
  });

  document.querySelectorAll("[data-doc-url]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("docsUrlInput").value = button.dataset.docUrl;
    });
  });
  document.getElementById("chatView").hidden = view !== "chat";
  document.getElementById("libraryView").hidden = view !== "library";
  document.getElementById("evaluationView").hidden = view !== "evaluation";
}

async function createCourse(event) {
  event.preventDefault();
  const nameInput = document.getElementById("courseNameInput");
  const descriptionInput = document.getElementById("courseDescriptionInput");
  try {
    const course = await api("/courses", {
      method: "POST",
      body: JSON.stringify({
        name: nameInput.value.trim(),
        description: descriptionInput.value.trim(),
        color: state.selectedColor,
      }),
    });
    document.getElementById("courseDialog").close();
    nameInput.value = "";
    descriptionInput.value = "";
    state.courses.push(course);
    await selectCourse(course.id);
    toast("课程已创建");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function runEvaluation(event) {
  event.preventDefault();
  if (!state.selectedCourseId) {
    toast("请先选择课程", "error");
    return;
  }
  const raw = document.getElementById("evaluationCases").value.trim();
  const cases = raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [question, terms = ""] = line.split("|");
      return {
        question: question.trim(),
        expected_terms: terms
          .split(/[,，]/)
          .map((term) => term.trim())
          .filter(Boolean),
      };
    })
    .filter((item) => item.question);

  if (!cases.length) {
    toast("至少需要一条测试用例", "error");
    return;
  }

  const button = document.getElementById("runEvaluationButton");
  button.disabled = true;
  try {
    state.evaluation = await api("/evaluations/run", {
      method: "POST",
      body: JSON.stringify({
        course_id: state.selectedCourseId,
        cases,
        top_k: Number(document.getElementById("topKInput").value || 5),
      }),
    });
    renderEvaluation();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function renderEvaluation() {
  const result = state.evaluation;
  const container = document.getElementById("evaluationResults");
  if (!result) return;

  container.innerHTML = `
    <div class="metric-grid">
      <div class="metric">
        <strong>${formatPercent(result.recall_at_k)}</strong>
        <span>Recall@k 召回率</span>
      </div>
      <div class="metric">
        <strong>${formatPercent(result.precision_at_k)}</strong>
        <span>Precision@k 准确率</span>
      </div>
      <div class="metric">
        <strong>${Number(result.ndcg_at_k || 0).toFixed(2)}</strong>
        <span>NDCG@k 排序质量</span>
      </div>
      <div class="metric">
        <strong>${Number(result.mrr || 0).toFixed(2)}</strong>
        <span>MRR</span>
      </div>
      <div class="metric">
        <strong>${formatPercent(result.hit_rate)}</strong>
        <span>Hit Rate</span>
      </div>
      <div class="metric">
        <strong>${formatPercent(result.average_term_coverage)}</strong>
        <span>关键词覆盖</span>
      </div>
      <div class="metric">
        <strong>${formatPercent(result.decision_accuracy)}</strong>
        <span>判定准确率</span>
      </div>
      <div class="metric">
        <strong>${Math.round(result.average_latency_ms)} ms</strong>
        <span>平均检索耗时</span>
      </div>
    </div>
    <div class="evaluation-case-list">
      ${result.cases
        .map(
          (item) => `
            <div class="evaluation-case">
              <div>
                <div class="evaluation-question">${escapeHtml(item.question)}</div>
                <div class="evaluation-meta">
                  ${item.answerable ? "可回答" : "应拒答"}
                  · ${escapeHtml(item.decision)}
                  · Recall ${Number(item.recall_at_k || 0).toFixed(2)}
                  · NDCG ${Number(item.ndcg_at_k || 0).toFixed(2)}
                  · ${item.top_document ? escapeHtml(item.top_document) : "未召回文档"}
                  · Top score ${Number(item.top_score || 0).toFixed(2)}
                  · ${item.latency_ms} ms
                </div>
              </div>
              <span class="result-pill ${item.passed ? "hit" : "miss"}">
                ${
                  item.answerable
                    ? item.hit
                      ? "命中"
                      : "未命中"
                    : item.decision === "refuse"
                      ? "正确拒答"
                      : "未拒答"
                }
              </span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function bindDialogCloseButtons() {
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.closeDialog).close();
    });
  });
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
}

function bindEvents() {
  document.getElementById("uploadButton").addEventListener("click", openUploadDialog);
  document.getElementById("libraryUploadButton").addEventListener("click", openUploadDialog);
  document.getElementById("addCourseButton").addEventListener("click", () => {
    document.getElementById("courseDialog").showModal();
  });
  document.getElementById("healthButton").addEventListener("click", loadHealth);

  document.getElementById("courseList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-course-id]");
    if (button) selectCourse(button.dataset.courseId);
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });

  document.getElementById("messages").addEventListener("click", (event) => {
    const prompt = event.target.closest("[data-prompt]");
    if (prompt) sendQuestion(prompt.dataset.prompt);
  });

  document.getElementById("chatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    sendQuestion(document.getElementById("questionInput").value);
  });
  document.getElementById("questionInput").addEventListener("input", resizeComposer);
  document.getElementById("questionInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendQuestion(event.currentTarget.value);
    }
  });

  document.getElementById("libraryBody").addEventListener("click", (event) => {
    const preview = event.target.closest("[data-preview-id]");
    const remove = event.target.closest("[data-delete-id]");
    if (preview) previewDocument(preview.dataset.previewId);
    if (remove) deleteDocument(remove.dataset.deleteId);
  });

  document.getElementById("fileInput").addEventListener("change", (event) => {
    addFiles(event.target.files);
  });

  const dropZone = document.getElementById("dropZone");
  ["dragenter", "dragover"].forEach((name) => {
    dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    });
  });
  dropZone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));

  document.getElementById("uploadForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!document.getElementById("webSourcePanel").hidden) {
      startWebImport();
    } else {
      uploadFiles();
    }
  });
  document.getElementById("courseForm").addEventListener("submit", createCourse);
  document.getElementById("evaluationForm").addEventListener("submit", runEvaluation);

  document.getElementById("colorSwatches").addEventListener("click", (event) => {
    const swatch = event.target.closest("[data-color]");
    if (!swatch) return;
    state.selectedColor = swatch.dataset.color;
    document.querySelectorAll(".swatch").forEach((item) => {
      item.classList.toggle("selected", item === swatch);
    });
  });
}

async function init() {
  hydrateIcons();
  bindEvents();
  bindDialogCloseButtons();
  resizeComposer();
  renderMessages();
  renderEvidence();
  await loadHealth();
  try {
    await loadCourses();
  } catch (error) {
    toast(error.message, "error");
  }
  window.setInterval(loadHealth, 30000);
}

document.addEventListener("DOMContentLoaded", init);
