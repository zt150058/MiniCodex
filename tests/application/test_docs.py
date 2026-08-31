from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from coding_agent.application.cli import build_parser
from coding_agent.engine.report import FinalReport
from coding_agent.engine.run_mode import RunMode
from coding_agent.operations.tools.filesystem import (
    CreateDirectoryTool,
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
from coding_agent.operations.tools.shell import InspectGitTool, RunCommandTool
from coding_agent.operations.tools.java import RunJavaTestsTool


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "README.txt",
    ROOT / "docs" / "USAGE.md",
    ROOT / "docs" / "OPENAI_API.md",
)
README_HARD_TOTAL = 850
REPOSITORY_URL = "https://github.com/zt150058/MiniCodex"


@dataclass(frozen=True, slots=True)
class ReadmeMetrics:
    unicode_chars: int
    non_whitespace_chars: int
    han_chars: int
    utf8_bytes: int
    lines: int


def _read_utf8(path: Path) -> str:
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8")


def _read_budget_contract_docs() -> str:
    paths = (ROOT / "AGENTS.md", *PUBLIC_DOCS)
    return "\n".join(_read_utf8(path) for path in paths)


def _readme_metrics(path: Path) -> ReadmeMetrics:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return ReadmeMetrics(
        unicode_chars=len(normalized),
        non_whitespace_chars=sum(not char.isspace() for char in normalized),
        han_chars=sum("\u4e00" <= char <= "\u9fff" for char in normalized),
        utf8_bytes=len(raw),
        lines=0 if not normalized else len(normalized.splitlines()),
    )


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    next_heading = text.find("\n## ", start + len(heading))
    return text[start:] if next_heading == -1 else text[start:next_heading]


def _assert_headings_in_order(text: str, headings: tuple[str, ...]) -> None:
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_required_public_documents_exist_and_are_utf8() -> None:
    missing = [str(path.relative_to(ROOT)) for path in PUBLIC_DOCS if not path.is_file()]
    assert missing == []
    for path in PUBLIC_DOCS:
        _read_utf8(path)


def test_readme_txt_meets_submission_contract() -> None:
    path = ROOT / "README.txt"
    text = _read_utf8(path)
    metrics = _readme_metrics(path)

    assert 650 <= metrics.unicode_chars <= README_HARD_TOTAL
    assert metrics.han_chars <= 1000
    assert REPOSITORY_URL in text
    for required in (
        "Windows",
        "Python 3.11+",
        "coding-agent",
        "--workspace",
        "--verify",
        "--api-mode",
        "--base-url",
        "responses",
        "chat-completions",
        "OPENAI_API_KEY",
        "CHAT_COMPLETIONS_API_KEY",
        "pytest -q",
        ".coding-agent/logs/",
        "docs/USAGE.md",
        "docs/OPENAI_API.md",
        "最后一次修改",
        "不是操作系统级沙箱",
    ):
        assert required in text


def test_all_markdown_relative_links_and_source_references_exist() -> None:
    markdown_paths = (
        ROOT / "README.md",
        ROOT / "docs" / "USAGE.md",
        ROOT / "docs" / "OPENAI_API.md",
    )
    for path in markdown_paths:
        text = _read_utf8(path)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = target.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (path.parent / target).resolve().exists(), (path, target)
        for reference in re.findall(r"`((?:src|tests|examples)/[^`\s]+)`", text):
            assert (ROOT / reference).exists(), (path, reference)


def test_usage_matches_parser_tools_exit_codes_and_log_path() -> None:
    text = _read_utf8(ROOT / "docs" / "USAGE.md")
    headings = (
        "# MiniCodex 使用说明",
        "## 功能与适用场景",
        "## 已验证环境与系统要求",
        "## Windows PowerShell 安装",
        "## 工作区与凭据准备",
        "## CLI 参数",
        "## 最小运行示例",
        "## 推荐的安全运行示例",
        "## Agent 运行流程",
        "## 按运行模式划分的本地工具",
        "## 成功、验证与退出码",
        "## JSONL 日志与 FinalReport",
        "## 离线演示与完整测试",
        "## 常见错误与排查",
        "## 停止运行与清理",
        "## 安全边界和已知限制",
    )
    _assert_headings_in_order(text, headings)

    help_text = build_parser().format_help()
    expected_cli_names = (
        "task",
        "--workspace",
        "--verify",
        "--model",
        "--api-mode",
        "--base-url",
        "-h",
        "--help",
    )
    for name in expected_cli_names:
        assert name in help_text
        assert f"`{name}`" in text

    tools_section = _section(text, "## 按运行模式划分的本地工具")
    modify_section = tools_section.split("### 只读问答（`read_only`）", 1)[0]
    read_only_section = tools_section.split("### 只读问答（`read_only`）", 1)[1]
    documented_modify_tools = re.findall(
        r"^\| `([^`]+)` \|", modify_section, flags=re.MULTILINE
    )
    documented_read_only_tools = re.findall(
        r"^\| `([^`]+)` \|", read_only_section, flags=re.MULTILINE
    )
    actual_modify_tools = [
        ListDirectoryTool.name,
        ReadFileTool.name,
        CreateDirectoryTool.name,
        ReplaceTextTool.name,
        WriteFileTool.name,
        RunCommandTool.name,
        RunJavaTestsTool.name,
    ]
    actual_read_only_tools = [
        ListDirectoryTool.name,
        ReadFileTool.name,
        InspectGitTool.name,
    ]
    assert documented_modify_tools == actual_modify_tools
    assert documented_read_only_tools == actual_read_only_tools

    assert FinalReport.__name__ in text
    for required in (
        "`0`",
        "`1`",
        "`2`",
        "`130`",
        "`success`",
        "`failed`",
        "`interrupted`",
        ".coding-agent/logs/<run_id>.jsonl",
        "OPENAI_API_KEY",
        "CHAT_COMPLETIONS_API_KEY",
        "OPENAI_MODEL",
        "`responses`",
        "`chat-completions`",
        "`responses + --base-url`",
        "`chat-completions` 必须提供 `--base-url`",
        (
            "`OPENAI_API_KEY` 和 `CHAT_COMPLETIONS_API_KEY` 都会从 "
            "`run_command` 子进程环境中移除"
        ),
        "`--base-url` 可配置不代表兼容所有服务",
        "validation_index == mutation_index",
        "Ctrl+C",
        "tests/integration/test_agent_repair.py",
    ):
        assert required in text

    for required in (
        "`run_java_tests`",
        "`source_root`",
        "`main_class`",
        "`tests_directory`",
        '`purpose="verification"`',
        "`.in`",
        "`.out`",
        "65,536",
        "262,144",
        "不支持 Maven、Gradle 或 JUnit",
        "不是操作系统级沙箱",
        'Java 项目不要附加无关的 `--verify "pytest -q"`',
        "只有新鲜的 Java verification 结果",
        "`run_command` 仍不能执行 Java 命令字符串",
    ):
        assert required in text


def test_usage_documents_exact_run_modes_tools_and_terminal_meanings() -> None:
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    help_text = build_parser().format_help()
    assert "--read-only" in help_text
    assert "`--read-only`" in usage
    assert f"`{RunMode.MODIFY.value}`" in usage
    assert f"`{RunMode.READ_ONLY.value}`" in usage
    assert "`ANSWERED`" in usage
    assert "已回答" in usage
    assert "`SUCCESS`" in usage
    assert "新鲜验证" in usage

    modify_tools = (
        ListDirectoryTool.name,
        ReadFileTool.name,
        CreateDirectoryTool.name,
        ReplaceTextTool.name,
        WriteFileTool.name,
        RunCommandTool.name,
        RunJavaTestsTool.name,
    )
    read_only_tools = (
        ListDirectoryTool.name,
        ReadFileTool.name,
        InspectGitTool.name,
    )
    for tool in (*modify_tools, *read_only_tools):
        assert f"`{tool}`" in usage
    assert "只读模式不会运行 `--verify`" in usage
    assert "同一会话的每条消息可以重新选择模式" in usage


def test_docs_lock_directory_integrity_and_chat_stream_fallback_contracts() -> None:
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    api = _read_utf8(ROOT / "docs" / "OPENAI_API.md")
    agents = _read_utf8(ROOT / "AGENTS.md")

    assert (
        "| `create_directory` | 一次只创建一级目录，不递归创建父目录；"
        in usage
    )
    assert "修改批次结束后" in usage
    assert "本地结构完整性" in usage
    assert "不代表测试、编译或用户指定验证已经通过" in usage
    assert "尚未向用户公开文本" in api
    assert "最多执行一次同步请求" in api
    assert "已经公开任何文本后不会同步回退" in api
    assert "exactly six" not in agents
    assert "恰好六个" not in agents


def test_readme_submission_stays_within_limit_and_names_read_only_mode() -> None:
    text = _read_utf8(ROOT / "README.txt")
    metrics = _readme_metrics(ROOT / "README.txt")
    assert metrics.unicode_chars <= README_HARD_TOTAL
    for value in ("--read-only", "只读问答", "允许修改", "ANSWERED"):
        assert value in text


def test_docs_explain_deterministic_decision_and_verification_recovery() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "docs" / "project" / "DESIGN.md",
            ROOT / "docs" / "project" / "TASKS.md",
            ROOT / "README.md",
            ROOT / "docs" / "USAGE.md",
        )
    )

    for phrase in (
        "Standard 1 / Deep 2",
        "decision_required",
        "changes_unverified",
        "拒绝但不自动改写",
        "修改待验证",
    ):
        assert phrase in combined


def test_docs_describe_run_scoped_exploration_convergence() -> None:
    design = _read_utf8(ROOT / "docs" / "project" / "DESIGN.md")
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    for text in (design, usage):
        assert "ExplorationLedger" in text or "探索账本" in text
        assert "decision_required" in text
        assert "Standard 1 / Deep 2" in text
        assert "运行级" in text
    assert "长期记忆" in usage
    assert "不保存文件正文" in usage


def test_docs_do_not_claim_unverified_changes_are_success() -> None:
    usage = (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8")

    assert "changes_unverified" in usage
    assert "退出码 1" in usage
    assert "文件不会自动回滚" in usage
    assert "SUCCESS" in usage


def test_model_instructions_and_streaming_are_documented_accurately() -> None:
    design = _read_utf8(ROOT / "docs" / "project" / "DESIGN.md")
    api_guide = _read_utf8(ROOT / "docs" / "OPENAI_API.md")
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    unsupported_or_deferred_section = _section(
        api_guide,
        "## 当前未实现的扩展",
    )

    assert "ModelRequest.instructions" in design
    assert "RunInstructionBuilder" in design
    assert "StreamingModelClient" in design
    assert "stream=True" in api_guide
    assert "首个 delta 前" in api_guide
    assert "delta 后不重试" in api_guide
    assert "CLI 仍使用同步最终报告" in usage
    assert "SSE / GUI" not in unsupported_or_deferred_section
    assert "coding-agent-web" in usage


def test_local_web_gui_is_documented_with_its_real_security_boundary() -> None:
    readme = _read_utf8(ROOT / "README.md")
    submission = _read_utf8(ROOT / "README.txt")
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    api_guide = _read_utf8(ROOT / "docs" / "OPENAI_API.md")
    combined = "\n".join((readme, submission, usage, api_guide))

    for required in (
        "coding-agent-web --workspace <path>",
        "--no-open-browser",
        "127.0.0.1",
        "随机端口",
        "Bearer",
        "Host",
        "Origin",
        "会话持久化",
        "一次只运行一个",
        "follow-up",
        "取消",
        "Skill",
        "关闭浏览器不会取消",
        "Responses",
        "Chat Completions",
    ):
        assert required in combined

    for limitation in (
        "不是远程服务",
        "不提供账户",
        "不支持 MCP",
        "不执行 Skill",
        "不支持并行运行",
    ):
        assert limitation in usage

    assert "安全诊断" not in usage
    assert "Skill 诊断" not in usage


def test_public_docs_lock_web_chat_completions_model_selection_contract() -> None:
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")

    for required in (
        "只在 Chat Completions mode",
        "所有返回且合法的模型 ID",
        "启动参数指定的默认模型",
        "只影响下一次提交",
        "Responses mode 不显示",
        "GET /models",
        "浏览器不会接触 API key 或 base URL",
    ):
        assert required in usage


def test_public_docs_explain_task31_local_gui_affordances_and_privacy_boundary() -> None:
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")

    for required in (
        "工作区绝对路径",
        "代码块右上角",
        "已复制",
        "当前活动回复",
        "减少动态效果",
        "不写入 REST、SSE、SQLite、JSONL 或模型上下文",
    ):
        assert required in usage


def test_public_docs_lock_local_skill_zip_import_contract() -> None:
    combined = "\n".join(
        (
            _read_utf8(ROOT / "README.md"),
            _read_utf8(ROOT / "README.txt"),
            _read_utf8(ROOT / "docs" / "USAGE.md"),
        )
    )
    for required in (
        ".zip",
        "当前工作区",
        "SKILL.md",
        "不覆盖",
        "不可执行",
        "128 KiB",
        "65,536 字节",
        "运行期间",
    ):
        assert required in combined


def test_public_docs_lock_confirmed_session_deletion_contract() -> None:
    readme = _read_utf8(ROOT / "README.md")
    submission = _read_utf8(ROOT / "README.txt")
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    combined = "\n".join((readme, submission, usage))

    for required in (
        "逐条删除",
        "标题二次确认",
        "不支持批量删除",
        "活动 run",
        ".coding-agent/logs/<audit_run_id>.jsonl",
        "cleanup_pending",
        "启动恢复",
        "不是 Agent 工具",
        "不会删除任意工作区文件",
    ):
        assert required in combined


def test_api_guide_matches_both_adapters_and_declares_unsupported_features() -> None:
    text = _read_utf8(ROOT / "docs" / "OPENAI_API.md")
    headings = (
        "# OpenAI Responses 与 compatible Chat Completions 接入说明",
        "## Provider 与 API mode 选择",
        "## 凭据与模型配置",
        "## PowerShell 当前会话设置",
        "## 不显示密钥的配置检查",
        "## 启动 MiniCodex",
        "## ModelClient 与适配器边界",
        "## Responses API 请求映射",
        "## Responses continuation 与本地历史",
        "## Chat Completions 完整历史映射",
        "## assistant tool_calls 与 tool result 配对",
        "## 共享 logical call、provider attempt 与重试",
        "## 隐私与日志边界",
        "## 完全离线的自动测试",
        "## 手工联网冒烟（自动测试不会执行）",
        "## 常见 API 错误",
        "## 当前未实现的扩展",
    )
    _assert_headings_in_order(text, headings)

    responses_source = _read_utf8(
        ROOT / "src" / "coding_agent" / "providers" / "openai_client.py"
    )
    chat_source = _read_utf8(
        ROOT
        / "src"
        / "coding_agent"
        / "providers"
        / "chat_completions_client.py"
    )
    assert ".responses.create(" in responses_source
    assert '"store": False' in responses_source
    assert "max_retries=0" in responses_source
    assert '"strict": True' in responses_source
    assert "chat.completions" not in responses_source
    assert ".chat.completions.create(" in chat_source
    assert "max_retries=0" in chat_source
    assert '"max_tokens"' in chat_source
    assert "previous_response_id" not in chat_source
    assert "conversation" not in chat_source

    for required in (
        "OpenAIResponsesClient",
        "ChatCompletionsModelClient",
        "ModelClient",
        "ModelResponse",
        "Responses API",
        "Chat Completions",
        "`responses`",
        "`chat-completions`",
        "--base-url",
        "store=False",
        "max_tokens",
        "max_retries=0",
        "function_call_output",
        "assistant tool_calls",
        "role=tool",
        "tool_call_id",
        'finish_reason="stop"',
        "call_id",
        "previous_response_id",
        "conversation",
        "0.25",
        "0.50",
        "OPENAI_API_KEY",
        "CHAT_COMPLETIONS_API_KEY",
        "OPENAI_MODEL",
        "tests/integration/test_chat_completions_agent.py",
        "可配置 base URL 不代表兼容所有服务",
        "手工联网冒烟（自动测试不会执行）",
        "可能产生费用",
    ):
        assert required in text

    unsupported = (
        "custom Responses endpoint",
        "Azure-specific API",
        "proxy 配置",
        "server conversation",
        "async API",
        "automatic endpoint detection",
        "executable Skills",
        "MCP",
        "legacy function_call",
        "non-function Chat tools",
    )
    unsupported_section = _section(text, "## 当前未实现的扩展")
    for feature in unsupported:
        assert re.search(
            rf"^\| {re.escape(feature)} \| 当前未实现 \|$",
            unsupported_section,
            flags=re.MULTILINE,
        )


def test_public_docs_contain_no_secret_or_personal_absolute_path() -> None:
    combined = "\n".join(_read_utf8(path) for path in PUBLIC_DOCS)
    forbidden_patterns = (
        r"sk-[A-Za-z0-9_-]{16,}",
        r"Bearer\s+[A-Za-z0-9._-]{12,}",
        r"[A-Za-z]:\\Users\\",
        r"[A-Za-z]:\\code\\",
        r"/home/[^/]+/",
    )
    for pattern in forbidden_patterns:
        assert re.search(pattern, combined, flags=re.IGNORECASE) is None


def test_docs_explain_profiles_phases_and_exact_default_limits() -> None:
    combined = _read_budget_contract_docs()
    for required in (
        "standard",
        "deep",
        "BudgetProfile",
        "RunMode",
        "DISCOVER",
        "ACT",
        "VERIFY",
        "FINISH",
        "24",
        "4",
        "48",
        "80",
        "20 分钟",
        "40",
        "6",
        "140",
        "30 分钟",
        "no_progress",
    ):
        assert required in combined


def test_docs_do_not_claim_unlimited_budget_planner_or_provider_memory() -> None:
    combined = _read_budget_contract_docs().lower()
    for forbidden in (
        "无限预算",
        "自动 planner",
        "服务端会话替代本地历史",
        "恢复 encrypted reasoning",
        "绕过验证",
    ):
        assert forbidden not in combined
