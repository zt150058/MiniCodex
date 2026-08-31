MiniCodex 是 Windows 本地 Coding Agent；自行实现循环、上下文、工具、安全、验证和会话。
https://github.com/zt150058/MiniCodex
要求 Python 3.11+。安装：py -3.11 -m venv .venv；.\.venv\Scripts\Activate.ps1；pip install -e ".[test]"

--api-mode responses 使用 OPENAI_API_KEY；chat-completions 使用 CHAT_COMPLETIONS_API_KEY 和 --base-url；模型来自 OPENAI_MODEL 或 --model。
允许修改：coding-agent "修复测试" --workspace . --budget-profile standard --verify "pytest -q"
只读问答：coding-agent "介绍项目" --workspace . --read-only
GUI：coding-agent-web --workspace .。

预算是硬上限，standard/deep可选；探索账本不存正文。只读模式仅列目录、读文件、查Git；modify零修改可ANSWERED。修改后执行合法验证；无--verify时可做UTF-8完整性检查（不代表编译或测试）。最后一次修改的validation_index == mutation_index才成功，否则保留文件并退出1。

GUI支持空闲会话逐条删除和Skill ZIP导入；删除有标题确认，不执行Skill，不删除任意工作区文件。

不支持任意 Shell、下载或 Git 写入。JSONL位于.coding-agent/logs/<run_id>.jsonl。不是操作系统级沙箱。详见docs/USAGE.md和docs/OPENAI_API.md。
