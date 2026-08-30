MiniCodex 是 Windows 本地 Coding Agent；实现循环、上下文、工具、安全、验证、会话和日志，以 ModelClient 隔离模型供应商。

仓库：https://github.com/zt150058/MiniCodex
环境：Windows，Python 3.11+。

PowerShell 安装：
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"

配置：--api-mode responses 读取 OPENAI_API_KEY；chat-completions 读取 CHAT_COMPLETIONS_API_KEY 和 --base-url。模型用 OPENAI_MODEL 或 --model。

允许修改（默认）：coding-agent "修复失败测试" --workspace . --verify "pytest -q"
只读问答：coding-agent "介绍项目" --workspace . --read-only
GUI：coding-agent-web --workspace .；每条消息可选择“允许修改”或“只读问答”。

只读模式仅列目录、读文件和检查本地 Git，答案为 ANSWERED；不修改或验证。允许修改支持 UTF-8 精确修改、受控命令和 JDK Java .in/.out 验证。--verify 是可选强制门槛；最后一次修改后验证为 0 且 validation_index == mutation_index 才可能成功。

不支持删除、任意 Shell、下载、Git 写入或推送。JSONL 位于 .coding-agent/logs/<run_id>.jsonl。项目不是操作系统级沙箱。安装见 docs/USAGE.md；API 与隐私见 docs/OPENAI_API.md。
