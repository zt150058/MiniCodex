MiniCodex 是 Windows 本地 Coding Agent；自研循环、安全与验证。
https://github.com/zt150058/MiniCodex
要求 Python 3.11+。安装：py -3.11 -m venv .venv；.\.venv\Scripts\Activate.ps1；pip install -e ".[test]"

--api-mode responses 使用 OPENAI_API_KEY；chat-completions 使用 CHAT_COMPLETIONS_API_KEY 和 --base-url；模型来自 OPENAI_MODEL 或 --model。
允许修改：coding-agent "修复测试" --workspace . --budget-profile standard --verify "pytest -q"
只读问答：coding-agent "介绍项目" --workspace . --read-only
GUI：coding-agent-web --workspace .。

预算是硬上限，standard/deep可选；探索账本不存正文。只读仅列目录、读文件、查Git；modify可单级建目录，零修改可ANSWERED。无--verify时修改批次后可做结构完整性检查（不代表编译或测试）。最后一次修改的validation_index == mutation_index才成功，否则保留文件并退出1。

GUI支持删会话、Skill ZIP导入；Skill不执行且不删工作区文件。

SDK单次等待30秒；GUI命令卡显示exit N。无PTY，交互需测试或人工验证，一次性脚本不得绕过策略。不支持任意Shell、下载或Git写入。JSONL位于.coding-agent/logs/<run_id>.jsonl。不是操作系统级沙箱。详见docs/USAGE.md和docs/OPENAI_API.md。
