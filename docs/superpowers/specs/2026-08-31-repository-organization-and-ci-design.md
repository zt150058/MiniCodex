# 仓库结构整理、文档收尾与持续集成设计

## 1. 背景与目标

MiniCodex 的主要功能已经完成，但生产模块和单元测试仍大量平铺在单个目录中，根目录文档也混合了承载不同用途的资料。当前仓库没有 GitHub Actions，提交后缺少统一、可重复的自动测试入口。

本次收尾工作的目标是：

1. 按稳定职责重组生产代码和测试代码，使目录能够表达模块边界。
2. 整理文档入口，根目录只保留 `AGENTS.md`、`README.md` 和 `README.txt` 三份说明文档。
3. 将 `README.md` 改为项目简介、目录结构和文件夹职责说明。
4. 将 `README.txt` 控制在 1000 个汉字以内，并包含仓库地址、运行方法、特色和必要边界。
5. 新增 Windows GitHub Actions，在 push 和 pull request 后自动执行完整离线测试与打包检查。

本设计以提交 `79ab64d` 为干净基线。它只调整目录、导入、资源定位、文档和 CI，不改变 Agent 权限、运行语义、安全策略、验证门槛、REST/SSE 合同或 SQLite schema。

## 2. 范围与兼容性

### 2.1 范围内

- 移动和适度重命名 `src/coding_agent/` 下的模块。
- 同步整理 `tests/`，使单元测试目录与生产职责相对应。
- 更新全部内部导入、测试导入、入口点和包资源配置。
- 移动根目录的设计、任务和原始需求文档。
- 重写两份 README，并更新仓库内的文档链接和文档测试。
- 新增 GitHub Actions 测试工作流。

### 2.2 范围外

- 不拆分或重写现有大文件。
- 不修改核心行为、公共 HTTP 合同、持久化格式或安全规则。
- 不保留旧的 `coding_agent.agent`、`coding_agent.session` 等 Python 模块路径兼容层。
- 不改变 `coding-agent` 和 `coding-agent-web` 两个命令名称及其用户可见行为。
- 不增加运行依赖或测试依赖。
- 不使用 Agent 框架、Agent SDK 或托管执行工具。
- 不提交、推送或操作远程仓库，除非用户另行明确授权。

项目仍处于 `0.1.0`，内部 Python 导入路径允许随本次整理迁移。命令行入口和 GUI/API 行为是本次需要保持稳定的兼容边界。

## 3. 生产代码结构

最终生产包结构为：

```text
src/coding_agent/
├── __init__.py
├── application/
├── engine/
├── providers/
├── operations/
│   └── tools/
├── sessions/
├── skills/
└── web/
    └── static/
```

各子包职责如下。

### 3.1 `application/`

保存应用装配和一次性命令入口：

- `app.py`
- `config.py`
- `cli.py`

该层负责把 engine、provider 和 operation 对象组合成可运行应用，不承载新的业务规则。

### 3.2 `engine/`

保存供应商无关的 Agent 核心：

- `agent.py`
- `budget.py`
- `context.py`
- `instructions.py`
- `logging.py`
- `messages.py`
- `model.py`
- `progress.py`
- `report.py`
- `run_mode.py`
- `state.py`
- `streaming.py`
- `termination.py`
- `verification.py`

现有 `ModelClient` 协议和 `FakeModelClient` 继续属于核心边界；具体网络适配器进入 providers。

### 3.3 `providers/`

保存模型供应商适配与远端模型目录：

- `openai_client.py`
- `chat_completions_client.py`
- `model_catalog.py`

这些模块继续只通过 engine 中的中立类型与核心交互。

### 3.4 `operations/`

保存确定性的本地安全与工具执行边界：

- `safety.py`
- `tools/base.py`
- `tools/filesystem.py`
- `tools/java.py`
- `tools/registry.py`
- `tools/shell.py`

安全裁决仍由本地代码完成；目录调整不得扩大命令或文件权限。

### 3.5 `sessions/`

保存本地会话领域和运行协调：

- `session.py`
- `session_controller.py`
- `session_deletion.py`
- `session_events.py`
- `session_runtime.py`
- `session_store.py`

本次只改变模块位置，不改变 SQLite schema、删除恢复协议、事件格式或并发约束。

### 3.6 `skills/`

保存声明式 Skill 的发现与安装：

- 原 `skills.py` 改为 `catalog.py`
- 原 `skill_packages.py` 改为 `packages.py`

Skill 仍是不可执行的声明式指令，不能增加工具权限。

### 3.7 `web/`

保存本地 Web 接口和资源：

- 原 `web.py` 改为 `app.py`
- 原 `web_auth.py` 改为 `auth.py`
- 原 `web_cli.py` 改为 `cli.py`
- 原 `web_static/` 改为 `static/`

FastAPI 路由、认证、REST/SSE 投影和静态 GUI 行为保持不变。

### 3.8 包与入口配置

每个 Python 子包增加 `__init__.py`。`pyproject.toml` 更新为：

- `coding-agent` 指向 `coding_agent.application.cli:entrypoint`。
- `coding-agent-web` 指向 `coding_agent.web.cli:entrypoint`。
- 静态资源从 `coding_agent.web/static/` 打包。

根包只保留 `__init__.py`，不增加旧模块兼容转发文件。

## 4. 测试代码结构

单元测试按照生产职责整理：

```text
tests/
├── application/
├── engine/
├── providers/
├── operations/
├── sessions/
├── skills/
├── web/
├── integration/
├── js/
└── manual/
```

- 现有核心、provider、session、Skill、Web 和工具单元测试进入对应目录。
- `tests/tools/` 合并到 `tests/operations/`。
- `tests/manual_web_fixture.py` 进入 `tests/manual/`。
- `tests/integration/` 和 `tests/js/` 保持现有职责。
- 可复用的 Web 测试支持代码与 Web 测试放在同一边界内。

只移动测试和更新导入，不改变断言语义或删减安全、失败路径和回归覆盖。Pytest 仍从整个 `tests/` 递归发现测试。

## 5. 文档结构

根目录只保留以下三份项目说明文档：

```text
AGENTS.md
README.md
README.txt
```

其他文档整理为：

```text
docs/
├── OPENAI_API.md
├── USAGE.md
├── project/
│   ├── DESIGN.md
│   ├── TASKS.md
│   └── requirement.pdf
└── superpowers/
    ├── plans/
    └── specs/
```

`.gitignore`、`pyproject.toml`、`.github/` 等不是项目说明文档，继续位于根目录。

### 5.1 `README.md`

新的 README 只承载：

- 项目简介与定位。
- 仓库文件夹级目录树。
- 顶层目录和 `src/coding_agent/` 各子包职责。
- 指向详细使用文档和 API 文档的链接。

README 不逐个解释源码文件，也不重复完整设计和任务历史。

### 5.2 `README.txt`

README.txt 不超过 1000 个汉字，至少包含：

- Git 仓库地址 `https://github.com/zt150058/MiniCodex`。
- Python 3.11+ 安装步骤。
- Responses 和 Chat Completions 的凭据、模型和 base URL 配置方式。
- CLI 修改模式、CLI 只读模式和 Web GUI 的启动示例。
- 本地显式 Agent 循环、安全工具、验证门、会话、Skill 等特色。
- 项目不是操作系统级沙箱等必要限制。

### 5.3 链接与规则更新

`AGENTS.md` 中的设计和任务路径改为 `docs/project/DESIGN.md` 与 `docs/project/TASKS.md`。仓库内全部相关链接和文档测试同步更新，不能残留仍指向旧根目录位置的有效引用。

## 6. GitHub Actions

新增 `.github/workflows/tests.yml`，配置如下：

- 触发：所有分支的 `push` 和 `pull_request`。
- Runner：`windows-latest`。
- Python：3.11。
- Node.js：固定 LTS 主版本。
- 权限：`contents: read`。
- Job 超时：30 分钟。
- 不注入 API Key，不执行 live provider 测试。

工作流按顺序执行：

1. Checkout。
2. 设置 Python 和 pip cache。
3. 设置 Node.js LTS。
4. 安装 `.[test]`。
5. 运行 `python -m pytest -q`。
6. 运行 `node --test tests/js/web_gui.test.mjs`。
7. 运行两个命令的 `--help` 冒烟检查。
8. 使用现有 setuptools 构建 wheel，并做基础包导入检查。
9. 运行 `git diff --check`。

CI 不引入新的项目依赖，不访问真实模型服务。任一步失败即使 workflow 失败。

## 7. 实施顺序与失败处理

1. 在移动前运行完整 Python 和 Node 测试，记录基线。
2. 先创建包目录和移动测试，再更新测试所期望的新导入及文档路径。
3. 移动生产模块，更新全部绝对/相对导入。
4. 更新 entry points、package data 和静态资源定位。
5. 移动文档并更新 AGENTS、README 和文档测试。
6. 新增 CI workflow。
7. 运行聚焦测试，再运行完整验证。

使用可被 Git 识别的移动操作，避免复制后遗留重复源码。任何失败都应保留真实输出并定位到本次移动引入的引用、资源或发现问题；不得通过削弱测试、安全限制或验证门槛解决。

若实施过程中发现现有模块依赖无法按上述边界移动而不改变架构，应停止实施并返回设计讨论，不得静默引入兼容层或新的抽象。

## 8. 验收标准

- `src/coding_agent/` 根部除 `__init__.py` 外不再平铺生产模块。
- 所有生产和测试导入都使用新的包路径，旧路径没有有效残留。
- `coding-agent --help` 和 `coding-agent-web --help` 正常运行。
- wheel 可以使用现有构建系统完成构建，Web 静态资源仍被打包。
- 根目录的项目说明文档只有 `AGENTS.md`、`README.md`、`README.txt`。
- README.md 只在文件夹级别解释结构与职责。
- README.txt 包含指定信息且不超过 1000 个汉字。
- 文档链接和测试中的设计、任务路径全部更新。
- GitHub Actions 在 push 与 pull request 上运行 Windows Python/Node 测试。
- 完整离线 Python 测试和 Node GUI 测试通过。
- `git diff --check` 通过。
- 未增加禁止的 Agent 框架、SDK、依赖或权限。
- 文件路径、命令超时、输出限制、终止条件、验证证据和秘密处理行为保持不变。

