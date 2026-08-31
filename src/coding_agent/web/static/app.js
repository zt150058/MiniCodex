const STATUS_LABELS = Object.freeze({
  idle: "空闲",
  queued: "排队中",
  running: "运行中",
  cancelling: "正在取消",
  succeeded: "成功",
  failed: "失败",
  interrupted: "已中断",
});

const ACTIVITY_LABELS = Object.freeze({
  model_progress: "MiniCodex 正在处理",
  tool_started: "工具开始",
  tool_finished: "工具完成",
  verification_started: "验证开始",
  verification_finished: "验证完成",
  controller_error: "控制器错误",
  run_failed: "运行失败",
  run_interrupted: "运行已中断",
  changes_unverified: "修改待验证",
});
const RUN_MODES = new Set(["modify", "read_only"]);
const RUN_MODE_LABELS = Object.freeze({
  modify: "可修改",
  read_only: "只读",
});
const BUDGET_PROFILES = new Set(["standard", "deep"]);
export function appendPlainText(document, parent, text) {
  parent.append(document.createTextNode(String(text)));
}


const INLINE_MARKDOWN_PATTERNS = Object.freeze([
  { kind: "code", expression: /`([^`\n]+)`/ },
  { kind: "link", expression: /\[([^\]\n]+)\]\(([^)\s]+(?:\([^)]*\))?)\)/ },
  { kind: "strong", expression: /\*\*([^*\n]+)\*\*/ },
  { kind: "delete", expression: /~~([^~\n]+)~~/ },
  { kind: "emphasis", expression: /\*([^*\n]+)\*/ },
]);


function isSafeMarkdownLink(href) {
  return /^(?:https?:\/\/|mailto:)[^\s]+$/i.test(href);
}


function nextInlineMarkdownMatch(text) {
  let selected = null;
  for (const pattern of INLINE_MARKDOWN_PATTERNS) {
    const match = pattern.expression.exec(text);
    if (!match) continue;
    if (!selected || match.index < selected.match.index) {
      selected = { kind: pattern.kind, match };
    }
  }
  return selected;
}


function appendInlineMarkdown(document, parent, text) {
  let remaining = String(text);
  while (remaining) {
    const selected = nextInlineMarkdownMatch(remaining);
    if (!selected) {
      appendPlainText(document, parent, remaining);
      return;
    }
    const { kind, match } = selected;
    appendPlainText(document, parent, remaining.slice(0, match.index));
    if (kind === "link" && !isSafeMarkdownLink(match[2])) {
      appendPlainText(document, parent, match[0]);
    } else {
      const tagName = {
        code: "code",
        link: "a",
        strong: "strong",
        delete: "del",
        emphasis: "em",
      }[kind];
      const element = document.createElement(tagName);
      if (kind === "link") {
        element.setAttribute("href", match[2]);
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer");
        appendInlineMarkdown(document, element, match[1]);
      } else if (kind === "code") {
        appendPlainText(document, element, match[1]);
      } else {
        appendInlineMarkdown(document, element, match[1]);
      }
      parent.append(element);
    }
    remaining = remaining.slice(match.index + match[0].length);
  }
}


function tableCells(line) {
  let source = line.trim();
  if (source.startsWith("|")) source = source.slice(1);
  if (source.endsWith("|")) source = source.slice(0, -1);
  const cells = [];
  let cell = "";
  let escaped = false;
  for (const character of source) {
    if (escaped) {
      cell += character === "|" || character === "\\"
        ? character
        : `\\${character}`;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  if (escaped) cell += "\\";
  cells.push(cell.trim());
  return cells;
}


function tableAlignments(line) {
  const cells = tableCells(line);
  if (!cells.length || cells.some((cell) => !/^:?-{3,}:?$/.test(cell))) {
    return null;
  }
  return cells.map((cell) => {
    if (cell.startsWith(":") && cell.endsWith(":")) return "center";
    if (cell.endsWith(":")) return "right";
    return "left";
  });
}


function isMarkdownTable(lines, index) {
  if (index + 1 >= lines.length || !lines[index].includes("|")) return false;
  const alignments = tableAlignments(lines[index + 1]);
  return alignments !== null && tableCells(lines[index]).length === alignments.length;
}


function isMarkdownBlockStart(lines, index) {
  const line = lines[index] ?? "";
  return /^ {0,3}```/.test(line)
    || /^ {0,3}#{1,6}[ \t]+/.test(line)
    || /^ {0,3}>/.test(line)
    || /^ {0,3}(?:[-+*][ \t]+|\d+[.)][ \t]+)/.test(line)
    || /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/.test(line)
    || isMarkdownTable(lines, index);
}


function appendMarkdownBlock(document, parent, element) {
  if (parent.childNodes.length && !parent.textContent.endsWith("\n")) {
    appendPlainText(document, parent, "\n");
  }
  parent.append(element);
}


function appendMarkdownTable(document, parent, lines, index) {
  const headers = tableCells(lines[index]);
  const alignments = tableAlignments(lines[index + 1]);
  const wrapper = document.createElement("div");
  wrapper.className = "markdown-table-wrapper";
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((content, cellIndex) => {
    const cell = document.createElement("th");
    cell.className = `markdown-align-${alignments[cellIndex]}`;
    appendInlineMarkdown(document, cell, content);
    headRow.append(cell);
  });
  head.append(headRow);
  table.append(head);

  const body = document.createElement("tbody");
  let cursor = index + 2;
  while (cursor < lines.length && lines[cursor].trim() && lines[cursor].includes("|")) {
    const values = tableCells(lines[cursor]);
    const row = document.createElement("tr");
    headers.forEach((_header, cellIndex) => {
      const cell = document.createElement("td");
      cell.className = `markdown-align-${alignments[cellIndex]}`;
      appendInlineMarkdown(document, cell, values[cellIndex] ?? "");
      row.append(cell);
    });
    body.append(row);
    cursor += 1;
  }
  table.append(body);
  wrapper.append(table);
  appendMarkdownBlock(document, parent, wrapper);
  return cursor;
}


function appendMarkdownBlocks(document, parent, text, onCopyCode = null) {
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = /^ {0,3}```([A-Za-z0-9_+-]*)[ \t]*$/.exec(line);
    if (fence) {
      let closing = index + 1;
      while (closing < lines.length && !/^ {0,3}```[ \t]*$/.test(lines[closing])) {
        closing += 1;
      }
      if (closing >= lines.length) {
        if (parent.childNodes.length && !parent.textContent.endsWith("\n")) {
          appendPlainText(document, parent, "\n");
        }
        appendPlainText(document, parent, lines.slice(index).join("\n"));
        return;
      }
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (fence[1]) code.className = `language-${fence[1].toLowerCase()}`;
      const codeLines = lines.slice(index + 1, closing);
      const codeText = codeLines.join("\n");
      appendPlainText(
        document,
        code,
        codeLines.length ? `${codeText}\n` : "",
      );
      pre.append(code);
      const wrapper = document.createElement("div");
      wrapper.className = "code-block";
      const copyButton = document.createElement("button");
      copyButton.setAttribute("type", "button");
      copyButton.className = "code-copy-button";
      copyButton.dataset.copyState = "idle";
      copyButton.setAttribute("aria-label", "复制代码");
      appendPlainText(document, copyButton, "复制");
      copyButton.disabled = typeof onCopyCode !== "function";
      copyButton.addEventListener("click", () => {
        if (typeof onCopyCode === "function") onCopyCode(copyButton, codeText);
      });
      wrapper.append(copyButton, pre);
      appendMarkdownBlock(document, parent, wrapper);
      index = closing + 1;
      continue;
    }

    if (isMarkdownTable(lines, index)) {
      index = appendMarkdownTable(document, parent, lines, index);
      continue;
    }

    const heading = /^ {0,3}(#{1,6})[ \t]+(.+)$/.exec(line);
    if (heading) {
      const element = document.createElement(`h${heading[1].length}`);
      const content = heading[2]
        .trimEnd()
        .replace(/[ \t]+#+[ \t]*$/, "");
      appendInlineMarkdown(document, element, content);
      appendMarkdownBlock(document, parent, element);
      index += 1;
      continue;
    }

    if (/^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/.test(line)) {
      appendMarkdownBlock(document, parent, document.createElement("hr"));
      index += 1;
      continue;
    }

    if (/^ {0,3}>/.test(line)) {
      const quoteLines = [];
      while (index < lines.length) {
        const quote = /^ {0,3}>[ \t]?(.*)$/.exec(lines[index]);
        if (!quote) break;
        quoteLines.push(quote[1]);
        index += 1;
      }
      const blockquote = document.createElement("blockquote");
      appendMarkdownBlocks(document, blockquote, quoteLines.join("\n"), onCopyCode);
      appendMarkdownBlock(document, parent, blockquote);
      continue;
    }

    const unordered = /^ {0,3}[-+*][ \t]+(.+)$/.exec(line);
    const ordered = /^ {0,3}\d+[.)][ \t]+(.+)$/.exec(line);
    if (unordered || ordered) {
      const tagName = ordered ? "ol" : "ul";
      const expression = ordered
        ? /^ {0,3}\d+[.)][ \t]+(.+)$/
        : /^ {0,3}[-+*][ \t]+(.+)$/;
      const list = document.createElement(tagName);
      while (index < lines.length) {
        const item = expression.exec(lines[index]);
        if (!item) break;
        const listItem = document.createElement("li");
        appendInlineMarkdown(document, listItem, item[1]);
        list.append(listItem);
        index += 1;
      }
      appendMarkdownBlock(document, parent, list);
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !isMarkdownBlockStart(lines, index)
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement("p");
    appendInlineMarkdown(document, paragraph, paragraphLines.join("\n"));
    appendMarkdownBlock(document, parent, paragraph);
  }
}


export function appendMessage(
  document,
  container,
  role,
  text,
  runMode = null,
  onCopyCode = null,
) {
  const message = document.createElement("article");
  message.className = `message message--${role === "user" ? "user" : "assistant"}`;
  const label = document.createElement("div");
  label.className = "message__label";
  appendPlainText(document, label, role === "user" ? "你" : "MiniCodex");
  if (role === "user" && Object.hasOwn(RUN_MODE_LABELS, runMode)) {
    const badge = document.createElement("span");
    badge.className = "run-mode-badge";
    appendPlainText(document, badge, RUN_MODE_LABELS[runMode]);
    label.append(badge);
  }
  const body = document.createElement("div");
  body.className = "message__body";
  if (role === "user") appendPlainText(document, body, String(text));
  else appendMarkdownBlocks(document, body, String(text), onCopyCode);
  message.append(label, body);
  container.append(message);
  return message;
}


function safeActivityDetails(kind, data) {
  if (kind === "model_progress") {
    return [data.content];
  }
  if (kind === "tool_started") {
    return [data.tool_name, `#${data.ordinal}`];
  }
  if (kind === "tool_finished") {
    const outcome = Number.isInteger(data.exit_code)
      ? `exit ${data.exit_code}`
      : data.status;
    return [data.tool_name, outcome, `${data.duration_ms} ms`];
  }
  if (kind === "verification_started") {
    return [data.source, `#${data.attempt_index}`];
  }
  if (kind === "verification_finished") {
    return [data.status, data.source, `${data.duration_ms} ms`];
  }
  if (kind === "controller_error") {
    return [data.code];
  }
  if (kind === "run_failed" || kind === "run_interrupted") {
    return [data.termination_reason];
  }
  if (kind === "changes_unverified") {
    return [
      `已修改：${data.changed_paths.join("、")}`,
      "验证：尚未执行或尚未通过",
      `原因：${data.safe_error_code}`,
      "建议：重新运行并提供强制验证命令，或让 Agent 使用允许的验证形式",
    ];
  }
  return [];
}


export function appendActivity(
  document,
  container,
  kind,
  data,
  { active = false } = {},
) {
  const card = document.createElement("div");
  card.className = kind === "changes_unverified"
    ? "activity-card activity-card--changes-unverified"
    : "activity-card";
  if (active) card.classList.add("activity-card--active");
  if (active) {
    const indicator = document.createElement("span");
    indicator.className = "activity-indicator";
    indicator.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      const dot = document.createElement("span");
      dot.className = "activity-indicator__dot";
      indicator.append(dot);
    }
    card.append(indicator);
  }
  const label = ACTIVITY_LABELS[kind] ?? String(kind);
  const details = safeActivityDetails(kind, data ?? {})
    .filter((value) => value !== undefined && value !== null && value !== "")
    .map(String);
  const content = document.createElement("span");
  content.className = "activity-card__content";
  appendPlainText(
    document,
    content,
    details.length ? `${label} · ${details.join(" · ")}` : label,
  );
  card.append(content);
  container.append(card);
  return card;
}


export function renderRunHeader(
  document,
  elements,
  run,
  transientStatus = null,
) {
  const status = run?.status;
  const answered = status === "succeeded" && run?.agent_status === "answered";
  const active = ["queued", "running", "cancelling"].includes(status);
  const label = active && typeof transientStatus === "string"
    ? transientStatus
    : answered ? "已回答" : STATUS_LABELS[status] ?? "状态未知";
  elements.runStatus.replaceChildren(document.createTextNode(label));
  elements.runStatus.className = `status-pill status-pill--${
    status === "succeeded"
      ? answered ? "answered" : "success"
      : status === "failed" || status === "interrupted"
        ? "failure"
        : status === "running" || status === "cancelling" || status === "queued"
          ? "running"
          : "idle"
  }`;
  elements.cancelButton.disabled = ![
    "queued",
    "running",
    "cancelling",
  ].includes(status);
}


export function consumeBootstrapToken(document) {
  const bootstrap = document.getElementById("coding-agent-bootstrap");
  const token = bootstrap?.getAttribute("content");
  if (typeof token !== "string" || token.trim() === "") {
    throw new Error("bootstrap token unavailable");
  }
  bootstrap.remove();
  return token;
}


export class WebClientError extends Error {
  constructor(code) {
    super(code);
    this.name = "WebClientError";
    this.code = code;
  }
}


export function createInitialUiState() {
  return {
    sessions: [],
    selectedSessionId: null,
    selectedSession: null,
    skills: [],
    skillDiagnostics: [],
    selectedSkillIds: [],
    selectedRunMode: "modify",
    selectedBudgetProfile: "standard",
    modelCatalog: {
      enabled: false,
      status: "disabled",
      defaultModelId: null,
      modelIds: [],
      errorCode: null,
    },
    selectedModelId: null,
    activeRunId: null,
    lastSequence: 0,
    provisionalText: "",
    activities: [],
    runProgress: null,
    transientStatus: null,
    connection: "connecting",
    phase: "waiting",
    errorCode: null,
  };
}


export function createApiClient({
  accessToken,
  fetchImpl = globalThis.fetch,
  baseUrl = "http://local.invalid",
}) {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");

  async function request(
    path,
    { method = "GET", json, rawBody, contentType } = {},
  ) {
    if (json !== undefined && rawBody !== undefined) {
      throw new WebClientError("invalid_request_body");
    }
    const headers = new Headers({
      Authorization: `Bearer ${accessToken}`,
    });
    const init = { method, headers };
    if (json !== undefined) {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(json);
    } else if (rawBody !== undefined) {
      headers.set("Content-Type", contentType);
      init.body = rawBody;
    }
    const response = await fetchImpl(
      new Request(`${normalizedBaseUrl}${path}`, init),
    );
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new WebClientError("invalid_response");
    }
    if (!response.ok) {
      const code = payload?.error?.code;
      throw new WebClientError(
        typeof code === "string" && code ? code : "request_failed",
      );
    }
    return payload;
  }

  return Object.freeze({
    listSessions: () => request("/api/v1/sessions?limit=50"),
    listModels: (refresh = false) =>
      request(`/api/v1/models?refresh=${refresh ? "true" : "false"}`),
    loadSession: (sessionId) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}`),
    deleteSession: (sessionId) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      }),
    listSkills: () => request("/api/v1/skills"),
    importSkillArchive: (archive) =>
      request("/api/v1/skills/import", {
        method: "POST",
        rawBody: archive,
        contentType: "application/zip",
      }),
    createSession: (
      message,
      skillIds,
      runMode = "modify",
      budgetProfile = "standard",
      modelId = null,
    ) =>
      request("/api/v1/sessions", {
        method: "POST",
        json: {
          message,
          skill_ids: skillIds,
          run_mode: runMode,
          budget_profile: budgetProfile,
          model_id: modelId,
        },
      }),
    submitFollowUp: (
      sessionId,
      message,
      runMode = "modify",
      budgetProfile = "standard",
      modelId = null,
    ) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: "POST",
        json: {
          message,
          run_mode: runMode,
          budget_profile: budgetProfile,
          model_id: modelId,
        },
      }),
    saveSkillSelection: (sessionId, skillIds) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/skills`, {
        method: "PUT",
        json: { skill_ids: skillIds },
      }),
    cancelRun: (runId) =>
      request(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
        json: {},
      }),
    openRunStream: (runId, afterSequence = 0, { signal } = {}) => {
      const headers = new Headers({
        Authorization: `Bearer ${accessToken}`,
        Accept: "text/event-stream",
      });
      if (afterSequence > 0) {
        headers.set("Last-Event-ID", String(afterSequence));
      }
      return fetchImpl(
        new Request(
          `${normalizedBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/events`,
          { method: "GET", headers, signal },
        ),
      );
    },
  });
}


const ACTIVE_SESSION_STATUSES = new Set(["running", "cancelling"]);
const RECONNECT_DELAYS_MS = Object.freeze([500, 1000, 2000, 5000]);
const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "interrupted"]);


export function reconnectDelayForAttempt(attempt) {
  const index = Math.max(0, Math.min(Number(attempt) || 0, RECONNECT_DELAYS_MS.length - 1));
  return RECONNECT_DELAYS_MS[index];
}


export function parseSseFrames(text, afterSequence = 0) {
  let remainder = String(text);
  let lastSequence = afterSequence;
  const frames = [];
  while (true) {
    const boundary = remainder.indexOf("\n\n");
    if (boundary < 0) break;
    const block = remainder.slice(0, boundary);
    remainder = remainder.slice(boundary + 2);
    if (!block || block.startsWith(":")) continue;
    const fields = new Map();
    for (const line of block.split("\n")) {
      const separator = line.indexOf(":");
      if (separator < 0) throw new WebClientError("invalid_event_stream");
      const name = line.slice(0, separator);
      const value = line.slice(separator + 1).replace(/^ /, "");
      if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
        throw new WebClientError("invalid_event_stream");
      }
      fields.set(name, value);
    }
    const event = fields.get("event");
    const serialized = fields.get("data");
    if (!event || serialized === undefined) {
      throw new WebClientError("invalid_event_stream");
    }
    let data;
    try {
      data = JSON.parse(serialized);
    } catch {
      throw new WebClientError("invalid_event_stream");
    }
    if (event === "reset_required" || event === "transport_error") {
      if (fields.has("id")) throw new WebClientError("invalid_event_stream");
      frames.push({ id: null, event, data });
      continue;
    }
    const rawId = fields.get("id");
    if (!rawId || !/^[1-9][0-9]*$/.test(rawId)) {
      throw new WebClientError("invalid_event_stream");
    }
    const id = Number(rawId);
    if (!Number.isSafeInteger(id) || id <= lastSequence) {
      throw new WebClientError("invalid_event_stream");
    }
    if (
      !data ||
      typeof data !== "object" ||
      data.sequence !== id ||
      data.kind !== event ||
      !data.data ||
      typeof data.data !== "object"
    ) {
      throw new WebClientError("invalid_event_stream");
    }
    lastSequence = id;
    frames.push({ id, event, data });
  }
  return { frames, remainder, lastSequence };
}


function safeActivityData(kind, data) {
  const fields = {
    tool_started: ["tool_name", "ordinal"],
    tool_finished: ["tool_name", "status", "duration_ms", "truncated", "exit_code", "safe_error_code", "changed_paths"],
    verification_started: ["source", "attempt_index", "mutation_index"],
    verification_finished: ["status", "source", "duration_ms", "exit_code", "timed_out", "truncated", "safe_error_code"],
    controller_error: ["code"],
  }[kind] ?? [];
  return Object.fromEntries(
    fields.filter((field) => Object.hasOwn(data, field)).map((field) => [field, data[field]]),
  );
}


export function reduceSessionUpdate(state, frame) {
  const payload = frame.data?.data ?? {};
  if (frame.id !== null) state.lastSequence = frame.id;
  if (frame.event === "run_progress") {
    const fields = [
      "budget_profile",
      "phase",
      "main_model_calls",
      "main_model_limit",
      "summary_model_calls",
      "summary_model_limit",
      "provider_attempts",
      "provider_attempt_limit",
      "tool_calls",
      "tool_limit",
    ];
    state.runProgress = Object.fromEntries(
      fields.map((field) => [field, payload[field]]),
    );
    if (typeof payload.phase === "string") state.phase = payload.phase;
    const runId = frame.data?.run_id ?? state.activeRunId;
    const run = state.selectedSession?.runs?.find((item) => item.run_id === runId);
    if (run && BUDGET_PROFILES.has(payload.budget_profile)) {
      run.budget_profile = payload.budget_profile;
    }
    return state;
  }
  if (frame.event === "phase_changed") {
    if (typeof payload.to_phase === "string") state.phase = payload.to_phase;
    state.transientStatus = null;
    return state;
  }
  if (frame.event === "decision_checkpoint") {
    state.transientStatus = payload.reason === "final_call_reserve"
      ? "正在使用最终决策预算"
      : "根据已有信息作出决策";
    return state;
  }
  if (frame.event === "context_compressed") {
    state.transientStatus = "上下文已压缩，继续执行";
    return state;
  }
  if (frame.event === "no_progress_detected") {
    state.transientStatus = "未取得足够进展，正在结束";
    return state;
  }
  if (frame.event === "assistant_text_delta" && typeof payload.content === "string") {
    state.activities = [];
    state.provisionalText += payload.content;
    return state;
  }
  if (frame.event === "assistant_text_committed" && typeof payload.content === "string") {
    state.provisionalText = payload.content;
    state.selectedSession?.events?.push({
      run_id: frame.data?.run_id ?? state.activeRunId,
      sequence: frame.id,
      kind: frame.event,
      data: { content: payload.content },
    });
    return state;
  }
  if (frame.event === "assistant_text_discarded") {
    state.provisionalText = "";
    return state;
  }
  if (Object.hasOwn(ACTIVITY_LABELS, frame.event)) {
    state.provisionalText = "";
    state.activities = [{
      kind: frame.event,
      data: safeActivityData(frame.event, payload),
    }];
    return state;
  }
  const lifecycleStatus = {
    run_queued: "queued",
    run_started: "running",
    run_cancelling: "cancelling",
    run_finished: payload.status,
  }[frame.event];
  if (typeof lifecycleStatus === "string") {
    const session = state.selectedSession?.session;
    const runId = frame.data?.run_id ?? state.activeRunId;
    const run = state.selectedSession?.runs?.find((item) => item.run_id === runId);
    if (session) session.status = lifecycleStatus;
    if (run) {
      run.status = lifecycleStatus;
      if (frame.event === "run_finished") {
        if ([
          "success",
          "answered",
          "failed",
          "interrupted",
        ].includes(payload.agent_status)) {
          run.agent_status = payload.agent_status;
        }
        run.termination_reason =
          typeof payload.termination_reason === "string" && payload.termination_reason
            ? payload.termination_reason
            : null;
      }
    }
    state.phase = frame.event === "run_finished" ? "finished" : "model";
    if (TERMINAL_RUN_STATUSES.has(lifecycleStatus)) {
      state.activeRunId = null;
      state.provisionalText = "";
      state.activities = [];
      state.runProgress = null;
      state.transientStatus = null;
    }
  }
  return state;
}


export async function consumeRunStream({
  api,
  runId,
  state,
  reloadSession,
  signal,
  sleep = (delay) => new Promise((resolve) => setTimeout(resolve, delay)),
  onState = () => {},
}) {
  let reconnectAttempt = 0;
  while (true) {
    if (signal?.aborted) return "aborted";
    let response;
    try {
      response = await api.openRunStream(runId, state.lastSequence, { signal });
    } catch (error) {
      if (signal?.aborted || error?.name === "AbortError") return "aborted";
      await sleep(reconnectDelayForAttempt(reconnectAttempt));
      reconnectAttempt += 1;
      continue;
    }
    if (response.status === 401 || response.status === 403) {
      state.connection = "authentication_failed";
      state.errorCode = response.status === 401 ? "unauthorized" : "forbidden";
      onState(state);
      return "authentication_failed";
    }
    if (!response.ok || !response.body) {
      await sleep(reconnectDelayForAttempt(reconnectAttempt));
      reconnectAttempt += 1;
      continue;
    }
    state.connection = "connected";
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let remainder = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        remainder += decoder.decode(value, { stream: true });
        const parsed = parseSseFrames(remainder, state.lastSequence);
        remainder = parsed.remainder;
        for (const frame of parsed.frames) {
          if (frame.event === "reset_required") {
            const lastSequence = frame.data?.last_sequence;
            if (!Number.isSafeInteger(lastSequence) || lastSequence < 0 || frame.data?.run_id !== runId) {
              throw new WebClientError("invalid_event_stream");
            }
            const detail = await reloadSession();
            state.selectedSession = detail;
            state.selectedSessionId = detail?.session?.session_id ?? state.selectedSessionId;
            state.selectedSkillIds = [...(detail?.skill_ids ?? [])];
            state.lastSequence = lastSequence;
            state.provisionalText = "";
            const status = detail?.session?.status;
            if (TERMINAL_RUN_STATUSES.has(status)) {
              state.activeRunId = null;
              onState(state);
              return "reset_terminal";
            }
            onState(state);
            reconnectAttempt = 0;
            break;
          }
          if (frame.event === "transport_error") break;
          reduceSessionUpdate(state, frame);
          onState(state);
          if (frame.event === "run_finished") return "terminal";
        }
      }
      const tail = decoder.decode();
      if (tail) remainder += tail;
      if (remainder.trim()) throw new WebClientError("invalid_event_stream");
    } catch (error) {
      if (signal?.aborted || error?.name === "AbortError") return "aborted";
      if (error instanceof WebClientError && error.code === "invalid_event_stream") {
        const detail = await reloadSession();
        state.selectedSession = detail;
        state.provisionalText = "";
        state.activeRunId = TERMINAL_RUN_STATUSES.has(detail?.session?.status) ? null : runId;
        onState(state);
        return "invalid_stream_reloaded";
      }
    } finally {
      reader.releaseLock();
    }
    if (!state.activeRunId) return "inactive";
    await sleep(reconnectDelayForAttempt(reconnectAttempt));
    reconnectAttempt += 1;
  }
}


function formatElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}


export function defaultClipboardWrite(text) {
  const clipboard = globalThis.navigator?.clipboard;
  if (!clipboard || typeof clipboard.writeText !== "function") {
    return Promise.reject(new Error("clipboard unavailable"));
  }
  return clipboard.writeText(text);
}


export function createUiController({
  document,
  elements,
  api,
  now = () => Date.now(),
  setIntervalImpl = globalThis.setInterval,
  clearIntervalImpl = globalThis.clearInterval,
  setTimeoutImpl = globalThis.setTimeout,
  clearTimeoutImpl = globalThis.clearTimeout,
  clipboardWrite = defaultClipboardWrite,
  streamConsumer = consumeRunStream,
  confirmDelete = () => false,
}) {
  if (typeof confirmDelete !== "function") {
    throw new TypeError("confirmDelete must be callable");
  }
  for (const [name, callback] of [
    ["setTimeoutImpl", setTimeoutImpl],
    ["clearTimeoutImpl", clearTimeoutImpl],
    ["clipboardWrite", clipboardWrite],
  ]) {
    if (typeof callback !== "function") {
      throw new TypeError(`${name} must be callable`);
    }
  }
  const state = createInitialUiState();
  let pending = Promise.resolve();
  let elapsedTimer = null;
  let activeStream = null;
  let skillImportPending = false;
  let expandedSkillId = null;
  let sessionDeletePending = false;
  let modelRefreshPending = false;
  let renderedModelIds = [];
  let destroyed = false;
  const copyResetTimers = new Set();

  function setCopyButtonState(button, stateName, text, ariaLabel, disabled) {
    button.dataset.copyState = stateName;
    button.disabled = disabled;
    button.setAttribute("aria-label", ariaLabel);
    button.replaceChildren(document.createTextNode(text));
  }

  function clearCopyResetTimers() {
    for (const timerId of copyResetTimers) clearTimeoutImpl(timerId);
    copyResetTimers.clear();
  }

  function scheduleCopyButtonReset(button) {
    const timerId = setTimeoutImpl(() => {
      copyResetTimers.delete(timerId);
      setCopyButtonState(button, "idle", "复制", "复制代码", false);
    }, 1500);
    copyResetTimers.add(timerId);
  }

  async function copyCodeText(button, codeText) {
    if (destroyed || button.disabled) return;
    setCopyButtonState(button, "pending", "复制中…", "正在复制代码", true);
    try {
      await clipboardWrite(codeText);
      if (destroyed) return;
      setCopyButtonState(button, "success", "已复制", "代码已复制", true);
    } catch {
      if (destroyed) return;
      setCopyButtonState(button, "error", "复制失败", "代码复制失败", true);
    }
    scheduleCopyButtonReset(button);
  }

  function setConnectionNotice(message) {
    elements.connectionStatus.replaceChildren();
    if (typeof message === "string" && message) {
      elements.connectionStatus.append(document.createTextNode(message));
      elements.connectionStatus.dataset.visible = "true";
      elements.connectionStatus.setAttribute("aria-hidden", "false");
    } else {
      elements.connectionStatus.dataset.visible = "false";
      elements.connectionStatus.setAttribute("aria-hidden", "true");
    }
  }

  function anySessionActive() {
    return state.sessions.some((session) =>
      ACTIVE_SESSION_STATUSES.has(session.status),
    );
  }

  function normalizeModelCatalog(payload) {
    const modelIds = Array.isArray(payload?.model_ids)
      ? payload.model_ids.filter((modelId) => typeof modelId === "string" && modelId)
      : [];
    const defaultModelId = typeof payload?.default_model_id === "string"
      && modelIds.includes(payload.default_model_id)
      ? payload.default_model_id
      : null;
    const enabled = payload?.enabled === true && defaultModelId !== null;
    const status = ["ready", "stale", "unavailable", "disabled"].includes(
      payload?.status,
    ) ? payload.status : "unavailable";
    return {
      enabled,
      status,
      defaultModelId,
      modelIds,
      errorCode: typeof payload?.error_code === "string"
        ? payload.error_code
        : null,
    };
  }

  function unavailableModelCatalog() {
    return {
      enabled: false,
      status: "unavailable",
      defaultModelId: null,
      modelIds: [],
      errorCode: "model_catalog_unavailable",
    };
  }

  function applyModelCatalog(payload, { preserveSelection = true } = {}) {
    const catalog = normalizeModelCatalog(payload);
    const preserved = preserveSelection
      && catalog.modelIds.includes(state.selectedModelId)
      ? state.selectedModelId
      : null;
    state.modelCatalog = catalog;
    state.selectedModelId = catalog.enabled
      ? preserved ?? catalog.defaultModelId
      : null;
  }

  function renderModelControl() {
    const catalog = state.modelCatalog;
    elements.modelControl.hidden = !catalog.enabled;
    const catalogChanged = renderedModelIds.length !== catalog.modelIds.length
      || renderedModelIds.some((modelId, index) => modelId !== catalog.modelIds[index]);
    if (catalogChanged) {
      elements.modelSelect.replaceChildren();
      for (const modelId of catalog.modelIds) {
        const option = document.createElement("option");
        option.value = modelId;
        option.setAttribute("title", modelId);
        appendPlainText(document, option, modelId);
        elements.modelSelect.append(option);
      }
      renderedModelIds = [...catalog.modelIds];
    }
    elements.modelSelect.value = state.selectedModelId ?? "";
    elements.modelSelect.setAttribute("title", state.selectedModelId ?? "");
    const mutationLocked = anySessionActive();
    elements.modelSelect.disabled = mutationLocked
      || modelRefreshPending
      || state.selectedModelId === null;
    elements.refreshModelsButton.disabled = mutationLocked || modelRefreshPending;
    const statusText = modelRefreshPending
      ? "正在刷新…"
      : catalog.status === "stale"
        ? "模型列表可能已过期"
        : catalog.status === "unavailable"
          ? "无法获取模型列表"
          : "";
    elements.modelCatalogStatus.replaceChildren(
      document.createTextNode(statusText),
    );
    elements.modelCatalogStatus.setAttribute("title", statusText);
  }

  function selectedRun() {
    const runs = state.selectedSession?.runs ?? [];
    const lastRunId = state.selectedSession?.session?.last_run_id;
    return runs.find((run) => run.run_id === lastRunId) ?? runs.at(-1) ?? null;
  }

  function runProjectionFacts(detail) {
    const runsById = new Map((detail?.runs ?? []).map((run) => [run.run_id, run]));
    const lastAssistantSequence = new Map();
    const lastEventSequence = new Map();
    const latestSafeErrorCode = new Map();
    for (const event of detail?.events ?? []) {
      if (typeof event.run_id !== "string") continue;
      lastEventSequence.set(event.run_id, event.sequence);
      if (event.kind === "assistant_text_committed") {
        lastAssistantSequence.set(event.run_id, event.sequence);
      }
      if (
        event.kind === "tool_activity" &&
        typeof event.data?.safe_error_code === "string" &&
        event.data.safe_error_code
      ) {
        latestSafeErrorCode.set(event.run_id, event.data.safe_error_code);
      }
    }
    return {
      runsById,
      lastAssistantSequence,
      lastEventSequence,
      latestSafeErrorCode,
    };
  }

  function renderControls() {
    const mutationLocked = anySessionActive();
    elements.sendButton.disabled = mutationLocked;
    for (const button of [
      elements.runModeModifyButton,
      elements.runModeReadOnlyButton,
    ]) {
      button.disabled = mutationLocked;
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.runMode === state.selectedRunMode),
      );
    }
    for (const button of [
      elements.budgetProfileStandardButton,
      elements.budgetProfileDeepButton,
    ]) {
      button.disabled = mutationLocked;
      button.setAttribute(
        "aria-pressed",
        String(
          button.dataset.budgetProfile === state.selectedBudgetProfile
        ),
      );
    }
    for (const input of findInputs(elements.skillList)) {
      input.disabled = mutationLocked;
    }
    elements.skillImportButton.disabled = mutationLocked || skillImportPending;
    elements.skillFileInput.disabled = mutationLocked || skillImportPending;
    for (const button of findSessionDeleteButtons(elements.sessionList)) {
      button.disabled = mutationLocked || sessionDeletePending;
    }
    renderModelControl();
  }

  function findInputs(root) {
    const inputs = [];
    function visit(node) {
      if (node?.nodeType === 1 && node.tagName === "INPUT") inputs.push(node);
      for (const child of node?.childNodes ?? []) visit(child);
    }
    visit(root);
    return inputs;
  }

  function findSessionDeleteButtons(root) {
    const buttons = [];
    function visit(node) {
      if (
        node?.nodeType === 1
        && node.tagName === "BUTTON"
        && node.dataset?.deleteSessionId
      ) {
        buttons.push(node);
      }
      for (const child of node?.childNodes ?? []) visit(child);
    }
    visit(root);
    return buttons;
  }

  function renderSessions() {
    elements.sessionList.replaceChildren();
    for (const session of state.sessions) {
      const item = document.createElement("li");
      item.className = "session-item";
      const button = document.createElement("button");
      button.setAttribute("type", "button");
      button.className = "session-button";
      button.dataset.sessionId = session.session_id;
      button.setAttribute(
        "aria-current",
        String(state.selectedSessionId === session.session_id),
      );
      const sessionTitle = session.title || "未命名会话";
      const title = document.createElement("span");
      title.className = "session-title";
      title.setAttribute("title", sessionTitle);
      appendPlainText(document, title, sessionTitle);
      button.append(title);
      const deleteButton = document.createElement("button");
      deleteButton.setAttribute("type", "button");
      deleteButton.className = "session-delete-button";
      deleteButton.dataset.deleteSessionId = session.session_id;
      deleteButton.setAttribute("aria-label", `删除会话：${sessionTitle}`);
      deleteButton.setAttribute("title", `删除会话：${sessionTitle}`);
      deleteButton.disabled = anySessionActive() || sessionDeletePending;
      appendPlainText(document, deleteButton, "删除");
      item.append(button, deleteButton);
      elements.sessionList.append(item);
    }
    elements.sessionCount.replaceChildren(
      document.createTextNode(String(state.sessions.length)),
    );
  }

  function renderSkills() {
    elements.skillList.replaceChildren();
    const selected = new Set(state.selectedSkillIds);
    if (!state.skills.some((skill) => skill.skill_id === expandedSkillId)) {
      expandedSkillId = null;
    }
    state.skills.forEach((skill, index) => {
      const skillName = skill.name ?? skill.skill_id;
      const skillDescription = skill.description ?? "";
      const expanded = skill.skill_id === expandedSkillId;
      const option = document.createElement("div");
      option.className = [
        "skill-option",
        selected.has(skill.skill_id) ? "skill-option--selected" : "",
        expanded ? "skill-option--expanded" : "",
      ].filter(Boolean).join(" ");
      const input = document.createElement("input");
      input.setAttribute("type", "checkbox");
      input.dataset.skillId = skill.skill_id;
      input.checked = selected.has(skill.skill_id);
      input.setAttribute("aria-label", `选择 Skill：${skillName}`);

      const detailsId = `skill-details-${index}`;
      const toggle = document.createElement("button");
      toggle.setAttribute("type", "button");
      toggle.className = "skill-option__toggle";
      toggle.dataset.skillExpandId = skill.skill_id;
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-controls", detailsId);
      toggle.setAttribute(
        "aria-label",
        `${expanded ? "收起" : "展开"} Skill：${skillName}`,
      );
      const name = document.createElement("strong");
      name.className = "skill-option__name";
      appendPlainText(document, name, skillName);
      const preview = document.createElement("span");
      preview.className = "skill-option__preview";
      preview.setAttribute("title", skillDescription);
      appendPlainText(document, preview, skillDescription);
      const chevron = document.createElement("span");
      chevron.className = "skill-option__chevron";
      chevron.setAttribute("aria-hidden", "true");
      appendPlainText(document, chevron, "⌄");
      toggle.append(name, preview, chevron);

      const details = document.createElement("div");
      details.setAttribute("id", detailsId);
      details.className = "skill-option__details";
      details.hidden = !expanded;
      const description = document.createElement("p");
      description.className = "skill-option__description";
      appendPlainText(document, description, skillDescription);
      const source = document.createElement("small");
      source.className = "skill-option__source";
      appendPlainText(document, source, `来源：${skill.source ?? "未知"}`);
      details.append(description, source);

      option.append(input, toggle, details);
      elements.skillList.append(option);
    });
    elements.skillSummary.replaceChildren(
      document.createTextNode(`已选择 ${state.selectedSkillIds.length} 个`),
    );
    elements.skillEmptyState.hidden = state.skills.length !== 0;
    renderControls();
  }

  function setSkillImportStatus(message) {
    elements.skillImportStatus.replaceChildren();
    if (message) {
      elements.skillImportStatus.append(document.createTextNode(message));
    }
  }

  function renderConversation() {
    clearCopyResetTimers();
    elements.conversationLog.replaceChildren();
    const detail = state.selectedSession;
    if (!detail) {
      elements.conversationLog.append(elements.emptyState);
      return;
    }
    const projection = runProjectionFacts(detail);
    const renderedTerminalRuns = new Set();

    function appendTerminalRun(run) {
      if (run.termination_reason === "changes_unverified") {
        const changedPaths = Array.isArray(run.final_report?.changed_paths)
          ? run.final_report.changed_paths
            .filter((path) => typeof path === "string" && path)
            .slice(0, 40)
          : [];
        const verificationStatus = run.final_report?.verification?.status;
        appendActivity(
          document,
          elements.conversationLog,
          "changes_unverified",
          {
            changed_paths: changedPaths,
            verification_status:
              typeof verificationStatus === "string" ? verificationStatus : "stale",
            safe_error_code:
              projection.latestSafeErrorCode.get(run.run_id) ?? "verification_not_run",
          },
        );
        renderedTerminalRuns.add(run.run_id);
        return;
      }
      appendActivity(
        document,
        elements.conversationLog,
        run.status === "failed" ? "run_failed" : "run_interrupted",
        {
          termination_reason:
            typeof run.termination_reason === "string"
              ? run.termination_reason
              : null,
        },
      );
      renderedTerminalRuns.add(run.run_id);
    }

    for (const event of detail?.events ?? []) {
      const eventRun = projection.runsById.get(event.run_id);
      if (event.kind === "user_message" && typeof event.data?.content === "string") {
        appendMessage(
          document,
          elements.conversationLog,
          "user",
          event.data.content,
          eventRun?.run_mode,
        );
      } else if (
        event.kind === "assistant_text_committed" &&
        typeof event.data?.content === "string" &&
        projection.runsById.get(event.run_id)?.status === "succeeded" &&
        projection.lastAssistantSequence.get(event.run_id) === event.sequence
      ) {
        appendMessage(
          document,
          elements.conversationLog,
          "assistant",
          event.data.content,
          null,
          copyCodeText,
        );
      }

      if (
        (eventRun?.status === "failed" || eventRun?.status === "interrupted") &&
        projection.lastEventSequence.get(event.run_id) === event.sequence
      ) {
        appendTerminalRun(eventRun);
      }
    }
    for (const run of detail?.runs ?? []) {
      if (
        (run.status === "failed" || run.status === "interrupted") &&
        !renderedTerminalRuns.has(run.run_id)
      ) {
        appendTerminalRun(run);
      }
    }
    const currentActivity = state.activeRunId ? state.activities.at(-1) : null;
    if (currentActivity) {
      appendActivity(
        document,
        elements.conversationLog,
        currentActivity.kind,
        currentActivity.data,
        { active: true },
      );
    } else if (state.activeRunId && state.provisionalText) {
      appendActivity(document, elements.conversationLog, "model_progress", {
        content: state.provisionalText,
      }, { active: true });
    }
  }

  function stopElapsedTimer() {
    if (elapsedTimer !== null) {
      clearIntervalImpl(elapsedTimer);
      elapsedTimer = null;
    }
  }

  function renderElapsed() {
    const run = selectedRun();
    const startedAt = Date.parse(run?.started_at_utc ?? "");
    const finishedAt = Date.parse(run?.finished_at_utc ?? "");
    const end = Number.isFinite(finishedAt) ? finishedAt : now();
    const elapsed = Number.isFinite(startedAt) ? end - startedAt : 0;
    elements.runElapsed.replaceChildren(
      document.createTextNode(formatElapsed(elapsed)),
    );
  }

  function renderSelectedSession() {
    const summary = state.selectedSession?.session ?? null;
    elements.conversationTitle.replaceChildren(
      document.createTextNode(summary?.title || "准备开始"),
    );
    const run = selectedRun();
    renderRunHeader(
      document,
      elements,
      run,
      state.transientStatus,
    );
    renderConversation();
    renderElapsed();
    stopElapsedTimer();
    if (run && ACTIVE_SESSION_STATUSES.has(run.status)) {
      elapsedTimer = setIntervalImpl(renderElapsed, 1000);
    }
    renderControls();
  }

  function stopActiveStream() {
    if (activeStream !== null) {
      activeStream.abortController.abort();
      activeStream = null;
    }
  }

  function synchronizeSelectedSummary() {
    const detail = state.selectedSession?.session;
    if (!detail) return;
    const summary = state.sessions.find(
      (session) => session.session_id === detail.session_id,
    );
    if (summary) {
      summary.status = detail.status;
      summary.last_run_id = detail.last_run_id;
    }
  }

  function projectStreamState() {
    synchronizeSelectedSummary();
    renderSessions();
    renderSelectedSession();
  }

  function startActiveStream(runId) {
    if (activeStream?.runId === runId) return;
    stopActiveStream();
    const abortController = new AbortController();
    const ownedStream = { runId, abortController, promise: null };
    activeStream = ownedStream;
    ownedStream.promise = Promise.resolve(
      streamConsumer({
        api,
        runId,
        state,
        signal: abortController.signal,
        reloadSession: () => api.loadSession(state.selectedSessionId),
        onState: projectStreamState,
      }),
    )
      .catch((error) => {
        if (error?.name !== "AbortError") {
          state.errorCode =
            error instanceof WebClientError ? error.code : "stream_unavailable";
          setConnectionNotice(`连接中断：${state.errorCode}`);
        }
      })
      .finally(() => {
        if (activeStream === ownedStream) activeStream = null;
      });
  }

  async function selectSession(sessionId) {
    if (state.selectedSessionId !== sessionId) stopActiveStream();
    const previousRunId = state.activeRunId;
    const detail = await api.loadSession(sessionId);
    state.selectedSessionId = sessionId;
    state.selectedSession = detail;
    state.selectedSkillIds = [...(detail.skill_ids ?? [])];
    const run = selectedRun();
    state.activeRunId =
      run && ACTIVE_SESSION_STATUSES.has(run.status) ? run.run_id : null;
    if (
      state.activeRunId &&
      BUDGET_PROFILES.has(run?.budget_profile)
    ) {
      state.selectedBudgetProfile = run.budget_profile;
    }
    if (state.activeRunId !== previousRunId) {
      state.lastSequence = 0;
      state.activities = [];
      state.provisionalText = "";
      state.runProgress = null;
      state.transientStatus = null;
    }
    synchronizeSelectedSummary();
    renderSkills();
    renderSelectedSession();
    if (state.activeRunId) startActiveStream(state.activeRunId);
    return detail;
  }

  function track(action) {
    pending = pending.then(action).catch((error) => {
      state.errorCode = error instanceof WebClientError ? error.code : "ui_action_failed";
      setConnectionNotice(`请求失败：${state.errorCode}`);
    });
    return pending;
  }

  function clearSelectedSession() {
    stopActiveStream();
    state.selectedSessionId = null;
    state.selectedSession = null;
    state.activeRunId = null;
    state.selectedSkillIds = [];
    state.lastSequence = 0;
    state.provisionalText = "";
    state.activities = [];
    state.runProgress = null;
    state.transientStatus = null;
    state.phase = "waiting";
  }

  function focusSessionButton(sessionId) {
    const button = Array.from(elements.sessionList.childNodes ?? [])
      .flatMap((item) => Array.from(item.childNodes ?? []))
      .find((item) => item?.dataset?.sessionId === sessionId);
    button?.focus?.();
  }

  function requestSessionDeletion(sessionId) {
    if (sessionDeletePending || anySessionActive()) return;
    const targetIndex = state.sessions.findIndex(
      (session) => session.session_id === sessionId,
    );
    if (targetIndex < 0) return;
    const target = state.sessions[targetIndex];
    const title = target.title || "未命名会话";
    const prompt = `确定删除会话“${title}”？此操作无法撤销。`;
    if (!confirmDelete(prompt)) return;
    const wasSelected = state.selectedSessionId === sessionId;
    sessionDeletePending = true;
    renderControls();
    track(async () => {
      try {
        const result = await api.deleteSession(sessionId);
        state.sessions = state.sessions.filter(
          (session) => session.session_id !== sessionId,
        );
        if (wasSelected) {
          clearSelectedSession();
          const replacement = state.sessions[targetIndex]
            ?? state.sessions[targetIndex - 1]
            ?? null;
          if (replacement) {
            await selectSession(replacement.session_id);
          } else {
            renderSkills();
            renderSelectedSession();
          }
        }
        renderSessions();
        if (wasSelected && state.selectedSessionId) {
          focusSessionButton(state.selectedSessionId);
        } else if (wasSelected) {
          elements.newSessionButton.focus?.();
        }
        if (result.cleanup_pending === true) {
          setConnectionNotice(
            "会话已删除；部分本地日志将在下次启动时继续清理。",
          );
        } else {
          setConnectionNotice(null);
        }
      } finally {
        sessionDeletePending = false;
        renderControls();
      }
    });
  }

  elements.sessionList.addEventListener("click", (event) => {
    let target = event.target;
    while (target && target !== elements.sessionList) {
      const deleteSessionId = target.nodeType === 1
        ? target.dataset?.deleteSessionId
        : null;
      if (deleteSessionId) {
        requestSessionDeletion(deleteSessionId);
        return;
      }
      const sessionId = target.nodeType === 1 ? target.dataset?.sessionId : null;
      if (sessionId) {
        track(() => selectSession(sessionId));
        return;
      }
      target = target.parentNode;
    }
  });

  elements.skillList.addEventListener("click", (event) => {
    let target = event.target;
    while (target && target !== elements.skillList) {
      const skillId = target.nodeType === 1
        ? target.dataset?.skillExpandId
        : null;
      if (skillId) {
        expandedSkillId = expandedSkillId === skillId ? null : skillId;
        renderSkills();
        return;
      }
      target = target.parentNode;
    }
  });

  elements.skillList.addEventListener("change", (event) => {
    const skillId = event.target?.dataset?.skillId;
    if (!skillId || anySessionActive()) {
      renderSkills();
      return;
    }
    const checked = Boolean(event.target.checked);
    const selection = new Set(state.selectedSkillIds);
    if (checked) selection.add(skillId);
    else selection.delete(skillId);
    state.selectedSkillIds = state.skills
      .map((skill) => skill.skill_id)
      .filter((id) => selection.has(id));
    renderSkills();
    if (state.selectedSessionId) {
      track(async () => {
        const result = await api.saveSkillSelection(
          state.selectedSessionId,
          state.selectedSkillIds,
        );
        state.selectedSkillIds = [...(result.skill_ids ?? [])];
        renderSkills();
      });
    }
  });

  elements.skillImportButton.addEventListener("click", () => {
    if (!anySessionActive() && !skillImportPending) {
      elements.skillFileInput.click();
    }
  });

  elements.skillFileInput.addEventListener("change", () => {
    const files = Array.from(elements.skillFileInput.files ?? []);
    if (anySessionActive() || skillImportPending) {
      elements.skillFileInput.value = "";
      renderControls();
      return;
    }
    if (files.length !== 1) {
      elements.skillFileInput.value = "";
      setSkillImportStatus("请选择一个 Skill ZIP 文件");
      return;
    }
    const archive = files[0];
    const selectionBeforeImport = [...state.selectedSkillIds];
    skillImportPending = true;
    setSkillImportStatus("正在导入…");
    renderControls();
    track(async () => {
      try {
        const imported = await api.importSkillArchive(archive);
        const catalog = await api.listSkills();
        state.skills = [...(catalog.skills ?? [])];
        state.skillDiagnostics = [...(catalog.diagnostics ?? [])];
        const importedSkill = state.skills.find(
          (skill) => skill.skill_id === imported.skill_id,
        );
        if (!importedSkill) {
          throw new WebClientError("skill_install_failed");
        }
        const selected = new Set(state.selectedSkillIds);
        selected.add(importedSkill.skill_id);
        state.selectedSkillIds = state.skills
          .map((skill) => skill.skill_id)
          .filter((skillId) => selected.has(skillId));
        if (
          state.selectedSessionId
          && state.selectedSession?.session?.status === "idle"
        ) {
          try {
            const result = await api.saveSkillSelection(
              state.selectedSessionId,
              state.selectedSkillIds,
            );
            state.selectedSkillIds = [...(result.skill_ids ?? [])];
          } catch (error) {
            state.selectedSkillIds = state.skills
              .map((skill) => skill.skill_id)
              .filter((skillId) => selectionBeforeImport.includes(skillId));
            const code = error instanceof WebClientError
              ? error.code
              : "skill_selection_failed";
            setSkillImportStatus(
              `已导入 ${importedSkill.name ?? importedSkill.skill_id}；自动选择失败：${code}`,
            );
            return;
          }
        }
        setSkillImportStatus(`已导入 ${importedSkill.name ?? importedSkill.skill_id}`);
      } catch (error) {
        const code = error instanceof WebClientError
          ? error.code
          : "skill_import_failed";
        setSkillImportStatus(`导入失败：${code}`);
      } finally {
        elements.skillFileInput.value = "";
        skillImportPending = false;
        renderSkills();
      }
    });
  });

  elements.runModeControl.addEventListener("click", (event) => {
    if (anySessionActive()) {
      renderControls();
      return;
    }
    let target = event.target;
    while (target && target !== elements.runModeControl) {
      const runMode = target.nodeType === 1 ? target.dataset?.runMode : null;
      if (RUN_MODES.has(runMode)) {
        state.selectedRunMode = runMode;
        renderControls();
        return;
      }
      target = target.parentNode;
    }
  });

  elements.budgetProfileControl.addEventListener("click", (event) => {
    if (anySessionActive()) {
      renderControls();
      return;
    }
    let target = event.target;
    while (target && target !== elements.budgetProfileControl) {
      const budgetProfile = target.nodeType === 1
        ? target.dataset?.budgetProfile
        : null;
      if (BUDGET_PROFILES.has(budgetProfile)) {
        state.selectedBudgetProfile = budgetProfile;
        renderControls();
        return;
      }
      target = target.parentNode;
    }
  });

  elements.modelSelect.addEventListener("change", () => {
    if (anySessionActive() || modelRefreshPending) {
      renderModelControl();
      return;
    }
    const selected = elements.modelSelect.value;
    if (state.modelCatalog.modelIds.includes(selected)) {
      state.selectedModelId = selected;
    }
    renderModelControl();
  });

  elements.refreshModelsButton.addEventListener("click", () => {
    if (anySessionActive() || modelRefreshPending) return;
    modelRefreshPending = true;
    renderControls();
    track(async () => {
      try {
        const catalog = await api.listModels(true);
        applyModelCatalog(catalog);
      } catch {
        state.modelCatalog = {
          ...state.modelCatalog,
          status: state.modelCatalog.modelIds.length ? "stale" : "unavailable",
          errorCode: "model_catalog_unavailable",
        };
      } finally {
        modelRefreshPending = false;
        renderControls();
      }
    });
  });

  function submitComposer() {
    const message = elements.messageInput.value.trim();
    if (!message || anySessionActive()) return;
    const runMode = state.selectedRunMode;
    const budgetProfile = state.selectedBudgetProfile;
    const modelId = state.selectedModelId;
    track(async () => {
      let handle;
      if (state.selectedSessionId) {
        handle = await api.submitFollowUp(
          state.selectedSessionId,
          message,
          runMode,
          budgetProfile,
          modelId,
        );
        await selectSession(handle.session_id);
      } else {
        handle = await api.createSession(
          message,
          state.selectedSkillIds,
          runMode,
          budgetProfile,
          modelId,
        );
        await selectSession(handle.session_id);
        if (!state.sessions.some((session) => session.session_id === handle.session_id)) {
          state.sessions.unshift(state.selectedSession.session);
        }
      }
      state.selectedSessionId = handle.session_id;
      state.activeRunId = handle.run_id;
      elements.messageInput.value = "";
      renderSessions();
      renderSelectedSession();
      startActiveStream(handle.run_id);
    });
  }

  elements.messageComposer.addEventListener("submit", (event) => {
    event.preventDefault();
    submitComposer();
  });

  elements.messageInput.addEventListener("keydown", (event) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.isComposing ||
      event.keyCode === 229
    ) {
      return;
    }
    event.preventDefault();
    submitComposer();
  });

  elements.cancelButton.addEventListener("click", () => {
    if (!state.activeRunId) return;
    track(async () => {
      const result = await api.cancelRun(state.activeRunId);
      const notice = document.createElement("div");
      notice.className = "activity-card";
      appendPlainText(document, notice, `取消请求：${result.result}`);
      elements.conversationLog.append(notice);
    });
  });

  elements.newSessionButton.addEventListener("click", () => {
    clearSelectedSession();
    renderSkills();
    renderSelectedSession();
  });

  elements.skillToggle.addEventListener("click", () => {
    const expanded = elements.skillToggle.getAttribute("aria-expanded") === "true";
    elements.skillToggle.setAttribute("aria-expanded", String(!expanded));
    elements.skillPanel.hidden = expanded;
  });

  document.addEventListener("visibilitychange", () => {
    if (
      document.visibilityState === "visible" &&
      state.activeRunId &&
      activeStream === null
    ) {
      startActiveStream(state.activeRunId);
    }
  });

  return Object.freeze({
    async initialize() {
      const modelCatalogRequest = typeof api.listModels === "function"
        ? api.listModels(false).catch(() => unavailableModelCatalog())
        : Promise.resolve(unavailableModelCatalog());
      const [sessions, skills, modelCatalog] = await Promise.all([
        api.listSessions(),
        api.listSkills(),
        modelCatalogRequest,
      ]);
      state.sessions = [...(sessions.sessions ?? [])];
      state.skills = [...(skills.skills ?? [])];
      state.skillDiagnostics = [...(skills.diagnostics ?? [])];
      applyModelCatalog(modelCatalog, { preserveSelection: false });
      const active = state.sessions.find((session) =>
        ACTIVE_SESSION_STATUSES.has(session.status),
      );
      state.activeRunId = active?.last_run_id ?? null;
      state.connection = "connected";
      setConnectionNotice(null);
      renderSessions();
      renderSkills();
      renderSelectedSession();
    },
    selectSession,
    getState: () => state,
    whenIdle: () => pending,
    destroy() {
      destroyed = true;
      stopActiveStream();
      stopElapsedTimer();
      clearCopyResetTimers();
    },
  });
}


export function collectGuiElements(document) {
  const ids = {
    sessionList: "session-list",
    sessionCount: "session-count",
    skillList: "skill-list",
    skillToggle: "skill-toggle",
    skillPanel: "skill-panel",
    skillSummary: "skill-summary",
    skillImportButton: "skill-import-button",
    skillFileInput: "skill-file-input",
    skillEmptyState: "skill-empty-state",
    skillImportStatus: "skill-import-status",
    conversationTitle: "conversation-title",
    runStatus: "run-status",
    workspacePath: "workspace-path",
    runElapsed: "run-elapsed",
    cancelButton: "cancel-run-button",
    conversationLog: "conversation-log",
    messageComposer: "message-composer",
    messageInput: "message-input",
    sendButton: "send-message-button",
    connectionStatus: "connection-status",
    newSessionButton: "new-session-button",
    runModeControl: "run-mode-control",
    runModeModifyButton: "run-mode-modify",
    runModeReadOnlyButton: "run-mode-read-only",
    budgetProfileControl: "budget-profile-control",
    budgetProfileStandardButton: "budget-profile-standard",
    budgetProfileDeepButton: "budget-profile-deep",
    modelControl: "model-control",
    modelSelect: "model-select",
    refreshModelsButton: "refresh-models-button",
    modelCatalogStatus: "model-catalog-status",
    emptyState: "empty-state",
  };
  const elements = Object.fromEntries(
    Object.entries(ids).map(([name, id]) => [name, document.getElementById(id)]),
  );
  if (Object.values(elements).some((element) => element === null)) {
    throw new Error("GUI structure unavailable");
  }
  return elements;
}


export async function startBrowserApplication({
  document,
  window,
  fetchImpl = globalThis.fetch,
}) {
  const accessToken = consumeBootstrapToken(document);
  const api = createApiClient({
    accessToken,
    fetchImpl,
    baseUrl: window.location.origin,
  });
  const controller = createUiController({
    document,
    elements: collectGuiElements(document),
    api,
    confirmDelete: (message) => window.confirm(message),
  });
  await controller.initialize();

  const sidebar = document.getElementById("session-sidebar");
  const scrim = document.getElementById("sidebar-scrim");
  const openButton = document.getElementById("sidebar-toggle");
  const closeButton = document.getElementById("sidebar-close");
  const setSidebarOpen = (open) => {
    sidebar?.classList.toggle("sidebar--open", open);
    scrim?.classList.toggle("sidebar-scrim--visible", open);
  };
  openButton?.addEventListener("click", () => setSidebarOpen(true));
  closeButton?.addEventListener("click", () => setSidebarOpen(false));
  scrim?.addEventListener("click", () => setSidebarOpen(false));

  return controller;
}


if (typeof window !== "undefined" && typeof document !== "undefined") {
  void startBrowserApplication({ document, window }).catch(() => {
    const connection = document.getElementById("connection-status");
    connection?.replaceChildren(document.createTextNode("无法连接本地服务"));
    if (connection) {
      connection.dataset.visible = "true";
      connection.setAttribute("aria-hidden", "false");
    }
  });
}
