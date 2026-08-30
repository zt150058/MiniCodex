import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { TestDocument, findElements } from "./dom_harness.mjs";


const appSource = await readFile(
  new URL("../../src/coding_agent/web_static/app.js", import.meta.url),
  "utf8",
);
const gui = await import(
  `data:text/javascript;base64,${Buffer.from(appSource).toString("base64")}`
);


test("model markup remains text and cannot create an element", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(
    document,
    container,
    "assistant",
    '<img src=x onerror="secret()">',
  );

  assert.equal(container.textContent.includes('<img src=x onerror="secret()">'), true);
  assert.deepEqual(findElements(container, "img"), []);
});


test("closed fenced code creates explicit pre and code nodes", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(
    document,
    container,
    "assistant",
    "before\n```py\nprint(1)\n```\nafter",
  );

  assert.equal(findElements(container, "pre").length, 1);
  assert.equal(findElements(container, "code")[0].textContent, "print(1)\n");
  assert.equal(container.textContent, "Agentbefore\nprint(1)\nafter");
});


test("an unclosed fence remains plain text", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(document, container, "assistant", "before\n```py\nsecret");

  assert.equal(findElements(container, "pre").length, 0);
  assert.equal(container.textContent, "Agentbefore\n```py\nsecret");
});


test("unknown activity never serializes unrecognized data", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendActivity(document, container, "future_kind", {
    private: "must-not-render",
  });

  assert.equal(container.textContent.includes("future_kind"), true);
  assert.equal(container.textContent.includes("must-not-render"), false);
});


test("known activity renders only allowlisted safe fields", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendActivity(document, container, "tool_finished", {
    tool_name: "pytest",
    status: "ok",
    duration_ms: 27,
    private: "must-not-render",
  });

  assert.equal(container.textContent.includes("pytest"), true);
  assert.equal(container.textContent.includes("ok"), true);
  assert.equal(container.textContent.includes("27 ms"), true);
  assert.equal(container.textContent.includes("must-not-render"), false);
});


test("bootstrap token is consumed once and its node is removed", () => {
  const document = new TestDocument();
  const meta = document.createElement("meta");
  meta.setAttribute("id", "coding-agent-bootstrap");
  meta.setAttribute("content", "fixed-test-token");
  document.body.append(meta);

  assert.equal(gui.consumeBootstrapToken(document), "fixed-test-token");
  assert.equal(document.getElementById("coding-agent-bootstrap"), null);
  assert.throws(
    () => gui.consumeBootstrapToken(document),
    /bootstrap token unavailable/,
  );
});


test("run header uses only server status and never invents success", () => {
  const document = new TestDocument();
  const elements = {
    runStatus: document.createElement("span"),
    runPhase: document.createElement("span"),
    cancelButton: document.createElement("button"),
  };

  gui.renderRunHeader(document, elements, { status: "running" }, "tool");
  assert.equal(elements.runStatus.textContent, "运行中");
  assert.equal(elements.runPhase.textContent, "执行工具");
  assert.equal(elements.cancelButton.disabled, false);

  gui.renderRunHeader(document, elements, { status: "future_status" }, "future");
  assert.equal(elements.runStatus.textContent, "状态未知");
  assert.equal(elements.runStatus.textContent.includes("成功"), false);
  assert.equal(elements.cancelButton.disabled, true);
});


test("list sessions authenticates without placing token in the URL", async () => {
  const calls = [];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json({ sessions: [] });
    },
  });

  assert.deepEqual(await api.listSessions(), { sessions: [] });
  assert.equal(calls.length, 1);
  assert.equal(calls[0] instanceof Request, true);
  assert.equal(calls[0].url, "http://local.invalid/api/v1/sessions?limit=50");
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[0].headers.get("authorization"), "Bearer fixed-test-token");
  assert.equal(calls[0].url.includes("fixed-test-token"), false);
});


test("mutation API methods send exact paths and JSON bodies once", async () => {
  const calls = [];
  const responses = [
    { session_id: "s1", run_id: "r1" },
    { session_id: "s1", run_id: "r2" },
    { skill_ids: ["workspace:review"] },
    { result: "requested" },
  ];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json(responses[calls.length - 1]);
    },
  });

  assert.deepEqual(
    await api.createSession("repair tests", ["workspace:review"]),
    responses[0],
  );
  assert.deepEqual(await api.submitFollowUp("s1", "continue"), responses[1]);
  assert.deepEqual(
    await api.saveSkillSelection("s1", ["workspace:review"]),
    responses[2],
  );
  assert.deepEqual(await api.cancelRun("r2"), responses[3]);

  assert.deepEqual(
    calls.map((request) => [request.method, request.url]),
    [
      ["POST", "http://local.invalid/api/v1/sessions"],
      ["POST", "http://local.invalid/api/v1/sessions/s1/messages"],
      ["PUT", "http://local.invalid/api/v1/sessions/s1/skills"],
      ["POST", "http://local.invalid/api/v1/runs/r2/cancel"],
    ],
  );
  assert.deepEqual(
    await Promise.all(calls.map((request) => request.clone().json())),
    [
      { message: "repair tests", skill_ids: ["workspace:review"] },
      { message: "continue" },
      { skill_ids: ["workspace:review"] },
      {},
    ],
  );
  assert.equal(
    calls.every(
      (request) =>
        request.headers.get("authorization") === "Bearer fixed-test-token" &&
        request.headers.get("content-type") === "application/json",
    ),
    true,
  );
});


test("session and skill reads use exact authenticated routes", async () => {
  const calls = [];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json({});
    },
  });

  await api.loadSession("session/value");
  await api.listSkills();

  assert.deepEqual(
    calls.map((request) => request.url),
    [
      "http://local.invalid/api/v1/sessions/session%2Fvalue",
      "http://local.invalid/api/v1/skills",
    ],
  );
  assert.equal(
    calls.every(
      (request) => request.headers.get("authorization") === "Bearer fixed-test-token",
    ),
    true,
  );
});


test("failed mutations are not retried and expose only a stable code", async () => {
  let attempts = 0;
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async () => {
      attempts += 1;
      return Response.json(
        {
          error: {
            code: "internal_server_error",
            detail: "private provider response",
          },
        },
        { status: 500 },
      );
    },
  });

  await assert.rejects(
    () => api.createSession("repair", []),
    (error) => {
      assert.equal(error instanceof gui.WebClientError, true);
      assert.equal(error.code, "internal_server_error");
      assert.equal(error.message, "internal_server_error");
      assert.equal(String(error).includes("private provider response"), false);
      return true;
    },
  );
  assert.equal(attempts, 1);
});


test("initial UI state is safe exact and independent", () => {
  const first = gui.createInitialUiState();
  const second = gui.createInitialUiState();

  assert.deepEqual(first, {
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
  });
  first.sessions.push({ session_id: "changed" });
  first.selectedSkillIds.push("changed");
  assert.deepEqual(second.sessions, []);
  assert.deepEqual(second.selectedSkillIds, []);
  for (const forbidden of [
    "token",
    "credential",
    "apiKey",
    "authorization",
    "provider",
    "continuation",
    "reasoning",
    "instructions",
  ]) {
    assert.equal(Object.hasOwn(first, forbidden), false);
  }
});


function controllerFixture() {
  const document = new TestDocument();
  const elements = {};
  for (const [name, [tag, id]] of Object.entries({
    sessionList: ["ol", "session-list"],
    sessionCount: ["span", "session-count"],
    skillList: ["div", "skill-list"],
    skillToggle: ["button", "skill-toggle"],
    skillPanel: ["div", "skill-panel"],
    skillSummary: ["span", "skill-summary"],
    conversationTitle: ["h1", "conversation-title"],
    runStatus: ["span", "run-status"],
    runPhase: ["span", "run-phase"],
    runElapsed: ["span", "run-elapsed"],
    cancelButton: ["button", "cancel-run-button"],
    conversationLog: ["section", "conversation-log"],
    messageComposer: ["form", "message-composer"],
    messageInput: ["textarea", "message-input"],
    sendButton: ["button", "send-message-button"],
    connectionStatus: ["div", "connection-status"],
    newSessionButton: ["button", "new-session-button"],
  })) {
    elements[name] = document.createElement(tag);
    elements[name].setAttribute("id", id);
    document.body.append(elements[name]);
  }
  elements.skillToggle.setAttribute("aria-expanded", "false");
  elements.skillToggle.setAttribute("aria-controls", "skill-panel");
  elements.skillPanel.hidden = true;
  return { document, elements };
}


function submitEvent() {
  return {
    type: "submit",
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
  };
}


test("controller creates a session with preselected ordered skills", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({
      skills: [
        { skill_id: "workspace:review", name: "Review", description: "Review changes", source: "workspace" },
        { skill_id: "user:tests", name: "Tests", description: "Run focused tests", source: "user" },
      ],
      diagnostics: [],
      usable: true,
    }),
    createSession: async (message, skillIds) => {
      calls.push(["createSession", message, skillIds]);
      return { session_id: "s1", run_id: "r1" };
    },
    loadSession: async () => ({
      session: { session_id: "s1", title: "Repair", status: "running", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "running", started_at_utc: "2026-08-30T00:00:00Z" }],
      events: [{ kind: "user_message", data: { content: "Repair" }, sequence: 1 }],
      skill_ids: ["workspace:review", "user:tests"],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  const skillInputs = findElements(elements.skillList, "input");
  for (const input of skillInputs) {
    input.checked = true;
    elements.skillList.dispatchEvent({ type: "change", target: input });
  }
  elements.messageInput.value = "Repair";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.deepEqual(calls, [["createSession", "Repair", ["workspace:review", "user:tests"]]]);
  assert.equal(controller.getState().selectedSessionId, "s1");
  assert.equal(controller.getState().activeRunId, "r1");
  assert.equal(elements.messageInput.value, "");
  controller.destroy();
});


test("controller submits follow-up for a selected idle session", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Existing", status: "idle", last_run_id: "r0" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => ({
      session: { session_id: sessionId, title: "Existing", status: "idle", last_run_id: "r0" },
      runs: [{ run_id: "r0", status: "succeeded", started_at_utc: null }],
      events: [],
      skill_ids: [],
    }),
    submitFollowUp: async (sessionId, message) => {
      calls.push(["submitFollowUp", sessionId, message]);
      return { session_id: sessionId, run_id: "r1" };
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];
  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();

  elements.messageInput.value = "Continue";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.deepEqual(calls, [["submitFollowUp", "s1", "Continue"]]);
  assert.equal(controller.getState().activeRunId, "r1");
  controller.destroy();
});


test("an active session locks mutations but keeps history navigation enabled", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [
        { session_id: "running", title: "Running", status: "running", last_run_id: "r1" },
        { session_id: "idle", title: "History", status: "idle", last_run_id: "r0" },
      ],
    }),
    listSkills: async () => ({
      skills: [{ skill_id: "workspace:review", name: "Review", description: "Review", source: "workspace" }],
      diagnostics: [],
      usable: true,
    }),
    loadSession: async (sessionId) => ({
      session: { session_id: sessionId, title: "History", status: "idle", last_run_id: "r0" },
      runs: [], events: [], skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  assert.equal(elements.sendButton.disabled, true);
  assert.equal(findElements(elements.skillList, "input")[0].disabled, true);
  const buttons = findElements(elements.sessionList, "button");
  assert.equal(buttons.every((button) => !button.disabled), true);
  elements.sessionList.dispatchEvent({ type: "click", target: buttons[1] });
  await controller.whenIdle();
  assert.equal(controller.getState().selectedSessionId, "idle");
  assert.equal(elements.sendButton.disabled, true);
  controller.destroy();
});


test("controller renders safe skill metadata and exact cancellation result", async () => {
  const { document, elements } = controllerFixture();
  const cancelCalls = [];
  let intervalCallback = null;
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Running", status: "running", last_run_id: "r1" }],
    }),
    listSkills: async () => ({
      skills: [{
        skill_id: "workspace:review", name: "Review", description: "Safe description", source: "workspace",
        instructions: "private instructions",
      }],
      diagnostics: [{ code: "invalid_skill_metadata", source: "workspace", entry_name: "broken", private: "secret" }],
      usable: true,
    }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Running", status: "running", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "running", started_at_utc: "2026-08-30T00:00:00Z" }],
      events: [], skill_ids: ["workspace:review"],
    }),
    cancelRun: async (runId) => {
      cancelCalls.push(runId);
      return { result: "requested" };
    },
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    now: () => Date.parse("2026-08-30T00:00:10Z"),
    setIntervalImpl: (callback) => { intervalCallback = callback; return 1; },
    clearIntervalImpl: () => {},
  });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];
  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();
  intervalCallback();

  assert.equal(elements.skillList.textContent.includes("Review"), true);
  assert.equal(elements.skillList.textContent.includes("Safe description"), true);
  assert.equal(elements.skillList.textContent.includes("workspace"), true);
  assert.equal(elements.skillList.textContent.includes("invalid_skill_metadata"), false);
  assert.equal(elements.skillList.textContent.includes("private instructions"), false);
  assert.equal(elements.skillList.textContent.includes("secret"), false);
  assert.equal(elements.runElapsed.textContent, "00:10");

  elements.cancelButton.dispatchEvent({ type: "click" });
  await controller.whenIdle();
  assert.deepEqual(cancelCalls, ["r1"]);
  assert.equal(elements.conversationLog.textContent.includes("requested"), true);
  assert.equal(elements.conversationLog.textContent.includes("成功"), false);
  controller.destroy();
});


test("skill panel starts compact and toggles without rendering diagnostics", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({
      skills: [{
        skill_id: "workspace:review",
        name: "Review",
        description: "Review changes",
        source: "workspace",
      }],
      diagnostics: [{
        code: "invalid_skill_metadata",
        source: "workspace",
        entry_name: "broken-skill",
      }],
      usable: true,
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  assert.equal(elements.skillPanel.hidden, true);
  assert.equal(elements.skillToggle.getAttribute("aria-expanded"), "false");
  assert.equal(elements.skillSummary.textContent, "已选择 0 个");
  assert.equal(elements.skillList.textContent.includes("invalid_skill_metadata"), false);
  assert.equal(elements.skillList.textContent.includes("broken-skill"), false);

  elements.skillToggle.dispatchEvent({ type: "click" });
  assert.equal(elements.skillPanel.hidden, false);
  assert.equal(elements.skillToggle.getAttribute("aria-expanded"), "true");
  elements.skillToggle.dispatchEvent({ type: "click" });
  assert.equal(elements.skillPanel.hidden, true);
  assert.equal(elements.skillToggle.getAttribute("aria-expanded"), "false");
  controller.destroy();
});


function updateFrame(id, kind, data) {
  return `id: ${id}\nevent: ${kind}\ndata: ${JSON.stringify({
    schema_version: 1,
    session_id: "s1",
    run_id: "r1",
    sequence: id,
    kind,
    created_at_utc: "2026-08-30T00:00:00.000000Z",
    data,
  })}\n\n`;
}


function chunkedResponse(chunks, init = {}) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" }, ...init },
  );
}


test("SSE parser preserves partial frames and rejects invalid sequence IDs", () => {
  const firstFrame = updateFrame(1, "run_started", { status: "running" });
  const secondFrame = updateFrame(2, "assistant_text_delta", { content: "你好" });
  const split = firstFrame.length - 3;
  const first = gui.parseSseFrames(firstFrame.slice(0, split), 0);
  assert.deepEqual(first.frames, []);
  assert.equal(first.remainder, firstFrame.slice(0, split));

  const second = gui.parseSseFrames(
    first.remainder + firstFrame.slice(split) + secondFrame,
    first.lastSequence,
  );
  assert.deepEqual(second.frames.map((frame) => [frame.id, frame.event]), [
    [1, "run_started"],
    [2, "assistant_text_delta"],
  ]);
  assert.equal(second.frames[1].data.data.content, "你好");
  assert.equal(second.remainder, "");
  assert.equal(second.lastSequence, 2);

  for (const text of [
    updateFrame(2, "run_started", { status: "running" }),
    "id: zero\nevent: run_started\ndata: {}\n\n",
    "event: run_started\ndata: {}\n\n",
  ]) {
    assert.throws(
      () => gui.parseSseFrames(text, 2),
      (error) => error instanceof gui.WebClientError && error.code === "invalid_event_stream",
    );
  }
});


test("SSE reducer handles provisional confirmed discarded activity and terminal facts", () => {
  const state = gui.createInitialUiState();
  state.selectedSessionId = "s1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running" }],
    events: [],
    skill_ids: [],
  };
  state.activeRunId = "r1";

  gui.reduceSessionUpdate(state, { id: 1, event: "assistant_text_delta", data: { data: { content: "hel" } } });
  gui.reduceSessionUpdate(state, { id: 2, event: "assistant_text_delta", data: { data: { content: "lo" } } });
  assert.equal(state.provisionalText, "hello");
  gui.reduceSessionUpdate(state, { id: 3, event: "assistant_text_committed", data: { data: { content: "hello" } } });
  assert.equal(state.provisionalText, "");
  assert.equal(state.selectedSession.events.at(-1).data.content, "hello");

  gui.reduceSessionUpdate(state, { id: 4, event: "assistant_text_delta", data: { data: { content: "discard" } } });
  gui.reduceSessionUpdate(state, { id: 5, event: "assistant_text_discarded", data: { data: { reason: "model_error" } } });
  assert.equal(state.provisionalText, "");
  gui.reduceSessionUpdate(state, { id: 6, event: "tool_started", data: { data: { tool_name: "read_file", ordinal: 1, private: "secret" } } });
  assert.deepEqual(state.activities.at(-1), {
    kind: "tool_started",
    data: { tool_name: "read_file", ordinal: 1 },
  });
  gui.reduceSessionUpdate(state, { id: 7, event: "run_finished", data: { data: { status: "succeeded" } } });
  assert.equal(state.selectedSession.session.status, "succeeded");
  assert.equal(state.selectedSession.runs[0].status, "succeeded");
  assert.equal(state.activeRunId, null);
  assert.equal(state.lastSequence, 7);
});


test("reconnect delay follows the fixed capped sequence", () => {
  assert.deepEqual(
    Array.from({ length: 7 }, (_, attempt) => gui.reconnectDelayForAttempt(attempt)),
    [500, 1000, 2000, 5000, 5000, 5000, 5000],
  );
});


test("openRunStream sends Bearer and Last-Event-ID without exposing the token", async () => {
  const calls = [];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return chunkedResponse([]);
    },
  });
  await api.openRunStream("run/value", 12);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://local.invalid/api/v1/runs/run%2Fvalue/events");
  assert.equal(calls[0].headers.get("authorization"), "Bearer fixed-test-token");
  assert.equal(calls[0].headers.get("accept"), "text/event-stream");
  assert.equal(calls[0].headers.get("last-event-id"), "12");
  assert.equal(calls[0].url.includes("fixed-test-token"), false);
});


test("stream consumption reconnects once and stops on the server terminal event", async () => {
  const fetchCalls = [];
  const sleeps = [];
  const responses = [
    chunkedResponse([
      updateFrame(1, "assistant_text_delta", { content: "你" }).slice(0, 31),
      updateFrame(1, "assistant_text_delta", { content: "你" }).slice(31),
    ]),
    chunkedResponse([
      updateFrame(2, "assistant_text_committed", { content: "你好" }) +
      updateFrame(3, "run_finished", { status: "succeeded" }),
    ]),
  ];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      fetchCalls.push(request);
      return responses.shift();
    },
  });
  const state = gui.createInitialUiState();
  state.activeRunId = "r1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running" }],
    events: [], skill_ids: [],
  };

  const outcome = await gui.consumeRunStream({
    api, runId: "r1", state,
    sleep: async (delay) => sleeps.push(delay),
    reloadSession: async () => { throw new Error("unexpected reload"); },
  });

  assert.equal(outcome, "terminal");
  assert.deepEqual(sleeps, [500]);
  assert.equal(fetchCalls.length, 2);
  assert.equal(fetchCalls[1].headers.get("last-event-id"), "1");
  assert.equal(state.selectedSession.session.status, "succeeded");
  assert.equal(state.provisionalText, "");
});


test("reset reloads durable state and does not reconnect a terminal run", async () => {
  let reloads = 0;
  let sleeps = 0;
  const api = {
    openRunStream: async () => chunkedResponse([
      'event: reset_required\ndata: {"last_sequence":42,"run_id":"r1"}\n\n',
    ]),
  };
  const state = gui.createInitialUiState();
  state.activeRunId = "r1";
  const outcome = await gui.consumeRunStream({
    api, runId: "r1", state,
    reloadSession: async () => {
      reloads += 1;
      return {
        session: { session_id: "s1", status: "succeeded", last_run_id: "r1" },
        runs: [{ run_id: "r1", status: "succeeded" }], events: [], skill_ids: [],
      };
    },
    sleep: async () => { sleeps += 1; },
  });
  assert.equal(outcome, "reset_terminal");
  assert.equal(reloads, 1);
  assert.equal(sleeps, 0);
  assert.equal(state.selectedSession.session.status, "succeeded");
  assert.equal(state.activeRunId, null);
  assert.equal(state.lastSequence, 42);
});


test("abort never requests Agent cancellation and auth failures never retry", async () => {
  let cancellations = 0;
  let sleeps = 0;
  const aborted = new AbortController();
  aborted.abort();
  const abortOutcome = await gui.consumeRunStream({
    api: {
      openRunStream: async () => { throw new DOMException("aborted", "AbortError"); },
      cancelRun: async () => { cancellations += 1; },
    },
    runId: "r1",
    state: gui.createInitialUiState(),
    signal: aborted.signal,
    reloadSession: async () => ({}),
    sleep: async () => { sleeps += 1; },
  });
  assert.equal(abortOutcome, "aborted");
  assert.equal(cancellations, 0);

  for (const status of [401, 403]) {
    const state = gui.createInitialUiState();
    const result = await gui.consumeRunStream({
      api: { openRunStream: async () => Response.json({}, { status }) },
      runId: "r1", state,
      reloadSession: async () => ({}),
      sleep: async () => { sleeps += 1; },
    });
    assert.equal(result, "authentication_failed");
    assert.equal(state.connection, "authentication_failed");
  }
  assert.equal(sleeps, 0);
});


test("controller owns one stream and history navigation only aborts that stream", async () => {
  const { document, elements } = controllerFixture();
  const streamCalls = [];
  let cancellations = 0;
  const api = {
    listSessions: async () => ({
      sessions: [
        { session_id: "running", title: "Running", status: "running", last_run_id: "r1" },
        { session_id: "history", title: "History", status: "idle", last_run_id: "r0" },
      ],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => ({
      session: {
        session_id: sessionId,
        title: sessionId === "running" ? "Running" : "History",
        status: sessionId === "running" ? "running" : "idle",
        last_run_id: sessionId === "running" ? "r1" : "r0",
      },
      runs: [{
        run_id: sessionId === "running" ? "r1" : "r0",
        status: sessionId === "running" ? "running" : "succeeded",
        started_at_utc: null,
      }],
      events: [], skill_ids: [],
    }),
    cancelRun: async () => { cancellations += 1; },
  };
  const streamConsumer = ({ state, signal, onState }) => {
    streamCalls.push({ signal });
    state.provisionalText = "live text";
    onState(state);
    return new Promise((resolve) => {
      signal.addEventListener("abort", () => resolve("aborted"), { once: true });
    });
  };
  const controller = gui.createUiController({
    document, elements, api, streamConsumer,
  });
  await controller.initialize();
  const buttons = findElements(elements.sessionList, "button");
  elements.sessionList.dispatchEvent({ type: "click", target: buttons[0] });
  await controller.whenIdle();
  assert.equal(streamCalls.length, 1);
  assert.equal(elements.conversationLog.textContent.includes("live text"), true);

  document.dispatchEvent({ type: "visibilitychange" });
  assert.equal(streamCalls.length, 1);
  elements.sessionList.dispatchEvent({ type: "click", target: buttons[1] });
  await controller.whenIdle();
  assert.equal(streamCalls[0].signal.aborted, true);
  assert.equal(cancellations, 0);
  assert.equal(streamCalls.length, 1);
  controller.destroy();
});


test("browser startup consumes bootstrap and initializes the real controller", async () => {
  const { document, elements } = controllerFixture();
  const meta = document.createElement("meta");
  meta.setAttribute("id", "coding-agent-bootstrap");
  meta.setAttribute("content", "fixed-test-token");
  document.body.append(meta);
  const requests = [];
  const fetchImpl = async (request) => {
    requests.push(request);
    if (request.url.endsWith("/api/v1/skills")) {
      return Response.json({ skills: [], diagnostics: [], usable: true });
    }
    return Response.json({ sessions: [] });
  };

  const controller = await gui.startBrowserApplication({
    document,
    window: { location: { origin: "http://127.0.0.1:43123" } },
    fetchImpl,
  });

  assert.equal(document.getElementById("coding-agent-bootstrap"), null);
  assert.deepEqual(
    requests.map((request) => request.url).sort(),
    [
      "http://127.0.0.1:43123/api/v1/sessions?limit=50",
      "http://127.0.0.1:43123/api/v1/skills",
    ].sort(),
  );
  assert.equal(
    requests.every((request) => request.headers.get("authorization") === "Bearer fixed-test-token"),
    true,
  );
  assert.equal(requests.every((request) => !request.url.includes("fixed-test-token")), true);
  assert.equal(elements.connectionStatus.textContent, "已连接本地服务");
  controller.destroy();
});


test("durable tool and verification activity render through safe cards", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "History", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "History", status: "idle", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "succeeded", started_at_utc: null }],
      events: [
        {
          kind: "tool_activity",
          data: { tool_name: "read_file", status: "ok", duration_ms: 12, private: "secret" },
        },
        {
          kind: "verification_activity",
          data: { status: "passed", source: "user_verify", duration_ms: 21, private: "secret" },
        },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();

  assert.equal(elements.conversationLog.textContent.includes("read_file"), true);
  assert.equal(elements.conversationLog.textContent.includes("passed"), true);
  assert.equal(elements.conversationLog.textContent.includes("secret"), false);
  controller.destroy();
});
