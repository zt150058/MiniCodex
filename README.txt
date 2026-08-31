MiniCodex 是 Windows 本地 Coding Agent。
Git 仓库：https://github.com/zt150058/MiniCodex
运行环境：Python 3.11+。

安装：py -3.11 -m venv .venv；.\.venv\Scripts\Activate.ps1；pip install -e ".[test]"
Responses（responses）：设置 OPENAI_API_KEY，以 OPENAI_MODEL 或 --model 指定模型。
Chat Completions：设置 CHAT_COMPLETIONS_API_KEY，并传 --api-mode chat-completions --base-url https://... --model ...。
允许修改：coding-agent "修复测试" --workspace . --verify "pytest -q"
只读问答：coding-agent "介绍项目" --workspace . --read-only
Web GUI：coding-agent-web --workspace .

特色功能：本地显式 Agent 循环；只读与修改权限；工作区和命令安全策略；修改后验证；上下文压缩；JSONL 审计；持久会话；声明式 Skill；双模型适配。零修改问答以 ANSWERED 结束；最后一次修改只有获得新鲜通过证据才能成功，否则保留文件并失败退出。日志位于 .coding-agent/logs/<run_id>.jsonl。

其它说明：测试默认离线，不需要真实 API Key。Web 仅供本机使用；Skill 不可执行。项目限制工具和工作区访问，但不是操作系统级沙箱，不应处理不可信代码。详见 docs/USAGE.md 和 docs/OPENAI_API.md。
