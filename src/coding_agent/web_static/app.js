const STATUS_LABELS = Object.freeze({
  idle: "空闲",
  queued: "排队中",
  running: "运行中",
  cancelling: "正在取消",
  succeeded: "成功",
  failed: "失败",
  interrupted: "已中断",
});

const PHASE_LABELS = Object.freeze({
  waiting: "等待任务",
  model: "模型处理中",
  tool: "执行工具",
  verification: "验证修改",
  finished: "运行结束",
});

const ACTIVITY_LABELS = Object.freeze({
  model_progress: "Agent 正在处理",
  tool_started: "工具开始",
  tool_finished: "工具完成",
  verification_started: "验证开始",
  verification_finished: "验证完成",
  controller_error: "控制器错误",
  run_failed: "运行失败",
  run_interrupted: "运行已中断",
});


export function appendPlainText(document, parent, text) {
  parent.append(document.createTextNode(String(text)));
}


function appendFencedText(document, parent, text) {
  let cursor = 0;
  while (cursor < text.length) {
    const opening = text.indexOf("```", cursor);
    if (opening < 0) {
      appendPlainText(document, parent, text.slice(cursor));
      return;
    }
    const codeStartLine = text.indexOf("\n", opening + 3);
    if (codeStartLine < 0) {
      appendPlainText(document, parent, text.slice(cursor));
      return;
    }
    const closing = text.indexOf("```", codeStartLine + 1);
    if (closing < 0) {
      appendPlainText(document, parent, text.slice(cursor));
      return;
    }
    appendPlainText(document, parent, text.slice(cursor, opening));
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    appendPlainText(
      document,
      code,
      text.slice(codeStartLine + 1, closing),
    );
    pre.append(code);
    parent.append(pre);
    cursor = closing + 3;
    if (text[cursor] === "\n") cursor += 1;
  }
}


export function appendMessage(document, container, role, text) {
  const message = document.createElement("article");
  message.className = `message message--${role === "user" ? "user" : "assistant"}`;
  const label = document.createElement("div");
  label.className = "message__label";
  appendPlainText(document, label, role === "user" ? "你" : "Agent");
  const body = document.createElement("div");
  body.className = "message__body";
  appendFencedText(document, body, String(text));
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
    return [data.tool_name, data.status, `${data.duration_ms} ms`];
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
  return [];
}


export function appendActivity(document, container, kind, data) {
  const card = document.createElement("div");
  card.className = "activity-card";
  const label = ACTIVITY_LABELS[kind] ?? String(kind);
  const details = safeActivityDetails(kind, data ?? {})
    .filter((value) => value !== undefined && value !== null && value !== "")
    .map(String);
  appendPlainText(
    document,
    card,
    details.length ? `${label} · ${details.join(" · ")}` : label,
  );
  container.append(card);
  return card;
}


export function renderRunHeader(document, elements, run, phase) {
  const status = run?.status;
  const label = STATUS_LABELS[status] ?? "状态未知";
  elements.runStatus.replaceChildren(document.createTextNode(label));
  elements.runStatus.className = `status-pill status-pill--${
    status === "succeeded"
      ? "success"
      : status === "failed" || status === "interrupted"
        ? "failure"
        : status === "running" || status === "cancelling" || status === "queued"
          ? "running"
          : "idle"
  }`;
  elements.runPhase.replaceChildren(
    document.createTextNode(PHASE_LABELS[phase] ?? "状态同步中"),
  );
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
    activeRunId: null,
    lastSequence: 0,
    provisionalText: "",
    activities: [],
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

  async function request(path, { method = "GET", body } = {}) {
    const headers = new Headers({
      Authorization: `Bearer ${accessToken}`,
    });
    const init = { method, headers };
    if (body !== undefined) {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(body);
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
    loadSession: (sessionId) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}`),
    listSkills: () => request("/api/v1/skills"),
    createSession: (message, skillIds) =>
      request("/api/v1/sessions", {
        method: "POST",
        body: { message, skill_ids: skillIds },
      }),
    submitFollowUp: (sessionId, message) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: "POST",
        body: { message },
      }),
    saveSkillSelection: (sessionId, skillIds) =>
      request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/skills`, {
        method: "PUT",
        body: { skill_ids: skillIds },
      }),
    cancelRun: (runId) =>
      request(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
        body: {},
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


export function createUiController({
  document,
  elements,
  api,
  now = () => Date.now(),
  setIntervalImpl = globalThis.setInterval,
  clearIntervalImpl = globalThis.clearInterval,
  streamConsumer = consumeRunStream,
}) {
  const state = createInitialUiState();
  let pending = Promise.resolve();
  let elapsedTimer = null;
  let activeStream = null;

  function anySessionActive() {
    return state.sessions.some((session) =>
      ACTIVE_SESSION_STATUSES.has(session.status),
    );
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
    for (const event of detail?.events ?? []) {
      if (typeof event.run_id !== "string") continue;
      lastEventSequence.set(event.run_id, event.sequence);
      if (event.kind === "assistant_text_committed") {
        lastAssistantSequence.set(event.run_id, event.sequence);
      }
    }
    return { runsById, lastAssistantSequence, lastEventSequence };
  }

  function renderControls() {
    const mutationLocked = anySessionActive();
    elements.sendButton.disabled = mutationLocked;
    for (const input of findInputs(elements.skillList)) {
      input.disabled = mutationLocked;
    }
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

  function renderSessions() {
    elements.sessionList.replaceChildren();
    for (const session of state.sessions) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.setAttribute("type", "button");
      button.className = "session-button";
      button.dataset.sessionId = session.session_id;
      appendPlainText(document, button, session.title || "未命名会话");
      const status = document.createElement("span");
      status.className = "session-button__status";
      appendPlainText(document, status, STATUS_LABELS[session.status] ?? "状态未知");
      button.append(status);
      item.append(button);
      elements.sessionList.append(item);
    }
    elements.sessionCount.replaceChildren(
      document.createTextNode(String(state.sessions.length)),
    );
  }

  function renderSkills() {
    elements.skillList.replaceChildren();
    const selected = new Set(state.selectedSkillIds);
    for (const skill of state.skills) {
      const label = document.createElement("label");
      label.className = "skill-option";
      const input = document.createElement("input");
      input.setAttribute("type", "checkbox");
      input.dataset.skillId = skill.skill_id;
      input.checked = selected.has(skill.skill_id);
      const copy = document.createElement("span");
      copy.className = "skill-option__copy";
      const name = document.createElement("strong");
      appendPlainText(document, name, skill.name ?? skill.skill_id);
      const description = document.createElement("span");
      appendPlainText(document, description, skill.description ?? "");
      const source = document.createElement("small");
      appendPlainText(document, source, skill.source ?? "");
      copy.append(name, description, source);
      label.append(input, copy);
      elements.skillList.append(label);
    }
    elements.skillSummary.replaceChildren(
      document.createTextNode(`已选择 ${state.selectedSkillIds.length} 个`),
    );
    renderControls();
  }

  function renderConversation() {
    elements.conversationLog.replaceChildren();
    const detail = state.selectedSession;
    const projection = runProjectionFacts(detail);
    const renderedTerminalRuns = new Set();

    function appendTerminalRun(run) {
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
      if (event.kind === "user_message" && typeof event.data?.content === "string") {
        appendMessage(document, elements.conversationLog, "user", event.data.content);
      } else if (
        event.kind === "assistant_text_committed" &&
        typeof event.data?.content === "string" &&
        projection.runsById.get(event.run_id)?.status === "succeeded" &&
        projection.lastAssistantSequence.get(event.run_id) === event.sequence
      ) {
        appendMessage(document, elements.conversationLog, "assistant", event.data.content);
      }

      const eventRun = projection.runsById.get(event.run_id);
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
      );
    } else if (state.activeRunId && state.provisionalText) {
      appendActivity(document, elements.conversationLog, "model_progress", {
        content: state.provisionalText,
      });
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
    renderRunHeader(document, elements, run, state.phase);
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
          elements.connectionStatus.replaceChildren(
            document.createTextNode(`连接中断：${state.errorCode}`),
          );
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
    if (state.activeRunId !== previousRunId) {
      state.lastSequence = 0;
      state.activities = [];
      state.provisionalText = "";
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
      elements.connectionStatus.replaceChildren(
        document.createTextNode(`请求失败：${state.errorCode}`),
      );
    });
    return pending;
  }

  elements.sessionList.addEventListener("click", (event) => {
    let target = event.target;
    while (target && target !== elements.sessionList) {
      const sessionId = target.nodeType === 1 ? target.dataset?.sessionId : null;
      if (sessionId) {
        track(() => selectSession(sessionId));
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

  elements.messageComposer.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = elements.messageInput.value.trim();
    if (!message || anySessionActive()) return;
    track(async () => {
      let handle;
      if (state.selectedSessionId) {
        handle = await api.submitFollowUp(state.selectedSessionId, message);
        await selectSession(handle.session_id);
      } else {
        handle = await api.createSession(message, state.selectedSkillIds);
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
    stopActiveStream();
    state.selectedSessionId = null;
    state.selectedSession = null;
    state.activeRunId = null;
    state.selectedSkillIds = [];
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
      const [sessions, skills] = await Promise.all([
        api.listSessions(),
        api.listSkills(),
      ]);
      state.sessions = [...(sessions.sessions ?? [])];
      state.skills = [...(skills.skills ?? [])];
      state.skillDiagnostics = [...(skills.diagnostics ?? [])];
      const active = state.sessions.find((session) =>
        ACTIVE_SESSION_STATUSES.has(session.status),
      );
      state.activeRunId = active?.last_run_id ?? null;
      state.connection = "connected";
      elements.connectionStatus.replaceChildren(
        document.createTextNode("已连接本地服务"),
      );
      renderSessions();
      renderSkills();
      renderSelectedSession();
    },
    selectSession,
    getState: () => state,
    whenIdle: () => pending,
    destroy() {
      stopActiveStream();
      stopElapsedTimer();
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
    conversationTitle: "conversation-title",
    runStatus: "run-status",
    runPhase: "run-phase",
    runElapsed: "run-elapsed",
    cancelButton: "cancel-run-button",
    conversationLog: "conversation-log",
    messageComposer: "message-composer",
    messageInput: "message-input",
    sendButton: "send-message-button",
    connectionStatus: "connection-status",
    newSessionButton: "new-session-button",
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
  });
}
