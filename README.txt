MiniCodex 是从零实现的 Windows 优先本地 Coding Agent。循环、上下文、工具、安全、验证和日志均本地实现；ModelClient 隔离 OpenAI Responses API。

仓库：https://github.com/zt150058/MiniCodex
环境：Windows，Python 3.11+。

PowerShell 安装：
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"

当前会话配置 OPENAI_API_KEY 和 OPENAI_MODEL（或 --model）；密钥不得写入项目或日志。

运行：
coding-agent "修复失败测试" --workspace . --model "<model-id>" --verify "pytest -q"

--workspace 指向工作区；--verify 可选，提供时是强制最终验证命令；未提供时仍须执行安全、可信的 verification 命令。

支持 UTF-8 文本读写、精确替换、受控命令、迭代修复和结构化摘要；不支持删除、任意 Shell、网络下载、包安装、Git 写入或自动推送。

只有最后一次修改后的验证退出码为 0 且 validation_index == mutation_index，才可能成功。FinalReport 展示真实证据，JSONL 位于 .coding-agent/logs/<run_id>.jsonl。

MiniCodex 以确定性代码限制路径和命令，但不是操作系统级沙箱；请使用工作区副本。安装与排错见 docs/USAGE.md；API、重试和隐私说明见 docs/OPENAI_API.md。
