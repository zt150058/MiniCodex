import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { TestDocument, findElements } from "./dom_harness.mjs";


const appSource = await readFile(
  new URL("../../src/coding_agent/web/static/app.js", import.meta.url),
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
  const copies = [];

  gui.appendMessage(
    document,
    container,
    "assistant",
    "before\n```py\nprint(1)\n```\nafter",
    null,
    (_button, text) => copies.push(text),
  );

  assert.equal(findElements(container, "pre").length, 1);
  assert.equal(findElements(container, "code")[0].textContent, "print(1)\n");
  const copyButtons = findElements(container, "button").filter(
    (button) => button.classList.contains("code-copy-button"),
  );
  assert.equal(copyButtons.length, 1);
  assert.equal(copyButtons[0].textContent, "复制");
  copyButtons[0].dispatchEvent({ type: "click" });
  assert.deepEqual(copies, ["print(1)"]);
  assert.equal(container.textContent, "MiniCodexbefore\n复制print(1)\nafter");
});


test("an unclosed fence remains plain text", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(document, container, "assistant", "before\n```py\nsecret");

  assert.equal(findElements(container, "pre").length, 0);
  assert.equal(findElements(container, "button").length, 0);
  assert.equal(container.textContent, "MiniCodexbefore\n```py\nsecret");
});


test("assistant messages render common Markdown as semantic DOM", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(
    document,
    container,
    "assistant",
    [
      "# 标题",
      "",
      "包含 **粗体**、*斜体*、~~删除~~ 和 `inline()`。",
      "",
      "- 第一项",
      "- 第二项",
      "",
      "1. 步骤一",
      "2. 步骤二",
      "",
      "> 引用内容",
      "",
      "---",
    ].join("\n"),
  );

  assert.equal(findElements(container, "h1")[0].textContent, "标题");
  assert.equal(findElements(container, "strong")[0].textContent, "粗体");
  assert.equal(findElements(container, "em")[0].textContent, "斜体");
  assert.equal(findElements(container, "del")[0].textContent, "删除");
  assert.equal(findElements(container, "code")[0].textContent, "inline()");
  assert.deepEqual(
    findElements(container, "ul")[0].childNodes.map((node) => node.textContent),
    ["第一项", "第二项"],
  );
  assert.deepEqual(
    findElements(container, "ol")[0].childNodes.map((node) => node.textContent),
    ["步骤一", "步骤二"],
  );
  assert.equal(findElements(container, "blockquote")[0].textContent, "引用内容");
  assert.equal(findElements(container, "hr").length, 1);
});


test("assistant Markdown tables render headers rows and alignment", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(
    document,
    container,
    "assistant",
    [
      "| 名称 | 状态 | 数量 |",
      "| :--- | :---: | ---: |",
      "| **构建** | 通过 | 12 |",
      "| 测试 | 通过 | 48 |",
    ].join("\n"),
  );

  const table = findElements(container, "table")[0];
  assert.equal(table.parentNode.className, "markdown-table-wrapper");
  assert.deepEqual(
    findElements(table, "th").map((cell) => cell.textContent),
    ["名称", "状态", "数量"],
  );
  assert.deepEqual(
    findElements(table, "th").map((cell) => cell.className),
    ["markdown-align-left", "markdown-align-center", "markdown-align-right"],
  );
  assert.deepEqual(
    findElements(table, "td").map((cell) => cell.textContent),
    ["构建", "通过", "12", "测试", "通过", "48"],
  );
  assert.equal(findElements(table, "strong")[0].textContent, "构建");
});


test("Markdown preserves coding text in headings and table cells", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(
    document,
    container,
    "assistant",
    [
      "# C#",
      "",
      "| 路径 | 说明 |",
      "| --- | --- |",
      "| C:\\work\\main.py | A\\|B |",
    ].join("\n"),
  );

  assert.equal(findElements(container, "h1")[0].textContent, "C#");
  assert.deepEqual(
    findElements(container, "td").map((cell) => cell.textContent),
    ["C:\\work\\main.py", "A|B"],
  );
});


test("assistant Markdown creates only allowlisted safe links", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  gui.appendMessage(
    document,
    container,
    "assistant",
    "[文档](https://example.com/docs) [邮件](mailto:test@example.com) [危险](javascript:alert(1))",
  );

  const links = findElements(container, "a");
  assert.deepEqual(links.map((link) => link.textContent), ["文档", "邮件"]);
  assert.deepEqual(
    links.map((link) => link.getAttribute("href")),
    ["https://example.com/docs", "mailto:test@example.com"],
  );
  assert.equal(links[0].getAttribute("target"), "_blank");
  assert.equal(links[0].getAttribute("rel"), "noopener noreferrer");
  assert.equal(container.textContent.includes("[危险](javascript:alert(1))"), true);
});


test("user messages preserve Markdown source as plain text", () => {
  const document = new TestDocument();
  const container = document.createElement("section");
  const source = "# 原始任务\n\n**不要改写**\n\n| A | B |\n| --- | --- |";

  gui.appendMessage(document, container, "user", source);

  assert.equal(container.textContent, `你${source}`);
  for (const tag of ["h1", "strong", "table", "p"]) {
    assert.equal(findElements(container, tag).length, 0);
  }
  assert.equal(findElements(container, "button").length, 0);
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


test("tool activity renders real exit codes", () => {
  const document = new TestDocument();
  const failed = document.createElement("section");
  const passed = document.createElement("section");
  const fileTool = document.createElement("section");

  gui.appendActivity(document, failed, "tool_finished", {
    tool_name: "run_command",
    status: "ok",
    duration_ms: 188,
    exit_code: 1,
  });
  gui.appendActivity(document, passed, "tool_finished", {
    tool_name: "run_command",
    status: "ok",
    duration_ms: 42,
    exit_code: 0,
  });
  gui.appendActivity(document, fileTool, "tool_finished", {
    tool_name: "read_file",
    status: "ok",
    duration_ms: 3,
    exit_code: null,
  });

  assert.equal(failed.textContent.includes("exit 1"), true);
  assert.equal(failed.textContent.includes("· ok ·"), false);
  assert.equal(passed.textContent.includes("exit 0"), true);
  assert.equal(passed.textContent.includes("· ok ·"), false);
  assert.equal(fileTool.textContent.includes("· ok ·"), true);
});


test("only active activity cards include an inaccessible three-dot indicator", () => {
  const document = new TestDocument();
  const container = document.createElement("section");

  const historyCard = gui.appendActivity(
    document,
    container,
    "tool_finished",
    { tool_name: "pytest", status: "ok", duration_ms: 27 },
  );
  const activeCard = gui.appendActivity(
    document,
    container,
    "model_progress",
    { content: "Still working" },
    { active: true },
  );

  assert.equal(historyCard.classList.contains("activity-card--active"), false);
  assert.equal(
    findElements(historyCard, "span").some(
      (element) => element.classList.contains("activity-indicator"),
    ),
    false,
  );
  assert.equal(activeCard.classList.contains("activity-card--active"), true);
  const indicators = findElements(activeCard, "span").filter(
    (element) => element.classList.contains("activity-indicator"),
  );
  assert.equal(indicators.length, 1);
  assert.equal(indicators[0].getAttribute("aria-hidden"), "true");
  assert.equal(
    findElements(indicators[0], "span").filter(
      (element) => element.classList.contains("activity-indicator__dot"),
    ).length,
    3,
  );
  assert.equal(container.textContent.includes("Still working"), true);
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
    cancelButton: document.createElement("button"),
  };

  gui.renderRunHeader(document, elements, { status: "running" });
  assert.equal(elements.runStatus.textContent, "运行中");
  assert.equal(elements.cancelButton.disabled, false);

  gui.renderRunHeader(document, elements, { status: "future_status" });
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
    await api.createSession(
      "repair tests",
      ["workspace:review"],
      "read_only",
      "deep",
      "chat-selected",
    ),
    responses[0],
  );
  assert.deepEqual(
    await api.submitFollowUp(
      "s1",
      "continue",
      "modify",
      "standard",
      "chat-follow",
    ),
    responses[1],
  );
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
      {
        message: "repair tests",
        skill_ids: ["workspace:review"],
        run_mode: "read_only",
        budget_profile: "deep",
        model_id: "chat-selected",
      },
      {
        message: "continue",
        run_mode: "modify",
        budget_profile: "standard",
        model_id: "chat-follow",
      },
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


test("delete session sends one authenticated bodyless request to the encoded URL", async () => {
  const calls = [];
  const payload = {
    session_id: "session/value",
    deleted: true,
    cleanup_pending: false,
  };
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json(payload);
    },
  });

  assert.deepEqual(await api.deleteSession("session/value"), payload);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://local.invalid/api/v1/sessions/session%2Fvalue");
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[0].headers.get("authorization"), "Bearer fixed-test-token");
  assert.equal(calls[0].headers.get("content-type"), null);
  assert.equal(await calls[0].clone().text(), "");
});


test("delete session failure is stable and is never retried", async () => {
  const calls = [];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json(
        { error: { code: "controller_busy", private: "secret" } },
        { status: 409 },
      );
    },
  });

  await assert.rejects(
    api.deleteSession("s1"),
    (error) => error instanceof gui.WebClientError && error.code === "controller_busy",
  );
  assert.equal(calls.length, 1);
  assert.equal(String(calls[0]).includes("secret"), false);
});


test("session skill and model reads use exact authenticated routes", async () => {
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
  await api.listModels(true);

  assert.deepEqual(
    calls.map((request) => request.url),
    [
      "http://local.invalid/api/v1/sessions/session%2Fvalue",
      "http://local.invalid/api/v1/skills",
      "http://local.invalid/api/v1/models?refresh=true",
    ],
  );
  assert.equal(
    calls.every(
      (request) => request.headers.get("authorization") === "Bearer fixed-test-token",
    ),
    true,
  );
});


test("skill import sends one authenticated raw zip request", async () => {
  const calls = [];
  const archive = new Blob([new Uint8Array([1, 2, 3])], {
    type: "application/zip",
  });
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json({ skill_id: "review" }, { status: 201 });
    },
  });

  assert.deepEqual(await api.importSkillArchive(archive), { skill_id: "review" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].url, "http://local.invalid/api/v1/skills/import");
  assert.equal(calls[0].headers.get("authorization"), "Bearer fixed-test-token");
  assert.equal(calls[0].headers.get("content-type"), "application/zip");
  assert.equal((await calls[0].clone().arrayBuffer()).byteLength, archive.size);
});


test("empty skill catalog imports one archive and auto-selects the new draft skill", async () => {
  const { document, elements } = controllerFixture();
  const archive = new Blob(["zip"], { type: "application/zip" });
  archive.name = "review.zip";
  let catalogCalls = 0;
  const imported = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => {
      catalogCalls += 1;
      return catalogCalls === 1
        ? { skills: [], diagnostics: [], usable: true }
        : {
            skills: [{
              skill_id: "review",
              name: "Review",
              description: "Review safely.",
              source: "workspace",
            }],
            diagnostics: [],
            usable: true,
          };
    },
    importSkillArchive: async (file) => {
      imported.push(file);
      return { skill_id: "review" };
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  assert.equal(elements.skillEmptyState.hidden, false);
  elements.skillImportButton.dispatchEvent({ type: "click" });
  assert.equal(elements.skillFileInput.clickCount, 1);
  elements.skillFileInput.files = [archive];
  elements.skillFileInput.value = "review.zip";
  elements.skillFileInput.dispatchEvent({ type: "change" });
  await controller.whenIdle();

  assert.deepEqual(imported, [archive]);
  assert.equal(catalogCalls, 2);
  assert.deepEqual(controller.getState().selectedSkillIds, ["review"]);
  assert.equal(elements.skillEmptyState.hidden, true);
  assert.equal(elements.skillImportStatus.textContent, "已导入 Review");
  assert.equal(elements.skillFileInput.value, "");
  controller.destroy();
});


test("skill import is single-flight and persists auto-selection only for an idle session", async () => {
  const { document, elements } = controllerFixture();
  const archive = new Blob(["zip"], { type: "application/zip" });
  let resolveImport;
  let importCalls = 0;
  const saved = [];
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Idle", status: "idle", last_run_id: null }],
    }),
    listSkills: async () => ({
      skills: importCalls
        ? [{ skill_id: "review", name: "Review", description: "", source: "workspace" }]
        : [],
      diagnostics: [],
      usable: true,
    }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Idle", status: "idle", last_run_id: null },
      runs: [], events: [], skill_ids: [],
    }),
    importSkillArchive: async () => {
      importCalls += 1;
      return new Promise((resolve) => { resolveImport = resolve; });
    },
    saveSkillSelection: async (sessionId, skillIds) => {
      saved.push([sessionId, skillIds]);
      return { skill_ids: skillIds };
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();

  elements.skillFileInput.files = [archive];
  elements.skillFileInput.dispatchEvent({ type: "change" });
  elements.skillFileInput.dispatchEvent({ type: "change" });
  await Promise.resolve();
  assert.equal(importCalls, 1);
  assert.equal(elements.skillImportButton.disabled, true);
  resolveImport({ skill_id: "review" });
  await controller.whenIdle();

  assert.deepEqual(saved, [["s1", ["review"]]]);
  assert.equal(elements.skillImportButton.disabled, false);
  controller.destroy();
});


test("successful import restores idle selection when automatic persistence fails", async () => {
  const { document, elements } = controllerFixture();
  const archive = new Blob(["zip"], { type: "application/zip" });
  let importCalls = 0;
  let saveCalls = 0;
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Idle", status: "idle", last_run_id: null }],
    }),
    listSkills: async () => ({
      skills: importCalls
        ? [{ skill_id: "review", name: "Review", description: "", source: "workspace" }]
        : [],
      diagnostics: [],
      usable: true,
    }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Idle", status: "idle", last_run_id: null },
      runs: [], events: [], skill_ids: [],
    }),
    importSkillArchive: async () => {
      importCalls += 1;
      return { skill_id: "review" };
    },
    saveSkillSelection: async () => {
      saveCalls += 1;
      throw new gui.WebClientError("invalid_skill_selection");
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();

  elements.skillFileInput.files = [archive];
  elements.skillFileInput.dispatchEvent({ type: "change" });
  await controller.whenIdle();

  assert.equal(importCalls, 1);
  assert.equal(saveCalls, 1);
  assert.deepEqual(controller.getState().selectedSkillIds, []);
  assert.equal(
    elements.skillImportStatus.textContent,
    "已导入 Review；自动选择失败：invalid_skill_selection",
  );
  controller.destroy();
});


test("skill import is disabled during active runs and exposes only a stable failure code", async () => {
  const { document, elements } = controllerFixture();
  let importCalls = 0;
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Busy", status: "running", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    importSkillArchive: async () => {
      importCalls += 1;
      throw new gui.WebClientError("invalid_skill_archive");
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  assert.equal(elements.skillImportButton.disabled, true);
  elements.skillFileInput.files = [new Blob(["bad"] )];
  elements.skillFileInput.dispatchEvent({ type: "change" });
  await controller.whenIdle();
  assert.equal(importCalls, 0);

  controller.getState().sessions[0].status = "idle";
  elements.skillFileInput.files = [new Blob(["bad"] )];
  elements.skillFileInput.dispatchEvent({ type: "change" });
  await controller.whenIdle();
  assert.equal(importCalls, 1);
  assert.equal(elements.skillImportStatus.textContent, "导入失败：invalid_skill_archive");
  assert.equal(elements.skillFileInput.value, "");
  controller.destroy();
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
    skillImportButton: ["button", "skill-import-button"],
    skillFileInput: ["input", "skill-file-input"],
    skillEmptyState: ["p", "skill-empty-state"],
    skillImportStatus: ["p", "skill-import-status"],
    conversationTitle: ["h1", "conversation-title"],
    runStatus: ["span", "run-status"],
    workspacePath: ["span", "workspace-path"],
    runElapsed: ["span", "run-elapsed"],
    cancelButton: ["button", "cancel-run-button"],
    conversationLog: ["section", "conversation-log"],
    messageComposer: ["form", "message-composer"],
    messageInput: ["textarea", "message-input"],
    sendButton: ["button", "send-message-button"],
    connectionStatus: ["div", "connection-status"],
    newSessionButton: ["button", "new-session-button"],
    runModeControl: ["div", "run-mode-control"],
    runModeModifyButton: ["button", "run-mode-modify"],
    runModeReadOnlyButton: ["button", "run-mode-read-only"],
    budgetProfileControl: ["div", "budget-profile-control"],
    budgetProfileStandardButton: ["button", "budget-profile-standard"],
    budgetProfileDeepButton: ["button", "budget-profile-deep"],
    modelControl: ["div", "model-control"],
    modelSelect: ["select", "model-select"],
    refreshModelsButton: ["button", "refresh-models-button"],
    modelCatalogStatus: ["span", "model-catalog-status"],
  })) {
    elements[name] = document.createElement(tag);
    elements[name].setAttribute("id", id);
    document.body.append(elements[name]);
  }
  elements.skillToggle.setAttribute("aria-expanded", "false");
  elements.skillToggle.setAttribute("aria-controls", "skill-panel");
  elements.skillPanel.hidden = true;
  elements.skillFileInput.files = [];
  elements.skillFileInput.clickCount = 0;
  elements.skillFileInput.click = () => {
    elements.skillFileInput.clickCount += 1;
  };
  elements.connectionStatus.dataset.visible = "false";
  elements.connectionStatus.setAttribute("aria-hidden", "true");
  elements.runModeModifyButton.dataset.runMode = "modify";
  elements.runModeReadOnlyButton.dataset.runMode = "read_only";
  elements.budgetProfileStandardButton.dataset.budgetProfile = "standard";
  elements.budgetProfileDeepButton.dataset.budgetProfile = "deep";
  elements.workspacePath.replaceChildren(
    document.createTextNode("D:\\code\\coding_agent"),
  );
  elements.emptyState = document.createElement("div");
  elements.emptyState.setAttribute("id", "empty-state");
  elements.emptyState.className = "empty-state";
  elements.emptyState.append(document.createTextNode("把一个清晰的代码任务交给 MiniCodex"));
  elements.conversationLog.append(elements.emptyState);
  return { document, elements };
}


function readyModelCatalog(modelIds = ["chat-default", "other-model"]) {
  return {
    enabled: true,
    status: "ready",
    default_model_id: "chat-default",
    model_ids: modelIds,
    error_code: null,
  };
}


test("initialization loads the model catalog and selects its default", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async (refresh) => {
      calls.push(refresh);
      return readyModelCatalog();
    },
  };
  const controller = gui.createUiController({ document, elements, api });

  await controller.initialize();

  assert.deepEqual(calls, [false]);
  assert.equal(controller.getState().selectedModelId, "chat-default");
  assert.equal(elements.modelControl.hidden, false);
  assert.equal(elements.modelSelect.value, "chat-default");
  assert.deepEqual(
    findElements(elements.modelSelect, "option").map((option) => option.textContent),
    ["chat-default", "other-model"],
  );
  controller.destroy();
});


test("unchanged model catalogs reuse existing options across control renders", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => readyModelCatalog(),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  const originalOptions = findElements(elements.modelSelect, "option");

  elements.modelSelect.value = "other-model";
  elements.modelSelect.dispatchEvent({ type: "change" });

  assert.equal(findElements(elements.modelSelect, "option")[0], originalOptions[0]);
  assert.equal(findElements(elements.modelSelect, "option")[1], originalOptions[1]);
  controller.destroy();
});


test("Responses mode hides model controls", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => ({
      enabled: false,
      status: "disabled",
      default_model_id: "responses-default",
      model_ids: ["responses-default"],
      error_code: null,
    }),
  };
  const controller = gui.createUiController({ document, elements, api });

  await controller.initialize();

  assert.equal(elements.modelControl.hidden, true);
  assert.equal(controller.getState().selectedModelId, null);
  controller.destroy();
});


test("refresh replaces options and falls back when selection disappeared", async () => {
  const { document, elements } = controllerFixture();
  let calls = 0;
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => {
      calls += 1;
      return calls === 1
        ? readyModelCatalog(["chat-default", "other-model"])
        : readyModelCatalog(["chat-default", "new-model"]);
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.modelSelect.value = "other-model";
  elements.modelSelect.dispatchEvent({ type: "change" });

  elements.refreshModelsButton.dispatchEvent({ type: "click" });
  await controller.whenIdle();

  assert.equal(calls, 2);
  assert.equal(controller.getState().selectedModelId, "chat-default");
  assert.deepEqual(
    findElements(elements.modelSelect, "option").map((option) => option.textContent),
    ["chat-default", "new-model"],
  );
  controller.destroy();
});


test("failed refresh keeps the last good model choices and selection", async () => {
  const { document, elements } = controllerFixture();
  let calls = 0;
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => {
      calls += 1;
      if (calls === 1) return readyModelCatalog();
      throw new Error("provider unavailable");
    },
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.modelSelect.value = "other-model";
  elements.modelSelect.dispatchEvent({ type: "change" });

  elements.refreshModelsButton.dispatchEvent({ type: "click" });
  await controller.whenIdle();

  assert.equal(controller.getState().selectedModelId, "other-model");
  assert.deepEqual(
    findElements(elements.modelSelect, "option").map((option) => option.textContent),
    ["chat-default", "other-model"],
  );
  assert.match(elements.modelCatalogStatus.textContent, /过期/);
  controller.destroy();
});


test("stale and unavailable catalogs keep safe usable choices", async () => {
  for (const status of ["stale", "unavailable"]) {
    const { document, elements } = controllerFixture();
    const api = {
      listSessions: async () => ({ sessions: [] }),
      listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
      listModels: async () => ({
        ...readyModelCatalog(["chat-default"]),
        status,
        error_code: "model_catalog_unavailable",
      }),
    };
    const controller = gui.createUiController({ document, elements, api });
    await controller.initialize();

    assert.equal(elements.modelControl.hidden, false);
    assert.equal(elements.modelSelect.value, "chat-default");
    assert.equal(elements.modelCatalogStatus.textContent.length > 0, true);
    controller.destroy();
  }
});


test("selected model is snapshotted into create requests", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => readyModelCatalog(),
    createSession: async (...args) => {
      calls.push(args);
      return { session_id: "s1", run_id: "r1", model_id: args.at(-1) };
    },
    loadSession: async () => ({
      session: { session_id: "s1", title: "Run", status: "running", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "running", model_id: "other-model" }],
      events: [],
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
  elements.modelSelect.value = "other-model";
  elements.modelSelect.dispatchEvent({ type: "change" });
  elements.messageInput.value = "Inspect";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.equal(calls[0].at(-1), "other-model");
  assert.equal(controller.getState().selectedModelId, "other-model");
  controller.destroy();
});


test("selected model is snapshotted into follow-up requests", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  let loads = 0;
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Existing", status: "idle", last_run_id: "r0" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => readyModelCatalog(),
    loadSession: async () => {
      loads += 1;
      return {
        session: {
          session_id: "s1",
          title: "Existing",
          status: loads === 1 ? "idle" : "running",
          last_run_id: loads === 1 ? "r0" : "r1",
        },
        runs: [{
          run_id: loads === 1 ? "r0" : "r1",
          status: loads === 1 ? "succeeded" : "running",
        }],
        events: [],
        skill_ids: [],
      };
    },
    submitFollowUp: async (...args) => {
      calls.push(args);
      return { session_id: "s1", run_id: "r1", model_id: args.at(-1) };
    },
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    streamConsumer: async () => "terminal",
  });
  await controller.initialize();
  elements.modelSelect.value = "other-model";
  elements.modelSelect.dispatchEvent({ type: "change" });
  elements.sessionList.dispatchEvent({
    type: "click",
    target: sessionSelectButtons(elements.sessionList)[0],
  });
  await controller.whenIdle();
  assert.equal(controller.getState().selectedModelId, "other-model");
  elements.messageInput.value = "Continue";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.equal(calls[0].at(-1), "other-model");
  controller.destroy();
});


test("initial model request failure does not block sessions or skills", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Visible", status: "idle", last_run_id: null }],
    }),
    listSkills: async () => ({
      skills: [{ skill_id: "review", name: "Review", description: "Review", source: "user" }],
      diagnostics: [],
      usable: true,
    }),
    listModels: async () => {
      throw new gui.WebClientError("model_catalog_unavailable");
    },
  };
  const controller = gui.createUiController({ document, elements, api });

  await controller.initialize();

  assert.equal(elements.sessionList.textContent.includes("Visible"), true);
  assert.equal(elements.skillList.textContent.includes("Review"), true);
  assert.equal(elements.modelControl.hidden, true);
  controller.destroy();
});


test("active sessions disable select and refresh", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", status: "running", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => readyModelCatalog(),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  assert.equal(elements.modelSelect.disabled, true);
  assert.equal(elements.refreshModelsButton.disabled, true);
  controller.destroy();
});


test("provider IDs render as text and never as HTML", async () => {
  const { document, elements } = controllerFixture();
  const malicious = "<img src=x onerror=alert(1)>";
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    listModels: async () => ({
      ...readyModelCatalog(["chat-default", malicious]),
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  assert.equal(elements.modelSelect.textContent.includes(malicious), true);
  assert.deepEqual(findElements(elements.modelSelect, "img"), []);
  controller.destroy();
});


function sessionSelectButtons(root) {
  return findElements(root, "button").filter(
    (button) => button.className === "session-button",
  );
}


function sessionDeleteButtons(root) {
  return findElements(root, "button").filter(
    (button) => button.className === "session-delete-button",
  );
}


function deletionControllerApi(sessions, { deleteImpl } = {}) {
  const loads = [];
  return {
    loads,
    listSessions: async () => ({ sessions }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async (sessionId) => {
      loads.push(sessionId);
      const session = sessions.find((item) => item.session_id === sessionId);
      return {
        session: { ...session },
        runs: [],
        events: [],
        skill_ids: [],
      };
    },
    deleteSession: deleteImpl ?? (async (sessionId) => ({
      session_id: sessionId,
      deleted: true,
      cleanup_pending: false,
    })),
  };
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


test("session deletion confirmation uses safe title and false sends no request", async () => {
  const { document, elements } = controllerFixture();
  const sessions = [
    { session_id: "s1", title: "<b>Plain title</b>", status: "idle", last_run_id: null },
  ];
  const deleted = [];
  const confirmations = [];
  const api = deletionControllerApi(sessions, {
    deleteImpl: async (sessionId) => {
      deleted.push(sessionId);
      return { session_id: sessionId, deleted: true, cleanup_pending: false };
    },
  });
  const controller = gui.createUiController({
    document,
    elements,
    api,
    confirmDelete: (message) => confirmations.push(message) && false,
  });
  await controller.initialize();

  const deleteButton = sessionDeleteButtons(elements.sessionList)[0];
  elements.sessionList.dispatchEvent({ type: "click", target: deleteButton });
  await controller.whenIdle();

  assert.deepEqual(confirmations, ["确定删除会话“<b>Plain title</b>”？此操作无法撤销。"]);
  assert.deepEqual(deleted, []);
  assert.equal(controller.getState().sessions.length, 1);
  assert.equal(findElements(elements.sessionList, "b").length, 0);
  controller.destroy();
});


test("confirmed deletion is single-flight and disables every delete control", async () => {
  const { document, elements } = controllerFixture();
  const sessions = [
    { session_id: "s1", title: "First", status: "idle", last_run_id: null },
    { session_id: "s2", title: "Second", status: "idle", last_run_id: null },
  ];
  let releaseDelete;
  const pendingDelete = new Promise((resolve) => {
    releaseDelete = resolve;
  });
  const calls = [];
  const api = deletionControllerApi(sessions, {
    deleteImpl: async (sessionId) => {
      calls.push(sessionId);
      return pendingDelete;
    },
  });
  const controller = gui.createUiController({
    document,
    elements,
    api,
    confirmDelete: () => true,
  });
  await controller.initialize();

  const first = sessionDeleteButtons(elements.sessionList)[0];
  elements.sessionList.dispatchEvent({ type: "click", target: first });
  elements.sessionList.dispatchEvent({ type: "click", target: first });
  await Promise.resolve();

  assert.deepEqual(calls, ["s1"]);
  assert.equal(
    sessionDeleteButtons(elements.sessionList).every((button) => button.disabled),
    true,
  );
  releaseDelete({ session_id: "s1", deleted: true, cleanup_pending: false });
  await controller.whenIdle();
  assert.deepEqual(controller.getState().sessions.map((item) => item.session_id), ["s2"]);
  controller.destroy();
});


for (const status of ["running", "cancelling"]) {
  test(`active ${status} state disables every delete control`, async () => {
    const { document, elements } = controllerFixture();
    const sessions = [
      { session_id: "active", title: "Active", status, last_run_id: "r1" },
      { session_id: "idle", title: "Idle", status: "idle", last_run_id: null },
    ];
    const calls = [];
    const api = deletionControllerApi(sessions, {
      deleteImpl: async (sessionId) => calls.push(sessionId),
    });
    const controller = gui.createUiController({
      document,
      elements,
      api,
      confirmDelete: () => true,
    });
    await controller.initialize();

    const buttons = sessionDeleteButtons(elements.sessionList);
    assert.equal(buttons.length, 2);
    assert.equal(buttons.every((button) => button.disabled), true);
    elements.sessionList.dispatchEvent({ type: "click", target: buttons[1] });
    await controller.whenIdle();
    assert.deepEqual(calls, []);
    controller.destroy();
  });
}


test("deleting an unselected row preserves the selected session without reload", async () => {
  const { document, elements } = controllerFixture();
  const sessions = [
    { session_id: "s1", title: "First", status: "idle", last_run_id: null },
    { session_id: "s2", title: "Selected", status: "idle", last_run_id: null },
    { session_id: "s3", title: "Third", status: "idle", last_run_id: null },
  ];
  const api = deletionControllerApi(sessions);
  const controller = gui.createUiController({
    document,
    elements,
    api,
    confirmDelete: () => true,
  });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: sessionSelectButtons(elements.sessionList)[1],
  });
  await controller.whenIdle();

  elements.sessionList.dispatchEvent({
    type: "click",
    target: sessionDeleteButtons(elements.sessionList)[0],
  });
  await controller.whenIdle();

  assert.equal(controller.getState().selectedSessionId, "s2");
  assert.deepEqual(api.loads, ["s2"]);
  assert.deepEqual(controller.getState().sessions.map((item) => item.session_id), ["s2", "s3"]);
  controller.destroy();
});


test("selected deletion chooses next then previous and last enters empty state", async () => {
  for (const scenario of [
    { ids: ["s1", "s2", "s3"], selected: "s2", expected: "s3" },
    { ids: ["s1", "s2"], selected: "s2", expected: "s1" },
    { ids: ["s1"], selected: "s1", expected: null },
  ]) {
    const { document, elements } = controllerFixture();
    const sessions = scenario.ids.map((sessionId) => ({
      session_id: sessionId,
      title: sessionId,
      status: "idle",
      last_run_id: null,
    }));
    const api = deletionControllerApi(sessions);
    const controller = gui.createUiController({
      document,
      elements,
      api,
      confirmDelete: () => true,
    });
    await controller.initialize();
    const selectedIndex = scenario.ids.indexOf(scenario.selected);
    elements.sessionList.dispatchEvent({
      type: "click",
      target: sessionSelectButtons(elements.sessionList)[selectedIndex],
    });
    await controller.whenIdle();
    elements.sessionList.dispatchEvent({
      type: "click",
      target: sessionDeleteButtons(elements.sessionList)[selectedIndex],
    });
    await controller.whenIdle();

    assert.equal(controller.getState().selectedSessionId, scenario.expected);
    if (scenario.expected === null) {
      assert.equal(controller.getState().selectedSession, null);
      assert.deepEqual(elements.conversationLog.childNodes, [elements.emptyState]);
    } else {
      assert.equal(api.loads.at(-1), scenario.expected);
    }
    controller.destroy();
  }
});


test("delete failure preserves row and selection", async () => {
  const { document, elements } = controllerFixture();
  const sessions = [
    { session_id: "s1", title: "Keep", status: "idle", last_run_id: null },
  ];
  const api = deletionControllerApi(sessions, {
    deleteImpl: async () => {
      throw new gui.WebClientError("controller_busy");
    },
  });
  const controller = gui.createUiController({
    document,
    elements,
    api,
    confirmDelete: () => true,
  });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: sessionSelectButtons(elements.sessionList)[0],
  });
  await controller.whenIdle();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: sessionDeleteButtons(elements.sessionList)[0],
  });
  await controller.whenIdle();

  assert.equal(controller.getState().selectedSessionId, "s1");
  assert.deepEqual(controller.getState().sessions.map((item) => item.session_id), ["s1"]);
  assert.equal(elements.connectionStatus.textContent, "请求失败：controller_busy");
  controller.destroy();
});


test("cleanup pending renders only the fixed local warning", async () => {
  const { document, elements } = controllerFixture();
  const sessions = [
    { session_id: "s1", title: "Delete", status: "idle", last_run_id: null },
  ];
  const api = deletionControllerApi(sessions, {
    deleteImpl: async () => ({
      session_id: "s1",
      deleted: true,
      cleanup_pending: true,
      warning_code: "private-provider-warning",
      private: "D:\\secret\\staging",
    }),
  });
  const controller = gui.createUiController({
    document,
    elements,
    api,
    confirmDelete: () => true,
  });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: sessionDeleteButtons(elements.sessionList)[0],
  });
  await controller.whenIdle();

  assert.equal(
    elements.connectionStatus.textContent,
    "会话已删除；部分本地日志将在下次启动时继续清理。",
  );
  assert.equal(elements.connectionStatus.textContent.includes("private"), false);
  assert.equal(elements.connectionStatus.textContent.includes("secret"), false);
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
    "把一个清晰的代码任务交给 MiniCodex",
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


test("controller captures selected read-only mode and locks it during a run", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    createSession: async (message, skillIds, runMode) => {
      calls.push({ message, skillIds, runMode });
      return { session_id: "s1", run_id: "r1", run_mode: runMode };
    },
    loadSession: async () => ({
      session: { session_id: "s1", title: "Inspect", status: "running", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "running", run_mode: "read_only", started_at_utc: null }],
      events: [{ run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Inspect" } }],
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

  elements.runModeControl.dispatchEvent({
    type: "click",
    target: elements.runModeReadOnlyButton,
  });
  assert.equal(controller.getState().selectedRunMode, "read_only");
  assert.equal(elements.runModeReadOnlyButton.getAttribute("aria-pressed"), "true");

  elements.messageInput.value = "Inspect";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.deepEqual(calls, [{ message: "Inspect", skillIds: [], runMode: "read_only" }]);
  assert.equal(elements.runModeModifyButton.disabled, true);
  assert.equal(elements.runModeReadOnlyButton.disabled, true);
  controller.destroy();
});


test("budget profile defaults standard and is sent per run", async () => {
  const { document, elements } = controllerFixture();
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    createSession: async (message, skillIds, runMode, budgetProfile) => {
      calls.push({ message, skillIds, runMode, budgetProfile });
      return {
        session_id: "s1",
        run_id: "r1",
        run_mode: runMode,
        budget_profile: budgetProfile,
      };
    },
    loadSession: async () => ({
      session: { session_id: "s1", title: "Inspect", status: "running", last_run_id: "r1" },
      runs: [{
        run_id: "r1",
        status: "running",
        run_mode: "modify",
        budget_profile: "deep",
        started_at_utc: null,
      }],
      events: [{ run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Inspect" } }],
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

  assert.equal(controller.getState().selectedBudgetProfile, "standard");
  elements.budgetProfileControl.dispatchEvent({
    type: "click",
    target: elements.budgetProfileDeepButton,
  });
  elements.messageInput.value = "Inspect";
  elements.messageComposer.dispatchEvent(submitEvent());
  await controller.whenIdle();

  assert.deepEqual(calls, [{
    message: "Inspect",
    skillIds: [],
    runMode: "modify",
    budgetProfile: "deep",
  }]);
  assert.equal(elements.budgetProfileStandardButton.disabled, true);
  assert.equal(elements.budgetProfileDeepButton.disabled, true);
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
  const buttons = sessionSelectButtons(elements.sessionList);
  assert.equal(buttons.every((button) => !button.disabled), true);
  assert.equal(
    sessionDeleteButtons(elements.sessionList).every((button) => button.disabled),
    true,
  );
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


test("unverified changes render one actionable terminal card after reload", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Pending", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Pending", status: "idle", last_run_id: "r1" },
      runs: [{
        run_id: "r1",
        status: "failed",
        agent_status: "failed",
        termination_reason: "changes_unverified",
        final_report: {
          changed_paths: ["task_manager.py"],
          verification: { status: "stale" },
        },
      }],
      events: [
        {
          run_id: "r1",
          sequence: 1,
          kind: "user_message",
          data: { content: "write a Python file" },
        },
        {
          run_id: "r1",
          sequence: 2,
          kind: "tool_activity",
          data: {
            tool_name: "run_command",
            status: "rejected",
            duration_ms: 0,
            exit_code: null,
            timed_out: false,
            truncated: false,
            safe_error_code: "executable_denied",
            changed_paths: [],
          },
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

  const cards = findElements(elements.conversationLog, "div").filter(
    (element) => element.classList.contains("activity-card--changes-unverified"),
  );
  const rendered = elements.conversationLog.textContent;
  controller.destroy();

  assert.equal(cards.length, 1);
  assert.match(rendered, /修改待验证/);
  assert.match(rendered, /task_manager\.py/);
  assert.match(rendered, /尚未执行或尚未通过/);
  assert.match(rendered, /executable_denied/);
  assert.doesNotMatch(rendered, /运行失败/);
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


test("code copy is single-flight and copies exact fenced text", async () => {
  const { document, elements } = controllerFixture();
  const writes = [];
  const timers = [];
  let resolveWrite;
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Code", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Code", status: "idle", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "succeeded", termination_reason: "completed" }],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Show code" } },
        {
          run_id: "r1",
          sequence: 2,
          kind: "assistant_text_committed",
          data: { content: "```js\nconst value = \"<img onerror=secret()>\";\n```" },
        },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    clipboardWrite: (text) => {
      writes.push(text);
      return new Promise((resolve) => { resolveWrite = resolve; });
    },
    setTimeoutImpl: (callback, delay) => {
      timers.push({ callback, delay });
      return timers.length;
    },
    clearTimeoutImpl: () => {},
  });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();
  const button = findElements(elements.conversationLog, "button").find(
    (candidate) => candidate.classList.contains("code-copy-button"),
  );

  button.dispatchEvent({ type: "click" });
  button.dispatchEvent({ type: "click" });
  await Promise.resolve();

  assert.deepEqual(writes, ['const value = "<img onerror=secret()>";']);
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, "复制中…");
  assert.equal(findElements(elements.conversationLog, "img").length, 0);

  resolveWrite();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(button.textContent, "已复制");
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 1500);
  timers[0].callback();
  assert.equal(button.textContent, "复制");
  assert.equal(button.disabled, false);
  controller.destroy();
});


test("clipboard failure stays local and clears its reset timer on redraw", async () => {
  const { document, elements } = controllerFixture();
  const timers = [];
  const cleared = [];
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Code", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Code", status: "idle", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "succeeded", termination_reason: "completed" }],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Show code" } },
        { run_id: "r1", sequence: 2, kind: "assistant_text_committed", data: { content: "```py\nprint(1)\n```" } },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({
    document,
    elements,
    api,
    clipboardWrite: async () => {
      throw new Error("private clipboard detail");
    },
    setTimeoutImpl: (callback, delay) => {
      timers.push({ callback, delay });
      return 77;
    },
    clearTimeoutImpl: (timerId) => cleared.push(timerId),
  });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();
  const button = findElements(elements.conversationLog, "button").find(
    (candidate) => candidate.classList.contains("code-copy-button"),
  );

  button.dispatchEvent({ type: "click" });
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(button.textContent, "复制失败");
  assert.equal(button.textContent.includes("private"), false);
  assert.equal(elements.connectionStatus.textContent, "");
  assert.equal(timers[0].delay, 1500);
  await controller.selectSession("s1");
  assert.deepEqual(cleared, [77]);
  controller.destroy();
  assert.deepEqual(cleared, [77]);
});


test("historical user messages show inline mode badges without activity cards", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "History", status: "idle", last_run_id: "r2" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "History", status: "idle", last_run_id: "r2" },
      runs: [
        { run_id: "r1", status: "succeeded", agent_status: "success", run_mode: "modify" },
        { run_id: "r2", status: "succeeded", agent_status: "answered", run_mode: "read_only" },
      ],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Change it" } },
        { run_id: "r2", sequence: 2, kind: "user_message", data: { content: "Explain it" } },
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

  const badges = findElements(elements.conversationLog, "span")
    .filter((element) => element.classList.contains("run-mode-badge"))
    .map((element) => element.textContent);
  const activityCards = findElements(elements.conversationLog, "div")
    .filter((element) => element.classList.contains("activity-card"));

  assert.deepEqual(badges, ["可修改", "只读"]);
  assert.equal(activityCards.length, 0);
  controller.destroy();
});


test("answered terminal renders 已回答 and keeps the final response", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Answer", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Answer", status: "idle", last_run_id: "r1" },
      runs: [{
        run_id: "r1",
        status: "succeeded",
        agent_status: "answered",
        run_mode: "read_only",
      }],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Explain it" } },
        { run_id: "r1", sequence: 2, kind: "assistant_text_committed", data: { content: "Explanation" } },
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

  assert.equal(elements.runStatus.textContent, "已回答");
  assert.equal(findElements(elements.conversationLog, "article").length, 2);
  assert.equal(elements.conversationLog.textContent.includes("Explanation"), true);
  assert.equal(elements.conversationLog.textContent.includes("验证成功"), false);
  controller.destroy();
});


test("SSE answered terminal preserves agent status for immediate projection", () => {
  const state = gui.createInitialUiState();
  state.activeRunId = "r1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running", run_mode: "read_only" }],
    events: [],
  };

  gui.reduceSessionUpdate(state, {
    id: 1,
    event: "run_finished",
    data: {
      run_id: "r1",
      data: { status: "succeeded", agent_status: "answered" },
    },
  });

  assert.equal(state.selectedSession.runs[0].status, "succeeded");
  assert.equal(state.selectedSession.runs[0].agent_status, "answered");
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


test("skill rows keep a compact preview and expand only one description", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({ sessions: [] }),
    listSkills: async () => ({
      skills: [
        {
          skill_id: "workspace:review",
          name: "Review",
          description: "Review every changed file and report actionable findings.",
          source: "workspace",
          sha256: "a".repeat(64),
          char_count: 120,
        },
        {
          skill_id: "workspace:test",
          name: "Test",
          description: "Run focused tests before the full regression suite.",
          source: "workspace",
          sha256: "b".repeat(64),
          char_count: 96,
        },
      ],
      diagnostics: [],
      usable: true,
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();

  let toggles = findElements(elements.skillList, "button");
  let details = findElements(elements.skillList, "div").filter(
    (element) => element.classList.contains("skill-option__details"),
  );
  const previews = findElements(elements.skillList, "span").filter(
    (element) => element.classList.contains("skill-option__preview"),
  );
  assert.equal(toggles.length, 2);
  assert.equal(details.length, 2);
  assert.equal(previews[0].textContent, "Review every changed file and report actionable findings.");
  assert.equal(previews[0].getAttribute("title"), previews[0].textContent);
  assert.equal(toggles[0].getAttribute("aria-expanded"), "false");
  assert.equal(details[0].hidden, true);

  elements.skillList.dispatchEvent({ type: "click", target: toggles[0] });
  toggles = findElements(elements.skillList, "button");
  details = findElements(elements.skillList, "div").filter(
    (element) => element.classList.contains("skill-option__details"),
  );
  assert.equal(toggles[0].getAttribute("aria-expanded"), "true");
  assert.equal(details[0].hidden, false);
  assert.equal(details[0].textContent.includes("workspace"), true);

  elements.skillList.dispatchEvent({ type: "click", target: toggles[1] });
  toggles = findElements(elements.skillList, "button");
  details = findElements(elements.skillList, "div").filter(
    (element) => element.classList.contains("skill-option__details"),
  );
  assert.equal(toggles[0].getAttribute("aria-expanded"), "false");
  assert.equal(details[0].hidden, true);
  assert.equal(toggles[1].getAttribute("aria-expanded"), "true");
  assert.equal(details[1].hidden, false);

  const inputs = findElements(elements.skillList, "input");
  inputs[0].checked = true;
  elements.skillList.dispatchEvent({ type: "change", target: inputs[0] });
  assert.deepEqual(controller.getState().selectedSkillIds, ["workspace:review"]);
  assert.equal(
    findElements(elements.skillList, "button")[1].getAttribute("aria-expanded"),
    "true",
  );
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


test("active header keeps workspace path and hides call counters", () => {
  const { document, elements } = controllerFixture();
  const state = gui.createInitialUiState();
  const run = {
    run_id: "r1",
    status: "running",
    budget_profile: "standard",
  };
  state.activeRunId = "r1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [run],
    events: [],
  };

  gui.reduceSessionUpdate(state, reducerFrame(1, "run_progress", {
    budget_profile: "standard",
    phase: "discover",
    main_model_calls: 8,
    main_model_limit: 24,
    summary_model_calls: 1,
    summary_model_limit: 4,
    provider_attempts: 10,
    provider_attempt_limit: 48,
    tool_calls: 17,
    tool_limit: 80,
  }));
  gui.reduceSessionUpdate(state, reducerFrame(2, "decision_checkpoint", {
    reason: "exploration_limit",
    phase: "discover",
    main_calls_remaining: 16,
  }));
  gui.renderRunHeader(
    document,
    elements,
    run,
    state.transientStatus,
  );

  assert.equal(elements.workspacePath.textContent, "D:\\code\\coding_agent");
  assert.equal(elements.workspacePath.textContent.includes("8/24"), false);
  assert.equal(elements.workspacePath.textContent.includes("17/80"), false);
  assert.equal(elements.runStatus.textContent, "根据已有信息作出决策");
  assert.deepEqual(state.activities, []);
});


test("terminal update clears transient convergence status", () => {
  const state = gui.createInitialUiState();
  state.activeRunId = "r1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running", budget_profile: "deep" }],
    events: [],
  };
  gui.reduceSessionUpdate(state, reducerFrame(1, "decision_checkpoint", {
    reason: "final_call_reserve",
    phase: "act",
    main_calls_remaining: 4,
  }));
  gui.reduceSessionUpdate(state, reducerFrame(2, "run_finished", {
    status: "succeeded",
    agent_status: "answered",
  }));

  assert.equal(state.transientStatus, null);
  assert.equal(state.runProgress, null);
  assert.deepEqual(state.activities, []);
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
  const buttons = sessionSelectButtons(elements.sessionList);
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
      "http://127.0.0.1:43123/api/v1/models?refresh=false",
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
  const indicators = findElements(elements.conversationLog, "span").filter(
    (element) => element.classList.contains("activity-indicator"),
  );
  controller.destroy();

  assert.equal(rendered.includes("read_file"), false);
  assert.equal(rendered.includes("user_verify"), false);
  assert.equal(activityCount, 1);
  assert.deepEqual(
    childClasses,
    [
      "message message--user",
      "activity-card activity-card--active",
    ],
  );
  assert.equal(indicators.length, 1);
  assert.equal(
    findElements(indicators[0], "span").filter(
      (element) => element.classList.contains("activity-indicator__dot"),
    ).length,
    3,
  );
  assert.equal(rendered.includes("list_directory"), false);
  assert.equal(rendered.includes("Writing the answer"), true);
  assert.equal(rendered.includes("secret"), false);
});
