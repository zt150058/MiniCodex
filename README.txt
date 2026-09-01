项目地址：https://github.com/zt150058/MiniCodex

MiniCodex 是面向 Windows 的本地 Coding Agent。
一、安装

要求 Python 3.11+。在项目根目录打开 PowerShell：

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"

二、配置 Chat Completions

先在当前 PowerShell 会话设置供应商密钥：

$env:CHAT_COMPLETIONS_API_KEY = "你的 API Key"

密钥只能放在环境变量中，不要写进命令、源码、Git、日志、截图或视频。

三、启动 GUI

coding-agent-web --workspace "D:\你的项目" `
  --api-mode chat-completions `
  --base-url "https://api.example.com/v1" `
  --model "模型 ID" `
  --verify "python -m pytest -q"

把工作区、Base URL、模型 ID 换成实际值。没有 pytest 验证命令时可去掉 --verify。服务启动后会自动打开浏览器，只监听本机 127.0.0.1。

四、核心特点

- 自研 Agent 闭环：AgentRunner 使用显式同步循环，按 DISCOVER、ACT、VERIFY、FINISH 四阶段推进。ProgressLedger 区分读取等弱进展与修改、验证等强进展，通过重复调用检测和 decision checkpoint 强制模型收敛，持续无进展以 no_progress 终止。
- 分层硬预算：standard 最多 24 次主调用、4 次摘要调用、80 次工具调用和 20 分钟；deep 对应 40、6、140 和 30 分钟。逻辑调用与真实 provider attempt 分开计数，并预留最终验证额度，防止重试或探索无限消耗。
- 结构化上下文压缩：ContextManager 达到 48,000 字符或 20 条历史时触发压缩，目标降至 33,000 字符和 12 条以内。固定 JSON 摘要保留任务、已查文件、修改、命令结果、验证状态和待办；摘要异常后锁定确定性的本地 fallback，不再重复浪费 API。
- 权限化工具注册：运行模式提交后不可改变。“允许修改”提供读取、创建目录、精确替换、创建文件、受控命令和 Java 验证；“只读问答”只提供目录、文件和 Git 检查。工具 strict Schema 之后仍本地复验参数，异常统一包装为结构化 ToolResult 返回模型修正。
- 确定性执行安全：PathGuard 规范化每条路径并拒绝工作区越界、.git/.coding-agent 及符号链接逃逸。命令解析为参数数组，以 shell=False、固定工作区、白名单、超时和输出上限串行执行；拒绝任意 Shell、网络下载、包安装和破坏性 Git。
- 修改后验证门：每次文件变更递增 mutation_index，并立即使旧证据过期。VerificationGate 只接受 validation_index 对齐最后一次修改的新鲜证据；用户提供的 --verify 是强制门槛。失败、超时或未验证时保留文件并以 changes_unverified 结束，模型文字不能决定 SUCCESS。
- 本地 GUI 与审计：SQLite 持久化会话、追问、模式、预算和模型，认证 SSE 实时投影文本、工具 exit code、修改与验证状态，并支持协作式取消。JSONL 只记录脱敏执行事实、哈希和相对路径，不保存 API Key、文件正文、完整历史或隐藏推理。

五、安全边界

GUI 仅供本机使用，不要通过代理、端口转发或网络共享对外暴露。项目限制 Agent 的工具能力，但不是操作系统级沙箱；被允许执行的项目脚本和测试仍属于可信代码，请只在已备份的项目副本中运行。
