MiniCodex 是从零实现的 Windows 优先本地 Coding Agent；循环、上下文、工具、安全、验证和日志均由本地代码实现，ModelClient 隔离 Responses 与 compatible Chat Completions。

仓库：https://github.com/zt150058/MiniCodex
环境：Windows，Python 3.11+。

PowerShell 安装：
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"

配置：--api-mode 默认 responses，读取 OPENAI_API_KEY；chat-completions 读取 CHAT_COMPLETIONS_API_KEY，并要求 HTTPS --base-url。模型使用 OPENAI_MODEL 或 --model。密钥不得进入 CLI、项目、日志或子进程。

运行：
coding-agent "修复失败测试" --workspace . --api-mode responses --verify "pytest -q"

--workspace 指定工作区；--verify 是可选强制验证。支持 UTF-8 文本、精确替换、受控命令和摘要；不支持删除、任意 Shell、下载、安装包、Git 写入或推送。

只有最后一次修改后的验证退出码为 0 且 validation_index == mutation_index 才可能成功。FinalReport 展示证据，JSONL 位于 .coding-agent/logs/<run_id>.jsonl。

本项目不是操作系统级沙箱，请使用工作区副本。安装见 docs/USAGE.md；API、重试和隐私见 docs/OPENAI_API.md。
