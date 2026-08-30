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
  elements.connectionStatus.dataset.visible = "false";
  elements.connectionStatus.setAttribute("aria-hidden", "true");
  elements.emptyState = document.createElement("div");
  elements.emptyState.setAttribute("id", "empty-state");
  elements.emptyState.className = "empty-state";
  elements.emptyState.append(document.createTextNode("把一个清晰的代码任务交给 Agent"));
  elements.conversationLog.append(elements.emptyState);
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


function keydownEvent({ key = "Enter", shiftKey = false, isComposing = false } = {}) {
  return {
    type: "keydown",
    key,
    shiftKey,
    isComposing,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
  };
}


test("session list renders only a compact title with the full title available", async () => {
  const { document, elements } = controllerFixture();
  const longTitle = "请检查项目中的所有失败测试并修复实现，同时解释每一处修改";
  const api = {
    listSessions: async () => ({
      sessions: [{
        session_id: "s1",
        title: longTitle,
        status: "idle",
        last_run_id: null,
      }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
  };
  const controller = gui.createUiController({ document, elements, api });

  await controller.initialize();

  const item = findElements(elements.sessionList, "li")[0];
  const button = findElements(item, "button")[0];
  const spans = findElements(button, "span");
  assert.equal(item.className, "session-item");
  assert.equal(button.className, "session-button");
  assert.deepEqual(spans.map((span) => span.className), ["session-title"]);
  assert.equal(spans[0].textContent, longTitle);
  assert.equal(spans[0].getAttribute("title"), longTitle);
  assert.equal(button.textContent.includes("空闲"), false);
  assert.equal(button.childNodes.every((node) => node.nodeType === 1), true);
  controller.destroy();
});


test("no selected session keeps the start prompt after initialization and reset", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Existing", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Existing", status: "idle", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "succeeded", started_at_utc: null }],
      events: [{ run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Inspect" } }],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });

  await controller.initialize();
  assert.deepEqual(elements.conversationLog.childNodes, [elements.emptyState]);

  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();
  assert.equal(elements.conversationLog.textContent.includes("Inspect"), true);

  elements.newSessionButton.dispatchEvent({ type: "click" });
  assert.deepEqual(elements.conversationLog.childNodes, [elements.emptyState]);
  assert.equal(
    elements.conversationLog.textContent,
    "把一个清晰的代码任务交给 Agent",
  );
  controller.destroy();
});


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


test("Enter submits while Shift Enter and IME confirmation keep editing", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    createSession: async (message) => {
      calls.push(message);
      return { session_id: "s1", run_id: "r1" };
    },
    loadSession: async () => ({
      session: { session_id: "s1", title: "Repair", status: "running", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "running", started_at_utc: null }],
      events: [{ run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Repair" } }],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    streamConsumer: async () => "terminal",
  });
  await controller.initialize();

  elements.messageInput.value = "Repair";
  const shifted = keydownEvent({ shiftKey: true });
  elements.messageInput.dispatchEvent(shifted);
  const composing = keydownEvent({ isComposing: true });
  elements.messageInput.dispatchEvent(composing);
  assert.equal(shifted.defaultPrevented, false);
  assert.equal(composing.defaultPrevented, false);
  assert.deepEqual(calls, []);
  assert.equal(elements.messageInput.value, "Repair");

  const entered = keydownEvent();
  elements.messageInput.dispatchEvent(entered);
  await controller.whenIdle();
  assert.equal(entered.defaultPrevented, true);
  assert.deepEqual(calls, ["Repair"]);
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


test("controller renders an accepted follow-up immediately from durable state", async () => {
  const { document, elements } = controllerFixture();
  let loads = 0;
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Existing", status: "idle", last_run_id: "r0" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => {
      loads += 1;
      if (loads === 1) {
        return {
          session: { session_id: sessionId, title: "Existing", status: "idle", last_run_id: "r0" },
          runs: [{ run_id: "r0", status: "failed", started_at_utc: null }],
          events: [{ sequence: 1, kind: "user_message", data: { content: "Initial" } }],
          skill_ids: [],
        };
      }
      return {
        session: { session_id: sessionId, title: "Existing", status: "running", last_run_id: "r1" },
        runs: [
          { run_id: "r0", status: "failed", started_at_utc: null },
          { run_id: "r1", status: "running", started_at_utc: null },
        ],
        events: [
          { sequence: 1, kind: "user_message", data: { content: "Initial" } },
          { sequence: 2, kind: "user_message", data: { content: "Continue" } },
        ],
        skill_ids: [],
      };
    },
    submitFollowUp: async (sessionId) => ({ session_id: sessionId, run_id: "r1" }),
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    streamConsumer: async () => "terminal",
  });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];
  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();

  elements.messageInput.value = "Continue";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  const renderedFollowUp = elements.conversationLog.textContent.includes("Continue");
  controller.destroy();
  assert.equal(loads, 2);
  assert.equal(renderedFollowUp, true);
});


test("controller starts each new run with clean transient state", async () => {
  const { document, elements } = controllerFixture();
  let loads = 0;
  const streamStarts = [];
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Existing", status: "idle", last_run_id: "r0" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => {
      loads += 1;
      return {
        session: {
          session_id: sessionId,
          title: "Existing",
          status: loads === 1 ? "idle" : "running",
          last_run_id: loads === 1 ? "r0" : "r1",
        },
        runs: loads === 1
          ? [{ run_id: "r0", status: "failed", started_at_utc: null }]
          : [{ run_id: "r1", status: "running", started_at_utc: null }],
        events: [],
        skill_ids: [],
      };
    },
    submitFollowUp: async (sessionId) => ({ session_id: sessionId, run_id: "r1" }),
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    streamConsumer: async ({ state }) => {
      streamStarts.push({
        lastSequence: state.lastSequence,
        activities: state.activities,
        provisionalText: state.provisionalText,
      });
      return "terminal";
    },
  });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];
  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();
  controller.getState().lastSequence = 9;
  controller.getState().activities = [{
    kind: "tool_finished",
    data: { tool_name: "old_tool", status: "ok", duration_ms: 1 },
  }];
  controller.getState().provisionalText = "old partial answer";

  elements.messageInput.value = "Continue";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  controller.destroy();
  assert.deepEqual(streamStarts, [{
    lastSequence: 0,
    activities: [],
    provisionalText: "",
  }]);
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


test("controller selects a session from nested session content", async () => {
  const { document, elements } = controllerFixture();
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
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  const nestedStatus = findElements(elements.sessionList, "span")[0];

  elements.sessionList.dispatchEvent({ type: "click", target: nestedStatus });
  await controller.whenIdle();

  const selectedSessionId = controller.getState().selectedSessionId;
  controller.destroy();
  assert.equal(selectedSessionId, "s1");
});


test("controller renders only the safe terminal reason for a failed run", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Failed", status: "failed", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => ({
      session: { session_id: sessionId, title: "Failed", status: "failed", last_run_id: "r1" },
      runs: [{
        run_id: "r1",
        status: "failed",
        started_at_utc: null,
        termination_reason: "invalid_model_response",
        private: "must-not-render",
      }],
      events: [],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];

  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();

  const rendered = elements.conversationLog.textContent;
  controller.destroy();
  assert.equal(rendered.includes("运行失败"), true);
  assert.equal(rendered.includes("invalid_model_response"), true);
  assert.equal(rendered.includes("must-not-render"), false);
});


test("controller keeps a failure card when the safe reason is unavailable", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Failed", status: "failed", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => ({
      session: { session_id: sessionId, title: "Failed", status: "failed", last_run_id: "r1" },
      runs: [{
        run_id: "r1",
        status: "failed",
        started_at_utc: null,
        termination_reason: null,
      }],
      events: [
        {
          kind: "tool_activity",
          data: { tool_name: "read_file", status: "rejected", duration_ms: 0 },
        },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];

  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();

  const rendered = elements.conversationLog.textContent;
  const activityCount = findElements(elements.conversationLog, "div").filter(
    (element) => element.classList.contains("activity-card"),
  ).length;
  controller.destroy();

  assert.equal(activityCount, 1);
  assert.equal(rendered.includes("运行失败"), true);
  assert.equal(rendered.includes("read_file"), false);
});


test("controller renders one safe terminal card for an interrupted run", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Interrupted", status: "interrupted", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => ({
      session: {
        session_id: sessionId,
        title: "Interrupted",
        status: "interrupted",
        last_run_id: "r1",
      },
      runs: [{
        run_id: "r1",
        status: "interrupted",
        started_at_utc: null,
        termination_reason: "user_interrupted",
      }],
      events: [
        { kind: "user_message", data: { content: "Stop this run" } },
        {
          kind: "tool_activity",
          data: { tool_name: "read_file", status: "ok", duration_ms: 4 },
        },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  const sessionButton = findElements(elements.sessionList, "button")[0];

  elements.sessionList.dispatchEvent({ type: "click", target: sessionButton });
  await controller.whenIdle();

  const rendered = elements.conversationLog.textContent;
  const activityCount = findElements(elements.conversationLog, "div").filter(
    (element) => element.classList.contains("activity-card"),
  ).length;
  controller.destroy();

  assert.equal(activityCount, 1);
  assert.equal(rendered.includes("运行已中断"), true);
  assert.equal(rendered.includes("user_interrupted"), true);
  assert.equal(rendered.includes("read_file"), false);
});


test("successful runs render only their last confirmed assistant text", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Done", status: "succeeded", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Done", status: "succeeded", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "succeeded", termination_reason: "completed" }],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Create README" } },
        { run_id: "r1", sequence: 2, kind: "assistant_text_committed", data: { content: "I will inspect more files" } },
        { run_id: "r1", sequence: 3, kind: "assistant_text_committed", data: { content: "README created and verified" } },
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

  assert.equal(elements.conversationLog.textContent.includes("I will inspect"), false);
  assert.equal(elements.conversationLog.textContent.includes("README created and verified"), true);
  assert.equal(findElements(elements.conversationLog, "article").length, 2);
  controller.destroy();
});


function terminalProjectionApi(status, text) {
  const terminationReason = status === "failed"
    ? "model_error_limit"
    : "user_interrupted";
  return {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Terminal", status, last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Terminal", status, last_run_id: "r1" },
      runs: [{ run_id: "r1", status, termination_reason: terminationReason }],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Do work" } },
        { run_id: "r1", sequence: 2, kind: "assistant_text_committed", data: { content: text } },
        { run_id: "r1", sequence: 3, kind: "assistant_text_committed", data: { content: `${text} again` } },
      ],
      skill_ids: [],
    }),
  };
}


test("failed and interrupted runs hide committed process narration", async () => {
  for (const status of ["failed", "interrupted"]) {
    const { document, elements } = controllerFixture();
    const api = terminalProjectionApi(status, "process text must disappear");
    const controller = gui.createUiController({ document, elements, api });
    await controller.initialize();
    elements.sessionList.dispatchEvent({
      type: "click",
      target: findElements(elements.sessionList, "button")[0],
    });
    await controller.whenIdle();

    assert.equal(
      elements.conversationLog.textContent.includes("process text must disappear"),
      false,
    );
    assert.equal(
      findElements(elements.conversationLog, "div").filter(
        (element) => element.classList.contains("activity-card"),
      ).length,
      1,
    );
    controller.destroy();
  }
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


function reducerFrame(id, kind, data, runId = "r1") {
  return {
    id,
    event: kind,
    data: {
      schema_version: 1,
      session_id: "s1",
      run_id: runId,
      sequence: id,
      kind,
      created_at_utc: "2026-08-30T00:00:00.000000Z",
      data,
    },
  };
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
  assert.equal(state.provisionalText, "hello");
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


test("live narration and tool activity replace one another in one card", () => {
  const state = gui.createInitialUiState();
  state.activeRunId = "r1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running" }],
    events: [],
  };
  gui.reduceSessionUpdate(
    state,
    reducerFrame(1, "assistant_text_delta", { content: "Inspecting" }),
  );
  assert.equal(state.provisionalText, "Inspecting");
  assert.deepEqual(state.activities, []);
  gui.reduceSessionUpdate(
    state,
    reducerFrame(2, "assistant_text_committed", { content: "Inspecting" }),
  );
  assert.equal(state.provisionalText, "Inspecting");
  assert.equal(state.selectedSession.events[0].run_id, "r1");
  gui.reduceSessionUpdate(
    state,
    reducerFrame(3, "tool_started", { tool_name: "read_file", ordinal: 1 }),
  );
  assert.equal(state.provisionalText, "");
  assert.equal(state.activities[0].kind, "tool_started");
  gui.reduceSessionUpdate(
    state,
    reducerFrame(4, "assistant_text_delta", { content: "Writing final answer" }),
  );
  assert.deepEqual(state.activities, []);
  assert.equal(state.provisionalText, "Writing final answer");
});


test("SSE reducer keeps only the current activity and clears it at success", () => {
  const state = gui.createInitialUiState();
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running" }],
    events: [],
    skill_ids: [],
  };
  state.activeRunId = "r1";

  gui.reduceSessionUpdate(state, {
    id: 1,
    event: "tool_started",
    data: { data: { tool_name: "list_directory", ordinal: 1 } },
  });
  gui.reduceSessionUpdate(state, {
    id: 2,
    event: "tool_finished",
    data: {
      data: {
        tool_name: "list_directory",
        status: "ok",
        duration_ms: 3,
      },
    },
  });

  assert.deepEqual(state.activities, [{
    kind: "tool_finished",
    data: {
      tool_name: "list_directory",
      status: "ok",
      duration_ms: 3,
    },
  }]);

  gui.reduceSessionUpdate(state, {
    id: 3,
    event: "run_finished",
    data: { data: { status: "succeeded" } },
  });

  assert.deepEqual(state.activities, []);
});


test("SSE reducer keeps the stable terminal reason and drops private fields", () => {
  const state = gui.createInitialUiState();
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running" }],
    events: [],
    skill_ids: [],
  };
  state.activeRunId = "r1";

  gui.reduceSessionUpdate(state, {
    id: 1,
    event: "run_finished",
    data: {
      run_id: "r1",
      data: {
        status: "failed",
        termination_reason: "invalid_model_response",
        private: "must-not-store",
      },
    },
  });

  assert.deepEqual(state.selectedSession.runs[0], {
    run_id: "r1",
    status: "failed",
    termination_reason: "invalid_model_response",
  });
  assert.equal(JSON.stringify(state).includes("must-not-store"), false);
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
  assert.equal(elements.connectionStatus.textContent, "");
  assert.equal(elements.connectionStatus.dataset.visible, "false");
  assert.equal(elements.connectionStatus.getAttribute("aria-hidden"), "true");
  controller.destroy();
});


test("request failures reveal the normally hidden connection notice", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    createSession: async () => {
      throw new gui.WebClientError("controller_busy");
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  elements.messageInput.value = "Inspect";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.equal(elements.connectionStatus.dataset.visible, "true");
  assert.equal(elements.connectionStatus.getAttribute("aria-hidden"), "false");
  assert.equal(elements.connectionStatus.textContent, "请求失败：controller_busy");
  controller.destroy();
});


test("conversation hides durable activity and shows one live card before the reply", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Active", status: "running", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Active", status: "running", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "running", started_at_utc: null }],
      events: [
        { kind: "user_message", data: { content: "Inspect" } },
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
  const streamConsumer = ({ state, signal, onState }) => {
    gui.reduceSessionUpdate(state, {
      id: 3,
      event: "tool_started",
      data: { data: { tool_name: "list_directory", ordinal: 2 } },
    });
    gui.reduceSessionUpdate(state, {
      id: 4,
      event: "tool_finished",
      data: {
        data: {
          tool_name: "list_directory",
          status: "ok",
          duration_ms: 7,
        },
      },
    });
    gui.reduceSessionUpdate(
      state,
      reducerFrame(5, "assistant_text_delta", { content: "Writing the answer" }),
    );
    onState(state);
    return new Promise((resolve) => {
      signal.addEventListener("abort", () => resolve("aborted"), { once: true });
    });
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    streamConsumer,
  });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();

  const rendered = elements.conversationLog.textContent;
  const activityCount = findElements(elements.conversationLog, "div").filter(
    (element) => element.classList.contains("activity-card"),
  ).length;
  const childClasses = elements.conversationLog.childNodes.map(
    (element) => element.className,
  );
  controller.destroy();

  assert.equal(rendered.includes("read_file"), false);
  assert.equal(rendered.includes("user_verify"), false);
  assert.equal(activityCount, 1);
  assert.deepEqual(
    childClasses,
    [
      "message message--user",
      "activity-card",
    ],
  );
  assert.equal(rendered.includes("list_directory"), false);
  assert.equal(rendered.includes("Writing the answer"), true);
  assert.equal(rendered.includes("secret"), false);
});
